# RAICA — Output-side Citation Grounding for the NON-DR path (bots + @Ask) — Solution Proposal

**Status:** Phase 0 SHADOW **IMPLEMENTED & DEPLOYED** (v1.0.0.141). Baselining on live. Enforcement (Phase 1+)
not wired yet. Original proposal below.
**Author:** drafted 2026-07-06. **Scope:** the non-Deep-Research answer path (`fastapi_server_complete.py`
streaming/post-LLM section) used by NewX bots and `@Ask`. **Risk class:** MEDIUM-HIGH — touches a **core hot
path** (every non-DR reply), so it is designed **shadow-first, reuse-only, lossless, fail-open**.

---

## 1. Problem (operator-reported, root-caused)

Non-DR bot posts carry bad citations: **fabricated URLs** (`houseofsud.com/riyadh-said-no-then-sent-the-deputy/`
— domain does not resolve; **0 occurrences in any log → the model invented it in its output**) and **generic
section/landing pages** (`bbc.com/news/world/middle_east`, `khaleejtimes.com/world/mena`) cited as if articles.

**Verified NOT a regression / NOT the model swap:**
- The bot's models (`deepseek-v4-pro` synth + `glm-5.2` tool-calling) were **unchanged** by the 2026-07 model
  retirement swap (v1.0.0.140).
- Section-page citations are **long-standing**: across 14 `@raicaMiddleEast` posts (id 5402→5564) the section
  count is consistently 3–12 per post, with several **older** posts worse than the flagged one (5544 had 12).
- Fabricated domains are **sporadic** (only `houseofsud` didn't resolve; `menatoday.info`, `mecouncil.org`,
  `middleeasteye.net`, `acleddata.com`, `liveuamap.com` are all real). `houseofsud` was a one-off hallucination
  that stood out because it 404s on click.

## 2. Root cause

The non-DR path filters **tool results at gather time** (`get_text_from_url_simplified` drops 404/homepage-
redirects; `get_news_summaries` drops dead + `non-RSS section/landing` URLs — **alive, 1,731 drops in the log**)
but has **NO output-side grounding**: nothing checks the model's FINAL answer. So a URL the model **fabricates**
or **recalls from memory** (a section page) is never caught. The **output-side grounding I built this week is
DR-only** (`research/pipeline.py` → `ground_citations` + liveness). The strong `system_prompt` "never fabricate
/ never cite homepages" rules are **soft and are violated** (raicaMiddleEast already has them). Only a
structural check works — proven on DR.

## 3. Proposed fix — extend the DR output-side grounding to non-DR (REUSE, don't rewrite)

After the non-DR answer is produced, classify each **cited** URL and strip the bad ones (keeping the visible
headline text — lossless for substance), using functions that ALREADY exist:

| Layer | Catches | Reuses (existing) |
|---|---|---|
| **A. Fabricated** | URL the model invented (not in the tool-result set) — e.g. `houseofsud` | `research/citation_grounding.ground_citations(answer, evidence_urls)` (by-reference; strip → keep text) |
| **B. Dead** | in-tool-results but now 404/410/homepage-redirect | `research/link_liveness.filter_live_article_urls` + `dead_urls=` into `ground_citations` (lenient + re-verify) |
| **C. Section/landing** | generic section pages (`/world/middle_east`) cited as articles | `_validate_article_url` (already used by `search_web` to SKIP non-article results at gather) applied to CITED urls |

**The "evidence set" for non-DR** = the URLs the tools actually returned this request. The tool results are
already assembled into the LLM context as `_format_source_block`s (`🔗 CITATION URL:` lines) — extract those
URLs (reuse `extract_cited_urls` / the `_URL_RE` regex) into the evidence set, exactly as DR does with its
`evidence[].urls`.

**Layering / risk order:** A (fabricated) is highest-confidence and lowest-risk (a URL no tool returned is
indefensible) → ship first. B (dead) reuses the proven lenient+re-verify liveness. C (section) has the most
false-positive risk (some "section-looking" URLs are real articles) → ship last, shadow-longest, and only strip
a section page when a SPECIFIC-article alternative exists or when it's clearly a landing page per
`_validate_article_url`.

## 4. The streaming / buffering decision (the crux)

Output-side grounding needs the FULL answer, but the non-DR path **streams**. Resolution:
- **NewX bots + @Ask collect the full reply anyway** (they post/store it; they do not render live tokens to a
  human). So for these, buffer-then-ground in RAICA is invisible.
- **Gate it** so a genuine token-streaming client (if any) is never buffered against its will: apply grounding
  only on the non-DR reply when the request is the collect-in-full shape (the `/v1` bot/@Ask path), matching how
  DR already returns a complete answer. Config flag governs on/off + shadow.
- Insertion point: the existing **post-LLM / post-processing section** (`fastapi_server_complete.py`, "Reached
  post-processing section") already runs AFTER the primary LLM completes and has the full answer — the natural,
  low-blast-radius seam (confirm exact locus in implementation).

## 5. Config (fail-open, reversible)
```yaml
non_dr:                      # NEW top-level (or under deep_research for reuse of the grounding cfg)
  citation_grounding:
    enabled: true
    shadow: true             # log would-be strips, answer UNCHANGED (baseline the non-DR fabrication/section rate)
    strip_fabricated: true   # Layer A
    strip_dead: true         # Layer B (liveness)
    strip_sections: false    # Layer C — enable last, after shadow review
```
Any failure (extraction, fetch, grounding) → today's behavior (answer never discarded).

## 6. Rollout (mirrors DR liveness Phase 0→1)
1. **Phase 0 — shadow.** Compute + log `🩹 nondr-citation [SHADOW]: fabricated=X dead=Y section=Z / N cited`
   on real bot/@Ask traffic. Answer unchanged. Baselines the true non-DR rate.
2. **Phase 1 — enforce A+B** (fabricated + dead). Lowest-risk, kills the houseofsud class.
3. **Phase 2 — enforce C** (sections) after its shadow numbers + false-positive audit look clean.

## 7. LLM-Policy-Gate compliance
- **No-Hardcoding:** grounding is **by-reference/structural** (URL in the gathered set or not); liveness is
  **empirical** (fetch → status); `_validate_article_url` is an existing structural article-vs-section check —
  no keyword/domain lists, no deciding *meaning*.
- **No-Inconsistency:** this makes the non-DR path enforce what its `system_prompt` already *asks* (never
  fabricate, never cite homepages) — the code now guarantees the policy the prompt states.

## 8. Test strategy
- Golden: an answer citing a fabricated URL (not in evidence) → stripped, headline kept; a real in-evidence
  article → untouched; byte-identical when nothing is wrong (reuse `test_citation_grounding` patterns).
- Section unit: `_validate_article_url` on `/world/middle_east` → non-article; on a datelined article → article.
- No-regression: existing non-DR flows; a normal @Ask with clean citations is unchanged.

> Bottom line: the non-DR bot/@Ask path never had the output-side grounding DR got this week. Reuse the exact
> proven machinery (fabricated-by-reference + lenient liveness + the existing article-vs-section check),
> shadow-first, on the already-full answer at the post-LLM seam — enforcing the citation policy the prompts
> already state, without penalizing or hiding a good citation.
