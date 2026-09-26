# CHANGELOG v1.0.0.331

**Date:** 2026-09-26
**Theme:** analytical_visualizer runs on RAICA's own config and delivers real charts; a stale warning removed

## analytical_visualizer (SI-106) — kept for two jobs, fixed end to end

Owner decision: keep it for the two jobs no other tool covers — charts of numbers the user typed (plot_data
requires a source URL) and data-free diagrams (flowcharts, concept illustrations).

- **Config:** read the arbitrator lane from this repo's `config/llm_config.yaml` (glm-5.3-flash on Ollama) instead of
  another project's laptop path; the silent fallbacks to a hardcoded OpenAI gpt-4o-mini (which spent
  `OPENAI_API_KEY` on live) and a local qwen2.5:14b are gone — a missing lane disables the tool with the reason.
- **Workspace:** resolved from `user_tools.sandboxed_executor`, reusing that tool's config loader (was hardcoded to the
  same foreign path).
- **Execution:** generated code runs on RAICA's own interpreter (`sys.executable`; live's system python3 has no
  matplotlib) with `MPLBACKEND=Agg` (the default Qt backend crashed headless).
- **Delivery:** the PNG is published through `utils/chart_publisher.publish_chart` and a real `[[chart:…]]` marker is
  returned — the path plot_data already uses. It used to paste the image as base64 into its text; nothing rendered
  it, so the answer model invented a marker from the filename. A failed publish now says there is no marker.
- **Filenames:** a unique default per call (concurrent charts overwrote `visualization_output.png`).
- **Description:** scoped to the two jobs in both modules; it used to claim "ALL visualization needs".

Evidence: `tests/unit/test_analytical_visualizer.py` (6) — all fail on the pre-fix file, all pass now. Real path on
the local server: typed-in revenue figures → analytical_visualizer on glm-5.3-flash → published → the answer
carries the real marker. A flowchart request rendered a correct diagram.

## Stale warning

`⚠️ PRIMARY SYSTEM PROMPT: Enhanced source block format MISSING` fired on every request: the debug check looked
for "🔗 MANDATORY CITATION URL:", a phrase the prompt no longer uses; its citation rules use "🔗 CITATION URL". The
check now matches the current wording (verified FOUND on the real prompt, MISSING with the rule removed).

## Docs

`docs/production/DEVELOPER_GUIDE.md`, `docs/production/USER_GUIDE.md` — the visualizer described by its two jobs.

## Breaking changes / migration

None. The visualizer now needs the `arbitrator` lane (present in the shipped config); OpenAI is no longer used by it.
