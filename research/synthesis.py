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

    # ---- step 1: credibility grading (C2/C3) ----
    def _unique_domains(self, evidence: List[Dict[str, Any]]) -> List[str]:
        domains = {d for e in evidence for u in e.get("urls", []) if (d := _domain_of(u))}
        return sorted(domains)

    async def grade_sources(self, evidence: List[Dict[str, Any]]) -> Dict[str, str]:
        """LLM grades each source domain into a credibility tier. No hardcoded lists."""
        domains = self._unique_domains(evidence)
        if not domains or not self._grading_on:
            return {}
        prompt = (
            "Grade each source domain below into exactly ONE credibility tier for use in a "
            "research report:\n"
            "- peer_reviewed: academic journals/preprint servers/databases (e.g. arxiv, pubmed, "
            "doi.org, core.ac.uk, journal sites)\n"
            "- reputable: established institutions, governments (.gov), universities (.edu), major "
            "news organizations, encyclopedias\n"
            "- popular: general-interest blogs/magazines/explainer sites (not scholarly, but not fringe)\n"
            "- low_credibility: fringe, pseudoscience, conspiracy, or self-published advocacy sites\n\n"
            "DOMAINS:\n" + "\n".join(f"- {d}" for d in domains) + "\n\n"
            "Respond with STRICT JSON only mapping each domain to its tier, e.g.:\n"
            '{"arxiv.org": "peer_reviewed", "somefringeblog.com": "low_credibility"}'
        )
        raw = await _collect_stream(self._gen, prompt, temperature=0.0, max_tokens=1500, stream=False)
        try:
            data = extract_json_object(raw)
        except Exception as e:  # noqa: BLE001
            logger.warning("🏷️ Credibility grading unparseable (%s) → all 'unknown'", e)
            return {d: "unknown" for d in domains}
        graded = {}
        for d in domains:
            tier = str(data.get(d, "unknown")).strip().lower()
            graded[d] = tier if tier in VALID_TIERS else "unknown"
        tally: Dict[str, int] = {}
        for t in graded.values():
            tally[t] = tally.get(t, 0) + 1
        logger.info("🏷️ Graded %d domains: %s", len(graded), tally)
        return graded

    @property
    def _evidence_token_budget(self) -> int:
        return int(self._cfg.get("synthesis", {}).get("evidence_token_budget", 110000))

    def _allocate_token_budget(self, evidence: List[Dict[str, Any]]) -> List[int]:
        """
        Fair token allocation across sources so the evidence document fits the model window:
        small sources are kept whole; leftover budget is split among the large ones (which are
        truncated only if still over). Returns a per-item token cap aligned with `evidence`.
        """
        budget = self._evidence_token_budget
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
                           credibility: Dict[str, str]) -> str:
        caps = self._allocate_token_budget(evidence)
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

    # ---- step 2: grounded, credibility-aware synthesis (C3) ----
    async def synthesize(self, user_request: str, evidence: List[Dict[str, Any]],
                         credibility: Dict[str, str], model: Optional[str] = None) -> str:
        doc = self._evidence_document(evidence, credibility)
        prompt = (
            "You are a meticulous research writer. Using ONLY the evidence below, write a "
            "comprehensive, well-structured answer to the user's request.\n\n"
            "RULES (strict):\n"
            "- Ground every factual claim in the evidence; cite as clickable [Title](URL) using "
            "ONLY URLs present in the evidence. Never invent URLs, facts, dates, or names.\n"
            "- Respect source credibility: support scholarly/scientific claims with peer_reviewed or "
            "reputable sources. Content from low_credibility sources must be presented as an "
            "ATTRIBUTED claim (e.g. 'X claims …') and clearly framed/debunked — never as fact.\n"
            "- Where sources CONFLICT, explicitly say so and present both sides with citations.\n"
            "- Do NOT overstate your sourcing (e.g. do not call popular/low-credibility sources "
            "'peer-reviewed'). If evidence is thin or absent for part of the request, say so plainly.\n"
            "- STRUCTURE: open with a brief **TL;DR** (2-4 sentences giving the bottom-line answer for "
            "skim readers), then the detailed sections, and ALWAYS end with a **## Conclusion** that "
            "recaps the key findings and directly answers the user's request.\n\n"
            f"USER REQUEST:\n{user_request}\n\n"
            f"EVIDENCE:\n{doc}"
        )
        kwargs = {"temperature": 0.3, "max_tokens": 8000, "stream": False}
        if model:
            kwargs["model"] = model
        draft = await _collect_stream(self._gen, prompt, **kwargs)
        logger.info("📝 Synthesized draft (%s): %d chars", model or "primary", len(draft))
        return draft

    # ---- step 3: multi-model arbitration (C1) ----
    async def arbitrate(self, user_request: str, drafts: List[Dict[str, str]]) -> str:
        labeled = "\n\n".join(
            f"===== DRAFT {i+1} (model: {d['model']}) =====\n{d['draft']}"
            for i, d in enumerate(drafts)
        )
        prompt = (
            "Multiple independent draft answers to the same research request are shown below. "
            "Produce a SINGLE reconciled final answer that:\n"
            "- OPENS with a brief **TL;DR** (2-4 sentences giving the bottom-line answer for skim readers);\n"
            "- keeps only claims that the drafts agree on or that carry stronger citations;\n"
            "- where the drafts materially DISAGREE, presents the disagreement explicitly rather "
            "than silently picking one side;\n"
            "- preserves all clickable [Title](URL) citations;\n"
            "- ALWAYS ends the main body with a **## Conclusion** that recaps the key findings and "
            "directly answers the request;\n"
            "- THEN, only if the drafts disagreed, appends a short **## Notable Source Conflicts** "
            "section AFTER the Conclusion.\n\n"
            f"USER REQUEST:\n{user_request}\n\n{labeled}"
        )
        final = await _collect_stream(self._gen, prompt, temperature=0.2, max_tokens=8000, stream=False)
        logger.info("⚖️ Arbitrated %d drafts → final answer (%d chars)", len(drafts), len(final))
        return final

    # ---- step 4: claim extraction + cross-source verification (C1) ----
    async def verify(self, user_request: str, answer: str,
                     evidence: List[Dict[str, Any]], credibility: Dict[str, str]) -> Dict[str, Any]:
        doc = self._evidence_document(evidence, credibility)
        prompt = (
            "Extract the distinct, checkable factual CLAIMS made in the ANSWER, then verify each "
            "against the EVIDENCE. For every claim assign:\n"
            f"- verdict: 'supported' (>= {self._min_sources} independent sources in the evidence agree), "
            "'contradicted' (evidence sources disagree), or 'unverified' (not found in evidence)\n"
            "- confidence: 0.0-1.0\n"
            "- citations: list of supporting/contradicting URLs taken ONLY from the evidence\n"
            "- note: one short sentence (e.g. flag a source conflict or weak/low-credibility support)\n\n"
            f"USER REQUEST:\n{user_request}\n\nANSWER:\n{answer}\n\nEVIDENCE:\n{doc}\n\n"
            "Respond with STRICT JSON only:\n"
            '{"claims": [{"text": "...", "verdict": "supported", "confidence": 0.9, '
            '"citations": ["https://..."], "note": "..."}]}'
        )
        raw = await _collect_stream(self._gen, prompt, temperature=0.0, max_tokens=4000, stream=False)
        try:
            data = extract_json_object(raw)
            claims = data.get("claims", []) if isinstance(data, dict) else []
        except Exception as e:  # noqa: BLE001
            logger.warning("🔬 Claim verification unparseable (%s)", e)
            claims = []
        counts: Dict[str, int] = {}
        for c in claims:
            v = str(c.get("verdict", "unverified")).lower()
            counts[v] = counts.get(v, 0) + 1
        logger.info("🔬 Verified %d claims: %s", len(claims), counts)
        return {"claims": claims, "verdict_counts": counts}

    # ---- orchestration ----
    async def run(self, user_request: str, evidence: List[Dict[str, Any]],
                  on_progress: Optional[Any] = None) -> Dict[str, Any]:
        async def emit(msg: str):
            if on_progress:
                await on_progress(msg)

        if not evidence:
            raise ValueError("synthesis requires a non-empty evidence pool")

        await emit("Grading source credibility…")
        credibility = await self.grade_sources(evidence)

        models = self._arbitration_models
        if models:
            await emit(f"Synthesizing with {len(models)} models ({', '.join(models)})…")
            drafts_raw = await asyncio.gather(*[
                self.synthesize(user_request, evidence, credibility, model=m) for m in models
            ])
            drafts = [{"model": m, "draft": d} for m, d in zip(models, drafts_raw)]
            await emit("Reconciling drafts (arbitration)…")
            final_answer = await self.arbitrate(user_request, drafts)
            arbitrated = True
        else:
            await emit("Synthesizing answer…")
            final_answer = await self.synthesize(user_request, evidence, credibility)
            drafts = [{"model": "primary", "draft": final_answer}]
            arbitrated = False

        if self._verify_on:
            await emit("Verifying claims against sources…")
            verification = await self.verify(user_request, final_answer, evidence, credibility)
        else:
            verification = {"claims": [], "verdict_counts": {}}

        return {
            "final_answer": final_answer,
            "credibility": credibility,
            "verification": verification,
            "metadata": {
                "arbitrated": arbitrated,
                "models": models or ["primary"],
                "claims_checked": len(verification.get("claims", [])),
                "verdict_counts": verification.get("verdict_counts", {}),
            },
        }
