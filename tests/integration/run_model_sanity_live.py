#!/usr/bin/env python3
"""
LIVE MODEL SANITY SUITE — vision, coding, and multi-model combo, each run N times.

Complements test_all_lanes_live.py (one call per lane, "is it served?"). This asks
"does each model DO the job, repeatedly, through the paths RAICA actually uses?":

  A) VISION
     A1  each configured vision model (vision.config.model + fallback_model), direct
     A2  ImageToTextTool.execute() as configured             (the real tool path)
     A3  ImageToTextTool with a dead primary                 (the FALLBACK branch)
     A4  the running server's /v1 endpoint with an image     (end to end)
  B) CODING — generated code is EXECUTED against asserts; "looks like code" is not a pass
     B1  CodeGenLLMClient.generate() for every code_generation preset model
     B2  every NewX bot plugin YAML whose model is passed in --newx-bot-models
     B3  the running server: write-and-run code, check the computed numbers
  C) MULTI-MODEL COMBO — one server request that must pass through vision, tool
     calling, arbitration and primary synthesis; the log slice proves each lane fired
     with the configured model.

Models are read from config/llm_config.yaml — nothing is hardcoded here, so the suite
follows the config. Run with the local server up (./start_complete.sh):

    python tests/integration/run_model_sanity_live.py [--runs 3] [--only A,B,C]

Exit 0 only if every case passes on every run. Pass RATES are printed per case,
because a single green run of a stochastic system is not evidence.
"""
import argparse
import asyncio
import base64
import io
import json
import logging
import math
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
CFG = yaml.safe_load((ROOT / "config" / "llm_config.yaml").read_text())
OLLAMA = CFG["llm"]["providers"]["ollama"]["base_url"]
SERVER = "http://localhost:5000"
LOG = ROOT / "logs" / "server_complete.log"
NEWX_PLUGINS = ROOT.parent / "NewX" / "newx" / "ai_plugins"

RESULTS = {}


def record(case, ok, detail):
    RESULTS.setdefault(case, []).append((ok, detail))
    mark = "\033[92m✓\033[0m" if ok else "\033[91m✗\033[0m"
    print(f"  {mark} {case:<58} {detail[:400]}", flush=True)


# ---------------------------------------------------------------- fixtures
def _font(size):
    try:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _png(im):
    b = io.BytesIO()
    im.save(b, "PNG")
    return base64.b64encode(b.getvalue()).decode()


def img_ocr():
    im = Image.new("RGB", (520, 200), "white")
    ImageDraw.Draw(im).text((30, 50), "ORANGE 314", fill="black", font=_font(64))
    return _png(im)


def img_shapes():
    im = Image.new("RGB", (500, 250), "white")
    d = ImageDraw.Draw(im)
    d.ellipse((40, 50, 190, 200), fill=(220, 0, 0))
    d.rectangle((300, 50, 450, 200), fill=(0, 0, 220))
    return _png(im)


def img_chart():
    im = Image.new("RGB", (500, 360), "white")
    d = ImageDraw.Draw(im)
    for i, (label, val) in enumerate([("A", 3), ("B", 7), ("C", 5)]):
        x = 80 + i * 130
        d.rectangle((x, 300 - val * 35, x + 80, 300), fill=(60, 120, 200))
        d.text((x + 28, 310), label, fill="black", font=_font(32))
        d.text((x + 28, 300 - val * 35 - 40), str(val), fill="black", font=_font(28))
    d.line((60, 300, 480, 300), fill="black", width=3)
    return _png(im)


def img_ticker():
    im = Image.new("RGB", (560, 200), "white")
    ImageDraw.Draw(im).text((30, 60), "Ticker: KO", fill="black", font=_font(60))
    return _png(im)


def _has(text, *words):
    t = text.lower()
    return all(w.lower() in t for w in words)


