# CHANGELOG v1.0.0.344 — 2026-10-24

## Arbitrator and vision model study recorded; shipped defaults follow the owner's switch

No server code changed. Live already runs these models (switched with the v1.0.0.343 deploy).

### Docs
- `docs/LLM_MODEL_SELECTION_STUDY.md` §4.6 — glm-5.3-flash vs deepseek-v4.1-flash for the arbitrator and vision,
  minimax-m3 vs minimax-m3.1-flash as the vision fallback: 240 real calls through RAICA's own code, the tables, the
  two arbitrator cases where the models differ, an estimated cost from live's measured arbitrator volume, and the
  limits. §1, §2 (what runs where, local == live), §3 (minimax-m3.1-flash price) and §7 updated; §4.1 notes its
  deepseek-v4.1-flash result predates Ollama's 2026-10-17 upgrade.
- README model list: arbitrator and vision `deepseek-v4.1-flash:cloud`, vision fallback `minimax-m3.1-flash:cloud`.
- SUSPECTED_ISSUES SI-108: deployed; the live Ask run produced its chart; the retry path is still to be seen live.

### Shipped defaults (`config/llm_config.defaults.yaml`)
- `arbitrator.config.model` and `vision.config.model` → `deepseek-v4.1-flash:cloud`; `vision.config.fallback_model` →
  `minimax-m3.1-flash:cloud`. A NEW installation starts on them; an existing site's `config/llm_config.yaml` is never
  changed by an update (site-owned). The `glm-4.7` code-generation preset is unchanged (a catalogue entry, not selected).

### Tests
- `tests/integration/run_vision_arbitrator_eval_live.py` — the study's harness, committed so it can be re-run when
  Ollama upgrades a model. Arms chosen with `--vision-arms` / `--arb-arms`. It COSTS real model calls on the account
  live shares (240 for the default run); its docstring says so. Two scorer bugs from the first scoring fixed: the date
  in RAICA's report wrapper failed the "blank image" case; the order check read first mentions only. Re-scoring the
  stored 240 rows with the fixed scorer reproduces the hand-checked figures (51/51, 51/51, 50/51, 51/51), and a wrong
  order still scores 0.

### Migration
None.
