# Changelog — v1.0.0.175

**Date:** 2026-07-11
**Scope:** Make inline chart cards **activatable on production** — the RAICA↔NewX chart wiring is now environment-aware and durable across deploys. Enables charts on sabawi.net for the first time (live NewX already carries the render code since v1.0.0.62).

## Changed
* **`utils/chart_publisher._charts_config`** — `.env` now takes **precedence** over `config/llm_config.yaml` for the two deployment-specific chart settings, so the same committed config works in every environment and survives a deploy's `git checkout -- config`:
  - `RAICA_CHARTS_ENABLED` (true/false) → overrides `charts.enabled`
  - `NEWX_CHART_UPLOAD_URL` → overrides `charts.newx_upload_url` (fixed precedence: env now wins when set)
  - `CHART_UPLOAD_SECRET` → the shared secret (already `.env`-only)
* **Why:** live NewX serves **HTTP** on `:9876` (TLS terminated upstream by the AWS LB), while local dev serves **HTTPS**. The upload URL and the enable flag differ per environment and must live in each box's `.env`, not the shared yaml (which the RAICA deploy discards). Local dev keeps the yaml `https` default.

## Activation (server-only `.env`, gitignored — not in the repo)
* Live RAICA `~/RAICA/.env`: `RAICA_CHARTS_ENABLED=true`, `NEWX_CHART_UPLOAD_URL=http://localhost:9876/internal/chart-upload`, `CHART_UPLOAD_SECRET=<shared>`.
* Live NewX `~/NewX/.env`: `CHART_CARDS_ENABLED=true`, `CHART_UPLOAD_SECRET=<same shared>`.
* Both remain OFF by default in the repo (`charts.enabled: false`, `CHART_CARDS_ENABLED` unset) — a fresh install stays dark until the secret + flags are configured (fail-closed).

## Verification
* Unit: `test_charts_env_override` (env precedence over yaml, incl. explicit env-false over yaml-true). Suite green.
* Live E2E: an `@Ask` stock query on sabawi.net renders chart cards.

## No new dependencies.
