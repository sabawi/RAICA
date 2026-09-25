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


# ---------------------------------------------------------------------------------------------------
# SI-098: a model can answer HTTP 200 with "I can't see an image" (deepseek-v4.1-flash:cloud did, 12/12,
# 2026-09-24). That reply was returned as a SUCCESS, so the fallback never ran and the answering model
# was told there was no image. These mock ollama.chat itself, so the real reply parsing is exercised.
# ---------------------------------------------------------------------------------------------------
import json as _json
import user_tools.image_to_text as _itt


def _chat_replies(replies, calls):
    def fake_chat(model, messages, **kw):
        calls.append(model)
        return {"message": {"content": replies[model]}}
    return fake_chat


def _run_with_chat(tool, replies, calls):
    orig = _itt.ollama.chat
    _itt.ollama.chat = _chat_replies(replies, calls)
    try:
        return tool.get_image_processing_results({"prompt": "x", "images": [_TINY_JPEG_B64]})
    finally:
        _itt.ollama.chat = orig


def test_blind_primary_reply_triggers_fallback():
    """image_received:false from the primary must NOT be returned as a success -- the fallback must run."""
    tool = _tool_with_models("blind:cloud", "sighted:cloud")
    calls = []
    res = _run_with_chat(tool, {
        "blind:cloud": _json.dumps({"image_received": False, "report": "No image was visible."}),
        "sighted:cloud": _json.dumps({"image_received": True, "report": "ORANGE 314 on white"}),
    }, calls)
    assert calls == ["blind:cloud", "sighted:cloud"], calls
    assert res.get("success") is True and "ORANGE 314" in res["description"], res
    assert "No image was visible" not in res["description"]


def test_fenced_json_reply_is_unwrapped_to_the_report():
    """Cloud models wrap the JSON in ```json fences; the answering model must get the report, not raw JSON."""
    tool = _tool_with_models("sighted:cloud", "backup:cloud")
    calls = []
    res = _run_with_chat(tool, {"sighted:cloud": '```json\n{"image_received": true, "report": "a red circle"}\n```'}, calls)
    assert calls == ["sighted:cloud"], calls
    assert res.get("success") is True and "a red circle" in res["description"]
    assert "image_received" not in res["description"], res["description"]


def test_reply_breaking_the_contract_goes_to_fallback():
    """A reply with no image_received verdict cannot be trusted to have seen the image -> fallback."""
    tool = _tool_with_models("prose:cloud", "sighted:cloud")
    calls = []
    res = _run_with_chat(tool, {
        "prose:cloud": "I don't see an image attached to your message.",
        "sighted:cloud": _json.dumps({"image_received": True, "report": "bar chart, B tallest at 7"}),
    }, calls)
    assert calls == ["prose:cloud", "sighted:cloud"], calls
    assert res.get("success") is True and "B tallest" in res["description"]


def test_both_blind_is_an_honest_failure():
    """If neither model can see the image the tool must FAIL, naming both -- never return a blind 'success'."""
    tool = _tool_with_models("blind-a:cloud", "blind-b:cloud")
    calls = []
    blind = _json.dumps({"image_received": False, "report": "No image."})
    res = _run_with_chat(tool, {"blind-a:cloud": blind, "blind-b:cloud": blind}, calls)
    assert calls == ["blind-a:cloud", "blind-b:cloud"], calls
    assert res.get("success") is False
    assert "blind-a:cloud" in res["error"] and "blind-b:cloud" in res["error"]


def test_returned_failure_dict_triggers_fallback():
    """The OpenAI-compatible transport RETURNS {'success': False} instead of raising; that must fall back too."""
    tool = _tool_with_models("returns-failure:cloud", "backup-good:cloud")
    calls = []

    def fake(model, prompt, img, today):
        calls.append(model)
        if model == "returns-failure:cloud":
            return {"success": False, "error": "API error: 404"}
        return {"success": True, "result": "BACKUP DESCRIPTION", "model": model}

    tool._process_with_ollama = fake
    res = tool.get_image_processing_results({"prompt": "x", "images": [_TINY_JPEG_B64]})
    assert calls == ["returns-failure:cloud", "backup-good:cloud"], calls
    assert res.get("success") is True and "BACKUP" in str(res.get("result"))


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS: {fn.__name__}")
    print("ALL TESTS PASSED")
