#!/bin/bash
# Nightly RAICA Tier-1 benchmark (LOCAL). Scores the golden scenarios against baseline.json and writes a
# dated scorecard; exits non-zero on a CODE regression so cron mail / a watcher can alert.
#
# Install (user crontab — NOT auto-installed): run `crontab -e` and add, e.g. (3:30am daily):
#   30 3 * * *  cd /home/USER/Development/RAICA && bash tools/benchmark_nightly.sh >> logs/benchmark/cron.log 2>&1
# (Local RAICA must be running; logs/ is gitignored.)
set -u
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT" || exit 2
mkdir -p logs/benchmark
STAMP="$(date +%F_%H%M)"
PY="$PROJECT_ROOT/venv/bin/python"; [ -x "$PY" ] || PY=python3

echo "=== RAICA Tier-1 benchmark $STAMP ==="
"$PY" tests/benchmark/run_benchmark.py --tier 1 2>&1 | tee "logs/benchmark/scorecard_$STAMP.log"
RC=${PIPESTATUS[0]}
if [ "$RC" -ne 0 ]; then
    echo "⚠️ RAICA benchmark REGRESSION ($STAMP) — see logs/benchmark/scorecard_$STAMP.log"
fi
exit "$RC"
