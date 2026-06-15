"""
Pure scoring helpers for the intent-classifier baseline (Phase 3a). Shared by the live harness
(run_intent_eval.py) and the deterministic regression test (test_intent_eval_baseline.py).

EVAL-ONLY — this tool→kind mapping is measurement code, not the production LLM-driven path.
"""
from typing import Dict, Iterable, Set

DELIVERY_KINDS = {"file", "email", "publish", "image"}

_KIND = {
    "sandboxed_executor": "file", "pdf_generator": "file", "html_generator": "file",
    "document_generator": "file", "create_file": "file", "save_file": "file",
    "generate_pdf": "file", "render_pdf": "file", "export_pdf": "file",
    "secure_email_sender": "email", "email": "email", "send_email": "email", "send_mail": "email",
    "social_media_wordpress": "publish", "social_media_twitter": "publish",
    "social_media_medium": "publish", "social_media_substack": "publish",
    "analytical_visualizer": "image", "generate_infographic": "image",
    "create_chart": "image", "make_flowchart": "image",
}


def kind_of(tool: str) -> str:
    """Map a tool name to a delivery KIND. Generic rules tolerate registry naming (e.g.
    social_media_*_test) so scoring isn't distorted by exact tool names."""
    if tool in _KIND:
        return _KIND[tool]
    if tool.startswith("social_media"):
        return "publish"
    base = tool[:-5] if tool.endswith("_test") else tool
    return _KIND.get(base, base)


def delivery_kinds(tool_names: Iterable[str]) -> Set[str]:
    """The set of DELIVERY kinds among the given tool names."""
    return {kind_of(t) for t in (tool_names or [])} & DELIVERY_KINDS


def score(truth_needs: bool, truth_kinds: Set[str], pred_needs: bool, pred_kinds: Set[str]) -> Dict[str, bool]:
    """needs_ok = delivery decision matches; full_ok = decision AND kind-set match."""
    needs_ok = bool(pred_needs) == bool(truth_needs)
    return {"needs_ok": needs_ok, "full_ok": needs_ok and (set(pred_kinds) == set(truth_kinds))}
