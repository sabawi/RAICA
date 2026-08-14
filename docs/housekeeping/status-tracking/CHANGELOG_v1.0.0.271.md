# CHANGELOG — v1.0.0.271

**Date:** 2026-08-14
**Type:** Operability — the shadow measurement must survive a deploy
**Design:** `docs/RAICA_NONDR_GATHER_GATE.md`

---

## The problem

The gather gate was enabled on production by editing `config/llm_config.yaml`. The documented RAICA
deploy step runs, before every pull:

```bash
git checkout -- config/llm_config.yaml config/model_aliases.json
```

That is correct in general — it keeps prod config converged with the repo — and fatal here: it
**silently reverts** `enabled: true`. The gate would stay deployed, healthy and visibly present in
the code while collecting nothing, and the Phase-0 measurement would quietly stop. That is SI-021's
silent inertness arriving by a different route.

Committing `enabled: true` is not the answer: a measurement flag that changes production behaviour
should not ship on by default, and `test_config_ships_disabled_and_in_shadow` asserts it does not.

## The fix

`RAICA_GATHER_GATE_ENABLED` / `RAICA_GATHER_GATE_SHADOW`, server-local and immune to
`git checkout`. Same pattern as `RAICA_DATA_CHARTS_ENABLED` (`datasources/__init__.py:40`).

**Order matters, and is the point of the SI-029 lesson:** `config_loader.load_config()` is what
POPULATES `os.environ` from `.env`, so the override is read **after** it. Reading the env first
made the FIRST caller in a process miss the override and every later caller see it — a feature flag
decided by import order, which cost seven builds of confusion last time.

`shadow` stays ON unless explicitly set to `false`: enabling the measurement must never
accidentally enable enforcement.

## Usage

```bash
# start collecting (shadow) — survives a deploy
RAICA_GATHER_GATE_ENABLED=true ./start_complete.sh

# kill switch, no config edit, no redeploy
RAICA_GATHER_GATE_ENABLED=false ./start_complete.sh
```

## Verification

| check | result |
|---|---|
| env enables a gate the file disables | ✓ |
| env can also disable (kill switch) | ✓ |
| shadow stays on unless explicitly `false` | ✓ |
| SI-029 ordering — config loaded before the env is read | ✓ asserted |
| unit suite | **459 passed**, 4 pre-existing failures unchanged |
