#!/usr/bin/env python3
"""LIVE lane suite — every model lane is CALLED ONCE with a real prompt and must return a
real, valid answer. Reachability is NOT enough.

WHY THIS FILE EXISTS
--------------------
A provider migration moved some lanes and left others behind, and every static check passed:

  * `doctor` reported "✓ Every active lane's model matches its endpoint" while SIX active
    lanes 404'd on every call (SI-057).
  * the arbitrator ran 178 attempts / 1 success for a night because a DeepInfra slug was
    pointed at the local Ollama proxy (SI-056).
  * vision died on a provider quota nothing else used, so nobody noticed.

Each of those is invisible to a config inspection and obvious to one real call. This file is
that call, for every lane, in one place.

WHAT "VALID" MEANS HERE
-----------------------
Not HTTP 200. Not "the model exists". Each probe asserts something only a WORKING model can
produce:
  * chat lanes      -> solve a small arithmetic problem; the exact answer must appear
  * tool-calling    -> must emit a structured tool_call naming the tool we offered
  * arbitrator      -> must emit parseable JSON with the requested key
  * vision / OCR    -> must name shapes AND READ TEXT out of a generated image

Lane inventory is taken from config_server_cli's own discovery, so a lane added to
llm_config.yaml is automatically covered here and cannot be silently skipped.

USAGE
    python tests/integration/test_all_lanes_live.py            # all active lanes
    python tests/integration/test_all_lanes_live.py --json     # machine-readable summary
Exit code 0 = every lane answered correctly; 1 = at least one lane is broken.
"""
import argparse
import base64
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
except Exception:
    pass

from config_server_cli import ModelAliasManager  # noqa: E402

TIMEOUT = 180


class C:
    OK = "\033[92m"; BAD = "\033[91m"; WARN = "\033[93m"; DIM = "\033[2m"; B = "\033[1m"; E = "\033[0m"


# ─────────────────────────────────────────────────────────── transport
def _post(endpoint, api_key, payload, timeout=TIMEOUT):
    """One OpenAI-compatible chat call. Ollama's /v1 proxy speaks this too."""
    url = endpoint.rstrip("/")
    if not url.endswith("/chat/completions"):
        url = url + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _ollama_v1(endpoint):
    """Ollama's native base_url is :11434; its OpenAI-compatible surface is :11434/v1."""
    e = (endpoint or "").rstrip("/")
    if "11434" in e and not e.endswith("/v1"):
        return e + "/v1"
    return e


def _api_key_for(manager, endpoint):
    env = manager._api_key_env_for_endpoint(endpoint or "")
    if env:
        return os.getenv(env, "")
    if "11434" in (endpoint or ""):
        return "ollama"
    return ""


def _content(resp):
    msg = (resp.get("choices") or [{}])[0].get("message") or {}
    return (msg.get("content") or "").strip()


# ─────────────────────────────────────────────────────────── probes
def probe_chat(endpoint, api_key, model):
    """A working model can do arithmetic; a reachable-but-wrong one cannot."""
    r = _post(endpoint, api_key, {
        "model": model,
        "messages": [{"role": "user", "content": "What is 17 plus 25? Reply with the number only."}],
        "max_tokens": 2048, "temperature": 0,
        "chat_template_kwargs": {"enable_thinking": False},
    })
    txt = _content(r)
    return ("42" in txt), f"answered {txt[:60]!r}" if txt else "returned EMPTY content"


def probe_tools(endpoint, api_key, model):
    """Tool lanes must emit a STRUCTURED call, not prose about calling one."""
    tools = [{"type": "function", "function": {
        "name": "get_weather", "description": "Get the weather for a city",
        "parameters": {"type": "object", "properties": {"city": {"type": "string"}},
                       "required": ["city"]}}}]
    r = _post(endpoint, api_key, {
        "model": model, "tools": tools, "tool_choice": "auto",
        "messages": [{"role": "user", "content": "What is the weather in Paris? Use the tool."}],
        "max_tokens": 2048, "temperature": 0,
        "chat_template_kwargs": {"enable_thinking": False},
    })
    calls = ((r.get("choices") or [{}])[0].get("message") or {}).get("tool_calls") or []
    names = [(c.get("function") or {}).get("name") for c in calls]
    return ("get_weather" in names), (f"emitted tool_call(s) {names}" if names
                                      else "emitted NO tool_calls (prose only)")


def probe_json(endpoint, api_key, model):
    """The arbitrator's whole contract is parseable JSON."""
    r = _post(endpoint, api_key, {
        "model": model,
        "messages": [{"role": "user", "content":
                      'Reply with ONLY this JSON and nothing else: {"verdict": "ok"}'}],
        "max_tokens": 2048, "temperature": 0,
        "chat_template_kwargs": {"enable_thinking": False},
    })
    txt = _content(r)
    body = txt[txt.find("{"): txt.rfind("}") + 1] if "{" in txt and "}" in txt else ""
    try:
        return (json.loads(body).get("verdict") == "ok"), f"parsed JSON from {txt[:50]!r}"
    except Exception:
        return False, f"NOT parseable JSON: {txt[:70]!r}"


