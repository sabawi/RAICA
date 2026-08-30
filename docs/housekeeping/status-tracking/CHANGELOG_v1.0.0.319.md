# CHANGELOG v1.0.0.319

**Date:** 2026-08-30
**Theme:** the tool whitelist is now enforced where tools are actually dispatched

---

## 1. `allowed_tools` was advisory, not enforced (SECURITY)

`allowed_tools` filtered the tools_array we OFFER the model and logged
`🔒 Tool whitelist enforced`. It never checked the tool names the model
actually returned.

Ollama's tool-calling preamble (`pre_tool_model_system_prompt.txt`, ~72KB)
describes the whole catalogue regardless of the request's whitelist, so a model
handed only `['document_search']` emitted `search_web` + `wikipedia_query` — and
both executed. A client restricted to an indexed corpus answered from the open
web instead, and invented a product that does not exist while doing it.

**Fix.** Model-returned tool calls are filtered where they ENTER the system
(`_filter_model_tool_calls`), at all three entry points. Filtering at entry
rather than at dispatch is deliberate: there are several dispatchers, including
two different nested functions both named `execute_single_tool`. Guarding
dispatchers individually missed a path on the first attempt.

### Deliberately NOT enforced in `safe_function_call`
RAICA calls that itself for system-initiated work (`secure_email_sender` on the
delivery path). Enforcing there would block RAICA's own calls and break delivery
for every bot. The guard sits exactly at the model-chosen boundary.

### `get_the_secret_tool` is exempt
It is injected on every request (it is the clock) and appears in NO plugin
whitelist. Enforcing against it would have broken every existing bot — found by
checking the historical logs BEFORE writing the guard, not after.

---

## 2. `RAGONLY` prompt variant (`rag_only_tool_model_system_prompt.txt`)

Blocking the wrong tool does not make a model call the right one. The standard
prompt names `search_web` 38 times against `document_search` 15, so a
corpus-only request still had its selector reaching for web search — measured at
6 / 6 / 0 across one run.

`load_tool_model_system_prompt(..., RAGONLY=False)` swaps in a 5.4KB
corpus-only prompt naming no web tools. Selected automatically when the
effective whitelist is exactly `{document_search}`, read from the same
ContextVar the dispatch guard uses so prompt and enforcement cannot disagree.

Default `False` — every existing caller gets byte-identical output.

After: `document_search` 4 calls, `search_web` 0, answers grounded in the corpus,
and "not covered" when it genuinely is not.

---

## 3. Citation titles are readable (`user_tools/document_search.py`)

Was `f"{doc_name} (Score: {similarity_score:.3f})"` — a filename plus a raw
similarity score, which the answering model rendered verbatim into user-facing
prose (`tip-001.md (Score: 0.537)`). Now the document's first Markdown heading,
falling back to a tidied filename for continuation chunks.

---

## Backward compatibility — verified, not assumed

Prod NewX has none of the client-side changes, so this release had to work
against it unmodified.

- **Real payload probe.** `Just4laughs`' exact whitelist and `deep_research:false`
  → normal answer, 0 blocked, tools all within whitelist.
- **Charting / stock / calculation.** `@Ask`'s exact 10-tool whitelist →
  `[[chart:` marker produced, live AAPL data returned, `compute` executed 4×
  with correct exact arithmetic, 0 blocked.
- **Structural.** All 11 of @Ask's tools survive the filter; unrestricted
  clients (no whitelist) pass through untouched.
- **Suites.** 978 unit passed / 4 failed — the same 4 fail on HEAD, confirmed by
  stashing the changes. Tool + delivery integration: 25/25.
- **Deferred POST-LLM plugins** (`social_media_wordpress`,
  `social_media_twitter_test`) bypass the filter by construction — they are not
  model-returned tool calls.

## Known / unchanged

- `pre_tool_model_system_prompt.txt` has no `{USER_ADDITIONAL_INSTRUCTIONS}`
  token, so `user_additional_instructions` has never had any effect on that path.
  Left as-is: adding the token would change behaviour for every bot at once.
  The RAG-only prompt does carry it.
- `document_search` still emits `file://` citation URLs. Harmless for local
  clients; web-facing consumers must strip them (NewX does).
