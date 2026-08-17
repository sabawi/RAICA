"""
Thin RAICA /v1 client + extraction helpers for the benchmark scenarios.

LOCAL by default (http://localhost:5000) — residential IP avoids the datacenter bot-blocking the live box
sees. `--live` switches the base URL. Parses the JSON-lines stream, extracts citation URLs, classifies
them specific-vs-homepage, resolves them (ENV), and tails the server log for delivery filenames.
"""
import base64
import json
import os
import re
import time
import urllib.request
from urllib.parse import urlsplit, urlunsplit, quote

LOCAL_BASE = "http://localhost:5000"
LIVE_BASE = "https://sabawi.net"
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SERVER_LOG = os.path.join(REPO_ROOT, "logs", "server_complete.log")

_URL_RE = re.compile(r'https?://[^\s)\]\"<>*]+')
# Known bare section roots (single segment) that are NOT specific articles.
_SECTION_WORDS = {"news", "world", "politics", "business", "sport", "sports", "technology", "tech",
                  "science", "health", "finance", "markets", "opinion", "latest", "us", "uk"}


def post_v1(prompt, *, base=LOCAL_BASE, images=None, deep_research=False, allowed_tools=None,
            model="deepseek-v4-pro:cloud", timeout=600):
    """POST to /v1, reassemble the streamed answer. Returns {text, urls, latency_s, ok}."""
    payload = {"prompt": prompt, "model": model, "toolsInUse": True,
               "deep_research": bool(deep_research)}
    if allowed_tools is not None:
        payload["allowed_tools"] = allowed_tools
    if images:
        payload["images"] = images
    data = json.dumps(payload).encode()
    req = urllib.request.Request(f"{base}/v1", data=data, headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        raw = urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "replace")
        ok = True
    except Exception as e:  # noqa: BLE001
        return {"text": "", "urls": [], "latency_s": time.time() - t0, "ok": False, "error": str(e)}
    buf = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except Exception:
            continue
        if o.get("response"):
            buf.append(o["response"])
    text = "".join(buf)
    return {"text": text, "urls": sorted(set(_URL_RE.findall(text))),
            "latency_s": round(time.time() - t0, 1), "ok": ok}