def _test_image():
    """A red circle, a blue square, and the word SEVEN — shapes AND text, so one image
    proves both scene understanding and OCR."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (260, 170), "white")
    d = ImageDraw.Draw(img)
    d.ellipse((20, 30, 100, 110), fill="red")
    d.rectangle((140, 40, 220, 110), fill="blue")
    d.text((100, 138), "SEVEN", fill="black")
    buf = io.BytesIO(); img.save(buf, format="JPEG")
    return base64.b64encode(buf.getvalue()).decode()


def probe_vision(endpoint, api_key, model):
    """Must SEE the shapes and READ the word. Naming one but not the other is a partial
    failure and is reported as a failure."""
    b64 = _test_image()
    r = _post(endpoint, api_key, {
        "model": model, "max_tokens": 2048, "temperature": 0,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": "List every shape, its colour, and any text you can read."},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}],
    })
    txt = _content(r).lower()
    shapes = ("red" in txt) and ("blue" in txt)
    ocr = "seven" in txt
    if shapes and ocr:
        return True, "named red+blue shapes AND read 'SEVEN' (OCR)"
    missing = []
    if not shapes: missing.append("shapes")
    if not ocr: missing.append("OCR text")
    return False, f"missing {', '.join(missing)} — said {txt[:70]!r}"


# Which probe a lane gets, decided by its config path. Longest match wins, so
# `llm.tool_calling` beats a generic `llm.` rule.
_PROBE_RULES = (
    ("vision.config.model", probe_vision),
    ("vision.config.fallback_model", probe_vision),
    ("llm.tool_calling", probe_tools),
    ("tool_calling.gather_gate", probe_tools),
    ("arbitrator", probe_json),
    ("code_generation.classification_model", probe_chat),
    ("convergence", probe_chat),
    ("deep_research", probe_chat),
    ("code_generation", probe_chat),
    ("llm.primary", probe_chat),
)


def probe_for(path):
    best, fn = -1, probe_chat
    for prefix, probe in _PROBE_RULES:
        if path.startswith(prefix) and len(prefix) > best:
            best, fn = len(prefix), probe
    return fn


# ─────────────────────────────────────────────────────────── runner
def collect_lanes():
    """Every ACTIVE lane, with its resolved endpoint — from the configurator's own
    discovery so this file cannot drift out of sync with `lanes` / `doctor` / `convert`."""
    m = ModelAliasManager()
    cfg = m._load_llm_config()
    primary = m._primary_endpoint(cfg)
    out = []
    for lane in m._discover_lanes(cfg):
        if lane["inert"]:
            continue
        endpoint = _ollama_v1(lane["own_endpoint"] or primary or "")
        out.append({"path": lane["path"], "model": lane["model"], "endpoint": endpoint,
                    "api_key": _api_key_for(m, endpoint)})
    return out


def run(as_json=False):
    lanes = collect_lanes()
    if not as_json:
        print(f"\n{C.B}LIVE LANE SUITE — every lane called once with a real prompt{C.E}")
        print("=" * 96)
        print(f"  {len(lanes)} active lane(s)\n")

    results, failures = [], 0
    for lane in lanes:
        probe = probe_for(lane["path"])
        t0 = time.time()
        try:
            if not lane["endpoint"]:
                ok, detail = False, "no endpoint resolved"
            else:
                ok, detail = probe(lane["endpoint"], lane["api_key"], lane["model"])
        except urllib.error.HTTPError as e:
            body = e.read().decode()[:110]
            ok, detail = False, f"HTTP {e.code}: {body}"
        except Exception as e:                                   # noqa: BLE001
            ok, detail = False, f"{type(e).__name__}: {str(e)[:110]}"
        dt = time.time() - t0
        failures += (0 if ok else 1)
        results.append({"lane": lane["path"], "model": lane["model"],
                        "endpoint": lane["endpoint"], "probe": probe.__name__,
                        "ok": ok, "detail": detail, "seconds": round(dt, 1)})
        if not as_json:
            mark = f"{C.OK}✓ PASS{C.E}" if ok else f"{C.BAD}✗ FAIL{C.E}"
            print(f"  {mark}  {lane['path']:<44} {C.DIM}{probe.__name__:<14}{C.E} {dt:5.1f}s")
            print(f"          {lane['model']}")
            print(f"          {'' if ok else C.WARN}{detail}{C.E}")

    if as_json:
        print(json.dumps({"total": len(results), "failures": failures, "lanes": results}, indent=2))
    else:
        print("-" * 96)
        if failures:
            print(f"  {C.BAD}{C.B}LANE SUITE FAILED — {failures}/{len(results)} lane(s) "
                  f"did not return a valid result.{C.E}\n")
        else:
            print(f"  {C.OK}{C.B}ALL {len(results)} LANES LIVE — every lane answered "
                  f"correctly.{C.E}\n")
    return 1 if failures else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Call every configured LLM lane for real.")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    sys.exit(run(as_json=ap.parse_args().json))
