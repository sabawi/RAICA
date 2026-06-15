# CHANGELOG v1.0.0.93

**Date:** 2026-06-07
**Previous:** v1.0.0.92 (sandboxed_executor description fix)
**Theme:** **Deep-code-review fix of the "deliver answer as a file attachment" path** — generic tool
execution (route 1) + no false delivery claims + correct tool steering, all gate-compliant (no keywords)

---

## What the deep review found (the REAL root cause, with evidence)

Prior diagnoses (whitelist hardcoding, description overlap) were partial. The user-facing failure
(@Ask "email me … as an HTML attachment" → arrived as email **body**, no file, with a false "delivered"
claim) traced to:

- **Root cause (CRITICAL):** `_execute_missing_tools_post_llm` creates a file **only** in the
  `tool_name == "sandboxed_executor"` branch — there is **no `pdf_generator` branch** (verified). The
  LLM intent classifier (authoritative, open vocabulary) picked **`pdf_generator`**, which matched no
  branch → **silently created nothing** → `created_filename=None` → "No attachments found" → **body
  email.** The LLM-classifier cutover introduced this: legacy *always* emitted `sandboxed_executor`.
  My `.92` whitelist change (opening the classifier's tools) did **not** fix it — `pdf_generator` had
  no executor branch regardless.
- **False success (HIGH):** with delivery *permitted*, the positive awareness ("handled automatically,
  don't disclaim") made the LLM write "✅ email sent … as an attachment" even though the file step
  silently no-op'd.
- **Ordering (MEDIUM):** the file was attached only if `sandboxed_executor` was iterated **before**
  `secure_email_sender` in the classifier's tool order.

## Fixes (all LLM-Policy-Gate compliant — no keyword/tool-name classification)

1. **Route 1 — generic execution of the classifier's chosen actions** (`_execute_missing_tools_post_llm`):
   added an `else` branch so any tool the classifier selects that has no native handler is **dispatched
   generically** (reusing the existing `_generate_intelligent_tool_parameters` arg-binder — RAICA runs
   the LLM's choice, no hardcoded per-tool branch). Files the tool writes (to the sandbox **or** cwd) are
   captured via a **before/after file snapshot diff** (no per-tool result parsing) and **normalized into
   the attachable workspace**, then attached. `secure_email_sender` stays special **only** for
   recipient-locking (a safety limit) and is **reordered last** so artifacts exist before it attaches.
2. **No false delivery claims** (`_POS_DELIVERY_AWARENESS`): the primary LLM is now told to produce the
   content and **claim nothing** about delivery — neither "I can't" nor "sent/attached/posted" — because
   it neither performs nor confirms delivery; the system reports the actual outcome. (Coherent with the
   NewX `DELIVERY & ACTIONS` directive — NO-INCONSISTENCY check passed.)
3. **Correct tool steering** (descriptions, language not keywords): `sandboxed_executor` leads with
   "Create a DOCUMENT FILE (HTML/Markdown/text/PDF)… the tool for any file/attachment"; `pdf_generator`
   narrowed to "use ONLY when a PDF is explicitly requested." Verified: HTML→`sandboxed_executor`,
   PDF→`pdf_generator`, stable across runs.
4. **Whitelist** (kept from the staged change): when delivery is permitted, the POST-LLM whitelist opens
   the **classifier-selected** tools (the LLM decides which; the gate decides whether) — removed the
   hardcoded `_DELIVERY_TOOLS` set.

## Why the HTML case now works
HTML request → classifier picks `sandboxed_executor` → the **existing native branch** writes the file
from the LLM's cited markdown via `_create_real_html_file` (markdown→HTML, `[Title](URL)` preserved) into
the workspace → email attaches it. Route 1 is the safety net for `pdf_generator`/future tools.

## Files
- `fastapi_server_complete.py` — route-1 generic `else` + email-last reorder + artifact snapshot/attach;
  `_POS_DELIVERY_AWARENESS`; whitelist opens classifier tools.
- `user_tools/sandboxed_executor.py`, `user_tools/pdf_generator_tool.py` — descriptions.
- `version.py` (→ 1.0.0.93), `README.md`, this changelog.

## Still open (flagged, not in this change)
- **Issue #2 (HIGH, latent):** `_maybe_llm_authoritative` `max_prompt_chars: 12000` **silently** falls
  back to the legacy classifier on very long prompts (legacy also creates the file via sandboxed_executor,
  so it's a consistency/observability gap, not a delivery breaker). Raise the limit / surface the fallback.
- The classifier sometimes also selects a research tool (`get_news_summaries`) for "the above news"; it
  has a native branch so it runs harmlessly (re-fetch), but the intent prompt's "exclude research tools"
  isn't fully honored on context-less prompts.

## Status — NOT declared fixed
Per CLAUDE.md, this is **unverified** until the user tests end-to-end. RAICA v1.0.0.93 (`mode: llm`)
healthy; NewX unchanged. Reversible. Not committed.
