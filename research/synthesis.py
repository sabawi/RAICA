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

from research.engine import extract_json_object, _collect_stream, GenerateStream

logger = logging.getLogger(__name__)

VALID_TIERS = ("peer_reviewed", "reputable", "popular", "low_credibility", "unknown")

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
        # Grading is non-essential context: on ANY failure (call or parse) fall back to
        # 'unknown' for every domain so synthesis can still proceed.
        try:
            raw = await _collect_stream(self._gen, prompt, system_prompt=system_prompt,
                                        temperature=0.0, max_tokens=3000, stream=False)
            data = extract_json_object(raw)
        except Exception as e:  # noqa: BLE001
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
            tiers = sorted({credibility.get(_domain_of(u), "unknown") for u in e.get("urls", [])})
            tier_tag = ",".join(tiers) if tiers else "unknown"
            blocks.append(
                f"───── EVIDENCE [{e.get('sub_question_id')} | source={e.get('source')} | "
                f"credibility={tier_tag}] ─────\n{content}"
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

    # ---- step 2: grounded, credibility-aware synthesis (C3) ----
    async def synthesize(self, user_request: str, evidence: List[Dict[str, Any]],
                         credibility: Dict[str, str], model: Optional[str] = None,
                         roster: Optional[str] = None) -> str:
        doc = self._evidence_document(evidence, credibility)
        system_prompt = (
            "You are an expert research writer producing an authoritative, in-depth report. A large "
            "body of evidence has been gathered for you — your job is to convey as much of its insight "
            "as possible to an avid, curious reader. Using ONLY the evidence provided, write the answer.\n\n"
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
            "- Ground every factual claim in the evidence; cite as clickable [Title](URL) using ONLY URLs "
            "present in the evidence. Never invent URLs, facts, dates, or names.\n"
            "- Calibrate CONFIDENCE to source credibility, but never use credibility to EXCLUDE a "
            "substantive point. Present well-established findings as established (citing peer_reviewed/"
            "reputable sources). Present contested or low-credibility-sourced claims as ATTRIBUTED "
            "positions (e.g. 'X argues …', 'According to Y …') with appropriate context about the "
            "source's standing — include and explain them, do not merely dismiss them. Reserve outright "
            "'debunking' for claims the evidence actually refutes; for the rest, present the debate fairly "
            "and let the reader weigh it.\n"
            "- Where sources CONFLICT, explicitly say so and present both/all sides with citations — the "
            "disagreement itself is valuable research content.\n"
            "- Do NOT overstate your sourcing (e.g. do not call popular/low-credibility sources "
            "'peer-reviewed'). If evidence is thin or absent for part of the request, say so plainly.\n"
            "- STRUCTURE: open with a brief **TL;DR** (2-4 sentences giving the bottom-line answer for "
            "skim readers), then the detailed sections (as many as the material warrants), and ALWAYS "
            "end with a **## Conclusion** that recaps the key findings and directly answers the request."
        )
        # For enumeration requests, the pre-extracted roster (from the FULL evidence set) is
        # injected so every qualifying item gets a row even if its detail evidence was truncated.
        roster_block = f"\n\n{roster}\n" if roster else ""
        prompt = f"USER REQUEST:\n{user_request}{roster_block}\n\nEVIDENCE:\n{doc}"
        kwargs = {"system_prompt": system_prompt, "temperature": 0.4,
                  "max_tokens": self._max_answer_tokens, "stream": False}
        if model:
            kwargs["model"] = model
        draft = await _collect_stream(self._gen, prompt, **kwargs)
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
            "Multiple independent draft answers to the same research request will be provided. "
            "Produce a SINGLE reconciled final answer that:\n"
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
        credibility = await self.grade_sources(evidence)
        timings["grade"] = round(time.monotonic() - _t, 1)

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
