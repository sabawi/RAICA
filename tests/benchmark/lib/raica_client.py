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
from urllib.parse import urlsplit

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


def resolve_ratio(urls, timeout=15):
    """Fraction of URLs returning a non-error HTTP status (ENV — sites bot-block; informational)."""
    urls = [u for u in urls if u]
    if not urls:
        return None
    ua = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ok = 0
    for u in urls:
        try:
            req = urllib.request.Request(u, headers={"User-Agent": ua}, method="HEAD")
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
    """Return server-log lines written since epoch t_start (best-effort; LOCAL only)."""
    if not os.path.exists(SERVER_LOG):
        return []
    try:
        with open(SERVER_LOG, encoding="utf-8", errors="replace") as f:
            return f.read().splitlines()[-4000:]
    except Exception:
        return []


def created_delivery_files(log_lines):
    """Parse '📦 delivery: created N document(s): [a.pdf, b.html]' -> absolute paths in the sandbox dir."""
    sandbox = os.path.join(os.path.expanduser("~"), "sandbox_workspace")
    for line in reversed(log_lines):
        if "delivery: created" in line and "[" in line:
            names = re.findall(r"'([^']+\.(?:pdf|html|md|txt))'", line)
            return [os.path.join(sandbox, n) for n in names]
    return []
