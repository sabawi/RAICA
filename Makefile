# RAICA quality/performance benchmark convenience targets. See docs/RAICA_QUALITY_BENCHMARK.md
PY := $(shell [ -x venv/bin/python ] && echo venv/bin/python || echo python3)

.PHONY: benchmark benchmark-full benchmark-all install-hooks smoke

benchmark:                ## Tier 0 — deterministic gates (fast; the pre-commit floor)
	$(PY) tests/benchmark/run_benchmark.py --tier 0

smoke:                    ## Tool smoke — INVOKE each core tool through the real code path (~30s; run before EVERY deploy)
	$(PY) tests/smoke/tool_smoke.py

benchmark-full:           ## Tier 1 — real-LLM golden scenarios vs baseline (local, ~15 min)
	$(PY) tests/benchmark/run_benchmark.py --tier 1

benchmark-all:            ## Tiers 0+1+2
	$(PY) tests/benchmark/run_benchmark.py --tier all

benchmark-nightly:        ## Tier 1 nightly run (local) -> logs/benchmark/ (cron-able)
	bash tools/benchmark_nightly.sh

install-hooks:            ## wire the benchmark Tier-0 pre-commit trigger (idempotent)
	bash tools/install_git_hooks.sh
