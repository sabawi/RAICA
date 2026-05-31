"""
Deep-Research Gate
==================

High-precision, LLM-driven decision: does this request warrant the (slow, expensive)
deep-research pipeline (Stage 1+2), or should it take the normal fast path?

Design goals:
- LLM decides semantically (NOT a keyword list) — but calibrated with contrastive
  few-shot examples so it is precise, not sloppy.
- Bias toward the FAST path: only route to deep research on an explicit/strong signal
  with HIGH confidence. A false positive costs the user minutes of unexpected latency,
  so the gate must be conservative.

Returns: {"deep_research": bool, "confidence": "high|medium|low", "rationale": str}
Only `deep_research == True AND confidence == "high"` should trigger the deep pipeline.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from research.engine import extract_json_object, _collect_stream, GenerateStream

logger = logging.getLogger(__name__)

# Contrastive calibration. These are EXAMPLES that teach the LLM the boundary; they are
# not matched against the user's text. The LLM generalizes from them semantically.
_FEWSHOT = """\
Examples (request -> verdict):
- "do a deep dive into the causes of the 2008 financial crisis with sources" -> deep_research=true, high (explicit deep + multi-source synthesis)
- "thoroughly research whether creatine is safe long-term and cite studies" -> deep_research=true, high (explicit thoroughness + citations)
- "comprehensively investigate the archaeological evidence for X and debunk fringe theories" -> deep_research=true, high (broad, multi-faceted, needs fact-checking)
- "give me an in-depth, well-cited report on the state of solid-state batteries" -> deep_research=true, high (explicit depth + report)
- "what's the latest news on the Fed rate decision?" -> deep_research=false, high (simple current-events lookup)
- "who won the 2022 world cup?" -> deep_research=false, high (single fact)
- "summarize this article for me" -> deep_research=false, high (single-source task)
- "fix this python bug" / "what's 12% of 340" / "draft an email to the team" -> deep_research=false, high (non-research task)
- "tell me about black holes" -> deep_research=false, medium (general explainer; broad but no depth/thoroughness signal)
"""


async def deep_research_gate(generate_stream: GenerateStream, user_request: str) -> Dict[str, Any]:
    """Decide whether to route a request into the deep-research pipeline. Fails safe to fast path."""
    prompt = (
        "You are a precise router for a research assistant. Decide whether the user's request "
        "warrants DEEP RESEARCH — a slow, expensive pipeline that plans sub-questions, searches "
        "many sources over multiple rounds, cross-checks claims, and reconciles conflicting "
        "findings — versus the NORMAL fast path (a quick answer, possibly with one search).\n\n"
        "Route to DEEP RESEARCH only when the request genuinely calls for depth/thoroughness: it "
        "either explicitly asks for it (deep dive, thorough/comprehensive/in-depth research, "
        "investigate deeply, well-cited report, literature review) OR is a complex, multi-faceted "
        "question that clearly needs synthesis across many sources and fact-checking.\n"
        "Keep it on the FAST path for: simple lookups, single facts, 'latest news on X', "
        "summarizing one source, casual questions, coding, math, email, or anything quick.\n"
        "When unsure, prefer the FAST path (false). A wrong 'true' wastes minutes of the user's time.\n\n"
        f"{_FEWSHOT}\n"
        f"USER REQUEST:\n{user_request}\n\n"
        "Respond with STRICT JSON only, no prose:\n"
        '{"deep_research": true|false, "confidence": "high|medium|low", "rationale": "<one sentence>"}'
    )
    try:
        raw = await _collect_stream(generate_stream, prompt, temperature=0.0, max_tokens=200, stream=False)
        data = extract_json_object(raw)
        deep = bool(data.get("deep_research", False))
        conf = str(data.get("confidence", "low")).strip().lower()
        if conf not in ("high", "medium", "low"):
            conf = "low"
        rationale = str(data.get("rationale", ""))[:200]
    except Exception as e:  # noqa: BLE001 — gate failure must never block the request
        logger.warning("🚪 Deep-research gate failed (%s) → fast path", e)
        return {"deep_research": False, "confidence": "low", "rationale": f"gate error: {e}"}

    triggered = deep and conf == "high"
    logger.info("🚪 Deep-research gate: deep=%s conf=%s trigger=%s — %s",
                deep, conf, triggered, rationale)
    return {"deep_research": deep, "confidence": conf, "rationale": rationale, "triggered": triggered}
