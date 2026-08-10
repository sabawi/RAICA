# CHANGELOG v1.0.0.247 — the Deep Research assessment loop was dead for 7 builds

**Date:** 2026-08-10 · **Previous:** v1.0.0.246 · **Type:** P0 regression fix

---

## SI-021 — `DeepResearchEngine` could never read its own token cap

From **v1.0.0.240** through **v1.0.0.246**, every Deep Research gap assessment raised:

```
AttributeError: 'DeepResearchEngine' object has no attribute '_assess_max_tokens'
```

SI-015 made the DR JSON-call output caps config-driven and placed `_assess_max_tokens` on
`ResearchPlanner` (`engine.py:272`). It is consumed in `DeepResearchEngine._assess`
(`engine.py:724`) — a different class. `_assess` wraps its call in a bare
`except Exception` whose documented purpose is *"never lose a round to a transient assess
error"*, so the failure was swallowed into a warning and returned:

```python
return {"status": "sufficient", "gaps": [], "next_queries": []}
```

**Deep Research therefore never requested a second round.** On every prompt, for every
provider, for 7 builds, it stopped at `min_rounds` while reporting success.

The sibling property `_planner_max_tokens` works because its consumer lives in the same
class — which is why the original commit looked symmetric and correct.

**Fix:** move the property to `DeepResearchEngine`.

### Measured through the real `@Ask` path (full NewX payload, 8-tool whitelist)

| | rounds | evidence | sources | chars | stop | unverified claims |
|---|---|---|---|---|---|---|
| prod (pre-fix code) | 4 | 44 | 171 | 502,264 | max_rounds | 12 / 92 |
| v1.0.0.246 DeepInfra | 2 | 19 | 63 | 132,786 | sufficient | 3 / 317 |
| v1.0.0.246 Ollama | 2 | 19 | 93 | 190,485 | sufficient | 0 / 240 |
| **v1.0.0.247 Ollama** | **4** | **40** | **161** | **595,254** | **max_rounds** | **3 / 123** |

v1.0.0.247 restores prod's structure (4 rounds, `max_rounds`, 94% of its unique sources),
gathers **18% more evidence**, and leaves **3 unverified claims against prod's 12**. Zero
truncations, zero errors.

Not better than prod everywhere: **1.7× slower** (561.1s vs 332.2s, driven by synthesis
327s vs 131s) and **40 low-credibility sources vs 28**. Both stated rather than smoothed.

**Caveat: n=1 per column.** Live web drifted between the prod run and these, and the
second ticker differs (prod AAPL, local MSFT), which moves every downstream number. This
establishes the regression is fixed and the pipeline healthy — not a stable quality
ranking.

---

## Collateral: `docs/PROVIDER_AB_TEST_RESULTS.md` is INVALID

The provider A/B ran entirely on the dead loop. Its DR half measured a crippled pipeline
**in both arms**, so these findings are withdrawn:

- "D1 evidence −48%" and "groundedness −12.4pp"
- the one-armed 32000-token truncation that tripped the blocking rule
- the whole "DeepInfra's planner assigns fewer sources per sub-question" mechanism, and
  the inference it supported about confound C4 (differing model weights/quantisation)

**The tell was in the data and was missed:** both arms returned *identical* round and
evidence counts. A provider comparison in which both arms agree exactly is not measuring
the provider. It was attributed to serving differences instead.

The non-DR half (§2 of that doc) does not traverse the DR loop and stands.

---

## Why it hid, and what now catches it

Nothing failed, nothing 500'd, and answers still read well — DR simply did less work.
Same class as the swallowed `NameError` that disabled `search_web` for six days: a real
exception absorbed by a catch-all that exists for good reasons.

`tests/unit/test_dr_gap_assessment_alive.py` (5 tests, **3 fail on pre-fix code**):

- `test_engine_resolves_its_own_assess_cap` — the property must live on its consumer
- `test_every_attribute_assess_touches_resolves_on_the_engine` — guards the whole class,
  so a second misplaced cap cannot reproduce this
- `test_assess_returns_the_llm_verdict_not_the_swallowed_fallback` — **behavioural**: a
  stub returning `needs_more` must produce `needs_more`; pre-fix the AttributeError fires
  before the stub is consulted
- `test_assess_failure_path_is_still_reachable_but_logs_loudly` — the catch-all is
  legitimate for transient errors and must not be deleted

## Files changed

| file | change |
|---|---|
| `research/engine.py` | move `_assess_max_tokens` to `DeepResearchEngine` |
| `tests/unit/test_dr_gap_assessment_alive.py` | **new** — 5 tests |
| `docs/PROVIDER_AB_TEST_RESULTS.md` | INVALID banner + withdrawn findings |
| `docs/housekeeping/status-tracking/SUSPECTED_ISSUES.md` | SI-021 |
| `version.py`, `README.md`, `config/logging_config.json` | 1.0.0.246 → 1.0.0.247 |

## Breaking changes / migration

None.

**Operational note:** any DR result produced by v1.0.0.240–v1.0.0.246 gathered roughly
half the evidence it should have. Prod was never on those builds and is unaffected.