VISION_CASES = [
    ("ocr", img_ocr, "What text is written in this image? Reply with the exact text.",
     lambda r: _has(r, "orange", "314")),
    ("shapes", img_shapes, "Name each shape in this image and its color.",
     lambda r: _has(r, "red", "blue", "circle") and ("square" in r.lower() or "rectangle" in r.lower())),
    ("chart", img_chart, "This is a bar chart. Which bar label is tallest, and what is its value?",
     lambda r: re.search(r"\bB\b", r) is not None and re.search(r"\b7\b", r) is not None),
]


# ---------------------------------------------------------------- transport
def post(url, body, timeout=600):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def ollama_chat(model, prompt, image=None, system=None):
    msgs = [{"role": "system", "content": system}] if system else []
    m = {"role": "user", "content": prompt}
    if image:
        m["images"] = [image]
    msgs.append(m)
    d = post(f"{OLLAMA}/api/chat", {"model": model, "messages": msgs, "stream": False,
                                     "options": {"num_predict": 4096}})
    return d["message"]["content"]


def server_chat(prompt, image=None):
    content = prompt if not image else [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + image}}]
    d = post(f"{SERVER}/v1/chat/completions",
             {"model": "raica", "stream": False, "messages": [{"role": "user", "content": content}]},
             timeout=900)
    return d["choices"][0]["message"]["content"]


class _Capture(logging.Handler):
    """In-process log capture: A2/A3 run the tool inside THIS process, so their log
    lines never reach server_complete.log."""
    def __init__(self):
        super().__init__(logging.INFO)
        self.lines = []

    def emit(self, rec):
        self.lines.append(rec.getMessage())


def log_mark():
    return LOG.stat().st_size


def log_since(mark):
    with open(LOG, "rb") as f:
        f.seek(mark)
        return f.read().decode("utf-8", "replace")


# ---------------------------------------------------------------- A) vision
def vision_models():
    v = CFG["vision"]["config"]
    return [("main", v["model"]), ("fallback", v.get("fallback_model"))]


def run_vision(runs):
    print("\n\033[1mA) VISION\033[0m")
    from user_tools.image_to_text import ImageToTextTool
    for role, model in vision_models():
        if not model:
            continue
        for name, mk, q, check in VISION_CASES:
            for i in range(runs):
                try:
                    r = ollama_chat(model, q, mk())
                    record(f"A1 {role} {model} {name}", check(r), repr(r[:100]))
                except Exception as e:
                    record(f"A1 {role} {model} {name}", False, f"ERR {e}")

    for name, mk, q, check in VISION_CASES:
        for i in range(runs):
            tool = ImageToTextTool()
            r = asyncio.run(tool.execute(prompt=q, image=mk()))
            text = json.dumps(r) if not isinstance(r, str) else r
            ok = not (isinstance(r, dict) and r.get("success") is False) and check(text)
            record(f"A2 tool path ({tool.vision_config['model']}) {name}", ok, text[:100])

    # A3: dead primary -> must recover via fallback_model. The injected name is
    # deliberately unservable so the primary call raises and the fallback branch runs.
    fb = CFG["vision"]["config"].get("fallback_model")
    for i in range(runs):
        tool = ImageToTextTool()
        tool.vision_config = dict(tool.vision_config, model="sanity-nonexistent-vision-model:cloud")
        cap = _Capture()
        logging.getLogger().addHandler(cap)
        logging.getLogger().setLevel(logging.INFO)
        try:
            r = asyncio.run(tool.execute(prompt=VISION_CASES[0][2], image=img_ocr()))
        finally:
            logging.getLogger().removeHandler(cap)
        text = json.dumps(r) if not isinstance(r, str) else r
        fired = any(f"Fallback vision model '{fb}' succeeded" in l for l in cap.lines)
        ok = fired and not (isinstance(r, dict) and r.get("success") is False) and VISION_CASES[0][3](text)
        record(f"A3 fallback branch -> {fb}", ok, f"fallback_logged={fired} " + text[:80])

    for name, mk, q, check in VISION_CASES:
        for i in range(runs):
            mark = log_mark()
            try:
                r = server_chat(q, mk())
                used = CFG["vision"]["config"]["model"] in log_since(mark)
                record(f"A4 server /v1 {name}", check(r) and used, f"vision_model_in_log={used} {r[:80]!r}")
            except Exception as e:
                record(f"A4 server /v1 {name}", False, f"ERR {e}")


