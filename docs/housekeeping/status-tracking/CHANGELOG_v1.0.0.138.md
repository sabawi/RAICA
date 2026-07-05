# CHANGELOG v1.0.0.138

**Date:** 2026-07-05
**Previous:** v1.0.0.137 (retrieval-quality audit — shadow instrumentation)
**Theme:** **Headline↔URL consistency check (folded into the retrieval-quality/groundedness audit).**
Measures how often a cited **headline** (link text) actually matches the **title RAICA gathered** for that
URL — i.e. true citation *mispairing* — while NOT false-flagging the common benign case where a page's
on-page `<h1>`/slug differs from its `<title>`. Shadow measurement only; no answer change.

---

## Motivation

Operator observed a citation whose clickable text ("What Comes After Transformers: Hybrid AI Architecture in
2026") didn't visually match the page it opened (`…/the-last-architecture-designed-by-hand/`, on-page `<h1>`
"The Last Architecture Designed by Hand"). Verified **benign**: the cited text is that page's real
`<title>`/`og:title` (which RAICA gathered); the blog just displays a different `<h1>` and slug. But the
*look-alike* real bug is a headline paired with a **different source's** URL. This check distinguishes them.

## Change (measurement only)

- **`research/citation_grounding.py`**: new `extract_cited_links(answer)` → `(headline_text, url)` pairs
  (HTML `<a>` inner text stripped of tags; Markdown `[text](url)`), sibling to `extract_cited_urls`.
- **`research/retrieval_quality.py`**: `assess_retrieval` now also returns a `headline` block —
  `{matched, mismatched, checked, flagged}`. For each cited link whose URL RAICA holds a **gathered title**
  for (from the source block's `📄 SOURCE:` / `Title:` line, both block formats), it compares the cited
  headline to that gathered title with a lenient, order-independent significant-token overlap (≥50% of the
  shorter). A benign `<title>≠<h1>`/slug page is **NOT** flagged (RAICA gathered the `<title>`, the model used
  it); a headline from a different source (near-disjoint tokens) **is**. Fail-safe: no gathered title, or no
  significant tokens → not judged (no false alarm).
- **`research/pipeline.py`**: logs a second shadow line per run:
  `📎 headline-audit: matched=… mismatched=… / … checked (cited headline vs gathered title) | flagged=[…]`.

## Config

Reuses `deep_research.engine.retrieval_audit` (no new keys). Pure/offline, fail-open.

## Tests

`tests/integration/test_retrieval_quality.py`: +4 headline tests — benign `<title>`-suffix case **matches**;
a true mispairing is **flagged**; papers-block format matches; URLs without a gathered title are not judged.
Plus a new `extract_cited_links`. 17 pass (9 retrieval-quality + 8 grounding).

## Known limits

Offline by design: it checks the cited headline against **what RAICA gathered**, not against a fresh fetch of
the page — so it catches the model *changing/mispairing* a headline, not a search tool that gathered a wrong
`(title, url)` pair. Soft-404s remain out of scope (see v1.0.0.135/137).

## Dependencies / breaking changes / migration

None. Shadow measurement only. Deploy: `git pull` + restart; grep `📎 headline-audit` alongside
`📊 retrieval-audit` to quantify true mispairing vs. benign title/h1 differences.
