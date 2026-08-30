#!/usr/bin/env bash
# RAICA production deploy — pull, restart, and PROVE the running process is the new code.
#
# WHY THIS EXISTS (2026-08-30)
# RAICA was placed under systemd (raica.service, Restart=always) on 2026-08-28, and on
# the same day stop_complete.sh / start_complete.sh were taught to DEFER to the unit —
# they print "stop it with: sudo systemctl stop raica" and exit 0. Correct on its own:
# hand-starting races systemd for port 5000, which caused two 503 outages during the
# NewX rollout.
#
# But nothing then covered the DEPLOY path. `git pull && ./stop_complete.sh &&
# ./start_complete.sh` became a silent no-op: files updated, process untouched. On
# 2026-08-30 that shipped a "successful" deploy where prod kept serving 2-day-old code,
# and version.py read the NEW number the whole time — so checking the file would have
# CONFIRMED the false success.
#
# THE INSIGHT: killing is safe, hand-STARTING is not. Under Restart=always, signalling
# the process makes systemd restart it from the current files, with no port race and no
# sudo. This script therefore never starts anything by hand while the unit is installed.
#
# VERIFICATION IS THE POINT: it compares the running process's START TIME against the
# moment of the pull. A file version proves nothing about what is executing.
#
# Usage:  ssh <host> 'cd ~/RAICA && ./scripts/deploy.sh'
# Exits non-zero — loudly — if the running process is not demonstrably the new code.

set -uo pipefail
cd "$(dirname "$0")/.." || exit 2

HEALTH_URL="http://localhost:5000/documents/stats"
READY_DEADLINE=120          # seconds to wait for the service to answer
red()  { printf '\033[31m%s\033[0m\n' "$*"; }
grn()  { printf '\033[32m%s\033[0m\n' "$*"; }
info() { printf '  %s\n' "$*"; }

systemd_managed() {
    command -v systemctl >/dev/null 2>&1 && \
    systemctl list-unit-files raica.service --no-pager 2>/dev/null | grep -q "^raica.service"
}

main_pid() {
    if systemd_managed; then systemctl show raica.service -p MainPID --value 2>/dev/null
    else pgrep -f fastapi_server_complete.py | head -1; fi
}

# Epoch second at which $1 started (now - elapsed). Empty if the pid is gone.
proc_start_epoch() {
    local pid="$1" et
    [ -n "$pid" ] && [ "$pid" != "0" ] || return 0
    et=$(ps -o etimes= -p "$pid" 2>/dev/null | tr -d ' ')
    [ -n "$et" ] && echo $(( $(date +%s) - et ))
}

echo "── RAICA deploy ─────────────────────────────────────────────"
OLD_PID=$(main_pid)
OLD_COMMIT=$(git rev-parse --short HEAD 2>/dev/null)
info "before:  commit=$OLD_COMMIT  pid=${OLD_PID:-none}  systemd=$(systemd_managed && echo yes || echo no)"

echo "── pull ─────────────────────────────────────────────────────"
git pull --ff-only || { red "✗ git pull failed — nothing changed, service untouched."; exit 1; }
PULL_EPOCH=$(date +%s)
NEW_COMMIT=$(git rev-parse --short HEAD)
NEW_VERSION=$(grep -m1 -E '^VERSION' version.py | cut -d'"' -f2)
info "after:   commit=$NEW_COMMIT  version.py=$NEW_VERSION"

if [ "$OLD_COMMIT" = "$NEW_COMMIT" ]; then
    info "commit unchanged — restarting anyway so the running process matches the tree."
fi

echo "── restart ──────────────────────────────────────────────────"
if systemd_managed; then
    # Signal only. systemd's Restart=always owns the (re)start, so there is no race
    # for port 5000 and no sudo is required. NEVER hand-start while the unit exists.
    info "systemd-managed: signalling pid $OLD_PID; Restart=always will bring it back"
    kill -TERM "$OLD_PID" 2>/dev/null || info "(process already gone)"
else
    info "script-managed: ./stop_complete.sh && ./start_complete.sh"
    ./stop_complete.sh >/dev/null 2>&1
    sleep 10
    nohup ./start_complete.sh >/dev/null 2>&1 &
fi

echo "── wait for ready ───────────────────────────────────────────"
deadline=$(( $(date +%s) + READY_DEADLINE ))
until curl -fsS -m 5 -o /dev/null "$HEALTH_URL" 2>/dev/null; do
    if [ "$(date +%s)" -ge "$deadline" ]; then
        red "✗ not answering $HEALTH_URL after ${READY_DEADLINE}s."
        red "  Service state:"; systemctl is-active raica.service 2>/dev/null | sed 's/^/    /'
        red "  Last log lines:"; tail -15 logs/server_complete.log 2>/dev/null | sed 's/^/    /'
        exit 1
    fi
    sleep 3
done
info "answering after $(( $(date +%s) - PULL_EPOCH ))s"

echo "── verify the RUNNING process is the new code ───────────────"
NEW_PID=$(main_pid)
START_EPOCH=$(proc_start_epoch "$NEW_PID")
FAIL=0
if [ -z "$NEW_PID" ] || [ "$NEW_PID" = "0" ]; then
    red "✗ no running process found"; FAIL=1
elif [ "$NEW_PID" = "$OLD_PID" ]; then
    red "✗ pid unchanged ($NEW_PID) — the process was NOT restarted."
    red "  The tree is on $NEW_COMMIT but the service is still executing the old code."
    FAIL=1
elif [ -z "$START_EPOCH" ] || [ "$START_EPOCH" -lt "$PULL_EPOCH" ]; then
    red "✗ process $NEW_PID started BEFORE the pull — it is not running $NEW_COMMIT."
    FAIL=1
else
    info "pid $OLD_PID -> $NEW_PID, started $(( START_EPOCH - PULL_EPOCH ))s after the pull"
fi

if [ "$FAIL" -ne 0 ]; then
    red "✗ DEPLOY FAILED — files may be updated but the service is not running them."
    exit 1
fi
grn "✓ deployed: $NEW_COMMIT (version.py $NEW_VERSION) — running process verified new"
