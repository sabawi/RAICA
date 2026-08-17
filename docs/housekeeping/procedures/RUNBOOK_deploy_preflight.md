# RUNBOOK — pre-deploy gate: run this BEFORE pulling to the live server

**Created:** 2026-08-17 · **Against:** v1.0.0.297 · **Closes:** SI-060

## Why this exists

A deploy is described as "pull the fixes", and the fixes are code. But the pull carries
`config/llm_config.yaml` too — so it also carries whatever provider the last local
experiment left committed.

Measured 2026-08-16, this repo was one `git pull` away from taking production down:

```
live (2f5a2e6) : every lane on Ollama at 127.0.0.1:11434    -- healthy
HEAD           : every lane on https://api.deepinfra.com    -- residue of a LOCAL trial
live .env      : DEEPINFRA_API_KEY  ->  ABSENT
```

All 11 lanes would have landed on a vendor the host holds no credential for: **401 on every
LLM call.** Nothing caught it because every check we own validates the config against the
machine it is ON — where the key exists. The deciding fact (a secret outside the repo) is
invisible to code review as well.

## The command

```bash
tools/deploy_preflight.py \
  --target-ssh "ssh -i /path/to/key user@host" \
  --target-dir '~/RAICA'
```

Defaults to comparing `HEAD` against the target. To check a different ref or a file:

```bash
tools/deploy_preflight.py --incoming-ref origin/main --target-ssh ... --target-dir ...
tools/deploy_preflight.py --incoming-file config/llm_config.yaml --target-ssh ... --target-dir ...
```

Secret **names** only are read from the target; no value is ever transferred or printed.

## Reading the result

| exit | meaning | what to do |
|---|---|---|
| **0** | **GO** — no provider change, all required credentials present | proceed with the deploy |
| **1** | **NO-GO** — a lane would land where it cannot authenticate | **stop.** Set the secret on the target, or `./config_server_cli.py convert --to <provider> --yes` to match what the target already runs |
| **2** | **GO WITH DECISION** — credentialled provider migration | legitimate, but confirm it is *intended*; a deploy must never change provider as a side effect |

## Where it sits in the deployment protocol

Between "push to GitHub" and "pull on the live server" — i.e. immediately before the change
reaches production:

1. commit locally
2. restart local, verify `/health`, review `logs/server_complete.log`
3. regression tests + E2E + **`make smoke`**
4. push to GitHub
5. **→ `tools/deploy_preflight.py` — must be GO (or an explicitly accepted GO-WITH-DECISION)**
6. pull on the live server, restart, verify remote `/health`, review remote logs

## What it does NOT check

Reachability and model validity on the target. Preflight answers *"can the target
authenticate where these lanes now point?"*, not *"does that endpoint serve these models?"*.
The second question belongs to `config_server_cli.py convert`, which runs
`tests/integration/test_all_lanes_live.py` automatically after every switch.

Nor does it check application code — it is a config/credential gate, not a test suite.

## Tests

`tests/integration/test_deploy_preflight.py` — 8 tests, including the control case (same
config deployed to itself must be GO, so a gate that always says NO-GO cannot pass) and a
false-alarm guard (a secret no active lane uses must not be demanded).
