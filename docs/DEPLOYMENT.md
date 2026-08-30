# RAICA Deployment

**Command — the only supported way to deploy:**

```bash
ssh -i <key> ubuntu@sabawi.net 'cd ~/RAICA && ./scripts/deploy.sh'
```

It pulls, restarts, waits for readiness, and **proves the running process is the new
code**. It exits non-zero and says why if it is not. No sudo required.

---

## Why a script, and why it verifies

RAICA runs under systemd on production (`raica.service`, `Restart=always`, installed
2026-08-28 after the service died and stayed dead). On the same day
`stop_complete.sh` / `start_complete.sh` were taught to **defer** to the unit: they
print `stop it with: sudo systemctl stop raica` and `exit 0`, because hand-starting
races systemd for port 5000 — that race produced two 503 outages during the NewX
rollout.

Both halves are correct. Together they left **no deploy path**, and nobody noticed
until a deploy was attempted:

> 2026-08-30 — `git pull && ./stop_complete.sh && ./start_complete.sh` on production.
> The pull succeeded. Both scripts printed their deferral notice and exited 0. The
> process kept running **two-day-old code** while `version.py` on disk read the new
> number the whole time. Reading the version file would have *confirmed* the false
> success. Only the process start time exposed it.

So the rule this encodes: **a version file proves nothing about what is executing.**
Verify the PROCESS.

## How it restarts without sudo

Under `Restart=always`, sending `SIGTERM` to the main PID makes **systemd** start the
replacement, from the files currently on disk.

- Killing is safe. Hand-**starting** is what races the unit — so the script never does
  it while `raica.service` is installed.
- No sudo, no `systemctl` verb, no port race.

If the unit is ever removed, the same script falls back to
`stop_complete.sh` → `start_complete.sh` automatically. The procedure does not change.

## What it checks before reporting success

| check | why |
|---|---|
| `git pull --ff-only` succeeded | a failed pull must not restart anything |
| health endpoint answers within 120s | polls; never a fixed sleep |
| **PID changed** | catches the exact 2026-08-30 no-op deploy |
| **process start time is AFTER the pull** | catches a restart that predates the new code |

Any failure → non-zero exit, the reason in red, plus service state and the last log
lines. Verified by test: with the restart stubbed out, it reports
`✗ pid unchanged … the service is still executing the old code` and exits 1.

## Do not

- **Do not deploy with `systemctl` verbs.** Owner directive, 2026-08-30.
- **Do not hand-run `start_complete.sh` on a systemd-managed host** — it will refuse,
  and forcing past it races the unit for port 5000.
- **Do not treat `version.py` as proof of what is running.** It is the input to a
  deploy, not evidence of one.

## Rollback

```bash
ssh <host> 'cd ~/RAICA && git log --oneline -5'          # pick the previous good sha
ssh <host> 'cd ~/RAICA && git checkout <sha> && ./scripts/deploy.sh'
```
`deploy.sh` verifies a rollback exactly as it verifies a deploy.
