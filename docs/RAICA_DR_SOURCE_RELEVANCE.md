# RAICA — Deep Research SOURCE↔TOPIC RELEVANCE (domain-fit pre-search judge + relevance gate) — Proposal

**Status:** PROPOSAL (for review → design → implementation). **No code changed yet.**
**Drafted:** 2026-07-07. **Scope:** DR evidence gathering + grading (`research/engine.py`, `research/synthesis.py`,
`research/pipeline.py`) — specifically `published_papers_search` source selection and cited-source relevance.
**Risk class:** MEDIUM — shadow-first, LLM-judged (no keyword lists), fail-open.

---

## 1. Problem (observed — post 5589 / reply 474)
A medieval-**history** question ("why did the Byzantine Empire lose to Khalid ibn al-Walid… using historical
primary sources") produced a strong answer but **8 citations, all arxiv.org, 7 of them computer-science papers
on the "Byzantine Generals Problem" / Byzantine fault-tolerance** — a distributed-systems **homonym** of the
Byzantine *Empire* (the 8th was arxiv climate science). All are real, live (HTTP 200), in-evidence papers — so
liveness + grounding passed them. The failure is **topical/domain relevance**, which nothing checks.

**Confirmed from logs (03:11:35):** `published_papers_search` sent the (well-planned) sub-questions to Semantic
Scholar + arXiv. `Semantic Scholar 429` (rate-limited — the one corpus that covers history was lost); `arXiv 500`
on full-sentence queries → surviving results came from arXiv keyword hits on "Byzantine" = the CS homonym.

## 2. Root cause — two missing LLM judges
The DR pipeline already: (a) LLM-plans good sub-questions, and (b) LLM-selects source TOOLS
(`engine.py:230` — "prefer published_papers_search for scholarly claims"). But:
- **No DOMAIN↔CORPUS fit judge before the paper search.** "Scholarly" is treated as "use published_papers_search",
  but its corpora (arXiv, PubMed, bioRxiv, Europe PMC) are STEM/biomedical. A humanities/history topic has **zero
  coverage** there, so the search can only return noise/homonyms. `published_papers_search` also queries **all
  corpora unconditionally** (it accepts an optional `sources` param that is not being scoped).
- **No SOURCE↔TOPIC relevance gate after gathering.** A cited paper that shares only a keyword ("Byzantine") with
  the topic is never rejected — liveness/grounding verify live + in-evidence, not *aboutness*.

## 3. Proposed fix — two LLM-judged layers (both policy-clean; the LLM decides, no keyword lists)

### A. Domain-fit PRE-SEARCH judge (sharpen focus BEFORE the search — directly answers "why no judge ahead?")
Before invoking `published_papers_search`, an LLM judges: *"Is this sub-question in a field that peer-reviewed
STEM/biomedical preprint databases (arXiv/PubMed/bioRxiv/Europe PMC) actually index?"* and returns a small
structured verdict:
- **in-corpus (STEM/biomed):** proceed; optionally pass tightened keyword terms + the right `sources` subset.
- **humanities/history/law/arts (out-of-corpus):** **skip** arXiv/PubMed etc.; route to the humanities-capable
  sources only (`semantic_scholar`, `doaj`, `crossref`) and/or lean on `search_web` + reputable
  reference/encyclopedic/history sources. Never cite a STEM preprint as a "primary source" for history.
- It also returns **sharpened query terms** (disambiguated for homonyms — "Byzantine Empire military history",
  not bare "Byzantine"), so even the in-corpus path searches with focus.

This reuses `published_papers_search`'s existing `sources` param (arxiv/semantic_scholar/pubmed/europe_pmc/doaj/
biorxiv) — the judge sets it instead of the default "all".

### B. SOURCE↔TOPIC relevance GATE after gathering (the general catch-all)
In grading/synthesis, the LLM scores each gathered/cited source's title+abstract against the sub-question it is
meant to support: *"Is this source actually ABOUT this topic, or only a keyword/homonym match?"* Off-topic
sources are dropped from the citable set (kept out of the answer). This is a natural extension of the existing
**headline↔URL consistency** check (retrieval_quality) — same shape, applied to source aboutness. It catches
ANY homonym/domain collision, not just "Byzantine", and is the safety net for whatever A misses.

**Layering:** A prevents the wrong corpus being searched (fixes the source of the noise); B rejects any off-topic
source that still slips through. Ship A + B together in shadow; they compound.

## 4. Shadow-first rollout (mirrors the liveness/grounding work)
1. **Phase 0 — shadow.** Log what A *would* skip/re-route and what B *would* drop
   (`🎯 dr-source-relevance [SHADOW]: domain=<in/out> reroute=<sources> off_topic_dropped=N/total`),
   answer unchanged. Baseline on real DR traffic (esp. any humanities queries).
2. **Phase 1 — enforce B** (drop off-topic cited sources; lowest-risk, output-side, keeps the answer text).
3. **Phase 2 — enforce A** (domain-scoped source selection) after its shadow numbers look clean.

## 5. Config (fail-open, reversible)
```yaml
deep_research:
  source_relevance:
    enabled: true
    shadow: true            # Phase 0 log-only
    domain_fit_judge: true  # A — pre-search corpus routing
    relevance_gate: true    # B — post-gather aboutness drop
```
Any judge failure/timeout → today's behavior (no source dropped, all corpora searched).

## 6. LLM-Policy-Gate compliance
- **No-Hardcoding:** both layers are **LLM verdicts** from the topic + source text — no keyword/discipline lists,
  no `if "history" in q`. The corpus routing uses the tool's own `sources` enum as the LLM's option set.
- **No-Inconsistency:** aligns the pipeline with what it already tries to do (`engine.py:230` "most appropriate
  source") — it just adds the missing "is this topic in this corpus?" and "is this source about the topic?" checks.

## 7. Also worth fixing (separate, infra)
- **Semantic Scholar 429s:** the one paper corpus with humanities coverage is being rate-limited, which is what
  left arXiv as the only survivor here. Add backoff/API key so humanities queries can reach it.
- **arXiv 500 on full-sentence queries:** send tightened keyword terms (from judge A), not raw sub-questions.

> Bottom line: DR already plans good queries and picks the paper tool — it's missing the two LLM judgments that
> *sharpen focus*: (A) "is this topic even in these databases?" **before** the search, and (B) "is this source
> actually about the topic?" **after**. Both LLM-driven, shadow-first, reusing the tool's `sources` param and the
> existing headline-consistency machinery.
