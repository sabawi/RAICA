# CHANGELOG v1.0.0.72

**Date:** 2026-06-04
**Previous:** v1.0.0.71
**Trigger:** Phase 2 of the Deep Research → Orchestration integration — the delivery fan-out. Deep
Research now turns its paper into a PDF and emails it, by directly dispatching existing tools.

**Design reference:** `docs/DEEP_RESEARCH_ORCHESTRATION_INTEGRATION.md` (Phase 2, §4 bridge + Principle 6).

---

## Summary

The research paper (the shared context) is now handed to a delivery fan-out that **renders it to a PDF
and emails it**, reusing the existing `sandboxed_executor` (file/PDF) and `secure_email_sender` tools
("A-hybrid": direct dispatch rather than the monolithic POST-LLM executor, which is coupled to the
normal-flow tools_results format). Authorization is a server-side **3-way gate**; everything is gated
so the normal and NewX flows are untouched.

This is the first cut: PDF + email via a thin capability adapter. The final cut generalizes to dynamic
registry dispatch over ANY tool (infographic, images, flowchart, publish, …) with no per-action code.

---

## Changes

- **Delivery fan-out** (`fastapi_server_complete.py` `_run_dr_delivery`): after the paper is produced,
  if the request decomposed into delivery actions AND delivery is permitted, render the footer-less
  paper → PDF (`sandboxed_executor` `convert_to_pdf`) and email it (`secure_email_sender`), streaming
  `📦 Delivery` progress. Helpers: `_resolve_email_recipients` (recipient from action args, else prompt
  regex), `_sweep_old_delivery_files` (TTL housekeeping), `_dr_delivery_permitted` (gate, below).
- **3-way delivery authorization** (`_dr_delivery_permitted`): (1) explicit `allow_delivery` true/false
  wins; (2) else a client with NO `allowed_tools` whitelist is auto-trusted (interactive internal
  clients like OpenWebUI on the firewalled /v1); (3) else denied. NewX bots always send `allowed_tools`,
  so they're never auto-trusted — governed entirely by the explicit flag (which NewX will set from a
  per-user privilege system; tracked separately). New `OpenAIChatRequest.allow_delivery` field plumbed
  end-to-end (model → endpoint → streaming → native_request_data → pipeline `data`).
- **Topic-derived naming**: filename slug + email subject + PDF title now come from the paper's real
  title (its first heading), not a generic "analysis_report".
- **Clean PDF title**: `sandboxed_executor._create_real_pdf_file` now accepts an explicit `title`
  (threaded from `_create_file`); the delivery passes the paper's title and strips the paper's own
  leading heading so the rendered title isn't duplicated. Removes the old "Analysis Report YYYY-MM-DD"
  filename-derived header.
- **No silent failures**: every delivery branch surfaces a visible alert in the response — document
  failure, email skipped (document failed → NOT sent attachment-less), no recipient, send failure
  (file kept + path reported), unwired/unsupported actions, and a top-level catch.
- **File lifecycle**: on email SUCCESS the email tool auto-cleans the working copy (accepted —
  delivered via email); on FAILURE the file is KEPT and its path reported. TTL sweep
  (`deep_research.engine.delivery.retention_hours`, default 72) reclaims leftovers.
- **Config**: `deep_research.engine.delivery.retention_hours`.

## Compliance with CLAUDE.md

- LLM decides the plan (JSON); RAICA dispatches. The thin name adapter is documented transitional
  (final cut = dynamic registry dispatch, retiring it).
- No regression: all delivery is gated; normal/NewX flows untouched; `allow_delivery`/auto-trust only
  affect deep-research delivery. No silent failures.

## Verification (live, user-confirmed)

- `curl` (allow_delivery:true): PDF rendered + emailed with attachment (coffee, tea topics).
- OpenWebUI (no flag, no allowed_tools → auto-trusted by the 3-way gate): paper + PDF emailed with
  attachment; `📦 DR delivery email result: ✅ Email sent successfully via gmail to 1 recipient(s)`.
- PDF title verified clean (single title, no "Analysis Report"/"Generated on") by inspecting a rendered PDF.
- Failure path verified: a PDF-creation bug produced a clear "Email not sent" alert + no empty email
  (then the bug was fixed).

## Deployment / security notes

- **Email channel must be enabled** in `config/communication_hub.yaml` (`email.enabled: true`) for
  sending. NOT committed here — it's deployment-specific. The 3-way gate + NewX `allowed_tools` keep
  bots locked even with the channel on.
- **/v1 must be internal-only / firewalled** (auto-trust rule #2 depends on it). Enforce at install.

## Known limitations / follow-ups

- NewX per-user delivery-privilege system (sets `allow_delivery`) — separate NewX effort.
- Final cut: dynamic registry dispatch for ALL actions (replaces the thin adapter).
- PDF title is title-cased by the shared `_format_title` ("Of/To" capitalized) — minor cosmetic.
- Pre-existing hardcoded /home paths + /v1 firewall enforcement — tracked action items.

## Dependencies

- None new.

## Migration

- None required for existing clients. New optional `allow_delivery` field; delivery is off unless
  permitted by the 3-way gate. Enable the email channel + firewall /v1 per deployment notes above.

## Files

- `fastapi_server_complete.py` — delivery fan-out, helpers, 3-way gate, allow_delivery plumbing, alerts.
- `research/pipeline.py` — decomposer action args guidance, `answer_body` (footer-less) return.
- `user_tools/sandboxed_executor.py` — explicit `title` param threaded into PDF creation.
- `config/llm_config.yaml` — `deep_research.engine.delivery.retention_hours`.
- `version.py` (→ 1.0.0.72), `README.md`, this changelog.
- (NOT committed) `config/communication_hub.yaml` — email channel enabled per deployment.
