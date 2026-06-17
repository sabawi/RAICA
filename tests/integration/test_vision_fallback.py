"""
Guards the vision-model FALLBACK wiring (user_tools/image_to_text.py).

Context: Ollama RETIRED the vision model `qwen3-vl:235b-cloud` on 2026-06-16 (HTTP 410), which broke ALL
image input — and the configured `fallback_model` was NOT actually used (the except block just returned an
error string). This test pins the new behavior: when the PRIMARY vision model fails, the configured
`fallback_model` is tried; if it succeeds the result is returned; if BOTH fail, a clear error is returned.

Run: python -m pytest tests/integration/test_vision_fallback.py -q
 or: python tests/integration/test_vision_fallback.py
"""
import base64
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from user_tools.image_to_text import ImageToTextTool

# A tiny valid JPEG (1x1) so _process_image_data yields usable data without needing a real photo.
_TINY_JPEG_B64 = (
    "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAx"
    "NDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAABAAAAAAAAAAAAAAAAAAAACv/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAI"
    "AQEAAD8AfwD/2Q=="
)


def _tool_with_models(primary, fallback):
    tool = ImageToTextTool()
    tool.vision_config = {"type": "ollama", "model": primary, "fallback_model": fallback}
    return tool


def test_fallback_runs_when_primary_fails():
    tool = _tool_with_models("primary-retired:cloud", "backup-good:cloud")
    calls = []

    def fake(model, prompt, img, today):
        calls.append(model)
        if model == "primary-retired:cloud":
            raise Exception("model was retired (status code: 410)")
        return {"success": True, "result": "BACKUP DESCRIPTION", "model": model}

    tool._process_with_ollama = fake
    res = tool.get_image_processing_results({"prompt": "what is this", "images": [_TINY_JPEG_B64]})
    assert calls == ["primary-retired:cloud", "backup-good:cloud"], calls
    assert res.get("success") is True and "BACKUP" in str(res.get("result")), res


def test_error_when_both_fail():
    tool = _tool_with_models("primary-retired:cloud", "backup-also-down:cloud")

    def fake(model, prompt, img, today):
        raise Exception("down (status code: 410)")

    tool._process_with_ollama = fake
    res = tool.get_image_processing_results({"prompt": "x", "images": [_TINY_JPEG_B64]})
    assert res.get("success") is False
    assert "primary-retired:cloud" in res.get("error", "") and "backup-also-down:cloud" in res.get("error", "")


def test_no_fallback_attempt_when_primary_succeeds():
    tool = _tool_with_models("primary-good:cloud", "backup:cloud")
    calls = []

    def fake(model, prompt, img, today):
        calls.append(model)
        return {"success": True, "result": "PRIMARY DESCRIPTION", "model": model}

    tool._process_with_ollama = fake
    res = tool.get_image_processing_results({"prompt": "x", "images": [_TINY_JPEG_B64]})
    assert calls == ["primary-good:cloud"], calls   # backup NOT called
    assert res.get("success") is True and "PRIMARY" in str(res.get("result"))


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS: {fn.__name__}")
    print("ALL TESTS PASSED")
