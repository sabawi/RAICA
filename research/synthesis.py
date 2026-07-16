"""
RAICA Deep Research — Stage 2: Synthesis, Verification & Arbitration
====================================================================

Turns a Stage-1 evidence pool into a *trustworthy* answer. Minimal scaffolding —
every judgement (credibility tier, synthesis, claim verdicts, reconciliation) is an
LLM call returning structured output; RAICA only orchestrates and enforces config.

Pipeline (ResearchSynthesizer.run):
  1. grade_sources  — LLM grades each source domain into a credibility tier   (fixes C2/C3)
  2. synthesize     — grounded, credibility-aware draft(s); one per model      (fixes C3)
  3. arbitrate      — if >1 model, reconcile drafts, surfacing disagreements   (fixes C1)
  4. verify         — extract atomic claims, label supported/contradicted/
                      unverified against the evidence (cross-source check)     (fixes C1)

Dependency-injected: `generate_stream(prompt, **kwargs) -> async iterator[str]`
(in production: llm_manager.generate_stream; pass `model=` to pick an ensemble member).

C1/C2/C3 refer to the credibility caveats recorded in docs/DEEP_RESEARCH_MULTIMODAL_PLAN.md.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from research.engine import extract_json_object, salvage_json_map, _collect_stream, GenerateStream

logger = logging.getLogger(__name__)

VALID_TIERS = ("peer_reviewed", "reputable", "popular", "low_credibility", "unknown")

# Structural extraction of the RAICA inline-chart markers `[[chart:<url>|align=...|caption="..."]]`.
# This matches the EXACT opaque token as it appears in the evidence — it does NOT interpret meaning,
# it only lets RAICA count/compare presence of a token that ORIGINATED in the evidence (used by the
# LLM-driven chart-completeness pass below). Non-greedy up to the first `]]` so a `]` inside a caption
# can never over-consume. (LLM-Policy Gate: this decides no meaning/intent/placement — the LLM does.)
_CHART_MARKER_RE = re.compile(r'\[\[chart:.*?\]\]', re.DOTALL)

# Canonical REASONING DIRECTIVE (v1.0.0.178) — shared by every prose-generating reasoning node so they
# speak with one voice (the no-inconsistency clause). Pushes the model to USE its full reasoning to get
# from the user's prompt to a VERIFIABLE answer, not just to convey/summarize evidence. Policy language
# only (LLM decides) — no hardcoded logic.
# v1.0.0.178 added two clauses hardening against the failures observed when native `think` is OFF (which
# the think-vs-directive A/B confirmed is the right default — think showed no quality gain, produced empty
# answers on hard prompts, and cost 3–10×): ONE COMMITTED ANSWER (kills a stale/superseded figure that
# survives into the final answer contradicting it — the "ghost" self-contradiction) and NO STAGED EVIDENCE
# (no presenting unexecuted code / an invented output as verification).
REASONING_DIRECTIVE = (
    "🧠 REASON TO A VERIFIABLE ANSWER — use your full reasoning; do not merely report or summarize:\n"
    "- Pin down what is TRULY being asked — the real question and the decision behind the words — and make "
    "the answer resolve THAT, not a loosely-related restatement.\n"
    "- Decompose the problem and reason through each part; connect the evidence to the specific question "
    "rather than laying sources side by side.\n"
    "- WEIGH competing, contradictory, or uneven evidence explicitly: state which is better-supported and WHY "
    "(directness, source quality, recency, corroboration), and reconcile or clearly flag genuine conflicts — "
    "never average them away or choose silently.\n"
    "- Draw the well-supported INFERENCES the evidence enables — the implications, mechanisms, and "
    "consequences a careful expert would deduce (reasoning beyond a bare restatement is the value) — but "
    "NEVER beyond what the evidence supports.\n"
    "- Reach a CLEAR, DIRECT conclusion that answers the question, and make it VERIFIABLE: every load-bearing "
    "claim must be checkable against the cited evidence, and every quantitative claim must follow "
    "arithmetically from the figures shown.\n"
    "- SELF-CHECK before finalizing: re-examine your own chain for unsupported leaps, arithmetic slips, and "
    "question-dodging, and fix them. If the evidence genuinely cannot settle the question, say so plainly and "
    "give the best-supported partial answer with its uncertainty stated.\n"
    "- ONE COMMITTED ANSWER: reconcile everything to a SINGLE final figure/verdict and state it once. If you "
    "revised a number or conclusion mid-reasoning, scrub the superseded value so it cannot survive into the "
    "answer contradicting your conclusion — a figure that contradicts your own final number is a defect even "
    "when the final number is correct.\n"
    "- NO STAGED EVIDENCE: you CANNOT execute code in this answer. You may show code to illustrate an "
    "approach, but NEVER append an 'Output:', 'Result:', or console block as if the code ran — instead "
    "compute the result yourself and show the ACTUAL arithmetic. A shown 'output' you did not truly produce "
    "is fabricated evidence, even if the number happens to be right.\n"
)

# Adversarial-balance directive (docs/RAICA_DR_ADVERSARIAL_BALANCE.md, Phase 1 / P3). As DR extends beyond
# hard science into humanities/philosophy/religion, "consensus" stops being a truth-signal and sources form
# ECHO CHAMBERS. Balance is PROPORTIONAL to genuine uncertainty — never manufactured. Policy language only:
# the LLM judges the domain, the epistemic status, the echo-chamber, and steelmans — NO hardcoded topic lists.
# Scopes the existing "surface controversial positions" rule so it cannot false-balance settled empirical science.
ADVERSARIAL_BALANCE_DIRECTIVE = (
    "⚖️ ADVERSARIAL BALANCE — CALIBRATE TO EPISTEMIC STATUS, NEVER MANUFACTURE BALANCE. First judge what KIND of "
    "question each claim is, and treat it accordingly — balance tracks genuine uncertainty, it is never a reflex "
    "symmetry:\n"
    "- ESTABLISHED EMPIRICAL (natural science / verifiable fact the evidence has settled — e.g. evolution, "
    "vaccine efficacy, heliocentrism): report it AS established. Do NOT invent balance, manufacture dissent, or "
    "elevate fringe denial to a 'side'. Settled science is not made 'balanced' by inventing critics; note only "
    "GENUINE live scientific disputes.\n"
    "- SPECULATIVE / UNSETTLED EMPIRICAL (a live hypothesis or open scientific question — e.g. string theory, a "
    "competing cosmological model): label it plainly as a HYPOTHESIS/CONJECTURE, not settled fact; represent the "
    "genuine rival hypotheses IN PROPORTION to their actual evidential support (never a forced 50/50); and "
    "EXPLAIN WHY the field currently favors one over the others — the specific evidence/reasoning that makes it "
    "catch on — rather than presenting it as proven.\n"
    "- SUBJECTIVE (humanities, philosophy, religion, ethics/normative, aesthetics — no empirical arbiter, and "
    "where sources form ECHO CHAMBERS that cite each other, exclude outsiders, and disparage dissent): here you "
    "MUST be the adversary the field lacks. For every significant point make the STRONGEST case you honestly can "
    "FOR it AND your utmost-effort STRONGEST case AGAINST it — a token 'some disagree' is a failure. Watch for "
    "the echo-chamber effect in the gathered sources and BREAK OUT of it: represent the excluded, dissenting, or "
    "outsider position at its strongest even if the pool under-supplies it, and SAY when the sources are "
    "one-sided. Distinguish what the evidence CAN establish (facts) from what it CANNOT (the normative/"
    "theological/interpretive claim). Do NOT declare a verdict on an unfalsifiable claim; commit instead to a "
    "clear characterization of the DEBATE — what is established, what is genuinely disputed, and the strongest "
    "case on each side.\n"
    "- GROUNDING: do NOT backfill a thin or one-sided evidence pool with confident specifics from your own "
    "trained knowledge dressed as sourced — if the evidence is thin or one-sided, say so plainly rather than "
    "padding it out. (This SCOPES the 'surface controversial positions' rule above: it applies to genuinely "
    "contested/subjective questions and does NOT license fringe dissent against established empirical findings.)\n"
)

# Token accounting for budgeting the evidence to the model window. tiktoken (cl100k_base)
# is a close-enough proxy for the cloud models; we keep headroom for tokenizer mismatch.
try:
    import tiktoken
    _ENC = tiktoken.get_encoding("cl100k_base")
except Exception:  # noqa: BLE001 — tiktoken optional; fall back to a char-based estimate
    _ENC = None


def _tok_count(text: str) -> int:
    if _ENC is not None:
        return len(_ENC.encode(text))
    return max(1, len(text) // 4)  # ~4 chars/token fallback


def _salvage_claim_objects(raw: str) -> List[Dict[str, Any]]:
    """
    Recover complete claim objects from a verification reply whose JSON was truncated mid-array
    (common for very long/enumerated answers). Scans for balanced top-level {...} blocks inside
    the "claims" array and json-loads each independently, skipping the incomplete trailing one.
    Best-effort; returns [] on total failure.
    """
    import json as _json
    text = raw or ""
    start = text.find('"claims"')
    if start == -1:
        return []
    objs: List[Dict[str, Any]] = []
    depth = 0
    buf_start = -1
    # Walk from the start of the claims array, capturing each balanced object.
    for i in range(text.find('[', start) + 1 if text.find('[', start) != -1 else start, len(text)):
        ch = text[i]
        if ch == '{':
            if depth == 0:
                buf_start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and buf_start != -1:
                try:
                    obj = _json.loads(text[buf_start:i + 1])
                    if isinstance(obj, dict):
                        objs.append(obj)
                except Exception:  # noqa: BLE001 — skip a malformed/partial object
                    pass
                buf_start = -1
    return objs


def _tok_truncate(text: str, max_tokens: int) -> str:
    if max_tokens <= 0:
        return ""
    if _ENC is not None:
        toks = _ENC.encode(text)
        if len(toks) <= max_tokens:
            return text
        return _ENC.decode(toks[:max_tokens])
    approx = max_tokens * 4
    return text if len(text) <= approx else text[:approx]


def _domain_of(url: str) -> str:
    try:
        net = urlparse(url).netloc.lower()
        return net[4:] if net.startswith("www.") else net
    except Exception:
        return ""


class ResearchSynthesizer:
    """Stage 2 orchestrator. See module docstring for the pipeline."""

    def __init__(self, generate_stream: GenerateStream, config: Dict[str, Any]):
        self._gen = generate_stream
        self._cfg = config or {}

    # ---- config accessors ----
    @property
    def _grading_on(self) -> bool:
        return bool(self._cfg.get("synthesis", {}).get("credibility_grading", True))

    @property
    def _provenance_cfg(self) -> Dict[str, Any]:
        return self._cfg.get("synthesis", {}).get("source_provenance", {}) or {}

    @property
    def _provenance_on(self) -> bool:
        """Master switch for the primary-vs-secondary provenance feature (docs/RAICA_SOURCE_PROVENANCE.md).
        Phase 0 wires ONLY the shadow role-grading + logging (no answer change)."""
        return bool(self._provenance_cfg.get("enabled", False))

    @property
    def _source_relevance_cfg(self) -> Dict[str, Any]:
        return self._cfg.get("synthesis", {}).get("source_relevance", {}) or {}

    @property
    def _source_relevance_on(self) -> bool:
        """Master switch for the SOURCE↔TOPIC relevance gate (docs/RAICA_DR_SOURCE_RELEVANCE.md — layer B).
        Phase 0 wires ONLY the shadow judge + logging (no answer change): flags gathered sources whose TITLE
        is only a keyword/homonym match for the topic (e.g. a CS 'Byzantine Agreement' paper for a query about
        the Byzantine Empire)."""
        return bool(self._source_relevance_cfg.get("enabled", False))

    @property
    def _verify_on(self) -> bool:
        return bool(self._cfg.get("verification", {}).get("enabled", True))

    @property
    def _min_sources(self) -> int:
        return int(self._cfg.get("verification", {}).get("min_corroborating_sources", 2))

    @property
    def _arbitration_models(self) -> List[str]:
        arb = self._cfg.get("arbitration", {})
        return list(arb.get("models", [])) if arb.get("enabled", False) else []

    @property
    def _max_answer_tokens(self) -> int:
        return int(self._cfg.get("synthesis", {}).get("max_answer_tokens", 16000))

    @property
    def _enumeration_two_pass(self) -> bool:
        return bool(self._cfg.get("synthesis", {}).get("enumeration_two_pass", True))

    # ---- chart-completeness (inline-chart marker relay) config ----
    @property
    def _chart_completeness_cfg(self) -> Dict[str, Any]:
        return self._cfg.get("synthesis", {}).get("chart_completeness", {}) or {}

    @property
    def _chart_completeness_on(self) -> bool:
        # Master switch for the LLM-driven chart-marker completeness pass (verify + re-place). Default ON:
        # inline charts are worthless if the synthesis silently drops them, and the pass is a no-op when the
        # evidence has no chart markers (normal research) or the draft already relayed them all.
        return bool(self._chart_completeness_cfg.get("enabled", True))

    @property
    def _chart_max_repair_passes(self) -> int:
        # How many bounded LLM re-place attempts before we give up and return the best draft (never destroy
        # the answer). Each pass is a narrow edit ("insert these markers into your report"), so 3 is ample.
        return int(self._chart_completeness_cfg.get("max_repair_passes", 3))

    @property
    def _chart_min_content_ratio(self) -> float:
        # A repair pass is ACCEPTED only if it kept at least this fraction of the prior draft's length —
        # a mechanical safety guard so a repair that summarizes/truncates the report is discarded (fail-safe:
        # a complete report missing a chart beats a shorter garbled one). Not a meaning judgement.
        return float(self._chart_completeness_cfg.get("min_content_ratio", 0.85))

    @property
    def _arbitration_model(self) -> Optional[str]:
        # Model that reconciles the drafts; None → primary (via generate_stream default).
        return self._cfg.get("arbitration", {}).get("arbitration_model") or None

    @property
    def _verify_model(self) -> Optional[str]:
        # Model that extracts + verifies claims; None → primary.
        return self._cfg.get("verification", {}).get("verify_model") or None

    @property
    def _verify_max_tokens(self) -> int:
        # Output budget for the verification JSON. Long answers have many claims, so this
        # must be generous or claim extraction gets truncated (under-sampling the answer).
        return int(self._cfg.get("verification", {}).get("max_tokens", 12000))

    # ---- step 1: credibility grading (C2/C3) ----
    def _unique_domains(self, evidence: List[Dict[str, Any]]) -> List[str]:
        domains = {d for e in evidence for u in e.get("urls", []) if (d := _domain_of(u))}
        return sorted(domains)

    async def grade_sources(self, evidence: List[Dict[str, Any]]) -> Dict[str, str]:
        """
        LLM grades each source domain into a credibility tier. No hardcoded lists.

        For low_credibility domains the LLM also returns a SPECIFIC reason (what exactly makes
        it low-credibility), captured into self.credibility_reasons[domain] for the footnote.
        Returns the tier map {domain: tier}; reasons are a side-channel to keep the tier dict
        compatible with all existing consumers.
        """
        self.credibility_reasons: Dict[str, str] = {}
        domains = self._unique_domains(evidence)
        if not domains or not self._grading_on:
            return {}
        system_prompt = (
            "Grade each source domain the user provides into exactly ONE credibility tier for use "
            "in a research report:\n"
            "- peer_reviewed: academic journals/preprint servers/databases (e.g. arxiv, pubmed, "
            "doi.org, core.ac.uk, journal sites)\n"
            "- reputable: established institutions, governments (.gov), universities (.edu), major "
            "news organizations, encyclopedias\n"
            "- popular: general-interest blogs/magazines/explainer sites (not scholarly, but not fringe)\n"
            "- low_credibility: fringe, pseudoscience, conspiracy, partisan/polemical advocacy, or "
            "self-published opinion sites\n\n"
            "For each domain return an object {\"tier\": <tier>, \"reason\": <reason>}. The reason is "
            "REQUIRED for low_credibility (and helpful for popular) — state the SPECIFIC concern in "
            "one short phrase, e.g. 'partisan conservative opinion site', 'advocacy org pushing "
            "anti-Islam polemics', 'self-published, cites no evidence', 'known for pseudoscience'. "
            "For peer_reviewed/reputable, reason may be an empty string.\n\n"
            "Respond with STRICT JSON only, e.g.:\n"
            '{"arxiv.org": {"tier": "peer_reviewed", "reason": ""}, '
            '"someblog.com": {"tier": "low_credibility", "reason": "self-published, no sourcing"}}'
        )
        prompt = "DOMAINS:\n" + "\n".join(f"- {d}" for d in domains)
        # Output budget auto-scales with the domain count (each domain returns {tier, reason}) so a large
        # run does not truncate the JSON mid-object; bounded to keep the call cheap.
        grade_max_tokens = min(16000, max(3000, 1000 + 80 * len(domains)))
        # Grading is non-essential context: never let a malformed/failed grade collapse the whole run.
        raw = ""
        try:
            raw = await _collect_stream(self._gen, prompt, system_prompt=system_prompt,
                                        temperature=0.0, max_tokens=grade_max_tokens, stream=False)
            data = extract_json_object(raw)
        except Exception as e:  # noqa: BLE001
            # Tolerant salvage: recover the domains that DID parse instead of zeroing ALL to 'unknown'
            # (root cause of the v1.0.0.133 "all unknown" collapse — one bad entry broke the whole batch).
            data = salvage_json_map(raw)
            n_ok = sum(1 for d in domains if d in data)
            if n_ok:
                logger.warning("🏷️ Credibility grading JSON malformed (%s) → salvaged %d/%d domains "
                               "(rest 'unknown')", e, n_ok, len(domains))
            else:
                logger.warning("🏷️ Credibility grading failed (%s) → all 'unknown'", e)
                return {d: "unknown" for d in domains}
        graded = {}
        for d in domains:
            entry = data.get(d, "unknown")
            # Accept both the new object form {tier,reason} and a bare tier string (resilience).
            if isinstance(entry, dict):
                tier = str(entry.get("tier", "unknown")).strip().lower()
                reason = str(entry.get("reason", "")).strip()
            else:
                tier = str(entry).strip().lower()
                reason = ""
            graded[d] = tier if tier in VALID_TIERS else "unknown"
            if graded[d] == "low_credibility" and reason:
                self.credibility_reasons[d] = reason
        tally: Dict[str, int] = {}
        for t in graded.values():
            tally[t] = tally.get(t, 0) + 1
        logger.info("🏷️ Graded %d domains: %s", len(graded), tally)
        return graded

    async def _grade_roles_shadow(self, evidence: List[Dict[str, Any]]) -> Dict[str, str]:
        """SHADOW (Phase 0, docs/RAICA_SOURCE_PROVENANCE.md): LLM classifies each source domain's ROLE
        (primary | secondary | unknown) for a factual claim — a SEPARATE call from grade_sources so tier
        grading stays byte-identical. No answer impact: the result is only logged (a baseline for the
        provenance feature). Semantic — NO hardcoded domain lists (LLM-Policy Gate). Any error → 'unknown'."""
        domains = self._unique_domains(evidence)
        if not domains:
            return {}
        system_prompt = (
            "Classify each source domain by its ROLE relative to a factual claim, into exactly ONE of:\n"
            "- primary: the ORIGIN of information — peer-reviewed papers/preprints, patents, court "
            "rulings, legislation and other .gov primary documents, company/regulatory filings, datasets, "
            "an author's own original work, or an original interview/speech/letter/transcript.\n"
            "- secondary: REPORTS, summarizes, or aggregates primary sources — encyclopedias (e.g. "
            "Wikipedia, Britannica), explainers, most news write-ups, review/aggregator sites.\n"
            "- unknown: cannot tell from the domain alone.\n"
            "A domain can host both — pick its PREDOMINANT role. Respond with STRICT JSON only, e.g.:\n"
            '{"arxiv.org": "primary", "en.wikipedia.org": "secondary", "example.com": "unknown"}'
        )
        prompt = "DOMAINS:\n" + "\n".join(f"- {d}" for d in domains)
        try:
            raw = await _collect_stream(self._gen, prompt, system_prompt=system_prompt,
                                        temperature=0.0, max_tokens=2000, stream=False)
            data = extract_json_object(raw)
        except Exception as e:  # noqa: BLE001
            logger.warning("🔬 Provenance role grading (shadow) failed (%s) → all 'unknown'", e)
            return {d: "unknown" for d in domains}
        roles = {}
        for d in domains:
            r = str(data.get(d, "unknown")).strip().lower()
            roles[d] = r if r in ("primary", "secondary", "unknown") else "unknown"
        return roles

    def _log_provenance_shadow(self, evidence: List[Dict[str, Any]],
                               credibility: Dict[str, str], roles: Dict[str, str]) -> None:
        """SHADOW (Phase 0): log the primary-vs-secondary baseline — the source role mix and how many
        sub-questions currently have NO primary source (future 'chase the primary' candidates). Pure
        logging; never raises, never alters the answer."""
        try:
            role_tally: Dict[str, int] = {}
            for r in roles.values():
                role_tally[r] = role_tally.get(r, 0) + 1
            sq_has_primary: Dict[str, bool] = {}
            for e in evidence:
                sq = str(e.get("sub_question_id", "?"))
                has_primary = any(roles.get(_domain_of(u)) == "primary"
                                  for u in (e.get("urls", []) or []) if u)
                sq_has_primary[sq] = sq_has_primary.get(sq, False) or has_primary
            total_sq = len(sq_has_primary)
            no_primary_sq = sum(1 for v in sq_has_primary.values() if not v)
            logger.info(
                "🔬 PROVENANCE SHADOW: domains — primary=%d secondary=%d unknown=%d | "
                "sub-questions with NO primary source (chase candidates): %d/%d",
                role_tally.get("primary", 0), role_tally.get("secondary", 0),
                role_tally.get("unknown", 0), no_primary_sq, total_sq,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("🔬 Provenance shadow logging failed (%s) — ignored", e)

    async def _grade_relevance_shadow(self, user_request: str,
                                      evidence: List[Dict[str, Any]]) -> Dict[str, Any]:
        """SHADOW (docs/RAICA_DR_SOURCE_RELEVANCE.md — layer B): LLM judges whether each gathered SOURCE
        (by its title) is actually ABOUT the user's research topic, or only a KEYWORD/HOMONYM match about a
        different subject (e.g. a CS 'Byzantine Generals Problem' paper for a query on the Byzantine EMPIRE;
        'mercury toxicity' for the planet Mercury). Log-only in Phase 0 → zero answer change. Semantic — NO
        keyword lists (LLM-Policy Gate). Any error → no-op. Title↔URL is extracted from the evidence content
        source blocks (works at title granularity — the homonym shares the same domain, so domain-grading
        cannot catch it)."""
        _TU = re.compile(r'(?:📄 SOURCE:|Title:)[ \t]*(.+?)[ \t]*\n🔗 (?:MANDATORY )?CITATION URL:\s*(\S+)')
        pairs: List[tuple] = []
        seen = set()
        for e in evidence:
            for title, url in _TU.findall(e.get("content", "") or ""):
                u = url.rstrip('.,);]')
                k = u.lower()
                t = (title or "").strip()
                if t and k not in seen:
                    seen.add(k)
                    pairs.append((t[:200], u))
        if not pairs:
            return {"off_topic": [], "checked": 0}
        # CONSERVATIVE + BATCHED. One big list makes the model over-flag (it once flagged on-topic Wikipedia
        # gang articles for a gang-history query); judge in small batches and keep-when-unsure.
        system_prompt = (
            "You audit whether gathered SOURCES are ON-TOPIC for a research request. A source is OFF-TOPIC "
            "ONLY when it is about a COMPLETELY DIFFERENT SUBJECT that merely shares a keyword/homonym with the "
            "request — e.g. a computer-science 'Byzantine Generals Problem' paper for a query on the Byzantine "
            "EMPIRE; 'mercury toxicity' for the planet Mercury; a football match report for a query on street "
            "gangs. Be CONSERVATIVE: KEEP anything plausibly relevant — broad, tangential, background, or "
            "partial-overlap sources are ON-topic. Flag ONLY the clearly-unrelated. When in doubt, KEEP.\n"
            'Respond with STRICT JSON only: {"off_topic": [<indices>]}. Empty list if all are on-topic.'
        )
        off: List[tuple] = []
        _BATCH = 18
        for _start in range(0, len(pairs), _BATCH):
            chunk = pairs[_start:_start + _BATCH]
            numbered = "\n".join(f"{i}. {t}" for i, (t, _) in enumerate(chunk))
            prompt = f"RESEARCH REQUEST:\n{(user_request or '')[:600]}\n\nSOURCES:\n{numbered}"
            try:
                raw = await _collect_stream(self._gen, prompt, system_prompt=system_prompt,
                                            temperature=0.0, max_tokens=400, stream=False)
                data = extract_json_object(raw)
                idxs = data.get("off_topic", []) if isinstance(data, dict) else []
                for i in idxs:
                    if isinstance(i, int) and 0 <= i < len(chunk):
                        off.append((chunk[i][0], chunk[i][1]))
            except Exception as e:  # noqa: BLE001 — one batch failing must not lose the rest
                logger.warning("🎯 Source-relevance batch failed (%s) → skip batch", e)
                continue
        return {"off_topic": off, "checked": len(pairs)}

    def _log_source_relevance_shadow(self, result: Dict[str, Any]) -> None:
        """SHADOW: log how many gathered sources are OFF-TOPIC (keyword/homonym) for the request. Pure
        logging; never raises, never alters the answer."""
        try:
            off = result.get("off_topic", []) or []
            checked = result.get("checked", 0)
            detail = ("  | " + "; ".join(f"{t[:55]!r}<-{_domain_of(u)}" for t, u in off[:6])) if off else ""
            logger.info("🎯 dr-source-relevance [SHADOW]: off_topic=%d/%d%s", len(off), checked, detail)
        except Exception as e:  # noqa: BLE001
            logger.warning("🎯 Source-relevance shadow logging failed (%s) — ignored", e)

    @property
    def _evidence_token_budget(self) -> int:
        return int(self._cfg.get("synthesis", {}).get("evidence_token_budget", 110000))

    @property
    def _verify_evidence_budget(self) -> int:
        # Smaller evidence budget for verify so the verify INPUT leaves room for the output JSON
        # within the model window. Falls back to ~55% of the synthesis budget if unset.
        return int(self._cfg.get("verification", {}).get(
            "evidence_token_budget", max(1, int(self._evidence_token_budget * 0.55))))

    def _allocate_token_budget(self, evidence: List[Dict[str, Any]],
                               budget: Optional[int] = None) -> List[int]:
        """
        Fair token allocation across sources so the evidence document fits the model window:
        small sources are kept whole; leftover budget is split among the large ones (which are
        truncated only if still over). Returns a per-item token cap aligned with `evidence`.
        """
        budget = self._evidence_token_budget if budget is None else budget
        sizes = [_tok_count(e.get("content", "")) for e in evidence]
        if sum(sizes) <= budget:
            return sizes  # everything fits — no truncation

        n = len(evidence)
        fair = max(1, budget // n)
        caps = [0] * n
        large_idx = []
        remaining = budget
        for i, sz in enumerate(sizes):
            if sz <= fair:
                caps[i] = sz
                remaining -= sz
            else:
                large_idx.append(i)
        if large_idx:
            share = max(1, remaining // len(large_idx))
            for i in large_idx:
                caps[i] = share
        return caps

    # ---- shared: build the annotated evidence document (budgeted to the model window) ----
    def _evidence_document(self, evidence: List[Dict[str, Any]],
                           credibility: Dict[str, str],
                           budget: Optional[int] = None) -> str:
        caps = self._allocate_token_budget(evidence, budget=budget)
        blocks = []
        truncated = 0
        for e, cap in zip(evidence, caps):
            content = e.get("content", "")
            if _tok_count(content) > cap:
                content = _tok_truncate(content, cap) + "\n[…source truncated to fit context budget…]"
                truncated += 1
            _block_urls = [u for u in (e.get("urls", []) or []) if u]
            tiers = sorted({credibility.get(_domain_of(u), "unknown") for u in _block_urls})
            tier_tag = ",".join(tiers) if tiers else "unknown"
            # Surface this block's source URL(s) EXPLICITLY so the synthesis model can attribute the
            # claims it draws from this block as clickable [Title](URL). Without this line the URLs are
            # buried inside the content text and the model fails to cite → the report comes out with NO
            # citations and is (rightly) rejected downstream. Cite ONLY URLs that appear in the evidence.
            _url_line = ""
            if _block_urls:
                _url_line = ("SOURCE URL(S) for this block — cite claims taken from it as a clickable "
                             "[SPECIFIC ARTICLE HEADLINE](URL): use the article's own headline (shown on "
                             "this block's '📄 SOURCE:' line) as the link TEXT — NEVER the bare outlet name "
                             "(NPR/BBC/…) or an outlet+date. Use ONLY these URL(s): "
                             + " , ".join(_block_urls) + "\n")
            blocks.append(
                f"───── EVIDENCE [{e.get('sub_question_id')} | source={e.get('source')} | "
                f"credibility={tier_tag}] ─────\n{_url_line}{content}"
            )
        doc = "\n\n".join(blocks)
        if truncated:
            logger.info("📐 Evidence budgeted to ~%d tokens: %d/%d source(s) truncated (~%d tokens)",
                        self._evidence_token_budget, truncated, len(evidence), _tok_count(doc))
        return doc

    # ---- step 1.5 (optional): enumeration roster extraction ----
    def _breadth_first_snippets(self, evidence: List[Dict[str, Any]],
                                per_source_tokens: int = 1200) -> str:
        """
        A breadth-FIRST view: a bounded slice of EVERY source (not the tail-truncated, depth-first
        evidence document). Used only for roster extraction so boundary items mentioned in any
        source survive — even sources the main evidence budget would truncate away.
        """
        blocks = []
        for i, e in enumerate(evidence, 1):
            content = _tok_truncate(str(e.get("content", "")), per_source_tokens)
            blocks.append(f"[SOURCE {i} | {e.get('source')}]\n{content}")
        return "\n\n".join(blocks)

    async def _extract_roster(self, user_request: str,
                              evidence: List[Dict[str, Any]]) -> Optional[str]:
        """
        For LIST/TABLE/'earliest/all' requests, extract the COMPLETE roster of qualifying items
        from a breadth-first view of ALL evidence (before depth-truncation can drop boundary items).

        Returns a markdown checklist string to inject into synthesis, or None if this is not an
        enumeration request, the feature is disabled, or anything fails (→ normal single-pass path).
        Best-effort and fully fail-safe: never raises.
        """
        if not self._enumeration_two_pass:
            return None
        try:
            snippets = self._breadth_first_snippets(evidence)
            system_prompt = (
                "You analyze a research request and its evidence. FIRST decide whether the request "
                "asks to LIST, TABULATE, ENUMERATE, or otherwise produce a SET OF ITEMS (a table, "
                "'list all/the …', 'the earliest/oldest/first …', a catalog). If it does NOT, return "
                '{\"is_enumeration\": false}.\n'
                "If it DOES: scan ALL the evidence and extract the COMPLETE roster of distinct items "
                "that fit the request's scope qualifier — be exhaustive, INCLUDING boundary cases and "
                "items mentioned only in passing or as background. Honor the qualifier exactly (e.g. "
                "for 'earliest', include the genuinely oldest items even if less famous; do NOT include "
                "items that fall outside the qualifier). Each item = one entry; do not merge distinct "
                "items.\n"
                "Respond with STRICT JSON only:\n"
                '{\"is_enumeration\": true, \"item_noun\": \"<what the items are, e.g. civilizations>\", '
                '\"scope\": \"<the qualifier, e.g. earliest in the Near East>\", '
                '\"items\": [\"item 1\", \"item 2\", ...]}'
            )
            prompt = f"USER REQUEST:\n{user_request}\n\nEVIDENCE (breadth-first snippets):\n{snippets}"
            raw = await _collect_stream(self._gen, prompt, system_prompt=system_prompt,
                                        temperature=0.0, max_tokens=6000, stream=False)
            data = extract_json_object(raw)
            if not isinstance(data, dict) or not data.get("is_enumeration"):
                return None
            items = [str(x).strip() for x in (data.get("items") or []) if str(x).strip()]
            if len(items) < 2:  # not a meaningful list → use normal path
                return None
            noun = str(data.get("item_noun", "items")).strip() or "items"
            scope = str(data.get("scope", "")).strip()

            # SELF-AUDIT PASS: the first extraction reliably drops qualifying items that ARE in
            # the evidence (observed: Natufian/Halaf present but excluded; 17→12 run-to-run swing).
            # Re-scan the SAME breadth-first evidence given the current roster and ask only "what is
            # MISSING?", then merge. Best-effort — failure keeps the initial roster.
            try:
                audit_system = (
                    "You are auditing a roster of items extracted from research evidence for "
                    "COMPLETENESS. Given the request scope, the current roster, and the full evidence, "
                    "find every ADDITIONAL distinct item that fits the scope and appears in the evidence "
                    "but is MISSING from the current roster (including items mentioned only in passing or "
                    "as background). Do not repeat items already in the roster; do not add items outside "
                    "the scope. If the roster is already complete, return an empty list.\n"
                    'Respond with STRICT JSON only: {"missing_items": ["item", ...]}'
                )
                audit_prompt = (
                    f"REQUEST SCOPE: {scope or user_request}\n\n"
                    f"CURRENT ROSTER ({len(items)} {noun}):\n" + "\n".join(f"- {it}" for it in items) +
                    f"\n\nEVIDENCE (breadth-first snippets):\n{snippets}"
                )
                araw = await _collect_stream(self._gen, audit_prompt, system_prompt=audit_system,
                                             temperature=0.0, max_tokens=3000, stream=False)
                adata = extract_json_object(araw)
                missing = [str(x).strip() for x in (adata.get("missing_items") or []) if str(x).strip()] \
                    if isinstance(adata, dict) else []
                # Merge, case-insensitively de-duplicated, preserving order.
                seen = {it.lower() for it in items}
                added = [m for m in missing if m.lower() not in seen]
                if added:
                    items.extend(added)
                    logger.info("📋 Roster self-audit added %d missing item(s): %s",
                                len(added), ", ".join(added[:8]) + ("…" if len(added) > 8 else ""))
            except Exception as audit_err:  # noqa: BLE001 — keep initial roster on audit failure
                logger.warning("📋 Roster self-audit failed (%s) — keeping initial roster", audit_err)

            logger.info("📋 Enumeration detected: %d %s%s — roster extracted (after self-audit)",
                        len(items), noun, f" ({scope})" if scope else "")
            checklist = "\n".join(f"- {it}" for it in items)
            return (
                f"REQUIRED ITEM ROSTER ({len(items)} {noun}"
                f"{' — ' + scope if scope else ''}). This roster was extracted from the FULL evidence "
                "set. You MUST produce one entry/row for EVERY item below — do not omit any, do not add "
                "items not relevant to the request. If the detailed evidence for an item is thin, still "
                "include it with what is known and mark missing cells 'unknown':\n"
                f"{checklist}"
            )
        except Exception as e:  # noqa: BLE001 — best-effort; fall back to normal synthesis
            logger.warning("📋 Roster extraction failed (%s) — using normal single-pass synthesis", e)
            return None

    # ---- step 1.7: inline-chart marker completeness (LLM verify + re-place) ----
    #
    # PROBLEM (evidence, 2026-07-11): the writer model (deepseek-v4-flash for sub-250K synthesis prompts)
    # relays the `[[chart:...]]` markers RELIABLY for a single-stock report, but on a multi-stock report it
    # drops them STOCHASTICALLY and ALL-OR-NOTHING: measured 6 identical runs = [0,5,0,0,0,5] markers — never
    # a partial count. The model makes ONE global sampling decision per generation about whether to reproduce
    # these opaque tokens, and once it strips the first it strips all (path-dependent). It is NOT a
    # length/opacity problem (short `[[chart:CHART1]]` ids drop just the same) and NOT truncation (drafts sit
    # at ~50% of the token cap). Policy-language strengthening alone can't hold a ~2/3 drop rate.
    #
    # FIX (CARDINAL-RULE compliant — the LLM-driven verify→feedback→regenerate loop, mirroring verify() and
    # enumeration_two_pass): RAICA MECHANICALLY checks whether every marker that ORIGINATED in the evidence is
    # present in the draft (a structural set-difference over exact tokens — no meaning/intent/placement is
    # decided by RAICA), and if any are missing it FEEDS THEM BACK to the LLM and asks the LLM to re-place
    # them. The LLM still decides WHERE each chart goes and emits the final text; RAICA only detects the
    # omission and bounds the retries. No hardcoded placement, no regex that injects a marker into a section.

    def _chart_markers_in_evidence(self, doc: str) -> List[str]:
        """The exact `[[chart:...]]` tokens present in the evidence document, de-duplicated in order.
        These are the markers the answer is REQUIRED to relay (they came from the evidence)."""
        seen, out = set(), []
        for m in _CHART_MARKER_RE.findall(doc or ""):
            if m not in seen:
                seen.add(m)
                out.append(m)
        return out

    async def _repair_chart_markers(self, draft: str, missing: List[str],
                                    model: Optional[str] = None) -> str:
        """Feed the writer its OWN draft + the exact markers it dropped, and ask it to reinsert each at the
        right place. This is a NARROW edit task (not re-synthesis), so the model complies where full
        synthesis stochastically doesn't. The LLM decides placement; RAICA supplies only the verified-missing
        tokens. temperature=0.0 for faithful verbatim copying + content preservation."""
        miss_list = "\n".join(missing)
        system_prompt = (
            "You are fixing an already-written research report that is missing some required inline CHART "
            "MARKERS. Return the COMPLETE corrected report, IDENTICAL to the input EXCEPT that you INSERT "
            "each missing chart marker listed below, exactly once, copied EXACTLY and VERBATIM (never alter "
            "the URL, caption, or align; never wrap it in a code fence). Place each on its OWN line inside "
            "the part of the report that discusses the stock its caption NAMES — its technical / price-action "
            "discussion. Do NOT remove, rewrite, shorten, reorder, or summarize ANY existing content: "
            "reproduce the entire report and ONLY add the markers. Do not add any marker that is not in the "
            "list below. Output ONLY the corrected report, nothing else."
        )
        prompt = (f"MISSING CHART MARKERS (insert every one of these, verbatim):\n{miss_list}\n\n"
                  f"CURRENT REPORT:\n{draft}")
        kwargs = {"system_prompt": system_prompt, "temperature": 0.0,
                  "max_tokens": self._max_answer_tokens, "stream": False}
        if model:
            kwargs["model"] = model
        return await _collect_stream(self._gen, prompt, **kwargs)

    async def _ensure_chart_completeness(self, draft: str, doc: str,
                                         model: Optional[str] = None) -> str:
        """Guarantee every evidence chart marker appears in the answer, via bounded LLM repair passes.
        No-op when there are no markers or the draft already relays them all. Fail-safe: a repair that
        doesn't strictly improve coverage or that shrinks the report past the content guard is rejected,
        and after all attempts the BEST draft is returned (a missing chart never destroys a good answer)."""
        if not self._chart_completeness_on or self._chart_max_repair_passes < 1:
            return draft
        required = self._chart_markers_in_evidence(doc)
        if not required:
            return draft
        missing = [m for m in required if m not in draft]
        if not missing:
            return draft  # first-pass draft already complete — nothing to do

        best = draft
        for attempt in range(1, self._chart_max_repair_passes + 1):
            missing = [m for m in required if m not in best]
            if not missing:
                break
            logger.info("🖼️🩹 chart-completeness repair %d/%d — %d/%d markers missing, re-prompting LLM to place them",
                        attempt, self._chart_max_repair_passes, len(missing), len(required))
            try:
                fixed = await self._repair_chart_markers(best, missing, model)
            except Exception as e:  # noqa: BLE001 — a repair failure must never discard the answer
                logger.warning("🖼️🩹 chart-completeness repair %d failed (%s) — keeping current draft", attempt, e)
                continue
            fixed_missing = [m for m in required if m not in fixed]
            improved = len(fixed_missing) < len([m for m in required if m not in best])
            preserved = len(fixed) >= self._chart_min_content_ratio * len(best)
            if improved and preserved:
                best = fixed
            else:
                logger.warning("🖼️🩹 chart-completeness repair %d rejected (improved=%s preserved=%s: "
                               "len %d→%d, missing %d→%d) — retrying with fresh sampling",
                               attempt, improved, preserved, len(best), len(fixed),
                               len([m for m in required if m not in best]), len(fixed_missing))

        final_missing = [m for m in required if m not in best]
        if final_missing:
            logger.warning("🖼️🩹 chart-completeness: %d/%d markers STILL missing after %d pass(es) — returning best draft",
                           len(final_missing), len(required), self._chart_max_repair_passes)
        else:
            logger.info("🖼️✅ chart-completeness: all %d chart markers present in the final answer", len(required))
        return best

    # ---- step 2: grounded, credibility-aware synthesis (C3) ----
    async def synthesize(self, user_request: str, evidence: List[Dict[str, Any]],
                         credibility: Dict[str, str], model: Optional[str] = None,
                         roster: Optional[str] = None) -> str:
        # ── Content-quality gate (docs/RAICA_DR_CITATION_LIVENESS.md §groundedness) ──────────────────────
        # Mark source blocks whose page BODY could not be fetched (extraction-error/paywall) so the writer
        # treats them as title-only and never attributes specific facts to them. SHADOW = count + log only
        # (evidence unchanged); ACTIVE = annotate the evidence + add the attribution rule to the prompt.
        _rg = self._cfg.get("synthesis", {}).get("retrieval_gate", {}) or {}
        _rg_active = bool(_rg.get("enabled", False)) and not bool(_rg.get("shadow", True))
        _ev = evidence
        if _rg.get("enabled", False):
            try:
                from research.retrieval_quality import annotate_unretrieved_blocks
                _marked, _gated = 0, []
                for e in evidence:
                    _c, _n = annotate_unretrieved_blocks(e.get("content", ""))
                    _marked += _n
                    _gated.append({**e, "content": _c} if _n else e)
                if _marked:
                    logger.info("🚧 retrieval-gate [%s]: %d source-block(s) body-not-retrieved (title-only)",
                                "ACTIVE" if _rg_active else "SHADOW", _marked)
                if _rg_active:
                    _ev = _gated
            except Exception as _rg_e:  # noqa: BLE001 — gate must NEVER break synthesis
                logger.warning("🚧 retrieval-gate skipped (non-fatal): %s", _rg_e)
        _gate_rule = (
            "- BODY-NOT-RETRIEVED SOURCES: a source block marked '⚠️ BODY-NOT-RETRIEVED' could NOT be fetched "
            "(paywall/block/error) — you hold ONLY its title, not its content. Do NOT attribute any specific "
            "fact, quote, statistic, figure, date, or detail to it; reference it only for the existence of a "
            "topic or as further reading, clearly framed. Never present unseen specifics as sourced to it, and "
            "prefer sources WITH a retrieved body for concrete claims. (Governs ATTRIBUTION, not exclusion.)\n"
        ) if _rg_active else ""

        # Adversarial balance (docs/RAICA_DR_ADVERSARIAL_BALANCE.md, P3) — steelman both sides + break the
        # echo chamber on subjective questions; calibrate to epistemic status; never false-balance settled
        # science. Policy language only (LLM judges), gated + reversible.
        _ab = self._cfg.get("synthesis", {}).get("adversarial_balance", {}) or {}
        _ab_rule = ADVERSARIAL_BALANCE_DIRECTIVE if bool(_ab.get("enabled", False)) else ""

        doc = self._evidence_document(_ev, credibility)
        system_prompt = (
            "You are an expert research writer producing an authoritative, in-depth report. A large "
            "body of evidence has been gathered for you — your job is to REASON over it and convey as much "
            "of its insight as possible to an avid, curious reader. Using ONLY the evidence provided, write "
            "the answer.\n\n"
            + REASONING_DIRECTIVE +
            "\n(Depth and reasoning are complementary: cover every substantive point below AND reason it "
            "through to a verifiable conclusion — a comprehensive answer that also THINKS is the goal.)\n\n"
            "🎯 PRIMARY DIRECTIVE — MAXIMIZE DEPTH AND COVERAGE:\n"
            "- COVER EVERY substantive point, finding, argument, example, and nuance the evidence "
            "supports that is relevant to the request — do NOT limit yourself to a handful of points. "
            "If the evidence supports ten relevant points, cover all ten. Leave no important angle out.\n"
            "- USE ALL SUBSTANTIVE EVIDENCE REGARDLESS OF SOURCE TIER. A point's importance is decided "
            "by its substance and relevance, NOT by the credibility tier of the source that raised it. "
            "Draw on popular and low-credibility sources for the substantive points, claims, and angles "
            "they contribute — just attribute them appropriately (see credibility rules). Do not silently "
            "drop a point merely because its source is not peer-reviewed.\n"
            "- THIS IS RESEARCH, NOT A CONSENSUS SUMMARY. Do NOT retreat to generalities or only the "
            "safe, universally-accepted narrative. Surface the contested, minority, heterodox, and "
            "controversial positions present in the evidence — controversial is NOT the same as wrong, "
            "and in research the prevailing narrative is itself open to challenge. Include important "
            "in-research and dissenting points, clearly framed as contested, with who argues them and "
            "on what basis. Omitting a substantive controversial point is a FAILURE of the report.\n"
            + _ab_rule +
            "- EXPAND AND ENRICH — never cut, trim, or summarize for brevity. For each point, develop it "
            "FULLY: explain the underlying reasoning, mechanisms, historical/scientific context, "
            "supporting examples, competing interpretations, caveats, and implications that the sources "
            "provide. Write well-developed multi-sentence paragraphs, not terse bullets.\n"
            "- MAINTAIN 100% of the depth, coverage, and detail available in the evidence. Brevity is NOT "
            "a goal here; thoroughness and enlightenment are. A longer, richer, more informative answer "
            "is BETTER, as long as every sentence earns its place with real substance.\n"
            "- The ONLY hard limit on length is the evidence itself: greater depth must come from drawing "
            "on MORE of the gathered evidence — NEVER from speculation, repetition, filler, or padding. "
            "Accuracy and grounding are never sacrificed for length.\n\n"
            "📋 ENUMERATION COMPLETENESS — when the request asks to LIST, TABULATE, ENUMERATE, or "
            "otherwise produce a set of items (a table, a list of X, 'all the …', a catalog):\n"
            "- COMPLETENESS HERE MEANS BREADTH OF ITEMS (rows/entries), NOT depth on a few. First cover "
            "EVERY qualifying item the evidence supports — be exhaustive in the ROW set — THEN add per-item "
            "detail. Never trade breadth of items for depth on a subset: a table with all the items and "
            "moderate per-row detail is FAR more complete than a few items described lavishly.\n"
            "- MATCH THE SCOPE QUALIFIER EXACTLY. If the request says 'earliest', 'first', 'oldest', "
            "'smallest', 'all', a date range, or any other qualifier, the item set MUST honor it. Do NOT "
            "drift to the famous/well-documented items while omitting ones that actually fit the qualifier "
            "(e.g. for 'earliest', include the genuinely earliest items even if the evidence on them is "
            "thinner, and do NOT pad the list with later items that no longer fit). Items at the boundary "
            "of the qualifier are exactly the ones most likely to be wrongly dropped — include them.\n"
            "- MINE THE EVIDENCE FOR EVERY QUALIFYING ITEM, including ones mentioned only in passing or "
            "as background to another item. If an item appears anywhere in the evidence and fits the "
            "request, it gets its own entry/row — do not fold it into another item's description.\n"
            "- For a TABLE, populate EVERY requested column for EVERY row; if a cell's value is unknown "
            "from the evidence, write 'unknown'/'uncertain' rather than dropping the row or the column.\n"
            "- If you can identify qualifying items but the evidence is too thin to fully detail them, "
            "STILL list them (with what is known + a note that detail is limited) rather than omitting "
            "them — an acknowledged-but-thin entry is more complete than a silent omission.\n\n"
            "GROUNDING & CREDIBILITY RULES (strict — these govern ATTRIBUTION, never EXCLUSION):\n"
            "- CITATIONS ARE MANDATORY (non-negotiable): ground every factual claim in the evidence and "
            "cite it inline as a clickable [Title](URL), using ONLY the SOURCE URL(S) provided with each "
            "evidence block. A substantive report with NO citations is a FAILURE and will be rejected. "
            "Never invent URLs, facts, dates, or names.\n"
            "- CITATION LINK TEXT = THE SPECIFIC ARTICLE HEADLINE (critical): the clickable text of every "
            "citation MUST be that article's specific headline/title (as shown on its evidence "
            "'📄 SOURCE:' line), NEVER the bare outlet/publisher name and NEVER an outlet+date. Write "
            "[Specific Article Headline](URL) — e.g. "
            "[NPR: US and Iran reach preliminary deal to end the war](https://www.npr.org/2026/06/15/...) — "
            "NEVER [NPR], [BBC], [New York Times], or [NPR, June 15, 2026]. Put the outlet name and date in "
            "the surrounding prose, not in the link text. The URL must be that block's specific article URL "
            "(never a homepage / section / feed).\n"
            "- Calibrate CONFIDENCE to source credibility, but never use credibility to EXCLUDE a "
            "substantive point. Present well-established findings as established (citing peer_reviewed/"
            "reputable sources). Present contested or low-credibility-sourced claims as ATTRIBUTED "
            "positions (e.g. 'X argues …', 'According to Y …') with appropriate context about the "
            "source's standing — include and explain them, do not merely dismiss them. Reserve outright "
            "'debunking' for claims the evidence actually refutes; for the rest, present the debate fairly "
            "and let the reader weigh it.\n"
            "- PRIMARY-FIRST, QUALITY-FIRST SOURCING: anchor the analysis on PRIMARY sources (original "
            "chronicles, documents, records, first-hand accounts, datasets, an author's own work) — they set "
            "the standard and must DOMINATE both the citations AND the coverage: build the substance and the "
            "SPACE of the analysis on the primary evidence, do not merely footnote it. Seek and use MORE "
            "DISTINCT primaries wherever they exist — a single primary is a starting point, not a stopping "
            "point (for a well-studied topic several usually exist). Diversify sources ONLY by adding ones of "
            "EQUAL OR HIGHER quality — additional primaries first, then reputable secondary scholarship; NEVER "
            "add a weak, low-credibility, or off-topic source to lengthen the reference list or manufacture "
            "variety (a lesser source can never substitute for, or dilute, a primary). Do NOT restate the SAME "
            "citation across many separate claims: cite a source where it best supports a point and corroborate "
            "DISTINCT points with DISTINCT sources; if one primary underpins a whole section, reference it once "
            "for that section rather than re-citing it claim-by-claim. When the gathered evidence NAMES a "
            "canonical primary source that has NO clickable URL (e.g. an ancient/medieval chronicle such as "
            "al-Tabari, al-Baladhuri, Ibn Ishaq, or Theophanes — listed in a bibliography or attributed in the "
            "gathered text, e.g. Wikipedia's 'Primary sources' list), you SHOULD still ATTRIBUTE the relevant "
            "claims to it BY NAME in prose (e.g. \"al-Tabari's account records …\", \"according to "
            "Theophanes …\") — named attribution to a canonical primary is proper scholarship even without a "
            "hyperlink, and is far better than omitting the primary. Attribute ONLY to primaries the evidence "
            "actually identifies; never invent a source or a specific claim for one.\n"
            + _gate_rule +
            "- Where sources CONFLICT, explicitly say so and present both/all sides with citations — the "
            "disagreement itself is valuable research content.\n"
            "- Do NOT overstate your sourcing (e.g. do not call popular/low-credibility sources "
            "'peer-reviewed'). If evidence is thin or absent for part of the request, say so plainly.\n"
            "- QUANTITATIVE DATA → TABLES: when the topic is economic/statistical/financial/scientific or "
            "otherwise data-driven AND the evidence provides concrete FIGURES (prices, quantities, shares, "
            "rates, %s, dates, before/after or by-region/by-year values), PRESENT them in clean Markdown "
            "TABLES (e.g. before-vs-after, current-vs-historical, by-region, by-source, trend-over-time) and "
            "lead the analysis FROM the data — do not bury the numbers in prose. Give each table a caption and "
            "cite the figures to their sources. ABSOLUTE, NON-NEGOTIABLE RULE: put ONLY figures the evidence "
            "ACTUALLY provides, each traceable to a cited source — NEVER invent, guess, estimate, extrapolate, "
            "interpolate, or 'round out' a number to fill a cell. If a needed value is not in the evidence, "
            "leave that cell EMPTY or write 'n/a (not in sources)'. A single fabricated figure is an ABSOLUTE "
            "FAILURE: when in doubt, DROP the table entirely and state only the sourced figures you do have, in "
            "prose, with citations. Better an honest gap than a fabricated cell. Reserve tables for genuinely "
            "quantitative material — do NOT tabulate a purely narrative/historical topic.\n"
            "- COMPARATIVE / SUPERLATIVE CLAIMS — VERIFY AGAINST THE FULL SET: before writing ANY ranking or "
            "superlative about the compared entities ('the lowest/highest/cheapest/most expensive/best/worst "
            "<metric>', 'the cheapest on earnings', 'ranks first', 'second-lowest', etc.), you MUST first "
            "assemble that ONE metric for EVERY entity from the evidence, order them, and confirm the extreme "
            "you are about to claim actually holds across ALL of them — never assert an extreme from a subset "
            "or from memory. When a metric has VARIANTS that can disagree (TRAILING vs FORWARD P/E, gross vs "
            "operating vs net margin, historical vs projected growth, TTM vs annual), name exactly WHICH "
            "variant the claim is about: a superlative true on one variant is frequently FALSE on another "
            "(e.g. a name can be cheapest on FORWARD P/E yet not on TRAILING P/E). If you present a comparison "
            "table, EVERY superlative in your prose MUST agree with that table — a claim that contradicts your "
            "own table is an absolute failure.\n"
            "- MODEL ESTIMATES vs SOURCED DATA: some SOURCE blocks are RAICA-computed MODEL ESTIMATES — their "
            "content is explicitly labeled 'RAICA MODEL ESTIMATE' (DCF intrinsic value) or 'Historical-CAGR "
            "Extrapolation' (forward revenue/earnings/FCF projections). These ARE permitted to be relayed, but "
            "you MUST (a) attribute them to the RAICA model — NEVER cite the Yahoo URL as the source of the "
            "estimate, and never present them as market-sourced data; (b) label them explicitly as estimates in "
            "the final answer; (c) never blend a model estimate with a sourced figure without distinguishing the "
            "two. The 'never invent/guess/estimate/extrapolate' rule above applies to figures YOU generate "
            "yourself — it does NOT forbid relaying a clearly-labeled model estimate from the evidence.\n"
            "- INLINE CHARTS (MANDATORY — treat exactly like a required citation): some SOURCE blocks "
            "contain a chart marker of the exact form `[[chart:<url>|align=...|caption=\"...\"]]` (a "
            "RAICA-generated technical chart for a specific stock — its caption names the stock). You MUST "
            "reproduce EVERY chart marker that appears in the evidence, each exactly once, copied EXACTLY and "
            "VERBATIM (never alter the URL, caption, or align; never wrap it in code fences). It is YOUR "
            "decision WHERE each belongs, but a chart marker present in the evidence and OMITTED from your "
            "answer is a FAILURE — as serious as dropping a required citation. Place each on its OWN line "
            "within that stock's technical / price-action discussion (the caption tells you which stock). "
            "So if the evidence has five chart markers, your answer MUST contain all five, one per stock. "
            "NEVER invent a marker, reuse one stock's URL for a different stock, or emit a marker that is not "
            "in the evidence. For your convenience these markers are ALSO listed together under 'AVAILABLE "
            "CHARTS' just below the USER REQUEST — treat that list as your authoritative checklist: your "
            "answer must contain EVERY marker in it, each placed in its stock's section. These markers are "
            "CONTENT you must reproduce, not reference artifacts to summarize away.\n"
            "- STRUCTURE: BEGIN with a SINGLE top-level title line — `# <a concise Title-Case name for "
            "the overall topic of THIS request>` (exactly one H1 naming the WHOLE report; it must NOT be "
            "numbered and must NOT be a section heading) — then a brief **TL;DR** (2-4 sentences giving "
            "the bottom-line answer for skim readers), then the detailed sections as `##` headings (as "
            "many as the material warrants), then a "
            "**## Conclusion** that recaps the key findings and directly answers the request, and "
            "FINALLY a **## References** section listing the sources you cited as clickable "
            "[Specific Article Headline](URL) (the headline as link text, never a bare outlet name) — "
            "every URL in References MUST be one provided in the evidence (never invented)."
        )
        # For enumeration requests, the pre-extracted roster (from the FULL evidence set) is
        # injected so every qualifying item gets a row even if its detail evidence was truncated.
        roster_block = f"\n\n{roster}\n" if roster else ""
        # AVAILABLE CHARTS inventory (fix, 2026-07-11): surface the evidence's chart markers as a distinct,
        # SALIENT list OUTSIDE the evidence SOURCE blocks. Measured effect on the 5-stock case: first-pass
        # marker relay jumped from ~2/6 to 5/5 — because buried in a SOURCE block the writer treats a marker
        # as read-only reference to summarize away, whereas an explicit "place each of these" checklist frames
        # it as content to emit. RAICA does NOT choose placement here: it only lists the exact tokens that
        # came from the evidence and tells the LLM each must appear in its stock's section (LLM decides where).
        _required_markers = self._chart_markers_in_evidence(doc) if self._chart_completeness_on else []
        chart_block = ""
        if _required_markers:
            _inv = "\n".join(_required_markers)
            chart_block = (
                f"\n\nAVAILABLE CHARTS — your answer MUST contain EVERY ONE of the {len(_required_markers)} "
                "chart markers below, each exactly once, copied VERBATIM, on its OWN line inside the section "
                "discussing the stock its caption names (its technical / price-action analysis). These are "
                "CONTENT to reproduce, not reference material to summarize. Do not omit any, do not add any "
                f"not listed, do not alter them:\n{_inv}\n"
            )
        prompt = f"USER REQUEST:\n{user_request}{roster_block}{chart_block}\n\nEVIDENCE:\n{doc}"
        kwargs = {"system_prompt": system_prompt, "temperature": 0.4,
                  "max_tokens": self._max_answer_tokens, "stream": False}
        if model:
            kwargs["model"] = model
        draft = await _collect_stream(self._gen, prompt, **kwargs)
        # First-pass probe (raw model behavior). Note: prompt now also contains the AVAILABLE CHARTS
        # inventory, so prompt count = evidence markers + inventory markers (2× the required count).
        logger.info("🖼️🔎 synth chart-markers — evidence=%d prompt=%d draft=%d",
                    doc.count('[[chart:'), prompt.count('[[chart:'), draft.count('[[chart:'))
        # GUARANTEE completeness: mechanically verify every evidence marker made it into the draft, and if
        # the writer dropped any (stochastic all-or-nothing drop), feed them back for the LLM to re-place
        # (bounded, LLM decides placement). No-op when there are no markers or the draft is already complete.
        draft = await self._ensure_chart_completeness(draft, doc, model)
        logger.info("🖼️🔎 synth chart-markers (final) — required=%d final_draft=%d",
                    len(_required_markers), draft.count('[[chart:'))
        _out_tok = _tok_count(draft)
        _cap = self._max_answer_tokens
        logger.info("📝 Synthesized draft (%s): %d chars, ~%d output tokens / %d cap (%d%% of cap)%s",
                    model or "primary", len(draft), _out_tok, _cap,
                    round(100 * _out_tok / max(1, _cap)),
                    "  ⚠️ AT CAP — output may be truncated" if _out_tok >= _cap * 0.98 else "")
        return draft

    # ---- step 3: multi-model arbitration (C1) ----
    async def arbitrate(self, user_request: str, drafts: List[Dict[str, str]]) -> str:
        labeled = "\n\n".join(
            f"===== DRAFT {i+1} (model: {d['model']}) =====\n{d['draft']}"
            for i, d in enumerate(drafts)
        )
        system_prompt = (
            "Multiple independent draft answers to the same research request will be provided. Reconcile "
            "them into ONE final answer — REASON about why they differ and which reasoning is better-"
            "grounded; do not merely union them.\n\n"
            + REASONING_DIRECTIVE +
            "\nThe reconciled answer must:\n"
            "- OPENS with a brief **TL;DR** (2-4 sentences giving the bottom-line answer for skim readers);\n"
            "- is COMPREHENSIVE and MUST be AT LEAST AS LONG AND DETAILED as the most thorough draft "
            "(do NOT compress or summarize) — take the UNION of the drafts: merge ALL complementary "
            "explanations, context, and detail from every draft rather than reducing to their common "
            "subset. Only drop content that is unsupported or contradicted by the evidence;\n"
            "- ENRICHES the key points: on the 2-4 most important points relevant to the user's "
            "request, ADD an extra sentence or two of supporting explanation, mechanism, context, or "
            "implication that the evidence supports — give the reader a little more depth and insight "
            "at the spots that matter most (without padding minor points or repeating yourself, and "
            "never adding anything not grounded in the evidence);\n"
            "- where the drafts materially DISAGREE, presents the disagreement explicitly rather "
            "than silently picking one side;\n"
            "- preserves all clickable [Title](URL) citations;\n"
            "- ALWAYS ends the main body with a **## Conclusion** that recaps the key findings and "
            "directly answers the request;\n"
            "- THEN, only if the drafts disagreed, appends a short **## Notable Source Conflicts** "
            "section AFTER the Conclusion."
        )
        prompt = f"USER REQUEST:\n{user_request}\n\n{labeled}"
        kwargs = {"system_prompt": system_prompt, "temperature": 0.2,
                  "max_tokens": self._max_answer_tokens, "stream": False}
        if self._arbitration_model:
            kwargs["model"] = self._arbitration_model
        final = await _collect_stream(self._gen, prompt, **kwargs)
        _out_tok = _tok_count(final)
        _cap = self._max_answer_tokens
        logger.info("⚖️ Arbitrated %d drafts (%s) → final answer (%d chars, ~%d output tokens / %d cap, %d%% of cap)%s",
                    len(drafts), self._arbitration_model or "primary", len(final), _out_tok, _cap,
                    round(100 * _out_tok / max(1, _cap)),
                    "  ⚠️ AT CAP — output may be truncated" if _out_tok >= _cap * 0.98 else "")
        return final

    # ---- step 4: claim extraction + cross-source verification (C1) ----
    async def verify(self, user_request: str, answer: str,
                     evidence: List[Dict[str, Any]], credibility: Dict[str, str]) -> Dict[str, Any]:
        # Use a SMALLER evidence budget for verify so input doesn't fill the window and starve
        # the output JSON (a full-budget evidence doc left only ~5K output room → 0 claims).
        doc = self._evidence_document(evidence, credibility, budget=self._verify_evidence_budget)
        system_prompt = (
            "You are a rigorous fact-checker. Extract EVERY distinct, checkable factual CLAIM made in "
            "the ANSWER — be EXHAUSTIVE, not selective. Long answers contain many claims; go through the "
            "answer section by section and capture each substantive factual assertion (statistics, "
            "dates, causal/mechanistic statements, attributions, named findings). Do NOT sample or "
            "summarize — aim for complete coverage of the answer's factual content. Then verify each "
            "claim against the EVIDENCE. For every claim assign:\n"
            f"- verdict: 'supported' (>= {self._min_sources} independent sources in the evidence agree), "
            "'contradicted' (evidence sources disagree), or 'unverified' (not corroborated by the evidence)\n"
            "- flag_reason: ONLY for contradicted/unverified claims, classify WHY (this matters — it "
            "distinguishes a possible error in the answer from the answer faithfully reporting a claim "
            "from a weak source):\n"
            "    * 'contradicted_by_evidence' — the evidence actively disagrees with the claim (possible error)\n"
            "    * 'not_in_evidence' — the answer asserts something the gathered sources simply don't cover "
            "(possibly ungrounded — scrutinize)\n"
            "    * 'attributed_to_low_credibility' — the answer is CORRECTLY presenting this as an attributed "
            "claim from a low-credibility/polemical source (e.g. 'Source X claims …'); the answer is being "
            "honest, the flag is about the SOURCE's reliability, not the answer's accuracy\n"
            "  (for 'supported' claims, set flag_reason to null)\n"
            "- confidence: 0.0-1.0\n"
            "- citations: list of supporting/contradicting URLs taken ONLY from the evidence\n"
            "- note: one short sentence explaining the verdict/flag\n\n"
            "Respond with STRICT JSON only:\n"
            '{"claims": [{"text": "...", "verdict": "supported", "flag_reason": null, "confidence": 0.9, '
            '"citations": ["https://..."], "note": "..."}]}'
        )
        prompt = f"USER REQUEST:\n{user_request}\n\nANSWER:\n{answer}\n\nEVIDENCE:\n{doc}"
        kwargs = {"system_prompt": system_prompt, "temperature": 0.0,
                  "max_tokens": self._verify_max_tokens, "stream": False}
        if self._verify_model:
            kwargs["model"] = self._verify_model
        raw = await _collect_stream(self._gen, prompt, **kwargs)
        try:
            data = extract_json_object(raw)
            claims = data.get("claims", []) if isinstance(data, dict) else []
        except Exception as e:  # noqa: BLE001
            # The verify JSON can be huge for long/enumerated answers and may get truncated mid-array.
            # Salvage every COMPLETE claim object rather than discarding the whole audit (→ 0 claims).
            claims = _salvage_claim_objects(raw)
            if claims:
                logger.warning("🔬 Claim verification JSON truncated (%s) — salvaged %d complete claims",
                               e, len(claims))
            else:
                logger.warning("🔬 Claim verification unparseable (%s)", e)
        counts: Dict[str, int] = {}
        for c in claims:
            v = str(c.get("verdict", "unverified")).lower()
            counts[v] = counts.get(v, 0) + 1
        logger.info("🔬 Verified %d claims (%s): %s", len(claims), self._verify_model or "primary", counts)
        return {"claims": claims, "verdict_counts": counts}

    # ---- orchestration ----
    async def run(self, user_request: str, evidence: List[Dict[str, Any]],
                  on_progress: Optional[Any] = None) -> Dict[str, Any]:
        async def emit(msg: str):
            if on_progress:
                await on_progress(msg)

        if not evidence:
            raise ValueError("synthesis requires a non-empty evidence pool")

        timings: Dict[str, float] = {}

        await emit("Grading source credibility…")
        _t = time.monotonic()
        if self._provenance_on:
            # SHADOW (Phase 0): grade source ROLES in PARALLEL with credibility so tier grading stays
            # byte-identical and no wall-clock is added; log the primary-vs-secondary baseline. The role
            # result is NOT fed to synthesis/verify yet → zero answer change (docs/RAICA_SOURCE_PROVENANCE.md).
            credibility, _roles = await asyncio.gather(
                self.grade_sources(evidence), self._grade_roles_shadow(evidence))
            self._log_provenance_shadow(evidence, credibility, _roles)
        else:
            credibility = await self.grade_sources(evidence)
        timings["grade"] = round(time.monotonic() - _t, 1)

        # SHADOW (docs/RAICA_DR_SOURCE_RELEVANCE.md — layer B): flag gathered sources that are only a
        # keyword/homonym match for the topic (e.g. CS 'Byzantine Agreement' papers for the Byzantine
        # Empire). Log-only in Phase 0 → zero answer change; fail-open.
        self._last_off_topic_urls = set()   # read by the pipeline for Layer-B enforce (drop off-topic citations)
        if self._source_relevance_on:
            try:
                _rel = await self._grade_relevance_shadow(user_request, evidence)
                self._log_source_relevance_shadow(_rel)
                self._last_off_topic_urls = {u for _t, u in _rel.get("off_topic", []) if u}
            except Exception as _sr_e:  # noqa: BLE001
                logger.warning("🎯 Source-relevance shadow skipped (%s)", _sr_e)

        # Optional enumeration roster (None for non-list requests → unchanged single-pass path).
        _t = time.monotonic()
        roster = await self._extract_roster(user_request, evidence)
        if roster is not None:
            await emit("Enumeration request — extracted complete item roster from all evidence…")
            timings["roster"] = round(time.monotonic() - _t, 1)

        models = self._arbitration_models
        if models:
            await emit(f"Synthesizing with {len(models)} models ({', '.join(models)})…")
            _t = time.monotonic()
            drafts_raw = await asyncio.gather(*[
                self.synthesize(user_request, evidence, credibility, model=m, roster=roster)
                for m in models
            ])
            timings["synthesize"] = round(time.monotonic() - _t, 1)
            drafts = [{"model": m, "draft": d} for m, d in zip(models, drafts_raw)]
            await emit("Reconciling drafts (arbitration)…")
            _t = time.monotonic()
            final_answer = await self.arbitrate(user_request, drafts)
            timings["arbitrate"] = round(time.monotonic() - _t, 1)
            arbitrated = True
        else:
            await emit("Synthesizing answer…")
            _t = time.monotonic()
            final_answer = await self.synthesize(user_request, evidence, credibility, roster=roster)
            timings["synthesize"] = round(time.monotonic() - _t, 1)
            drafts = [{"model": "primary", "draft": final_answer}]
            arbitrated = False

        if self._verify_on:
            await emit("Verifying claims against sources…")
            _t = time.monotonic()
            try:
                verification = await self.verify(user_request, final_answer, evidence, credibility)
            except Exception as e:  # noqa: BLE001 — a verify failure must NOT discard a good answer
                logger.warning("🔬 Verification failed (%s) — returning answer without audit", e)
                verification = {"claims": [], "verdict_counts": {}}
            timings["verify"] = round(time.monotonic() - _t, 1)
        else:
            verification = {"claims": [], "verdict_counts": {}}

        logger.info("⏱️ Stage 2 timings (s): %s", timings)
        return {
            "final_answer": final_answer,
            "credibility": credibility,
            "credibility_reasons": getattr(self, "credibility_reasons", {}),
            "verification": verification,
            "metadata": {
                "arbitrated": arbitrated,
                "models": models or ["primary"],
                "claims_checked": len(verification.get("claims", [])),
                "verdict_counts": verification.get("verdict_counts", {}),
                "timings": timings,
            },
        }
