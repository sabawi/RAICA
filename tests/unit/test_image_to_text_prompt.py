"""Regression guard for SI-097: the vision tool must send its configured system prompt AS WRITTEN.

image_to_text.py used to replace any system prompt of 500+ chars with a generic one-liner. The
SCOPE policy that stops the vision model inventing figures the image does not show (a "hypothetical
price" for an image containing only a ticker) pushed the prompt past that cap, so the fix would have
been silently discarded. These tests fail on that code.
"""
import asyncio
import base64
import io

from PIL import Image

from user_tools.image_to_text import ImageToTextTool


def _png_b64():
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _captured_prompt(system_prompt):
    tool = ImageToTextTool()
    tool.system_prompt = system_prompt
    tool.vision_config = dict(tool.vision_config, type="ollama", fallback_model=None)
    seen = {}

    def fake(model, prompt, image_data, timestamp):
        seen["prompt"] = prompt
        return {"success": True, "description": "ok", "model": model, "timestamp": timestamp}

    tool._process_with_ollama = fake
    asyncio.run(tool.execute(prompt="USER-QUESTION-MARKER", image=_png_b64()))
    return seen["prompt"]


def test_long_system_prompt_reaches_the_model_unchanged():
    """A >=500-char system prompt must not be swapped for a generic default (the SI-097 trap)."""
    long_prompt = "POLICY-START " + ("x" * 900) + " POLICY-END"
    sent = _captured_prompt(long_prompt)
    assert sent.startswith(long_prompt)
    assert "USER-QUESTION-MARKER" in sent


def test_shipped_prompt_file_is_sent_in_full():
    """The prompt actually shipped in config/ is what the model receives, whatever its length."""
    tool = ImageToTextTool()
    sent = _captured_prompt(tool.system_prompt)
    assert sent.startswith(tool.system_prompt)
