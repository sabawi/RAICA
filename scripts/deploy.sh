#!/usr/bin/env bash
# RAICA production deploy — systemd-controlled, verified, and self-reversing.
#
#   ./scripts/deploy.sh              deploy origin/<branch>
#   ./scripts/deploy.sh --dry-run    show exactly what would change; touch nothing
#   ./scripts/deploy.sh --to <ref>   deploy a specific commit
#   ./scripts/deploy.sh --rollback   return to the previously deployed commit
#
# THREE PROPERTIES, each earned from a specific failure on 2026-08-30:
#
# FAIL-PROOF   Every step is verified, and a failed deploy ROLLS ITSELF BACK and
#              re-verifies, so the service is never left down or on broken code.
#              A deploy that cannot verify itself is treated as a failed deploy.
#
# TRANSPARENT  Prints the commits being shipped BEFORE shipping them, and appends
#              every attempt — success or failure — to logs/deploy.log.
#              (`git pull && stop_complete.sh && start_complete.sh` once reported
#              success while prod kept serving two-day-old code. Silence is the enemy.)
#
# REVERSIBLE   The pre-deploy commit is recorded before anything changes, so
#              --rollback is always available and never has to be reconstructed.
#
# CONTROLLER   systemd owns the process (`raica.service`, Restart=always). We restart
#              THROUGH it. We never hand-start: that races the unit for port 5000 and
#              produced two 503 outages during the NewX rollout.
#
# VERIFICATION IS OF THE PROCESS, NEVER THE FILES. version.py read the NEW number
# throughout the failed deploy above, so checking it would have confirmed the lie.

set -uo pipefail
cd "$(dirname "$0")/.." || exit 2

SERVICE="raica.service"
HEALTH_URL="http://localhost:5000/documents/stats"
CYCLE_DEADLINE=90
READY_DEADLINE=180
DEPLOY_LOG="logs/deploy.log"
STATE_FILE=".deploy_previous_sha"

red()  { printf '\033[31m%s\033[0m\n' "$*"; }
grn()  { printf '\033[32m%s\033[0m\n' "$*"; }
ylw()  { printf '\033[33m%s\033[0m\n' "$*"; }
info() { printf '  %s\n' "$*"; }
hdr()  { printf '\n── %s %s\n' "$*" "$(printf '─%.0s' $(seq 1 $((56 - ${#1}))))"; }
record() { mkdir -p logs; printf '%s | %s\n' "$(date -Is)" "$*" >> "$DEPLOY_LOG"; }

MODE=deploy; TARGET=""
while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run)  MODE=dryrun ;;
        --rollback) MODE=rollback ;;
        --to)       TARGET="${2:-}"; shift ;;
        -h|--help)  sed -n '2,12p' "$0"; exit 0 ;;
        *) red "unknown argument: $1"; exit 2 ;;
    esac
    shift
done

systemd_managed() {
    command -v systemctl >/dev/null 2>&1 && \
    systemctl list-unit-files "$SERVICE" --no-pager 2>/dev/null | grep -q "^$SERVICE"
}
main_pid() {
    if systemd_managed; then systemctl show "$SERVICE" -p MainPID --value 2>/dev/null
    else pgrep -f fastapi_server_complete.py | head -1; fi
}
proc_start_epoch() {
    local pid="$1" et
    [ -n "$pid" ] && [ "$pid" != "0" ] || return 0
    et=$(ps -o etimes= -p "$pid" 2>/dev/null | tr -d ' ')
    [ -n "$et" ] && echo $(( $(date +%s) - et ))
}

# Restart THROUGH the controller. systemctl when we may use it, signal otherwise —
# under Restart=always a SIGTERM still makes systemd perform the start, so we never
# hand-start either way.
restart_service() {
    if systemd_managed && sudo -n systemctl is-active "$SERVICE" >/dev/null 2>&1; then
        info "controller: sudo systemctl restart $SERVICE"
        sudo -n systemctl restart "$SERVICE" || { red "systemctl restart failed"; return 1; }
    elif systemd_managed; then
        info "controller: SIGTERM to $(main_pid) (no passwordless sudo; Restart=always performs the start)"
        kill -TERM "$(main_pid)" 2>/dev/null
    else
        info "controller: stop_complete.sh / start_complete.sh (no unit installed)"
        ./stop_complete.sh >/dev/null 2>&1; sleep 10
        nohup ./start_complete.sh >/dev/null 2>&1 &
    fi
}

# Wait for the PID to change, then for health. Checking health first proves nothing:
# between SIGTERM and RestartUSec the DYING process still answers (found on this
# script's own first production run).
verify_running() {
    local old_pid="$1" ref_epoch="$2" cur start
    local d=$(( $(date +%s) + CYCLE_DEADLINE ))
    while :; do
        cur=$(main_pid)
        [ -n "$cur" ] && [ "$cur" != "0" ] && [ "$cur" != "$old_pid" ] && break
        [ "$(date +%s)" -ge "$d" ] && { red "✗ process never cycled (still ${cur:-none})"; return 1; }
        sleep 2
    done
    info "process cycled: $old_pid -> $cur"
    d=$(( $(date +%s) + READY_DEADLINE ))
    until curl -fsS -m 5 -o /dev/null "$HEALTH_URL" 2>/dev/null; do
        [ "$(date +%s)" -ge "$d" ] && { red "✗ not answering $HEALTH_URL after ${READY_DEADLINE}s"; return 1; }
        sleep 3
    done
    start=$(proc_start_epoch "$cur")
    [ -n "$start" ] && [ "$start" -ge "$ref_epoch" ] || { red "✗ pid $cur predates this deploy — not the new code"; return 1; }
    info "healthy; process started $(( start - ref_epoch ))s after the change"
    return 0
}

