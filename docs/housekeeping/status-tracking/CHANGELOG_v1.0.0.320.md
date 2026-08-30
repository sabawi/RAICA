# CHANGELOG v1.0.0.320

**Date:** 2026-08-30
**Theme:** follow-up to .319 — the whitelist guard must not police RETRIES

---

## The defect .319 shipped

v1.0.0.319 filtered model-returned tool calls at three entry points. One of them —
`_regenerate_failed_tools_with_llm` — was the wrong place.

That path REGENERATES calls that already FAILED. The whitelist question was settled
when those calls were first dispatched, and some legitimately originate outside the
request whitelist: deferred POST-LLM plugins and classifier-selected delivery actions.
Filtering there blocks a legitimate retry of work the system had already authorised.

Observed in the Tier-1 benchmark, which is what caught it:

    BLOCKED off-whitelist tool call(s) [regenerated]: ['social_media_wordpress']

**Fix:** the regeneration path no longer filters. The two entry points where the
actual vulnerability lives — structured `tool_calls` and content-parsed `tool_calls`,
i.e. a model naming a tool it was never OFFERED — remain filtered.

Re-verified after the change: `document_search` 3 calls, `search_web` 0, 0 blocks,
answers still grounded in the corpus. The security fix is intact.

---

## A measurement correction (no code change)

Tier 1 reported `S2_dr_delivery` collapsed — `attachment_count 2 -> 0`,
`pdf_valid True -> False`, `html_self_contained True -> False`. **Delivery was never
broken.** The PDF and HTML were produced correctly and were on disk in
`sandbox_workspace` the whole time.

`created_delivery_files()` greps `logs/server_complete.log` for
`📦 delivery: created`. The server had been started as
`python3 fastapi_server_complete.py > <other file>`, so that log sat frozen and every
log-derived metric measured a stale file. Starting via `./start_complete.sh` restored
all four rows to PASS with no code change.

Recorded because the failure mode is generic: **a log-derived metric is only a
measurement if the emitter writes where the reader reads.**

---

## Tier 1 status at release

- All CODE/correctness rows PASS, including the full S2 delivery set.
- `dr_latency_s` 453 vs base 141 — the PRE-CHANGE code regressed identically (401),
  and the run logged 204 rate-limit responses (ELEVATED), 136 of them inside the
  scenario that regressed. Environmental, not this change; a set-membership check
  over tool names cannot triple deep-research latency.

## Known / unchanged from .319

- `_SYSTEM_INJECTED_TOOLS` is a hardcoded name (`get_the_secret_tool`). The model
  emits it as a real tool call 47 times in the logs, so the exemption is load-bearing:
  without it, the guard blocks the clock for every bot whose whitelist omits it. It is
  nonetheless a hardcoded list, which this project's CLAUDE.md forbids, and a second
  always-on tool would break it. Flagged for the owner rather than generalised
  unilaterally — there is no always-available tool registry to derive it from.
