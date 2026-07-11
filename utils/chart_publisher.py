"""
Publish a generated chart PNG to NewX's /internal/chart-upload endpoint (Option B, Phase 3).

Config-driven + flag-gated (config/llm_config.yaml `charts:` block for enabled + upload URL; the shared
secret is a .env secret, CHART_UPLOAD_SECRET, matching NewX). Never raises — returns None on any failure
or when disabled, so a chart problem or a NewX hiccup can never break the analysis/answer.
"""
import io
import os
import logging

import requests

logger = logging.getLogger(__name__)


def _charts_config():
    """(enabled, upload_url, secret). Fail-closed: all three must be present to publish."""
    try:
        from utils.config_loader import config_loader
        cfg = (config_loader.load_config().get('charts', {}) or {})
    except Exception:
        cfg = {}
    enabled = bool(cfg.get('enabled', False))
    url = (cfg.get('newx_upload_url') or os.getenv('NEWX_CHART_UPLOAD_URL', '')).strip()
    secret = os.getenv('CHART_UPLOAD_SECRET', '').strip()
    return enabled, url, secret


def charts_enabled() -> bool:
    """True only when the feature is on AND both the endpoint URL and the shared secret are configured."""
    enabled, url, secret = _charts_config()
    return bool(enabled and url and secret)


def chart_display_days(default: int = 126) -> int:
    """Trading sessions to show on the main chart (config/llm_config.yaml charts.display_days)."""
    try:
        from utils.config_loader import config_loader
        return int((config_loader.load_config().get('charts', {}) or {}).get('display_days', default))
    except Exception:
        return default


def publish_chart(png_bytes, filename_hint: str = "chart", timeout: float = 15.0):
    """POST the PNG to NewX; return the same-origin media URL it mints, or None (failure/disabled)."""
    if not png_bytes:
        return None
    enabled, url, secret = _charts_config()
    if not (enabled and url and secret):
        return None
    try:
        files = {'file': (f"{filename_hint}.png", io.BytesIO(png_bytes), 'image/png')}
        r = requests.post(url, files=files, headers={'X-Chart-Upload-Secret': secret}, timeout=timeout)
        if r.status_code == 200:
            return (r.json() or {}).get('url') or None
        logger.warning(f"chart_publisher: upload failed HTTP {r.status_code}: {r.text[:120]}")
    except Exception as e:  # noqa: BLE001 — never break the caller
        logger.warning(f"chart_publisher: upload error: {e}")
    return None
