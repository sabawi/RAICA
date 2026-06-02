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
import re
import time
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

from research.engine import DeepResearchEngine
from research.synthesis import ResearchSynthesizer

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r'https?://[a-zA-Z0-9./_%?=&:+~#-]+')


def _domain_of(url: str) -> str:
    try:
        net = urlparse(url).netloc.lower()
        return net[4:] if net.startswith("www.") else net
    except Exception:
        return ""


def _credibility_tally(credibility: Optional[Dict[str, str]]) -> str:
    counts: Dict[str, int] = {}
    for tier in (credibility or {}).values():
        counts[tier] = counts.get(tier, 0) + 1
    order = ["peer_reviewed", "reputable", "popular", "low_credibility", "unknown"]
    parts = [f"{t}: {counts[t]}" for t in order if counts.get(t)]
    return ", ".join(parts) if parts else "n/a"


def _timing_breakdown(engine_meta: Dict[str, Any], synth_meta: Dict[str, Any],
                      total_seconds: float) -> str:
    """One-line per-phase timing so the bottleneck is visible at a glance."""
    engine_meta = engine_meta or {}
    st = (synth_meta or {}).get("timings", {}) or {}
    parts = [
        f"plan {engine_meta.get('plan_seconds', 0)}s",
        f"gather {engine_meta.get('gather_seconds', 0)}s",
    ]
    if "grade" in st:
        parts.append(f"grade {st['grade']}s")
    if "synthesize" in st:
        parts.append(f"synthesize {st['synthesize']}s")
    if "arbitrate" in st:
        parts.append(f"arbitrate {st['arbitrate']}s")
    if "verify" in st:
        parts.append(f"verify {st['verify']}s")
    return f"**Total {total_seconds}s** — " + " · ".join(parts)


def _format_claim_line(c: Dict[str, Any]) -> str:
    text = str(c.get("text", "")).strip()
    note = str(c.get("note", "")).strip()
    raw_cites = c.get("citations") or []
    cites = " ".join(str(u) for u in raw_cites if u) if isinstance(raw_cites, list) else str(raw_cites)
    line = f"- {text or '(claim text unavailable)'}"
    if note:
        line += f" — _{note}_"
    if cites:
        line += f"  ({cites})"
    return line


def _flagged_claims_section(verification: Dict[str, Any]) -> str:
    """
    Surface claims the verifier did not fully support, split by WHAT the flag means:
      - scrutiny: the answer may be wrong/ungrounded (contradicted_by_evidence / not_in_evidence)
      - source notes: the answer is correctly attributing a claim to a low-credibility source
        (attributed_to_low_credibility) — a feature (fair presentation), not a defect.

    Defensive: the verifier is an LLM returning arbitrary JSON, so every claim is coerced
    and non-dict entries are skipped — a malformed claim must never crash the user's footer.
    """
    raw = verification.get("claims") or []
    claims = [c for c in raw if isinstance(c, dict)]
    if not claims:
        return ""

    def reason(c):
        return str(c.get("flag_reason", "")).lower()

    def verdict(c):
        return str(c.get("verdict", "")).lower()

    scrutiny = [c for c in claims
                if verdict(c) in ("contradicted", "unverified")
                and reason(c) != "attributed_to_low_credibility"]
    low_cred = [c for c in claims if reason(c) == "attributed_to_low_credibility"]

    parts = []
    if scrutiny:
        parts.append("\n\n**⚠️ Claims to scrutinize** (the answer may overstate these — the evidence "
                     "contradicts them or does not cover them; verify before relying on them):")
        parts.extend(_format_claim_line(c) for c in scrutiny)
    if low_cred:
        parts.append("\n\n**ℹ️ Attributed to low-credibility sources** (the answer reports these as "
                     "claims made BY the cited source, not as established fact — included for balance; "
                     "weigh the source accordingly):")
        parts.extend(_format_claim_line(c) for c in low_cred)
    if not parts:
        return "\n- **✅ Verification:** all checked claims are evidence-supported"
    return "\n".join(parts)


