# CHANGELOG v1.0.0.135

**Date:** 2026-07-05
**Previous:** v1.0.0.134 (DR citation-liveness Phase 0 — shadow)
**Theme:** **Fix endemic EuropePMC "Page not found" citations in academic Deep Research.** Academic DR
citations to EuropePMC were built with a mismatched source↔id pair and rendered "Page not found" in the
browser — a *soft-404* invisible to every HTTP/status check. Now built from the record's own `source`+`id`.

---

## Symptom (operator-reported)

A persistent, endemic problem: EuropePMC (`https://europepmc.org/`) citations in academic DR responses lead
to **"Page not found"**. EuropePMC hosts a large share of the scholarly sources RAICA cites, so this recurs
across academic research answers.

## Root cause

`user_tools/published_papers_search_tool.py _parse_europe_pmc_data()` built the citation URL as
`https://europepmc.org/article/MED/{pmcid}`. EuropePMC article URLs are `/article/{SOURCE}/{ID}` and the
SOURCE and ID **must match** — `MED`→a PubMed id (numeric), `PMC`→a PMCID (`PMC…`), `PPR`→a preprint id, etc.
The code always used `MED` but fed it the **PMCID**, producing a mismatched pair (e.g. `…/article/MED/PMC13246667`).

**Why it was invisible / "endemic":** EuropePMC is a JavaScript app that returns **HTTP 200** and an identical
page shell for *any* URL, then resolves the article **client-side**. So the malformed URL is a **soft-404** —
it renders "Page not found" in a browser while `curl`, status-code monitors, and even the new citation-liveness
check (v1.0.0.134, which keys on hard 404/410/redirect) all see `200 OK`. Confirmed against EuropePMC's own REST
resolver (the endpoint the article page calls): `MED/{pmcid}` returns an empty result (not found), while the
correct `{source}/{id}` returns the real record.

## Fix

Use the record's own `source` and `id` (both returned by the EuropePMC search API), which are always a valid
matching pair for every source type; fall back to the primary DOI. No hardcoded namespace.

```python
src = article.get("source")   # MED | PMC | PPR | AGR | …
aid = article.get("id")
if src and aid:
    europe_url = f"https://europepmc.org/article/{src}/{aid}"
elif doi:
    europe_url = f"https://doi.org/{doi}"
```

## Tests

- **`tests/integration/test_europepmc_citation_url.py` (NEW, 6 tests)** — PMC record → `/article/PMC/{pmcid}`;
  MED record → `/article/MED/{pmid}` (never the pmcid); PPR source generalizes; DOI fallback; `None` when no
  ids; plus a best-effort **live-resolution** check (the fixed `MED/{pmid}` resolves; the old `MED/{pmcid}`
  does not). All pass, incl. the live check.

## Dependencies / breaking changes / migration

None. Pure URL-construction fix inside the EuropePMC parser. Deploy: `git pull` on live + restart. No config
change.

## Related

Complements the DR citation-liveness work (`docs/RAICA_DR_CITATION_LIVENESS.md`, v1.0.0.134): that catches
*hard* dead links at output; this fixes a *soft-404* at the source (the only layer that can, since a soft-404
returns 200).
