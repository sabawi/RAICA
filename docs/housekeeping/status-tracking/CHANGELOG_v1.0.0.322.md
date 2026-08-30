# CHANGELOG v1.0.0.322

**Date:** 2026-08-30
**Theme:** deploy.sh waits for the process to CYCLE before it checks health

## The bug its own first production run found

`scripts/deploy.sh` (v1.0.0.321) sent `SIGTERM` and immediately polled the health
endpoint. Under `Restart=always` with `RestartUSec=5s` the OLD process is still
listening for that moment, so:

    ── wait for ready ──
      answering after 0s                 ← the DYING process answered
    ── verify ──
      ✗ pid unchanged (134722) — the process was NOT restarted.

The health check passed against the process being replaced and proved nothing. The
PID check then caught it and the deploy failed loudly — the verification worked, but
it was doing the job the readiness wait should have done.

## Fix

Poll for the **PID to change** first (90s deadline), and only then poll the health
endpoint. A health check aimed at the outgoing process is not a readiness signal.

Same principle already in the repo's operational rules: readiness is never
instantaneous, and anything asking "is it up yet?" must poll with a deadline —
against the thing that is actually supposed to be up.