# ---------------------------------------------------------------- B) coding
CODE_TASKS = [
    ("roman_to_int", "Write a Python function roman_to_int(s: str) -> int that converts a Roman numeral to an integer.",
     "assert roman_to_int('III')==3\nassert roman_to_int('LVIII')==58\nassert roman_to_int('MCMXCIV')==1994\nassert roman_to_int('IX')==9"),
    ("merge_intervals", "Write a Python function merge_intervals(intervals: list[list[int]]) -> list[list[int]] that merges all overlapping intervals and returns them sorted by start.",
     "assert merge_intervals([[1,3],[2,6],[8,10],[15,18]])==[[1,6],[8,10],[15,18]]\nassert merge_intervals([[1,4],[4,5]])==[[1,5]]\nassert merge_intervals([])==[]\nassert merge_intervals([[5,7],[1,2]])==[[1,2],[5,7]]"),
    ("valid_parens", "Write a Python function is_valid(s: str) -> bool that returns True if the brackets ()[]{} in s are balanced and correctly nested.",
     "assert is_valid('()[]{}')\nassert not is_valid('(]')\nassert is_valid('{[()()]}')\nassert not is_valid('([)]')\nassert is_valid('')\nassert not is_valid('((')"),
]
CODE_SUFFIX = " Return ONLY one ```python code block containing the function, with no example usage."


def extract_code(text):
    blocks = re.findall(r"```(?:python|py)?\s*\n(.*?)```", text, re.S)
    return max(blocks, key=len) if blocks else text


def run_asserts(code, asserts):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(code + "\n\n" + asserts + "\nprint('ALL_ASSERTS_PASSED')\n")
    try:
        p = subprocess.run([sys.executable, f.name], capture_output=True, text=True, timeout=20)
        return "ALL_ASSERTS_PASSED" in p.stdout, (p.stderr.strip().splitlines() or ["ok"])[-1]
    except subprocess.TimeoutExpired:
        return False, "timeout"
    finally:
        Path(f.name).unlink(missing_ok=True)


def run_coding(runs, newx_bot_models):
    print("\n\033[1mB) CODING\033[0m")
    from agents.coding_agent.llm_client import CodeGenLLMClient
    cg = CFG["code_generation"]
    models = sorted({(p["provider"], p["model"]) for p in cg["model_presets"].values()
                     if p.get("provider") == "ollama"})
    for provider, model in models:
        client = CodeGenLLMClient(provider_override=provider, model_override=model)
        for name, task, asserts in CODE_TASKS:
            for i in range(runs):
                try:
                    r = client.generate(task + CODE_SUFFIX)
                    if r.model != model:
                        record(f"B1 codegen {model} {name}", False, f"served by {r.provider}/{r.model} (fell back)")
                        continue
                    ok, why = run_asserts(extract_code(r.content), asserts)
                    record(f"B1 codegen {model} {name}", ok, why)
                except Exception as e:
                    record(f"B1 codegen {model} {name}", False, f"ERR {e}")

    for yml in sorted(NEWX_PLUGINS.glob("*.yaml")):
        bot = yaml.safe_load(yml.read_text()) or {}
        api = bot.get("api", {})
        if api.get("model") not in newx_bot_models:
            continue
        for name, task, asserts in CODE_TASKS:
            for i in range(runs):
                try:
                    d = post(api["endpoint"], {"model": api["model"], "messages": [
                        {"role": "system", "content": api.get("system_prompt", "")},
                        {"role": "user", "content": task + CODE_SUFFIX}]}, timeout=api.get("timeout", 180))
                    ok, why = run_asserts(extract_code(d["choices"][0]["message"]["content"]), asserts)
                    record(f"B2 NewX @{bot['username']} ({api['model']}) {name}", ok, why)
                except Exception as e:
                    record(f"B2 NewX @{bot['username']} {name}", False, f"ERR {e}")

    # B3: ground truth computed HERE, independently of the model.
    fib = [0, 1]
    while len(fib) <= 30:
        fib.append(fib[-1] + fib[-2])
    primes = sum(n for n in range(2, 10000) if all(n % k for k in range(2, math.isqrt(n) + 1)))
    q = ("Write Python code and EXECUTE it to compute (1) the 30th Fibonacci number where F(1)=1 and F(2)=1, "
         "and (2) the sum of all prime numbers below 10000. Report both results.")
    tc_model = CFG["llm"]["tool_calling"]["config"]["model"]
    for i in range(runs):
        mark = log_mark()
        try:
            r = server_chat(q)
            lg = log_since(mark)
            nums = r.replace(",", "")
            ok_nums = str(fib[30]) in nums and str(primes) in nums
            tc = f"Tool calling request: {tc_model}" in lg
            record("B3 server write+execute code", ok_nums and tc,
                   f"F30={fib[30]} in={str(fib[30]) in nums} primes={primes} in={str(primes) in nums} tool_lane={tc}")
        except Exception as e:
            record("B3 server write+execute code", False, f"ERR {e}")


