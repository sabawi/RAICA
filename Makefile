# RAICA quality/performance benchmark convenience targets. See docs/RAICA_QUALITY_BENCHMARK.md
PY := $(shell [ -x venv/bin/python ] && echo venv/bin/python || echo python3)

.PHONY: benchmark benchmark-full benchmark-all install-hooks

benchmark:                ## Tier 0 — deterministic gates (fast; the pre-commit floor)
	$(PY) tests/benchmark/run_benchmark.py --tier 0

benchmark-full:           ## Tier 1 — real-LLM golden scenarios vs baseline (local, ~15 min)
	$(PY) tests/benchmark/run_benchmark.py --tier 1

benchmark-all:            ## Tiers 0+1+2
	$(PY) tests/benchmark/run_benchmark.py --tier all

install-hooks:            ## wire the benchmark Tier-0 pre-commit trigger (idempotent)
	bash tools/install_git_hooks.sh
