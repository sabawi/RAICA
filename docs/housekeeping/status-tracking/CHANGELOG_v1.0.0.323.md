# CHANGELOG v1.0.0.323

**Date:** 2026-08-30
**Theme:** systemd is the controller again, and the deploy is fail-proof, transparent, reversible

## Controller

`scripts/deploy.sh` restarts THROUGH systemd — `sudo systemctl restart raica.service`
where passwordless sudo is available (it is on prod), else SIGTERM which `Restart=always`
answers. It never hand-starts while the unit exists: that races port 5000 and caused two
503 outages in the NewX rollout.

## Fail-proof

A failed deploy now **rolls itself back and re-verifies**, so the service is never left
down or on broken code. If the rollback also fails it exits 3 and says so — the one
state that must never be silent.

Verification is of the PROCESS: PID must change, health must answer, and the process
start time must be after the change. Files are never treated as evidence.

## Transparent

- Prints the incoming commits BEFORE applying them.
- Appends every attempt — OK, REFUSED, FAILED, ROLLED-BACK, CRITICAL — to `logs/deploy.log`.
- `--dry-run` previews and touches nothing (works on a dirty tree, since it changes nothing).

## Reversible

`.deploy_previous_sha` is written BEFORE anything changes, so `--rollback` never has to
reconstruct the target. `--to <sha>` deploys any specific commit.

## Refusals

Dirty working tree (exit 2, lists the files), unresolvable ref, failed checkout — in
each case the service is left untouched.

## Tested

- `--dry-run` on a dirty tree: warns, changes nothing, PID unchanged.
- dirty tree, real deploy: refused, exit 2, files listed.
- (prod) deploy + verify: see the run recorded in `logs/deploy.log`.
