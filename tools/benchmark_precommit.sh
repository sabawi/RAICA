#!/bin/bash
# RAICA benchmark pre-commit trigger.
# Runs the Tier-0 quality benchmark whenever a CORE workflow file is staged, blocking the commit on a
# regression; reminds to run the full Tier-1 suite before deploy. Logic is version-controlled here; the
# repo's .git/hooks/pre-commit calls this AFTER the CLAUDE.md compliance check.
#
# Install into a fresh clone:  bash tools/install_git_hooks.sh
# Bypass (NOT recommended):     git commit --no-verify
# Design + decisions:           docs/RAICA_QUALITY_BENCHMARK.md
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT" || exit 0

# CORE workflow files — a staged change to ANY of these triggers the Tier-0 gate (+ Tier-1 reminder).
# Keep in sync with docs/RAICA_QUALITY_BENCHMARK.md §7.
#
# version.py / README.md / config/logging_config.json are here for test_version_sync.py. They are not
# "workflow" files, but a VERSION BUMP is the exact moment the version surfaces drift, so the gate has
# to fire then or the test never runs when it matters. (Before this, a bump triggered NOTHING: README
# reached 44 builds stale and logging_config.json sat on a different version series entirely.)
CORE_REGEX='^(fastapi_server_complete\.py|research/|llm_providers/|orchestration/|user_tools/(image_to_text|sandboxed_executor|pdf_generator_tool)\.py|services/pdf_service\.py|utils/html_generator\.py|config/(llm_config\.yaml|pdf_styles\.css|logging_config\.json)|primary_model_system_prompt\.txt|pre_tool_model_system_prompt\.txt|version\.py|README\.md)'

CORE_HITS="$(git diff --cached --name-only | grep -E "$CORE_REGEX" || true)"
[ -z "$CORE_HITS" ] && exit 0   # no core workflow files staged -> nothing to gate

echo ""
echo "🧪 CORE workflow change detected — running Tier-0 quality benchmark:"
echo "$CORE_HITS" | sed 's/^/     • /'

PY="$PROJECT_ROOT/venv/bin/python"
[ -x "$PY" ] || PY="python3"
"$PY" tests/benchmark/run_benchmark.py --tier 0
RC=$?

if [ $RC -ne 0 ]; then
    echo ""
    echo "❌ Tier-0 benchmark FAILED — a locked-in behavior regressed. Commit blocked."
    echo "   Investigate the failing gate; bypass only if intentional: git commit --no-verify"
    exit 1
fi

echo "📋 REMINDER: core workflow touched — run the full real-LLM suite before deploy/checkpoint:"
echo "     make benchmark-full     # Tier 1 (local, ~15 min) — proves no quality/latency degradation"
echo ""
exit 0
