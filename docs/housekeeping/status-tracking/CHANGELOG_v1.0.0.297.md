# CHANGELOG v1.0.0.297 — the deploy itself was the unguarded step

**Date:** 2026-08-17 · **Against:** v1.0.0.296 · **Closes:** SI-060, SI-061 · **Logs:** SI-062
· **Corrects:** SI-056, SI-057 (scope)

## How this release started: a claim about production that was wrong

The previous session ended with a recommendation to deploy, on the grounds that live was
running with dead lanes (SI-056/057), fabricated statistics (SI-048) and undelivered charts
(SI-051). The user disputed it, having just run a real Deep Research query on live and
received a well-researched answer.

The user was right. **Reading live's actual config refuted the claim:**

| lane | live (`2f5a2e6`) | verdict |
|---|---|---|
| `llm.primary` | `deepseek-v4-pro:cloud` @ `127.0.0.1:11434` | consistent |
| `tool_calling` / `arbitrator` | `glm-5.2:cloud` @ `127.0.0.1:11434/v1`, `api_key: "ollama"` | consistent |
| `deep_research.engine` (+heavy) | `deepseek-v4-flash:cloud` / `-pro:cloud` | consistent |
| `convergence` ×2, `code_generation` ×2 | Ollama slugs, Ollama endpoint | consistent |

Every live lane is an Ollama slug at an Ollama endpoint. **SI-056 and SI-057 were created by
the LOCAL DeepInfra trial and never reached production** — the config's own comments even say
"LOCAL DEEPINFRA TRIAL". Both entries and both changelogs are now annotated with that scope
correction. The `api.deepinfra.com` line in live's file sits inside the dormant `providers:`
block.

## SI-060 — and the deploy would have taken production down

Checking live instead of inferring it also exposed something worse than the thing I got wrong:

```
live (2f5a2e6) : every lane on Ollama at 127.0.0.1:11434    -- healthy
HEAD           : every lane on https://api.deepinfra.com    -- residue of the local trial
live .env      : DEEPINFRA_API_KEY  ->  ABSENT  (grep -c returned 0)
```

"Deploy the fixes" means `git pull`, and a pull carries `config/llm_config.yaml`. Deploying
would have repointed all 11 lanes at a vendor the host holds no credential for: **401 on
every LLM call — primary, tool-calling, arbitrator, DR, convergence, codegen, vision.** A
total outage, from a provider migration nobody asked for.

**Why nothing caught it:** every check we own validates the config against the machine it is
ON — `doctor`, the lane suite, the Tier-0 transport gate — where the key exists. None asked
whether the config about to LAND works on the host it is landing on. The deciding fact lives
outside the repo, so no diff review could see it either.

### The guard: `tools/deploy_preflight.py`

Compares the incoming config against the target's **current** config and environment:

1. **Provider migration** — any lane whose endpoint host changes. A deploy must never change
   a provider as a side effect; that is a decision.
2. **Credential reachability** — every `${VAR}` an incoming *active* lane needs must be
   present and non-empty on the target.

Secret **names** only — no value is ever transferred or printed. Both checks are derived from
the config (secrets from its own `${VAR}` references, providers from endpoint hostnames), so
a provider added tomorrow is covered with no edit here.

```
exit 0  GO                 no provider change, all credentials present
exit 1  NO-GO              a lane would land somewhere it cannot authenticate
exit 2  GO WITH DECISION   credentialled migration — legitimate, but never silent
```

**Falsified against the real hazard, not a mock:** `HEAD`→live returns **exit 1**, naming
`DEEPINFRA_API_KEY` × 11 lanes. Live's own config→live returns **exit 0**.

A first version dumped every provider block for every lane and demanded `OPENROUTER_*` and
`ANTHROPIC_API_KEY` for lanes serving neither — 5 of 7 rows wrong. Secrets are now scoped to
the one provider block matching the lane's endpoint plus the lane's own `api_key`. A gate
whose headline is mostly false alarm is a gate people learn to skip, which costs exactly the
outage it was written to stop.

