"""
S3 — Vision (image recognition). Locks in: an attached image is processed (kimi-k2.7-code:cloud, gemma3
fallback) and the description hits the known content of a fixed fixture. (Vision swap + wired fallback.)
"""
import os

from lib import raica_client as RC

SCENARIO = "S3_vision"
FIXTURE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "fixtures", "known_object.jpg"))
# Known fixture content: a RED circle, a BLUE border, and the TEXT "RAICA TEST" on white.
EXPECTED = ["red", "blue", "circle", "text"]
PROMPT = "What is in this image? Describe the shapes, colors, and any text you can read."


def _m(name, cls, value, unit, direction, tol):
    return {"scenario": SCENARIO, "name": name, "cls": cls, "value": value,
            "unit": unit, "direction": direction, "tolerance": tol}


def run(base, repeats=3):
    import time
    img = RC.encode_image(FIXTURE)
    runs = []
    for _ in range(repeats):
        t0 = time.time()
        r = RC.post_v1(PROMPT, base=base, images=[img], deep_research=False, timeout=180)
        low = (r["text"] or "").lower()
        ran = bool(r["text"]) and len(r["text"]) > 40
        hits = round(sum(1 for k in EXPECTED if k in low) / len(EXPECTED), 3)
        vis_s = RC.vision_seconds(RC.log_window_since(t0))   # Tier-2 per-stage (the kimi/minimax dial)
        runs.append(RC.unmeasured_if_no_response(r, [
            _m("vision_ran",               "CODE", ran,            "bool",    "must_equal",    0),
            _m("description_keyword_hits", "CODE", hits,           "ratio",   "higher_better", 0.25),
            _m("vision_model_s",           "PERF", vis_s,          "seconds", "lower_better",  10),
            _m("latency_s",                "PERF", r["latency_s"], "seconds", "lower_better",  20),
        ]))
    return runs
