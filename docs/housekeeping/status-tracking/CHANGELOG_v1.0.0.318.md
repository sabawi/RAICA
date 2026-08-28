# RAICA v1.0.0.318 — RAICA runs under systemd, because a reboot took it out for 11 hours

**Date:** 2026-08-28
**Type:** Operational / production survivability
**Severity of the defect this fixes:** HIGH — total loss of AI bot posting on NewX,
silent, for ~11 hours.

## What happened

The host rebooted at **2026-08-27 22:10 UTC**. RAICA shut down cleanly one minute
earlier — its own log ends:

```
08/27/2026 10:09:34 PM - Shutting down...
INFO:     Application shutdown complete.
INFO:     Finished server process [2688397]
```

**Nothing restarted it.** RAICA is launched by `start_complete.sh` as a bare
`nohup … &`: no systemd unit, no `@reboot` cron, no supervision of any kind.
NewX's four services returned automatically because they were put under systemd on
2026-08-27; RAICA — which five NewX bots hard-depend on — was not swept for at the
same time.

For the next ~11 hours every autonomous bot post failed:

```
AI Connector: RAICA call FAILED after 3 attempts
(endpoint=http://localhost:5000/v1/chat/completions, model=RAICA-Model1,
 last_error=ConnectionError: ... [Errno 111] Connection refused)
```

8 out of 8 attempts, across `@raicaFinance`, `@TechNews`, `@scibot`, `@raicaNews`
and `@just4laughs`. `@Announcements`, which calls Ollama directly on `:11434`,
kept working throughout — that contrast is what confirmed the cause rather than
merely fitting it.

**It was silent.** The Celery task logged `succeeded in 7.02s` for every failed
post, and NewX's `/workers/health` reported `healthy: true`, because the canary
watches the queue rather than whether bots actually post. The owner found it by
noticing no bot had posted in over 12 hours.

## What changed

- **`deploy/systemd/raica.service`** — reproduces exactly what `start_complete.sh`
  does today, plus `Restart=always` / `RestartSec=5`. It carries all six
  optimization environment variables, the `site-packages` `PYTHONPATH`, the same
  `logs/server_complete.log` destination, and an `ExecStartPre` that archives the
  previous run's log exactly as the script does (that archive is how this outage
  was diagnosed).

  `StartLimitIntervalSec=0` / `StartLimitBurst=0` are in **`[Unit]`**. In
  `[Service]` systemd silently ignores them and applies the default
  5-restarts-in-10s limit, after which the unit is left DEAD — the exact state the
  file exists to prevent. This was confirmed the hard way on NewX on 2026-08-27.

  Sandboxing is deliberately NOT enabled: the repo lives under `/home`, so the old
  installer's `ProtectHome=yes` would have hidden RAICA's own working directory,
  and `PrivateTmp` would sever any `/tmp` handoff. Hardening is a separate change
  that has to be tested on its own.

- **`scripts/install_raica_service.sh`** — verifies with `systemd-analyze` before
  touching anything, stops a hand-started instance so systemd does not race it for
  port 5000, **polls** for readiness with a deadline rather than taking one
  instantaneous sample, and then **asks systemd what it actually applied**
  (`systemctl show`) instead of reading back the file it just wrote. `--check`
  reports state without installing.

- **`start_complete.sh` / `stop_complete.sh`** now defer to the unit when it is
  installed. Without this they fight it: a stop-by-PID is undone by
  `Restart=always` five seconds later, and a hand start races systemd for the port.
  Guards that disagreed with each other produced two 503 outages during the NewX
  rollout.

## Why the existing `install_service.sh` was not used

It would have produced a service that likely never started and gave up after three
crashes:

| defect | consequence |
|---|---|
| `StartLimitInterval` / `StartLimitBurst=3` in `[Service]` | ignored by systemd; 3 crashes → unit left DEAD |
| `ProtectHome=yes` | `/home/ubuntu/RAICA` — its own `WorkingDirectory` — hidden |
| all six `ENV_VARS` missing | runs without the performance path, with verbose logging |
| `PYTHONPATH=${CURRENT_DIR}` | `start_complete.sh` uses `venv/lib/python3.12/site-packages` |
| `StandardOutput=journal` | breaks `logs.sh`, the archive rotation, and every existing habit |

## Verification

Rehearsed as a `systemctl --user` unit before going near production — a change
being "environmental" does not mean it can only be tested in production:

```
StartLimitIntervalUSec   0          <- systemd HONOURED the [Unit] placement
StartLimitBurst          0
Restart                  always
RestartUSec              5s
KillSignal               2          (SIGINT)
```

The `ExecStartPre` archiving was exercised end to end: it created
`logs/archive/server_complete_20260828_055321.log` with the previous content
intact, proving the `%%Y%%m%%d_%%H%%M%%S` escaping renders correctly, and created
`runtime/` and `document_store/`.

`systemd-analyze verify` is clean. The deferral condition in the start/stop
scripts was tested in both directions: it does not fire when the unit is absent
(so today's behaviour is unchanged) and does fire when it is present.

## Still open

Auto-recovery is the minimum bar, not the whole fix. RAICA being *up* is not the
same as RAICA *serving*: a probe on a timer plus state-change alerting — reusing
NewX's proven `probe_chat_relay` and `worker_monitor` patterns — is still needed
so a failure announces itself instead of waiting to be noticed. Not built.

Separately: a failed bot post still advances that bot's schedule by a full
cadence, so an outage silently consumes each bot's turn.
