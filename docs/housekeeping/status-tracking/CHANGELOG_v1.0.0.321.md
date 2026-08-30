# CHANGELOG v1.0.0.321

**Date:** 2026-08-30
**Theme:** a deploy path that exists, and proves itself

---

## The gap

Putting RAICA under systemd (2026-08-28) and teaching `stop_complete.sh` /
`start_complete.sh` to defer to the unit were both correct in isolation. Together
they removed the deploy path, and nothing covered it.

The failure, on production:

    git pull            → succeeded, files now v1.0.0.320
    ./stop_complete.sh  → "raica.service is installed…"  exit 0   (no-op)
    ./start_complete.sh → "raica.service is installed…"  exit 0   (no-op)
    running process     → still 2-day-old code

`version.py` read the NEW number throughout, so the obvious check would have
confirmed the false success. Only the process start time exposed it.

## `scripts/deploy.sh` — the only supported deploy

    ssh <host> 'cd ~/RAICA && ./scripts/deploy.sh'

Pull → restart → poll for readiness → **verify the running process is the new code**
→ non-zero and loud if not. No sudo.

**Restarting without sudo:** under `Restart=always`, `SIGTERM` to the main PID makes
*systemd* start the replacement from the files on disk. Killing is safe; hand-STARTING
is what races the unit for port 5000, so the script never does that while the unit is
installed. If the unit is ever removed it falls back to the old scripts automatically —
the operator's command does not change.

**Verification (a version file proves nothing about what is executing):**
- `git pull --ff-only` must succeed before anything restarts
- health endpoint must answer within 120s — polled, never a fixed sleep
- **PID must change** — catches the exact no-op above
- **process start time must be AFTER the pull** — catches a stale process

Tested both ways: real deploy → `✓ … running process verified new`, exit 0; restart
stubbed out → `✗ pid unchanged … still executing the old code`, exit 1.

Also: both `stop_complete.sh` and `start_complete.sh` now name `./scripts/deploy.sh`
in their deferral notice, so the next person who hits that message is told where to go.

## Related

- `docs/DEPLOYMENT.md` — full procedure, rationale, rollback.
