# CHANGELOG — RAICA v1.0.0.153

**Date:** 2026-07-08
**Type:** Fix — carry parent book/journal (container-title) into paper-search evidence

## Summary
A Byzantine DR cited `doi.org/10.5406/j.ctt2050vt5.13` — a chapter titled **"Consideration of Counterarguments"**
that reads perfectly on-topic — but its PARENT BOOK is **"The Ethical Case against Animal Experiments" (2017)**.
A generic chapter title is topically ambiguous in isolation; the container reveals the real subject. The DR only
saw the chapter title (Crossref/OpenAlex parsers dropped `container-title`), so neither the synthesis nor Layer B
could catch the mismatch — and JSTOR paywalled it (`turn_away=true`), so it was never actually read.

## Changes (`user_tools/published_papers_search_tool.py`)
- **Crossref** parser: title now `"<chapter> — in: <container-title>"` when a `container-title` exists and
  differs (book chapters, journal articles). Was: chapter title only.
- **OpenAlex** parser: same, using `primary_location.source.display_name` as the container.

## Verification
- Query "Consideration of Counterarguments Byzantine Arab conquest" now returns
  `Consideration of Counterarguments — in: The Ethical Case against Animal Experiments` (off-topic parent
  visible), and correctly contextualizes others ("Notes — in: From Byzantine to Islamic Egypt"). Also caught a
  second trap: "THE MILITARY SUPERIORITY THESIS — in: The Emergence of the Global Political Economy".

## Risk / rollback
- Additive to the title string (adds venue context); helps Layer B + synthesis judge relevance. Version → 1.0.0.153.