# ---------------------------------------------------------------- C) combo
def run_combo(runs):
    print("\n\033[1mC) MULTI-MODEL COMBO (vision -> tools -> arbitration -> primary)\033[0m")
    lanes = {
        "vision": f"vision processing with {CFG['vision']['config']['model']}",
        "tool_calling": f"Tool calling request: {CFG['llm']['tool_calling']['config']['model']}",
        "primary": f"streaming request: model={CFG['llm']['primary']['config']['model']}",
    }
    q = ("Read the stock ticker shown in this image, look up that company's current stock price, "
         "and tell me how many whole shares $10,000 would buy at that price.")
    for i in range(runs):
        mark = log_mark()
        try:
            r = server_chat(q, img_ticker())
            lg = log_since(mark)
            fired = {k: (v in lg) for k, v in lanes.items()}
            # The arbitrator ALWAYS runs, but it skips its LLM call when a tool result
            # already carries a pre-detected error. Either path is legitimate; report which.
            arb_llm = "No pre-detected errors - calling arbitrator LLM" in lg
            arb_bypass = "bypassing LLM call" in lg
            fired["arbitrator"] = arb_llm or arb_bypass
            tool_errs = lg.count("Tool 'compute' error")
            stock = "get_stock_and_company_data" in lg or "comprehensive_stock_analyzer" in lg
            price = re.search(r"\$\s?(\d{2,4}\.\d{2})", r)
            shares_ok = False
            if price:
                expect = math.floor(10000 / float(price.group(1)))
                shares_ok = re.search(rf"\b{expect}\b", r.replace(",", "")) is not None
            names_ko = _has(r, "ko") or _has(r, "coca")
            ok = all(fired.values()) and stock and names_ko and shares_ok
            record("C  image->ticker->price->shares", ok,
                   f"lanes={fired} arbitrator={'LLM' if arb_llm else 'bypassed(pre-detected tool error)'} "
                   f"compute_error_lines={tool_errs} stock_tool={stock} KO={names_ko} "
                   f"price={price.group(1) if price else None} shares_consistent={shares_ok}")
        except Exception as e:
            record("C  image->ticker->price->shares", False, f"ERR {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--only", default="A,B,C")
    ap.add_argument("--newx-bot-models", default="",
                    help="comma-separated models; NewX bots on these models get the coding test")
    a = ap.parse_args()
    parts = set(a.only.upper().split(","))
    t0 = time.time()
    if "A" in parts:
        run_vision(a.runs)
    if "B" in parts:
        run_coding(a.runs, set(filter(None, a.newx_bot_models.split(","))))
    if "C" in parts:
        run_combo(a.runs)

    print("\n\033[1mPASS RATES\033[0m")
    all_ok = True
    for case, rs in RESULTS.items():
        n = sum(ok for ok, _ in rs)
        all_ok &= n == len(rs)
        print(f"  {'✓' if n == len(rs) else '✗'} {n}/{len(rs)}  {case}")
    print(f"\n{'ALL PASS' if all_ok else 'FAILURES PRESENT'} — {time.time() - t0:.0f}s")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
