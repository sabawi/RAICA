# CHANGELOG v1.0.0.132

**Date:** 2026-07-03
**Previous:** v1.0.0.131 (vision restored — kimi-k2.7-code:cloud)
**Theme:** **Image-aware evidence gathering.** When a user attaches an image and asks the bot to
*evaluate / verify / assess* what it shows, the tool-calling model now sees the vision analysis and
searches the actual subject — so replies carry real citations and stop being silently dropped.

---

## Symptom (live)

An `@Ask` post with an image — "will this design in the image work for its intended purpose" (a Mars
oxygen-plant infographic) — produced **no reply at all**. NewX ran its 2-attempt guard loop, discarded
both RAICA responses with `reason=missing required citations`, and posted nothing.

## Root cause (multi-stage, RAICA side)

The **vision analysis reached the synthesis LLM but never the tool-calling (query-generation) LLM.**

1. The forced image-processing stage runs `image_to_text` and stores the description **only** in
   `tools_results_list` (consumed later by the primary/synthesis LLM).
2. The tool-calling model is text-only and received just the fixed instruction + the user's wrapper text
   (`User Prompt: …`). It had no view of the image content.
3. Result: it formed evidence-gathering queries from the **wrapper text** (e.g. `"user posted design
   image will it work"`) and searched **blind** — returning irrelevant results (graphic/social-media
   "design" pages) instead of the real subject (solid oxide electrolysis / Mars ISRU oxygen).
4. The synthesis LLM correctly refused to cite the irrelevant URLs → a substantial url-less reply →
   NewX's citation guard (correctly, for a citation-required bot) discarded it. Twice → nothing posted.

## Fix (2 edits, RAICA)

- **`fastapi_server_complete.py`** (tool-message builder, STAGE 1): when the forced image-processing
  block already produced an analysis (`image_to_text` in `tools_called`), inject that analysis into the
  tool-calling model's user message as *"ANALYSIS OF THE USER'S ATTACHED IMAGE(S)"*. This is the model's
  "eyes" so it can decide, per policy, whether external evidence is needed and what to query. The model
  still decides — this is context, not a keyword router. The same `user_message` flows into the
  NO-TOOLS RE-PROMPT, so both call sites are covered by one change. Guarded to fire only on a successful
  analysis; a vision failure injects nothing.
- **`pre_tool_model_system_prompt.txt`**: added an `IMAGE-ATTACHED REQUESTS` directive making the
  describe-vs-evaluate boundary authoritative in the tool-model prompt — **describe / transcribe /
  translate / summarize → no external tools** (the image is the source); **assess / evaluate / verify /
  fact-check / explain real-world claims about what the image depicts → search + cite the specific
  subjects.** One voice with the existing bot-side citation policy (no conflicting directives).

No config, schema, dependency, or API changes. NewX's citation guard is unchanged.

## Verified (end-to-end, real posts through NewX → RAICA)

| Test | Server | Tool behavior | Posted |
|---|---|---|---|
| Evaluate — Mars oxygen plant | local | `search_web ×2 + wikipedia_query ×2` on SOXE/MOXIE → real NASA/Wikipedia/journal citations, 1 attempt | ✅ |
| Evaluate — Mars oxygen plant | live | same subject-relevant queries → real citations, 1 attempt | ✅ |
| Evaluate — plane range feasibility | live | identified aircraft + tail number **from the image**, queried Cessna 172 specs + route distance → 5 real citations, 1 attempt | ✅ |
| Describe (boundary regression) | live | `image_to_text` only — **0 searches**; url-less description | ✅ |

Before the fix these evaluate-with-image posts were discarded for missing citations; after, they post on
the first attempt with real, clickable sources. The describe path does **not** over-search.

## Known follow-up (separate component — NewX, not this change)

The describe test was discarded once then rescued by the guard's LLM judge on retry: NewX
`_classify_user_intent` uses a hardcoded keyword list that does not match phrasings like *"describe
what's shown in this image"*, so it falls through to the non-deterministic LLM judge. Tracked as a NewX
citation-guard robustness follow-up; it does not block posting.

## Files
- `fastapi_server_complete.py` (image analysis → tool-calling message)
- `pre_tool_model_system_prompt.txt` (IMAGE-ATTACHED REQUESTS boundary)
- `version.py` (→ 1.0.0.132)
- `README.md` (version bump)
- this changelog