## SI-061 — `convert` to a keyless provider stranded the old credential

Found by the new preflight on its first real use: three lanes read
`api_key: ${DEEPINFRA_API_KEY}` while sitting on `http://127.0.0.1:11434`.

`API_KEY_ENV_VARS['ollama'] is None`, so `_target_transport` returned `api_key: None` and the
writer's rewrite branch never fired — the stale line simply survived. This is the **exact
mirror of SI-017**, which fixed keyless→keyed (INSERT a key); keyed→keyless (NEUTRALISE one)
was never fixed.

Harmless on Ollama, which ignores the key — but the same branch strands `DEEPINFRA_API_KEY`
on an **OpenRouter** endpoint, which is a 401, and it silently drifted the repo config away
from the deployed one.

**Fix:** a keyless target now yields the provider name as a literal (`"ollama"`) instead of
`None`. The line cannot simply be deleted — lanes declared `type: openai` against a local
Ollama endpoint use an OpenAI-compatible client that requires a non-empty token — and this
reproduces exactly what the deployed config already carries.

## Benchmark: the spread is retained, and every run is archived

The GLM-vs-Flash comparison reported `unique_sources` **+46.3%** on one pair of runs and
**~0%** at n=4. Deciding which was signal required the per-repeat numbers — and they no
longer existed. `median_runs` computed them and kept only the median, and `scorecard.json` is
overwritten by the next run, so an arm survived only if someone remembered to `cp` it.

- `median_runs` now attaches `samples` and `n` to every metric.
- Every Tier-1 run is archived to `tests/benchmark/runs/<UTC>_<label>.json`, with `--label`
  to tag an A/B arm.

This is the repo's own standing rule (`docs/RESPONSE_QUALITY_BASELINE.md`: RETAIN artifacts)
enforced by a test rather than by memory.

## SI-062 (logged, not fixed) — a green headline over 59 unexamined failures

`pytest tests/unit tests/integration` → **63 failed / 707 passed**. Every changelog reports
"552 passed, 4 pre-existing failures" — and `tests/unit` does fail exactly 4. **The 59
integration failures have never been inside the reported scope.** Not a missing server (a
healthy one was running). Some pass as standalone Tier-0 scripts, suggesting harness
artifacts — a hypothesis, not a finding. Logged with the evidence needed to clear it.

## Verification

- **Preflight, real path, against the live host:** NO-GO (exit 1) on `HEAD`; **GO (exit 0)**
  on the repaired config. Control included so a gate that always says NO-GO cannot pass.
- **Regression control at HEAD in a clean worktree:** 63 failed / 698 passed. With these
  changes: 63 failed / 707 passed. **Failure sets identical — zero regressions introduced.**
  (The +9 passes are the new tests.)
- **Tier-0 10/10.** New tests: `test_deploy_preflight.py` **8/8**,
  `test_benchmark_run_retention.py` **6/6**. Version sync **19/19**.
- **Config repaired through the configurator, not by hand:** `convert --to ollama` →
  `SUCCESS — ALL 11 LANES LIVE`, each answering a real probe.
- `test_the_shipped_config_has_no_stranded_credential` FAILED naming all three lanes before
  the re-conversion and passes after.

## Deployment state

The repo config now matches live **lane-for-lane** (verified: 0 differing lanes) and
preflight returns **GO**. This release is a repair-and-guard release; it does **not** switch
any model.

## Still open

- Throttle threshold is mis-derived (150 flagged runs whose metrics were healthy; 231
  measured fine, 488 did not). Needs re-deriving before it can gate anything.
- `evidence_items` −42% in the earlier A/B remains unexplained, and the arms were not matched
  on retrieval (throttle 84 vs 141; S4 40 vs 90) — so the Flash decision is **not** evidenced
  yet.
- SI-059 (Ollama ignores a lane's `max_tokens`), SI-062 (above).
