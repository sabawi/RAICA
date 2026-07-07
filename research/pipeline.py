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

from research.engine import (DeepResearchEngine, _collect_stream, extract_json_object,
                             configure_retry, set_retry_notice_callback)
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


def _format_tool_catalog(tool_catalog: Optional[List[Dict[str, Any]]]) -> str:
    """Render the live tool catalog (name + description) for the decomposition prompt. The action
    vocabulary is grounded in THIS list — the LLM may only name capabilities that exist here."""
    if not tool_catalog:
        return "(no delivery/action tools are currently available)"
    lines = []
    for t in tool_catalog:
        name = (t.get("name") or "").strip()
        desc = (t.get("description") or "").strip().replace("\n", " ")
        if name:
            lines.append(f"- {name}: {desc}")
    return "\n".join(lines) if lines else "(no delivery/action tools are currently available)"


async def _decompose_request(
    generate_stream: Callable, config: Dict[str, Any], user_request: str,
    tool_catalog: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Phase 1 (orchestration retrofit): LLM-decompose a possibly-compound request into three parts:

      {"research_request": <delivery-stripped research+writing intent>,
       "deliverable_spec": {<format/length/style/sections of the written artifact>},
       "actions":          [{"type": <capability from the live tool catalog>, "args": {...}}, ...]}

    The research engine + synthesizer run ONLY on `research_request` (so they never refuse over
    "can't email/PDF" — Phase 0 behavior is preserved). `deliverable_spec` + `actions` are returned
    for the orchestrator's downstream fan-out (Phase 2+), which is NOT executed here.

    OPEN VOCABULARY (Principle 6): `actions[].type` is grounded in the provided `tool_catalog` — the
    LLM names only capabilities that actually exist; the vocabulary grows as tools are added, with no
    code change here. On ANY failure this degrades gracefully to {research_request: original,
    deliverable_spec: {}, actions: []} so a research run is never aborted or made worse than legacy.
    """
    catalog_text = _format_tool_catalog(tool_catalog)
    system_prompt = (
        "You are the request decomposer for a RESEARCH-AND-WRITING engine. The engine's ONLY job is "
        "to research a topic and write the requested content (paper, report, brief, etc.). Separate "
        "DELIVERY/PACKAGING — generating files (PDF/HTML), saving, emailing, posting, generating "
        "images/infographics/diagrams, scheduling, etc. — which is performed AFTER writing by separate "
        "tools. Decompose the USER REQUEST into STRICT JSON with exactly these keys:\n"
        "  \"research_request\": the research-and-writing instructions ONLY (topic, scope, required "
        "sections/structure/format of the WRITTEN content, length, citation/accuracy requirements). "
        "REMOVE every delivery/packaging instruction (file formats, saving, emailing, posting, image/"
        "diagram generation, scheduling) and remove recipient addresses. Keep content requirements "
        "close to verbatim; do not invent requirements.\n"
        "  \"deliverable_spec\": an object describing the written artifact to produce (e.g. "
        "{\"format\":\"academic_paper\",\"min_words\":1500,\"style\":\"arXiv\",\"sections\":[...]}). "
        "Empty object {} if the user only wants a plain answer.\n"
        "  \"actions\": an array of downstream delivery/packaging actions the user requested, each "
        "{\"type\": <capability>, \"args\": {...}}. The \"type\" MUST be the name of an AVAILABLE "
        "CAPABILITY from the list below — never invent capability names. Put any parameters the "
        "action needs into args — e.g. for an email action include the recipient(s): "
        "\"args\": {\"to\": [\"name@example.com\"]}. If the user requests something with no matching "
        "capability, include {\"type\":\"unsupported\",\"args\":{\"requested\":\"<what they asked>\"}} "
        "so it can be reported. Empty array [] if the user requested no delivery/packaging.\n\n"
        "AVAILABLE CAPABILITIES (name: description):\n" + catalog_text + "\n\n"
        "Respond with STRICT JSON only, no prose."
    )
    prompt = f"USER REQUEST:\n{user_request}"
    fallback = {"research_request": user_request, "deliverable_spec": {}, "actions": []}
    try:
        raw = await _collect_stream(generate_stream, prompt, system_prompt=system_prompt,
                                    temperature=0.0, max_tokens=2000, stream=False)
        data = extract_json_object(raw)
        research_request = (data.get("research_request") or "").strip()
        if not research_request:
            logger.warning("🔬 request decomposition returned no research_request → using original")
            return fallback
        deliverable_spec = data.get("deliverable_spec") if isinstance(data.get("deliverable_spec"), dict) else {}
        actions = data.get("actions") if isinstance(data.get("actions"), list) else []
        return {"research_request": research_request, "deliverable_spec": deliverable_spec, "actions": actions}
    except Exception as e:  # noqa: BLE001 — decomposition is best-effort; never abort a research run
        logger.warning("🔬 request decomposition failed (%s) → using original request", e)
        return fallback


async def run_deep_research_pipeline(
    generate_stream: Callable,
    dispatch_tool: Callable,
    config: Dict[str, Any],
    user_request: str,
    on_progress: Optional[Callable] = None,
    tool_catalog: Optional[List[Dict[str, Any]]] = None,
    retry_notice: Optional[Callable] = None,
) -> Dict[str, Any]:
    """
    Execute the full deep-research flow. Returns:
      {"answer": <markdown str for the user>, "engine_metadata": {...}, "synth_metadata": {...},
       "deliverable_spec": {...}, "actions": [...]}
    `deliverable_spec`/`actions` come from Phase-1 decomposition and are for the orchestrator's
    downstream fan-out (Phase 2+); this pipeline does NOT execute them.
    Raises only on planner failure (no evidence to work with); individual source failures
    are tolerated upstream.
    """
    async def emit(msg: str):
        if on_progress:
            await on_progress(msg)

    pipeline_start = time.monotonic()

    # Resilience: set the transient-5xx retry policy for all pipeline LLM calls from config so a
    # transient upstream provider blip doesn't fail a long, resource-heavy research run.
    _retry_cfg = config.get("retry", {}) or {}
    configure_retry(_retry_cfg.get("max_attempts", 1), _retry_cfg.get("delay_seconds", 0))
    # Register the retry-notice callback in THIS task's context (concurrency-safe — each run has its
    # own copied context), so _collect_stream can stream keepalive notices during retry waits.
    set_retry_notice_callback(retry_notice)

    # Phase 1: LLM-decompose the (possibly compound) request into research_request + deliverable_spec
    # + actions[]. Research + synthesis run ONLY on research_request (Phase 0 behavior preserved — no
    # refusing over "can't email/PDF"). deliverable_spec/actions are grounded in the live tool catalog
    # and returned for the orchestrator's downstream fan-out (Phase 2+) — NOT executed here.
    # Toggle: deep_research.engine.normalize_request.
    research_request = user_request
    deliverable_spec: Dict[str, Any] = {}
    actions: List[Dict[str, Any]] = []
    if config.get("normalize_request", True):
        plan = await _decompose_request(generate_stream, config, user_request, tool_catalog)
        research_request = plan["research_request"]
        deliverable_spec = plan["deliverable_spec"]
        actions = plan["actions"]
        if research_request != user_request:
            logger.info("🔬 Research request normalized (delivery/action directives stripped)")
            await emit("Scoping the research (delivery handled separately)…")
        # Phase 1 observability: log the parsed delivery plan (NOT executed yet — Phase 2).
        logger.info("🧩 Request decomposed — deliverable_spec=%s, actions=%s",
                    deliverable_spec or "{}", [a.get("type") for a in actions] or "[]")

    engine = DeepResearchEngine(generate_stream, dispatch_tool, config)
    stage1 = await engine.run(research_request, on_progress=on_progress)
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
            "deliverable_spec": deliverable_spec,
            "actions": actions,
        }

    synthesizer = ResearchSynthesizer(generate_stream, config)
    stage2 = await synthesizer.run(research_request, evidence, on_progress=on_progress)

    total_seconds = round(time.monotonic() - pipeline_start, 1)
    answer = (stage2.get("final_answer") or "").rstrip()
    if not answer:
        answer = ("Deep research gathered evidence but the synthesis step produced no answer. "
                  "Please try again.")

    # ── Citation grounding (output-side, news-focused safety net) ──────────────────────────────────────
    # Classify every cited URL against the GATHERED evidence set. A URL no tool returned was INVENTED by the
    # model (e.g. a 404 news article with a fabricated opaque ID — the reply-409 failure) → strip the link,
    # keep the visible text; a gathered-but-now-dead URL is provider-ROTTED (hot breaking stories get pulled/
    # re-titled/moved within minutes) and is distinguished, not blamed on the model. PURE + config-gated;
    # SHADOW (default) logs the would-be changes WITHOUT touching the answer, to baseline the live fabrication
    # rate first. No-op on healthy paths (wiki/papers/static: every cited URL is in evidence). Must NEVER
    # discard a hard-won answer. See docs/RAICA_CITATION_GROUNDING_BY_REFERENCE.md.
    try:
        from research.citation_grounding import ground_citations, extract_cited_urls
        _cg = config.get("citation_grounding", {}) or {}
        if _cg.get("enabled", True):
            _shadow = bool(_cg.get("shadow", True))
            _ev_urls = {u for e in evidence for u in (e.get("urls") or []) if u}

            # ── Output-side citation LIVENESS (docs/RAICA_DR_CITATION_LIVENESS.md) ─────────────────────────
            # The evidence URL set (engine.py `_URL_RE` over the WHOLE block) also captures URLs embedded in
            # snippets / page-body cross-references that were NEVER fetch-verified — so a cited-but-dead
            # ("Page not found") link is "in evidence" and grounding-by-reference keeps it as VALID. Here we
            # actually FETCH each *cited* URL (lenient: only hard 404/410 or homepage-redirect = dead; 403/
            # paywall/timeout kept; each dead verdict re-verified once to survive transient flaps) and feed
            # the verified-dead set into grounding as `dead_urls`, so a dead link is stripped as ROTTED
            # (headline text kept, only the broken link removed). Phase 1 (shadow:false) = ENFORCE the strip;
            # Phase 0 (shadow:true) = fetch + log only (answer UNCHANGED) to baseline the dead-link rate.
            _dead_urls = None
            _vl_enforcing = False
            _vl = _cg.get("verify_live", {}) or {}
            if _vl.get("enabled", False):
                _vl_shadow = bool(_vl.get("shadow", True))
                _vl_enforcing = not _vl_shadow
                try:
                    from research.link_liveness import filter_live_article_urls
                    _cited = extract_cited_urls(answer)
                    _dead = []
                    if _cited:
                        _live = filter_live_article_urls(
                            _cited, timeout=float(_vl.get("timeout_seconds", 6)),
                            max_workers=int(_vl.get("max_workers", 8)))
                        _dead = [u for u in _cited if u not in _live]
                    # ALWAYS log when the step runs (dead=0 included): the baseline needs the denominator
                    # (total cited checked) AND confirmation the step executed.
                    logger.info("🩺 citation-liveness [%s]: dead=%d/%d cited (verified 404/410/homepage-"
                                "redirect)%s", "SHADOW" if _vl_shadow else "ACTIVE", len(_dead), len(_cited),
                                (" sample=%s" % _dead[:6]) if _dead else "")
                    # SHADOW → do NOT strip (answer unchanged). ENFORCE → feed the dead set to grounding.
                    if _dead and _vl_enforcing:
                        _dead_urls = _dead
                except Exception as _vl_e:  # noqa: BLE001 — liveness must NEVER discard a hard-won answer
                    logger.warning("🩺 citation-liveness skipped (non-fatal): %s", _vl_e)

            # When liveness is ENFORCING, grounding must run ACTIVE so the dead (rotted) links are actually
            # stripped — keeping the visible headline text. This also enforces fabricated-link stripping
            # (URLs no tool returned); both are lossless, link-only removals of a bad citation.
            _effective_shadow = _shadow and not _vl_enforcing
            # Layer B ENFORCE (docs/RAICA_DR_SOURCE_RELEVANCE.md): drop OFF-TOPIC (homonym/domain-collision)
            # citations. B judged the gathered evidence during synthesis (synthesizer._last_off_topic_urls);
            # pass them here when B is enforcing (source_relevance.shadow=false) so ground_citations strips the
            # link but KEEPS the headline text — lossless, exactly like fabricated/dead.
            _b_off = getattr(synthesizer, "_last_off_topic_urls", None) or set()
            _sr_cfg = config.get("synthesis", {}).get("source_relevance", {}) or {}
            _b_off_arg = _b_off if (_b_off and not _sr_cfg.get("shadow", True)) else None
            _gr = ground_citations(answer, _ev_urls, dead_urls=_dead_urls, off_topic_urls=_b_off_arg,
                                   on_unsourced=_cg.get("on_unsourced", "flag"), shadow=_effective_shadow)
            _s = _gr["stats"]
            if _s["fabricated"] or _s["rotted"] or _s.get("off_topic") or _s["items_unsourced"]:
                logger.info("🔗 citation-grounding [%s]: fabricated=%d rotted=%d off_topic=%d unsourced=%d/%d "
                            "valid=%d stripped=%s", "SHADOW" if _effective_shadow else "ACTIVE",
                            _s["fabricated"], _s["rotted"], _s.get("off_topic", 0), _s["items_unsourced"],
                            _s["items_total"], _s["valid"], [u for _v, u in _s["stripped_urls"][:6]])
            answer = _gr["text"]   # SHADOW → original unchanged; ACTIVE → grounded text
    except Exception as _cg_e:  # noqa: BLE001 — grounding must NEVER discard a hard-won answer
        logger.warning("🔗 citation-grounding skipped (non-fatal): %s", _cg_e)

    # ── Citation DIVERSITY (SHADOW measurement — docs/RAICA_DR_SOURCE_RELEVANCE.md §reuse) ──
    # Baselines source diversity vs over-citation (the al-Ṭabarī ×68 case): how many DISTINCT sources back the
    # answer and how heavily one is reused. Quality-aware — heavy reuse of a genuine PRIMARY is a 'drive MORE
    # primaries' signal (the PRIMARY-FIRST directive), NOT a strip target. Log-only.
    try:
        from research.citation_grounding import extract_cited_links
        from collections import Counter as _Counter
        _pairs = extract_cited_links(answer)
        if _pairs:
            _cnt = _Counter(u for _t, u in _pairs)
            _top_n = _cnt.most_common(1)[0][1]
            _frac = _top_n / max(1, len(_pairs))
            logger.info("📚 citation-diversity [SHADOW]: cited=%d distinct=%d max_reuse=%d (%.0f%% one source)%s",
                        len(_pairs), len(_cnt), _top_n, 100.0 * _frac,
                        " ← over-reliance; drive MORE primaries" if (_top_n >= 5 and _frac > 0.4) else "")
    except Exception as _div_e:  # noqa: BLE001
        logger.warning("📚 citation-diversity shadow skipped (non-fatal): %s", _div_e)

    # ── Retrieval-quality audit (SHADOW measurement — docs/RAICA_DR_CITATION_LIVENESS.md §groundedness) ──
    # Liveness proves a URL RESOLVES; it does NOT prove RAICA retrieved the real page BODY. For each URL the
    # (post-grounding) answer cites, classify what RAICA actually held: real body / thin (snippet-only) /
    # error (403/paywall/5xx extraction-error) / over_captured (cited but never a fetched source) / absent.
    # Also checks HEADLINE↔URL consistency (does the cited headline match the title RAICA gathered for that
    # URL — a true mispairing, vs a benign <title>≠<h1>/slug page which is NOT flagged).
    # Log-only, PURE, fail-open — quantifies the body-retrieval (hallucination) exposure before any fix.
    try:
        _ra = config.get("retrieval_audit", {}) or {}
        if _ra.get("enabled", True):
            from research.retrieval_quality import assess_retrieval
            _rq = assess_retrieval(answer, evidence, min_body_chars=int(_ra.get("min_body_chars", 200)))
            _rs = _rq["stats"]
            logger.info("📊 retrieval-audit: real=%d thin=%d error=%d over_captured=%d absent=%d / %d cited "
                        "| flagged=%s", _rs["real"], _rs["thin"], _rs["error"], _rs["over_captured"],
                        _rs["absent"], _rs["cited_total"], _rq["flagged"][:8])
            _hl = _rq.get("headline", {})
            if _hl.get("checked"):
                logger.info("📎 headline-audit: matched=%d mismatched=%d / %d checked (cited headline vs "
                            "gathered title) | flagged=%s", _hl.get("matched", 0), _hl.get("mismatched", 0),
                            _hl.get("checked", 0), _hl.get("flagged", [])[:6])
    except Exception as _ra_e:  # noqa: BLE001 — measurement must NEVER affect the answer
        logger.warning("📊 retrieval-audit skipped (non-fatal): %s", _ra_e)

    # Footer-less body for downstream delivery (PDF/email document content) — the audit footer is a
    # chat-UX affordance, not part of the deliverable. answer_body is captured BEFORE the footer.
    answer_body = answer
    if config.get("output", {}).get("include_audit_footer", True):
        # The footer is cosmetic — never let a footer error discard a hard-won answer.
        # Pass the answer body so the footer can footnote low-cred sources it actually cited.
        try:
            answer += _verification_footer(engine_meta, stage2, total_seconds, answer_text=answer)
        except Exception as e:  # noqa: BLE001
            logger.warning("🔎 Research audit footer failed to render (%s) — answer kept", e)
    await emit("Done.")
    logger.info("🧪 Deep research pipeline complete in %ss: %s", total_seconds, stage2.get("metadata"))
    return {"answer": answer, "answer_body": answer_body, "engine_metadata": engine_meta,
            "synth_metadata": stage2["metadata"], "total_seconds": total_seconds,
            "deliverable_spec": deliverable_spec, "actions": actions}