def encode_image(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def is_specific_url(u):
    """Heuristic: a deep article URL (good citation) vs a homepage/bare-section landing page (weak)."""
    try:
        s = urlsplit(u)
        segs = [p for p in (s.path or "").split("/") if p]
        if not segs:
            return False                                  # homepage
        if len(segs) == 1:
            seg = segs[0].lower()
            if seg in _SECTION_WORDS:
                return False                              # bare section (/news, /world)
            return len(seg) > 18 or any(c.isdigit() for c in seg)  # long slug or id => article
        last = segs[-1].lower()
        return len(last) > 8 or any(c.isdigit() for c in last) or len(segs) >= 3
    except Exception:
        return False


def specific_url_ratio(urls):
    urls = [u for u in urls if u]
    return round(sum(1 for u in urls if is_specific_url(u)) / len(urls), 3) if urls else 0.0


def _ascii_url(u):
    """Percent-encode a URL so raw urllib can send it. Unlike requests/urllib3, urllib does NOT auto-encode
    non-ASCII characters, so a citation URL with an accented slug (e.g. 'jürgen') would raise
    UnicodeEncodeError and be falsely counted as unresolved. IDNA-encode the host and percent-encode the
    path/query (with '%' in safe so already-encoded sequences aren't double-encoded)."""
    try:
        s = urlsplit(u)
        host = s.netloc.encode("idna").decode("ascii") if any(ord(c) > 127 for c in s.netloc) else s.netloc
        path = quote(s.path, safe="/%:@!$&'()*+,;=~-._")
        query = quote(s.query, safe="=&/?%:@!$'()*+,;~-._")
        return urlunsplit((s.scheme, host, path, query, s.fragment))
    except Exception:
        return u


def resolve_ratio(urls, timeout=15):
    """Fraction of URLs returning a non-error HTTP status (ENV — sites bot-block; informational)."""
    urls = [u for u in urls if u]
    if not urls:
        return None
    ua = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ok = 0
    for u in urls:
        try:
            req = urllib.request.Request(_ascii_url(u), headers={"User-Agent": ua}, method="HEAD")
            with urllib.request.urlopen(req, timeout=timeout) as r:
                if r.status < 400:
                    ok += 1
        except urllib.error.HTTPError as he:   # noqa
            if he.code in (403, 405, 406, 429):  # blocked/method-not-allowed: page likely exists -> count
                ok += 1
        except Exception:
            pass
    return round(ok / len(urls), 3)


def log_window_since(t_start):
    """Return server-log lines written since epoch t_start (best-effort; LOCAL only).

    The previous implementation IGNORED t_start and returned the last 4000 lines, so every
    log-derived metric silently absorbed whatever the PREVIOUS scenario had written. It
    showed up on 2026-08-10 as three different scenarios all reporting
    `sources_truncated=17`, and as an immigration-simulation run whose "chart markers" were
    the stock tickers from the scenario before it. Log-derived metrics were therefore not
    measurements at all.

    Now filters on the log's own timestamp prefix ('MM/DD/YYYY HH:MM:SS AM - '), falling
    back to the old behaviour only if nothing parses (so a log-format change degrades to
    noisy rather than empty).
    """
    if not os.path.exists(SERVER_LOG):
        return []
    try:
        with open(SERVER_LOG, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except Exception:
        return []

    import datetime as _dt
    stamp = re.compile(r"^(\d{2}/\d{2}/\d{4} \d{1,2}:\d{2}:\d{2} [AP]M) - ")
    start_i, seen = None, False
    for i, ln in enumerate(lines):
        m = stamp.match(ln)
        if not m:
            continue
        seen = True
        try:
            ts = _dt.datetime.strptime(m.group(1), "%m/%d/%Y %I:%M:%S %p").timestamp()
        except ValueError:
            continue
        if ts >= t_start - 2:          # 2s slack for clock/flush skew
            start_i = i
            break
    if not seen:
        return lines[-4000:]           # unparseable format -> old behaviour
    return lines[start_i:] if start_i is not None else []


def vision_seconds(log_lines):
    """Per-stage latency (Tier 2): seconds the VISION model took, from
    '🖼️ FORCED IMAGE PROCESSING COMPLETE: 1 images processed in Xs'. None if not found."""
    for line in reversed(log_lines):
        m = re.search(r"images processed in ([\d.]+)s", line)
        if m:
            return float(m.group(1))
    return None


def dr_phase_timings(log_lines):
    """Per-stage latency (Tier 2): DR pipeline phase seconds from the 'Deep research pipeline complete'
    metadata timings dict (synthesize/verify/grade/gather). {} if not found."""
    for line in reversed(log_lines):
        if "Deep research pipeline complete" in line:
            out = {}
            for k in ("synthesize", "verify", "grade", "gather"):
                m = re.search(rf"'{k}':\s*([\d.]+)", line)
                if m:
                    out[k] = float(m.group(1))
            return out
    return {}


def created_delivery_files(log_lines):
    """Parse '📦 delivery: created N document(s): [a.pdf, b.html]' -> absolute paths in the sandbox dir."""
    sandbox = os.path.join(os.path.expanduser("~"), "sandbox_workspace")
    for line in reversed(log_lines):
        if "delivery: created" in line and "[" in line:
            names = re.findall(r"'([^']+\.(?:pdf|html|md|txt))'", line)
            return [os.path.join(sandbox, n) for n in names]
    return []


def unmeasured_if_no_response(r, metrics):
    """Null every metric value when the request never came back.

    WHY (2026-08-17): `post_v1` returns `ok: False` on a timeout, and NOT ONE scenario looked
    at it. They computed metrics from the empty response instead, so a client timeout was
    indistinguishable from a broken system: `dr_completed False`, `attachment_count 0`,
    `pdf_valid False`.

    In the run that exposed this the server had actually SUCCEEDED — "Deep research complete:
    4 rounds, 53 evidence items", a verified 107,956-byte %PDF-1.7 and a 72,405-byte HTML on
    disk — written roughly 30 seconds AFTER the client stopped listening at exactly 700.0s.
    The suite called that a CODE REGRESSION on seven rows.

    `dr_latency_s` is deliberately KEPT: how long we waited before giving up is a real
    observation, and it is the value that makes the timeout visible in the scorecard.

    None then scores as UNMEASURED (never REGRESSION) and forces the suite to INCONCLUSIVE —
    the honest outcome, which also prompts a re-run instead of a false alarm.
    """
    if r.get("ok"):
        return metrics
    return [m if m["name"].endswith("latency_s") else {**m, "value": None} for m in metrics]
