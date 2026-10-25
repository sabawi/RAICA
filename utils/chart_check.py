"""Look at a computed chart before it is published: can a reader actually read it? (SI-115)

run_python_analysis charts were often unreadable — three translucent 3D surfaces blended into one tangle, a legend whose
colours matched nothing, one 1/r spike dwarfing two other surfaces (NewX post 9088 and its re-runs, 2026-10-25). The
writer's policy names these defects and was still ignored in 2 of 3 runs, so the chart itself is now LOOKED AT.

The vision model (vision.config: model, then fallback_model) gets the image and what it was drawn to show, and returns
a structured verdict. Measured before this was built, 2026-10-25, deepseek-v4.1-flash, 6 charts × 3: the three clearly
unreadable charts were flagged 9/9, the two clearly readable ones passed 6/6, a borderline wireframe chart split.

Fails OPEN: any failure to obtain a verdict returns None and the chart is published as before. This module never
blocks an answer.
"""
import base64
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_SCHEMA = {"type": "object",
           "properties": {"image_received": {"type": "boolean"}, "readable": {"type": "boolean"},
                          "problems": {"type": "string"}},
           "required": ["image_received", "readable", "problems"]}

CHECK_POLICY = (
    "You check a chart before it is published. It was drawn to show: {purpose}\n"
    "Judge only what a reader can SEE. readable=false when any of these holds: a series or surface the chart is meant "
    "to show is hidden, covered or blended into others so a reader cannot follow it on its own; the legend does not "
    "match what is drawn; axes or labels are missing or unreadable; one element dwarfs the rest so they cannot be read; "
    "most of the image is empty or taken up by decoration. Otherwise readable=true. In problems, name each defect in "
    "one short line (empty when readable).\n\n"
    'Respond with STRICT JSON only, no prose: {{"image_received": true|false, "readable": true|false, '
    '"problems": "<lines or empty>"}}'
)


def _vision_settings() -> Optional[dict]:
    try:
        from user_tools.image_to_text import ImageToTextTool
        return ImageToTextTool().vision_config
    except Exception as e:  # noqa: BLE001
        logger.warning("📊 chart check: no vision settings (%s) — charts publish unchecked", e)
        return None


def check_chart(image_bytes: bytes, purpose: str, timeout: float = 60.0) -> Optional[dict]:
    """Return {"readable": bool, "problems": str, "model": str}, or None when no verdict could be obtained.

    Blocking (call it with asyncio.to_thread). Thread-safe: a client timeout, no signals."""
    vc = _vision_settings()
    if not vc or str(vc.get('type', 'ollama')) != 'ollama':
        return None
    try:
        import ollama
        from research.engine import extract_json_object
    except Exception as e:  # noqa: BLE001
        logger.warning("📊 chart check unavailable (%s)", e)
        return None
    key = vc.get('api_key') or ''
    client = ollama.Client(host=vc.get('base_url') or None, timeout=timeout,
                           headers={'Authorization': f'Bearer {key}'} if key else None)
    img = base64.b64encode(image_bytes).decode()
    prompt = CHECK_POLICY.format(purpose=str(purpose)[:600])
    models = [m for m in (vc.get('model'), vc.get('fallback_model')) if m]
    for model in dict.fromkeys(models):
        try:
            resp = client.chat(model=model, messages=[{'role': 'user', 'content': prompt, 'images': [img]}],
                               format=_SCHEMA, stream=False)
            v = extract_json_object(resp['message']['content'] or '')
            if not isinstance(v, dict) or v.get('image_received') is not True or not isinstance(v.get('readable'), bool):
                raise ValueError(f"no usable verdict: {str(resp['message']['content'])[:120]!r}")
            return {"readable": v['readable'], "problems": str(v.get('problems') or '').strip()[:800], "model": model}
        except Exception as e:  # noqa: BLE001 — try the fallback model, then give up (fail open)
            logger.warning("📊 chart check with '%s' failed: %s", model, str(e)[:200])
    return None
