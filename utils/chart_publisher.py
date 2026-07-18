"""
Publish a generated chart PNG to NewX's /internal/chart-upload endpoint (Option B, Phase 3).

Config-driven + flag-gated (config/llm_config.yaml `charts:` block for enabled + upload URL; the shared
secret is a .env secret, CHART_UPLOAD_SECRET, matching NewX). Never raises — returns None on any failure
or when disabled, so a chart problem or a NewX hiccup can never break the analysis/answer.

Production load guards (v1.0.0.171), both enforced in `get_or_publish_chart` — the single choke-point:
  • Same-window cache keyed by (ticker, display_days): a daily-bar chart is identical within a short
    window, so a popular ticker renders once per `cache_ttl_seconds` (default 30 min) and every later
    request — any user, and repeats inside one response — reuses the minted URL (no render, no upload).
  • Per-response cap (`max_per_response`, default 6): a hard fail-safe so no single user response can
    render an unbounded number of charts. Over the cap → no chart (text is unaffected). The counter is a
    shared mutable budget on a contextvar, reset per response, so it aggregates across sequential AND
    concurrently-gathered tool calls in the same response.
"""
import io
import os
import time
import logging
import threading
import contextvars

import requests

logger = logging.getLogger(__name__)


def _charts_config():
    """(enabled, upload_url, secret, verify_tls). Fail-closed: enabled+url+secret must all be present.

    Deployment (.env) overrides take PRECEDENCE over the yaml so the SAME committed config works across
    environments and survives a deploy's `git checkout -- config` (v1.0.0.175):
      • RAICA_CHARTS_ENABLED  (true/false) → overrides `charts.enabled`
      • NEWX_CHART_UPLOAD_URL             → overrides `charts.newx_upload_url`
      • CHART_UPLOAD_SECRET               → the shared secret (always .env; never in yaml)
    Live (sabawi.net) NewX runs HTTP on :9876 (TLS terminated upstream) → set the URL to
    http://localhost:9876/...; local dev uses the yaml https default. verify_tls defaults True (secure),
    is irrelevant for http, and is set false for the loopback self-signed https case.
    """
    try:
        from utils.config_loader import config_loader
        cfg = (config_loader.load_config().get('charts', {}) or {})
    except Exception:
        cfg = {}
    _env_enabled = os.getenv('RAICA_CHARTS_ENABLED')
    enabled = (_env_enabled.strip().lower() == 'true') if _env_enabled is not None else bool(cfg.get('enabled', False))
    url = (os.getenv('NEWX_CHART_UPLOAD_URL') or cfg.get('newx_upload_url') or '').strip()
    secret = os.getenv('CHART_UPLOAD_SECRET', '').strip()
    verify_tls = bool(cfg.get('verify_tls', True))
    return enabled, url, secret, verify_tls


def charts_enabled() -> bool:
    """True only when the feature is on AND both the endpoint URL and the shared secret are configured."""
    enabled, url, secret, _ = _charts_config()
    return bool(enabled and url and secret)


def chart_display_days(default: int = 126) -> int:
    """Trading sessions to show on the main chart (config/llm_config.yaml charts.display_days)."""
    try:
        from utils.config_loader import config_loader
        return int((config_loader.load_config().get('charts', {}) or {}).get('display_days', default))
    except Exception:
        return default


def _cap_and_ttl(max_default: int = 6, ttl_default: int = 1800):
    """(max_per_response, cache_ttl_seconds) from config/llm_config.yaml charts block."""
    try:
        from utils.config_loader import config_loader
        cfg = (config_loader.load_config().get('charts', {}) or {})
        return int(cfg.get('max_per_response', max_default)), int(cfg.get('cache_ttl_seconds', ttl_default))
    except Exception:
        return max_default, ttl_default


# --- same-window URL cache (process-global, thread-safe) --------------------------------------------
_cache_lock = threading.Lock()
_url_cache = {}   # (TICKER, display_days) -> (url, expiry_epoch)


def _cache_get(key):
    with _cache_lock:
        v = _url_cache.get(key)
        if not v:
            return None
        url, exp = v
        if time.time() >= exp:
            _url_cache.pop(key, None)
            return None
        return url


def _cache_put(key, url, ttl):
    with _cache_lock:
        _url_cache[key] = (url, time.time() + max(0, ttl))


# --- per-response chart budget (shared mutable object on a contextvar) -------------------------------
class _Budget:
    __slots__ = ("count", "lock")

    def __init__(self):
        self.count = 0
        self.lock = threading.Lock()


_response_budget: "contextvars.ContextVar" = contextvars.ContextVar("raica_chart_budget", default=None)


def reset_response_charts():
    """Start a fresh per-response chart budget. Call once at the start of each user response so the
    `max_per_response` cap counts from zero (set before any tool dispatch so gathered tool calls share it)."""
    _response_budget.set(_Budget())


def get_or_publish_chart(ticker: str, display_days: int, render_fn, variant: str = None):
    """Cache- and cap-aware chart publishing (the single entry point callers should use).

    render_fn is a zero-arg callable that produces PNG bytes (deferred so a cache hit skips rendering).
    `variant` distinguishes different charts for the SAME (ticker, display_days) — e.g. an event
    sub-chart keyed by its type+date — so they don't collide in the cache (default None = the main chart).
    Returns the same-origin URL to embed in a [[chart:...]] marker, or None (disabled / capped / failed).
    """
    if not charts_enabled():
        return None
    key = (str(ticker).upper(), int(display_days), variant)

    # 1) cache hit → reuse, no render/upload, no budget spend
    hit = _cache_get(key)
    if hit:
        logger.info(f"chart cache HIT {key[0]}@{key[1]}d → {hit}")
        return hit

    # 2) per-response cap (reserve a slot up front so concurrent calls can't overshoot)
    max_per, ttl = _cap_and_ttl()
    budget = _response_budget.get()
    if budget is not None:
        with budget.lock:
            if budget.count >= max_per:
                logger.info(f"chart cap reached ({budget.count}/{max_per}) — skipping chart for {key[0]}")
                return None
            budget.count += 1

    # 3) render (deferred) + publish; cache the URL on success, release the reserved slot on failure
    url = None
    try:
        png = render_fn()
        url = publish_chart(png, f"{key[0]}_{variant or 'technical'}") if png else None
    except Exception as e:  # noqa: BLE001 — a chart failure must never break the caller
        logger.info(f"get_or_publish_chart error for {key[0]}: {e}")
    if url:
        _cache_put(key, url, ttl)
    elif budget is not None:
        with budget.lock:
            budget.count = max(0, budget.count - 1)
    return url


def publish_chart(png_bytes, filename_hint: str = "chart", timeout: float = 15.0):
    """POST the PNG to NewX; return the same-origin media URL it mints, or None (failure/disabled)."""
    if not png_bytes:
        return None
    enabled, url, secret, verify_tls = _charts_config()
    if not (enabled and url and secret):
        return None
    try:
        files = {'file': (f"{filename_hint}.png", io.BytesIO(png_bytes), 'image/png')}
        r = requests.post(url, files=files, headers={'X-Chart-Upload-Secret': secret},
                          timeout=timeout, verify=verify_tls)
        if r.status_code == 200:
            return (r.json() or {}).get('url') or None
        logger.warning(f"chart_publisher: upload failed HTTP {r.status_code}: {r.text[:120]}")
    except Exception as e:  # noqa: BLE001 — never break the caller
        logger.warning(f"chart_publisher: upload error: {e}")
    return None