def _low_cred_cited_section(answer_text: str, credibility: Dict[str, str],
                            reasons: Dict[str, str]) -> str:
    """
    Footnote each LOW-CREDIBILITY source the ANSWER actually CITED, with the specific
    credibility concern. Cross-references the answer's URLs against the graded low-cred
    domains so the reader knows whether the answer leaned on sketchy sources (and why).
    """
    credibility = credibility or {}
    reasons = reasons or {}
    low_cred_domains = {d for d, t in credibility.items() if str(t).lower() == "low_credibility"}
    if not low_cred_domains or not answer_text:
        return ""
    # Which low-cred domains are actually cited in the answer body?
    cited = {}
    for url in _URL_RE.findall(answer_text):
        d = _domain_of(url.rstrip(".,);"))
        if d in low_cred_domains and d not in cited:
            cited[d] = url.rstrip(".,);")
    if not cited:
        return ""
    lines = ["\n\n**⚠️ Low-credibility sources cited in this answer** — the response references the "
             "following sources that were graded low-credibility; weigh them accordingly:"]
    for d in sorted(cited):
        reason = reasons.get(d, "graded low-credibility")
        lines.append(f"- **{d}** — _{reason}_  ({cited[d]})")
    return "\n".join(lines)


def _grounding_caveat(verification: Dict[str, Any]) -> str:
    """
    Honest grounding signal: if a large fraction of the answer's claims could not be
    corroborated by the gathered evidence, the answer likely over-reached its sources
    (e.g. an enumeration that listed items the thin evidence didn't actually support).
    Surfaces a caveat so the reader knows the breadth came at the cost of grounding.
    """
    vc = (verification or {}).get("verdict_counts") or {}
    supported = int(vc.get("supported", 0))
    unverified = int(vc.get("unverified", 0))
    contradicted = int(vc.get("contradicted", 0))
    total = supported + unverified + contradicted
    if total < 8:  # too few claims to judge reliability
        return ""
    weak_frac = (unverified + contradicted) / total
    if weak_frac >= 0.30:  # ≥30% of claims not solidly grounded
        return (
            f"\n\n**⚠️ Grounding caveat:** {round(weak_frac * 100)}% of this answer's claims "
            f"({unverified + contradicted} of {total}) could not be corroborated by the gathered "
            "evidence. The answer may reach beyond what the sources solidly support — treat the "
            "less-grounded portions (see flags above) as tentative, and consider a follow-up query "
            "for deeper sourcing."
        )
    return ""


def _verification_footer(engine_meta: Dict[str, Any], synth_result: Dict[str, Any],
                         total_seconds: float, answer_text: str = "") -> str:
    engine_meta = engine_meta or {}
    synth_result = synth_result or {}
    cred = synth_result.get("credibility") or {}
    cred_reasons = synth_result.get("credibility_reasons") or {}
    verification = synth_result.get("verification") or {}
    vc = verification.get("verdict_counts") or {}
    meta = synth_result.get("metadata") or {}
    verdicts = ", ".join(f"{k}: {v}" for k, v in vc.items()) or "n/a"
    models = ", ".join(str(m) for m in (meta.get("models") or []))
    return (
        "\n\n---\n### 🔎 Research Audit\n"
        f"- **Evidence:** {engine_meta.get('evidence_items', 0)} results across "
        f"{engine_meta.get('rounds', 0)} round(s), {engine_meta.get('unique_urls', 0)} unique sources "
        f"({engine_meta.get('total_chars', 0):,} chars)\n"
        f"- **Source credibility:** {_credibility_tally(cred)}\n"
        f"- **Claims checked:** {meta.get('claims_checked', 0)} ({verdicts})\n"
        f"- **Synthesis:** {'arbitrated across ' if meta.get('arbitrated') else ''}{models}\n"
        f"- **Stop reason:** {engine_meta.get('stop_reason', 'n/a')}\n"
        f"- **⏱️ Timing:** {_timing_breakdown(engine_meta, meta, total_seconds)}"
        + _grounding_caveat(verification)
        + _low_cred_cited_section(answer_text, cred, cred_reasons)
        + _flagged_claims_section(verification)
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

    pipeline_start = time.monotonic()
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

    total_seconds = round(time.monotonic() - pipeline_start, 1)
    answer = (stage2.get("final_answer") or "").rstrip()
    if not answer:
        answer = ("Deep research gathered evidence but the synthesis step produced no answer. "
                  "Please try again.")
    if config.get("output", {}).get("include_audit_footer", True):
        # The footer is cosmetic — never let a footer error discard a hard-won answer.
        # Pass the answer body so the footer can footnote low-cred sources it actually cited.
        try:
            answer += _verification_footer(engine_meta, stage2, total_seconds, answer_text=answer)
        except Exception as e:  # noqa: BLE001
            logger.warning("🔎 Research audit footer failed to render (%s) — answer kept", e)
    await emit("Done.")
    logger.info("🧪 Deep research pipeline complete in %ss: %s", total_seconds, stage2.get("metadata"))
    return {"answer": answer, "engine_metadata": engine_meta,
            "synth_metadata": stage2["metadata"], "total_seconds": total_seconds}
