#!/usr/bin/env bash
# ── Put RAICA under systemd supervision ──────────────────────────────────────
#
# WHY: on 2026-08-27 a host reboot stopped RAICA and nothing restarted it. It ran
# as a bare `nohup ... &`. Five NewX bots depend on it; every post they attempted
# for the next ~11 hours failed with "Connection refused" while the Celery task
# reported success. `Restart=always` is the difference between 5 seconds and half
# a day.
#
# This installer ASKS SYSTEMD what it actually applied rather than reading back
# the file it just wrote — a check that reads its own output proves nothing. It
# also POLLS for readiness instead of taking one instantaneous sample, because
# three single-instant checks during the NewX rollout each declared a healthy
# service dead and triggered a rollback.
#
#   --check   report the current state and verify the unit; install nothing
#
set -uo pipefail

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[ ok ]${NC} $*"; }
warn() { echo -e "${YELLOW}[warn]${NC} $*"; }
fail() { echo -e "${RED}[FAIL]${NC} $*"; FAILED=1; }
FAILED=0

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
UNIT_SRC="$ROOT/deploy/systemd/raica.service"
UNIT_DST="/etc/systemd/system/raica.service"
PORT=5000
CHECK_ONLY=0
[ "${1:-}" = "--check" ] && CHECK_ONLY=1

[ -f "$UNIT_SRC" ] || { fail "missing $UNIT_SRC"; exit 1; }

RUN_USER="$(id -un)"
PYVER="$(ls -d "$ROOT"/venv/lib/python3.* 2>/dev/null | head -1 | sed 's#.*/python##')"
[ -n "$PYVER" ] || { fail "no venv at $ROOT/venv — create it before installing"; exit 1; }
[ -x "$ROOT/venv/bin/python3" ] || { fail "$ROOT/venv/bin/python3 is not executable"; exit 1; }
ok "root=$ROOT user=$RUN_USER python=$PYVER"

TMP_UNIT="$(mktemp)"
trap 'rm -f "$TMP_UNIT"' EXIT
sed -e "s#__ROOT__#$ROOT#g" -e "s#__USER__#$RUN_USER#g" -e "s#__PYVER__#$PYVER#g" \
    "$UNIT_SRC" > "$TMP_UNIT"

# Verify BEFORE touching the system. Needs no root.
if command -v systemd-analyze >/dev/null 2>&1; then
    # Capture, then match: under pipefail `verify | grep -q` fails on SIGPIPE and a REJECTED unit read as clean.
    if grep -qE "Unknown|Failed|ignoring" <<<"$(systemd-analyze verify "$TMP_UNIT" 2>&1)"; then
        systemd-analyze verify "$TMP_UNIT" 2>&1 | head -10
        fail "systemd-analyze rejected the unit — not installing"
        exit 1
    fi
    ok "systemd-analyze verify: clean"
fi

if [ "$CHECK_ONLY" = "1" ]; then
    echo; echo "── current state ──"
    if grep -q raica <<<"$(systemctl list-unit-files raica.service --no-pager 2>/dev/null)"; then
        ok "unit installed; ActiveState=$(systemctl show -p ActiveState --value raica 2>/dev/null)"
        # Ask systemd what it APPLIED, not what the file says.
        limit="$(systemctl show -p StartLimitIntervalUSec --value raica 2>/dev/null)"
        [ "$limit" = "0" ] || [ "$limit" = "infinity" ] \
            && ok "StartLimitIntervalUSec=$limit (no give-up limit)" \
            || warn "StartLimitIntervalUSec=$limit — systemd did NOT honour 0; check the [Unit] section"
        ok "Restart=$(systemctl show -p Restart --value raica 2>/dev/null)"
    else
        warn "raica.service is NOT installed — RAICA is unsupervised"
    fi
    curl -s --max-time 5 -o /dev/null -w "       :$PORT responds HTTP %{http_code}\n" \
        "http://localhost:$PORT/v1/models" 2>/dev/null || echo "       :$PORT unreachable"
    exit $FAILED
fi

[ "$(id -u)" -eq 0 ] || { fail "installing needs root — re-run with sudo"; exit 1; }

# The invoking (non-root) user owns the files; run the service as them.
RUN_USER="${SUDO_USER:-$RUN_USER}"
sed -i -e "s#^User=.*#User=$RUN_USER#" -e "s#^Group=.*#Group=$RUN_USER#" "$TMP_UNIT"

# Stop any hand-started instance first, or systemd will start a SECOND one and
# the port bind will fail in a way that looks like a crash loop.
# systemd sends the unit's output to logs/server_complete.log and opens that file BEFORE ExecStartPre (which would
# create the folder) runs: on a fresh clone every start failed with 209/STDOUT (NewX installer test, 2026-10-18)
install -d -o "$RUN_USER" -g "$RUN_USER" "$ROOT/logs" "$ROOT/logs/archive" "$ROOT/runtime" "$ROOT/document_store"
# A RAICA started by hand — NOT the one systemd already runs (pgrep matches both; the unit's own MainPID is excluded)
unit_pid="$(systemctl show -p MainPID --value raica.service 2>/dev/null || echo 0)"
hand_pids() { pgrep -f "python3 fastapi_server_complete.py" 2>/dev/null | grep -vx "${unit_pid:-0}" || true; }
if [ -n "$(hand_pids)" ]; then
    warn "a hand-started RAICA is running — stopping it so systemd can own the port"
    hand_pids | xargs -r kill -INT 2>/dev/null || true   # only the hand-started ones, never the unit's own
    for _ in $(seq 1 20); do
        [ -n "$(hand_pids)" ] || break
        sleep 1
    done
    [ -n "$(hand_pids)" ] \
        && { fail "could not stop the existing process"; exit 1; }
    ok "hand-started instance stopped"
fi

install -m 0644 "$TMP_UNIT" "$UNIT_DST" && ok "installed $UNIT_DST"
systemctl daemon-reload && ok "daemon-reload"
systemctl enable raica.service >/dev/null 2>&1 && ok "enabled at boot"
systemctl restart raica.service && ok "started"

# Readiness is never instantaneous — POLL with a deadline.
ready=0
for i in $(seq 1 30); do
    code="$(curl -s --max-time 5 -o /dev/null -w "%{http_code}" "http://localhost:$PORT/v1/models" 2>/dev/null)"
    [ "$code" = "200" ] && { ok "RAICA answering on :$PORT after ~$((i*3))s"; ready=1; break; }
    sleep 3
done
[ "$ready" = "1" ] || fail "RAICA did not answer on :$PORT within 90s — check logs/server_complete.log"

# Ask systemd what it applied. Reading back our own file would prove nothing.
limit="$(systemctl show -p StartLimitIntervalUSec --value raica)"
if [ "$limit" = "0" ] || [ "$limit" = "infinity" ]; then
    ok "StartLimitIntervalUSec=$limit — will retry forever"
else
    fail "StartLimitIntervalUSec=$limit — systemd IGNORED the 0; the unit can still be left dead"
fi
[ "$(systemctl show -p Restart --value raica)" = "always" ] \
    && ok "Restart=always" || fail "Restart is not 'always'"

echo
[ "$FAILED" = "0" ] && ok "RAICA is supervised. Reboot-safe." || fail "install completed WITH problems"
exit $FAILED
