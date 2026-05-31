"""
Deep Research Pipeline
======================

Single entry point that runs Stage 1 (evidence gathering) -> Stage 2 (synthesis,
arbitration, verification) and returns a trust-annotated, user-facing answer.

Dependency-injected so it stays decoupled from the server and unit-testable:
  * generate_stream(prompt, **kwargs) -> async iterator[str]   (Primary LLM)
  * dispatch_tool(tool_name, query)   -> awaitable[str]        (existing tools)
  * config: the deep_research.engine config dict
  * on_progress: optional async callable(str) for live status streaming
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from research.engine import DeepResearchEngine
from research.synthesis import ResearchSynthesizer

logger = logging.getLogger(__name__)


def _credibility_tally(credibility: Dict[str, str]) -> str:
    counts: Dict[str, int] = {}
    for tier in credibility.values():
        counts[tier] = counts.get(tier, 0) + 1
    order = ["peer_reviewed", "reputable", "popular", "low_credibility", "unknown"]
    parts = [f"{t}: {counts[t]}" for t in order if counts.get(t)]
    return ", ".join(parts) if parts else "n/a"


def _verification_footer(engine_meta: Dict[str, Any], synth_result: Dict[str, Any]) -> str:
    cred = synth_result.get("credibility", {})
    vc = synth_result.get("verification", {}).get("verdict_counts", {})
    meta = synth_result.get("metadata", {})
    verdicts = ", ".join(f"{k}: {v}" for k, v in vc.items()) or "n/a"
    models = ", ".join(meta.get("models", []))
    return (
        "\n\n---\n### 🔎 Research Audit\n"
        f"- **Evidence:** {engine_meta.get('evidence_items', 0)} results across "
        f"{engine_meta.get('rounds', 0)} round(s), {engine_meta.get('unique_urls', 0)} unique sources "
        f"({engine_meta.get('total_chars', 0):,} chars)\n"
        f"- **Source credibility:** {_credibility_tally(cred)}\n"
        f"- **Claims checked:** {meta.get('claims_checked', 0)} ({verdicts})\n"
        f"- **Synthesis:** {'arbitrated across ' if meta.get('arbitrated') else ''}{models}\n"
        f"- **Stop reason:** {engine_meta.get('stop_reason', 'n/a')}"
    )


async def run_deep_research_pipeline(
    generate_stream: Callable,
    dispatch_tool: Callable,
    config: Dict[str, Any],
    user_request: str,
    on_progress: Optional[Callable] = None,
) -> Dict[str, Any]:
    """
    Execute the full deep-research flow. Returns:
      {"answer": <markdown str for the user>, "engine_metadata": {...}, "synth_metadata": {...}}
    Raises only on planner failure (no evidence to work with); individual source failures
    are tolerated upstream.
    """
    async def emit(msg: str):
        if on_progress:
            await on_progress(msg)

    engine = DeepResearchEngine(generate_stream, dispatch_tool, config)
    stage1 = await engine.run(user_request, on_progress=on_progress)
    evidence: List[Dict[str, Any]] = stage1["evidence"]
    engine_meta = stage1["metadata"]

    if not evidence:
        await emit("No sources could be retrieved.")
        return {
            "answer": ("I attempted deep research but could not retrieve any usable sources "
                       "(all configured search backends failed or returned nothing). "
                       "Please try again shortly."),
            "engine_metadata": engine_meta,
            "synth_metadata": {},
        }

    synthesizer = ResearchSynthesizer(generate_stream, config)
    stage2 = await synthesizer.run(user_request, evidence, on_progress=on_progress)

    answer = stage2["final_answer"].rstrip() + _verification_footer(engine_meta, stage2)
    await emit("Done.")
    logger.info("🧪 Deep research pipeline complete: %s", stage2.get("metadata"))
    return {"answer": answer, "engine_metadata": engine_meta, "synth_metadata": stage2["metadata"]}