hdr "preflight"
BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
PREV_SHA=$(git rev-parse HEAD 2>/dev/null)
DIRTY=$(git status --porcelain --untracked-files=no | wc -l)
info "branch=$BRANCH  current=$(git rev-parse --short HEAD)  systemd=$(systemd_managed && echo yes || echo no)"
if [ "$DIRTY" -ne 0 ] && [ "$MODE" = dryrun ]; then
    # A preview changes nothing, and a messy tree is exactly when you want one.
    ylw "note: $DIRTY uncommitted change(s) present — a real deploy would refuse."
elif [ "$DIRTY" -ne 0 ]; then
    red "✗ working tree has $DIRTY uncommitted change(s) — refusing."
    red "  A deploy must not silently discard or collide with local edits:"
    git status --porcelain --untracked-files=no | sed 's/^/    /'
    record "REFUSED dirty-tree branch=$BRANCH sha=$PREV_SHA"
    exit 2
fi

if [ "$MODE" = rollback ]; then
    [ -s "$STATE_FILE" ] || { red "✗ no previous deploy recorded in $STATE_FILE"; exit 2; }
    TARGET=$(cat "$STATE_FILE")
    ylw "ROLLBACK requested -> $TARGET"
fi

hdr "what will change"
git fetch --quiet origin "$BRANCH" 2>/dev/null
RESOLVED="${TARGET:-origin/$BRANCH}"
git rev-parse --verify --quiet "$RESOLVED" >/dev/null || { red "✗ cannot resolve '$RESOLVED'"; exit 2; }
TARGET_SHA=$(git rev-parse "$RESOLVED")
if [ "$TARGET_SHA" = "$PREV_SHA" ]; then
    info "already at $(git rev-parse --short "$TARGET_SHA") — will restart so the process matches the tree"
else
    git --no-pager log --oneline "$PREV_SHA".."$TARGET_SHA" 2>/dev/null | sed 's/^/    /' | head -20
    info "$(git rev-list --count "$PREV_SHA".."$TARGET_SHA" 2>/dev/null || echo '?') commit(s) incoming"
fi

if [ "$MODE" = dryrun ]; then
    ylw "DRY RUN — nothing changed."; exit 0
fi

hdr "apply"
echo "$PREV_SHA" > "$STATE_FILE"     # recorded BEFORE anything changes
git checkout --quiet "$TARGET_SHA" 2>/dev/null || git merge --ff-only --quiet "$TARGET_SHA" || {
    red "✗ could not move to $TARGET_SHA — service untouched"; record "FAILED checkout target=$TARGET_SHA"; exit 1; }
git checkout --quiet "$BRANCH" 2>/dev/null && git merge --ff-only --quiet "$TARGET_SHA" 2>/dev/null
CHANGE_EPOCH=$(date +%s)
NEW_VERSION=$(grep -m1 -E '^VERSION' version.py | cut -d'"' -f2)
info "tree now at $(git rev-parse --short HEAD)  version.py=$NEW_VERSION"

hdr "restart"
OLD_PID=$(main_pid)
restart_service

hdr "verify"
if verify_running "$OLD_PID" "$CHANGE_EPOCH"; then
    grn "✓ DEPLOYED  $(git rev-parse --short HEAD)  (version.py $NEW_VERSION)  — running process verified"
    record "OK deploy $PREV_SHA -> $(git rev-parse HEAD) version=$NEW_VERSION"
    info "rollback if needed:  ./scripts/deploy.sh --rollback   (-> $(git rev-parse --short "$PREV_SHA"))"
    exit 0
fi

red "✗ DEPLOY FAILED — rolling back to $(git rev-parse --short "$PREV_SHA")"
record "FAILED deploy target=$TARGET_SHA — rolling back to $PREV_SHA"
git merge --ff-only --quiet "$PREV_SHA" 2>/dev/null || git reset --hard --quiet "$PREV_SHA"
RB_EPOCH=$(date +%s); RB_OLD=$(main_pid)
restart_service
if verify_running "$RB_OLD" "$RB_EPOCH"; then
    ylw "↩ ROLLED BACK to $(git rev-parse --short HEAD) — service healthy on the previous code."
    record "ROLLED-BACK to $PREV_SHA — healthy"
    exit 1
fi
red "✗✗ ROLLBACK ALSO FAILED — SERVICE MAY BE DOWN. Investigate now:"
red "   systemctl status $SERVICE ; tail -50 logs/server_complete.log"
record "CRITICAL rollback failed — service state unknown"
exit 3
