# CHANGELOG v1.0.0.277

**Date:** 2026-08-14
**Focus:** SI-041(b) — a chart described in prose but never rendered.

## The defect

A production statistics request (USGS M5.5+ catalogue) asked for a plot. The answer stated
*"The plot below shows the frequency of events by magnitude"*. There was no `plot_data` call and no
`[[chart:…]]` marker anywhere in the run.

This is a distinct fabrication shape from SI-038 (an *invented* marker). Here the model narrated a
visual that does not exist. `plot_data`'s own failure path cannot cover it, because the tool was
never called.

## Trace

Availability was never the problem — verified by invoking the real tool manager, not by reading
config:

- `plot_data` is registered and loads (`✅ Loaded user tool: plot_data`)
- exposed to the LLM among **35** tool definitions
- present in `tool_manager.available_functions`
- whitelisted in NewX `Ask.yaml`

The chain broke at **selection**, and required two independent failures:

1. **The directive was ignored.** `_ARTIFACT_MARKER_RELAY` already states *"You CANNOT create a
   chart, plot, graph or image yourself"* and prescribes prose when no marker is present.
2. **The gather gate had no basis to object.** It judged whether DATA and DERIVED FIGURES were in
   hand. It said nothing about artifacts, so `sufficient` was an **honest** verdict with no chart
   made.

## Change

`_gather_gate_assess` now applies the same in-hand test to anything the request asks the system to
PRODUCE: a chart/plot/graph/rendered file is not in hand unless a tool produced it and its marker
appears in the gathered output.

*A directive can be ignored; a gate that withholds `sufficient` cannot.* The loop is otherwise
untouched — `needs_more` re-runs the existing selector, which can pick `plot_data`.

**Stated as policy, LLM-judged.** No phrase list and no regex, per the standing no-keyword
directive. Phrase-matching an answer for "the plot below" fails on "the graphic above", on another
language, and on the next phrasing.

**Damper.** The fix creates a control loop (it demands an artifact), so the gate must be able to
observe one. It can: `plot_data` returns short prose, so `describe_reference` renders it in full
and the `[[chart:…]]` marker reaches the next assessment — verified empirically. `no_progress`
backstops it.

**Consistency.** Gate and relay sequence rather than conflict: the gate says *go make it* while
gathering; the relay says *if it still does not exist, say so* at synthesis.

## Tests

`tests/unit/test_gather_gate_shadow.py` (+3):

| Test | Discriminates? |
|---|---|
| `test_a_requested_ARTIFACT_is_judged_like_a_derived_figure` | **Yes** — fails on pre-fix code |
| `test_a_produced_chart_marker_is_VISIBLE_to_the_next_assessment` | No — damper pin (passes both ways by design) |
| `test_the_artifact_rule_is_POLICY_not_a_keyword_matcher` | No — pin-out for keyword regression |

Suite: **473 passed**, 4 pre-existing failures unchanged (`test_html_entities`,
`test_phase5_integration` ×2, `test_title_escaping`). Version sync 5/5.

## Status — NOT validated end-to-end

Unit tests only, with a stubbed LLM. No chart request has been run through the real server since
the change. Local server restarted and healthy on 1.0.0.277.

## Open residue

The fix makes the chart EXIST when one can be made. It does **not** stop the model narrating a
visual when the gate exhausts its rounds and no chart could be produced — that case still rests on
the relay directive alone, which is what failed here. The right home is a post-answer LLM-judged
fabrication check beside the `nondr-citation` shadow audit. Not built.

The SI-041 model-choice error (normal fit understating a Gutenberg-Richter tail ~9x) is unrelated
to this change and remains unaddressed.

## Files

- `fastapi_server_complete.py` — artifact clause in `_gather_gate_assess`
- `tests/unit/test_gather_gate_shadow.py` — 3 named tests
- `docs/RAICA_NONDR_GATHER_GATE.md` — §10
- `docs/housekeeping/status-tracking/SUSPECTED_ISSUES.md` — SI-041(b)
- `version.py`, `config/logging_config.json`, `README.md` — 1.0.0.277
