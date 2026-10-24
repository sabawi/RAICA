# DESIGN — `run_python_analysis`: solve it with code when no tool fits

Status: **APPROVED (owner, 2026-10-24). P0 built (1.0.0.346); P1 built and verified locally (1.0.0.347); P2 audit done (1.0.0.348, §12):**
`user_tools/run_python_analysis_tool.py`, OFF by default, not on Ask's whitelist, not on live. P1 results in §11.

## 1. What the owner asked for

> "no ready tool, solvable through code, write the code and generate the results — show the chart"

When a request needs a calculation no ready tool can do — a simulation, an equation solved numerically, a model
run forward in time — the bot writes a Python program, runs it, and answers from what the program printed and drew.

**Why (measured 2026-10-24).** The solar-sail prompt (NewX post 9010) asked when a 400 kg probe with a 200 × 200 m
sail escapes the solar system. Ask has only `compute` (one numpy expression per value — no loops, no time-stepping)
and `plot_data` (sorts points by x, so a path cannot be drawn). Across 7 runs it gave 157 days, 1.5 years, 88 years,
or "years/decades"; live doubled the light pressure; no chart showed a trajectory. Given the same prompt and a
"write a program" instruction, `deepseek-v4-pro` wrote a 100-line `scipy.integrate.solve_ivp` simulation in one call;
run in isolation it gave β = 0.1530 and a bound orbit of 1.000–1.441 AU — identical to an independent simulation —
and an equal-scale trajectory chart. The model can do the work; it lacks a safe place to run code.

## 2. Threat model — assume every program is hostile

- **Who controls the code:** anyone who can post `@Ask` on NewX, and anyone whose text reaches the model — a
  fetched web page, a document, a quoted reply (prompt injection). The model can be talked into writing anything.
  So the program is treated as written by an attacker, every time.
- **What an attacker wants:** RAICA's and NewX's secrets (`.env`, API keys, the database), other members' data,
  the server itself (persistence, crypto-mining, spam/attack traffic from our IP), denial of service (exhaust the
  2-CPU / 3.9 GB host that also runs NewX), or a forged answer (fake chart markers, poisoned images).
- **What makes the host sensitive:** RAICA runs as `ubuntu`, which is in the `docker` and `sudo` groups — so the
  RAICA process is already root-equivalent. The sandboxed program must never reach the Docker socket, any host
  file, or the network. Nothing in the runner may pass a host path, environment variable or socket into it.

## 3. Reference model — how Anthropic runs untrusted code

- **Claude.ai** runs code in an **ephemeral gVisor container** on isolated infrastructure, with no access to the
  user's filesystem (InfoQ, July 2026; Simon Willison, 30 May 2026). gVisor (`runsc`) is a user-space kernel: the
  program's system calls are served by gVisor, not by the host kernel, so a kernel exploit inside the container does
  not reach the host. A plain container shares the host kernel — one kernel bug is an escape.
- **Claude Code** sandboxes commands with Bubblewrap on Linux / Seatbelt on macOS, **network denied by default**.
- Anthropic's stated layers: process sandboxes, VMs, filesystem boundaries, egress controls.

We copy the claude.ai shape: **a fresh gVisor container per run, no network, nothing from the host inside, thrown
away afterwards.** Sources: infoq.com/news/2026/07/anthropic-claude-containment,
simonwillison.net/2026/May/30/how-we-contain-claude/, code.claude.com/docs/en/agent-sdk/secure-deployment.

## 4. Architecture

```
model (tool call)                         RAICA process (host)                       gVisor container (throwaway)
run_python_analysis(task, program?) ──► utils/py_sandbox.py ──► docker run --runtime=runsc … ──► python3 /sandbox/runner.py
                                         • fixed argv, no shell                     • reads the program from STDIN
                                         • program via STDIN only                   • runs it in /work (tmpfs)
                                         • 1 run at a time (semaphore)              • prints ONE JSON envelope:
                                         • wall-clock kill                            {stdout, stderr, exit, files{png}}
                                  ◄──── • validates envelope + caps sizes
                                         • re-encodes each PNG (Pillow) → /static/images/media/<uuid>.jpg
                                         • returns text + [[chart:…]] markers it created itself
```

- **New tool**, not `sandboxed_executor`. That tool is a general shell (`permissive` mode, `pip`, `npm`, `cat`,
  `find`, host paths) and stays off every bot's whitelist.
- **No shell anywhere.** The runner calls `subprocess.run([...], input=program)` with a fixed argument list; the
  program text never touches a command line.
- **One image, built by us, pinned by digest:** `raica-pysandbox` = `python:3.12-slim` + pinned numpy, scipy,
  matplotlib (Agg), sympy, pandas. No pip, no compilers, no network tools at run time. Rebuilt only on purpose.

## 5. Container controls (every one is required)

| Control | Setting | Stops |
|---|---|---|
| Kernel isolation | `--runtime=runsc` (gVisor) | host-kernel exploits, `/proc`/`/sys` probing of the host |
| Network | `--network none` | exfiltration, attack traffic, downloads, calling our own APIs on localhost |
| Host files | **no `-v` mounts at all**; `--read-only` root | reading `.env`, the DB, media; persistence |
| Scratch space | `--tmpfs /work:size=64m,noexec,nosuid` and `/tmp` the same | disk filling; running dropped binaries |
| Identity | `--user 65534:65534` (nobody) | root inside the container |
| Privileges | `--cap-drop ALL`, `--security-opt no-new-privileges` | privilege escalation |
| Processes | `--ulimit nproc=32` (the limit the program meets) + `--pids-limit 256` (host backstop) | fork bombs |
| Open files | `--ulimit nofile=256` | descriptor exhaustion |
| Memory | `--memory 512m --memory-swap 512m` | starving NewX/RAICA (host has 3.9 GB, overcommitted) |
| CPU | `--cpus 1` | starving the 2-CPU host |
| Time | 60 s wall clock, then `docker kill`; `--stop-timeout 1` | infinite loops, sleeps |
| Files | `--ulimit fsize=…`, `nofile=…` | huge files, descriptor exhaustion |
| Environment | `--env` none; no host variables passed | leaking keys through `os.environ` |
| Lifetime | `--rm`, unique `--name`, reaped on timeout | leftovers, state shared between users/runs |
| Concurrency | one run at a time in RAICA; a second waits ≤ 30 s, then is refused | memory exhaustion under load |

Settings live in `config/llm_config.yaml` under `user_tools.run_python_analysis` (RAICA forbids hardcoded limits);
the tool **refuses to run** if gVisor is not the runtime, the network is not `none`, or any mount is configured —
a fail-closed check at every call, not only at start-up.

## 6. Output handling — the answer must not be forgeable

**Measured in P0:** a program can write straight to the in-container runner's stdout (`/proc/<ppid>/fd/1`), around
the runner's own cap. So the envelope is hostile by construction; the host caps it while reading (`max_envelope_bytes`)
and rejects anything that is not a well-formed envelope.

- Envelope size capped (stdout 32 KB, stderr 8 KB, at most 3 images × 2 MB). Anything over is cut and said so.
- **Images are re-encoded** with Pillow from decoded pixels (bounded dimensions) before publishing — a crafted file
  never reaches a member's browser as-is.
- **Chart markers are created only by the runner** for images it re-encoded. Any `[[chart:` text the program
  prints is neutralised before the output reaches the model, so a program cannot point the answer at another file.
- The program text is returned with the results, so the answer can say what was computed and a member can check it.

## 7. Who writes the program, and the policy text

- The tool takes `task` (what to compute and plot, with every given number) and runs **`deepseek-v4-pro`** (RAICA's
  configured `code_generation` model, the one tested above) to write the program. On an error it gets **one** repair
  attempt with the traceback; at most 2 runs per call. Each call logs the model tokens it used (shared quota).
- **Description (policy language, no keyword lists):** "Use when the request needs a calculation that no other tool
  provides — a simulation, a quantity that evolves over time, an equation that must be solved numerically, a
  trajectory or other path to draw. Describe the task fully, with every given number and what to plot. Prefer a
  ready tool when one answers the question." The code-writing prompt requires: state assumptions as comments,
  derive every number in code, simulate instead of using shortcuts that do not apply, equal axes for spatial plots,
  and — when the question's premise has more than one reading (e.g. "tracking the sun") — compute each reading.
- Must be checked against the other layers the model receives (gather gate, `compute`, `plot_data`, Ask.yaml
  preamble, citation guard) so they speak with one voice: the answer must be allowed to cite program output as its
  source (the citation guard previously rejected sourced chart answers that lacked a URL).

## 8. Switches and rollout

- `user_tools.run_python_analysis.enabled` — default **false** in shipped defaults and on live until certified.
- NewX: added to `Ask.yaml` `allowed_tools` only after P3; removable without a deploy.
| Phase | What | Exit condition |
|---|---|---|
| P0 | Install gVisor locally, build the image, the runner with no model | **red-team suite (§9) all blocked, each test watched FAIL with its control removed** |
| P1 | The tool + code-writing call, local RAICA | real path (NewX `call_raica` + Ask.yaml) on the sail prompt + 2 other code-only prompts, 3× each, answers checked against independent results |
| P2 | Security audit per NewX `docs/SECURITY_SPEC_AND_AUDIT.md` (new capability: code execution) + §5 entry | CERTIFIED, or the owner accepts named risks |
| P3 | Live: install gVisor from the official apt repo, add `runsc` to Docker's `daemon.json` (restarts Docker; no containers run today), pull/build the pinned image (~0.5 GB of 18 GB free), deploy RAICA with the switch OFF, run the red-team suite ON live, then switch ON for Ask | suite green on live; first real member request read in the log |

## 9. Red-team suite (each must be BLOCKED, and each test must go red with its control removed)

1. Read `/home/ubuntu/RAICA/.env`, `/etc/shadow`, `~/.ssh` — host files absent.
2. Open a TCP connection to the internet, to `127.0.0.1:5000` (RAICA), `:5432` (Postgres), `:6379` (Redis), and
   `169.254.169.254` (AWS instance metadata → cloud credentials).
3. Reach `/var/run/docker.sock`.
4. Fork bomb; 2 GB allocation; infinite loop; `time.sleep(600)`.
5. Fill disk (`/work`, `/tmp`); write outside them (read-only root).
6. Print 50 MB; print a fake `[[chart:/static/images/media/other.jpg]]`; save a 10 000 × 10 000 PNG and a
   non-PNG renamed `.png`.
7. `os.environ` contains no host variables.
8. Two runs at once: the second waits, then is refused; a member cannot see another run's files.
9. Container left behind after a timeout or a RAICA restart → reaped.
10. Runtime check: a configuration without `runsc`, or with a mount, refuses to run.

## 9a. Found in P0 (each now a named test that failed on the code before the fix)

1. **Under gVisor, `--pids-limit` counts gVisor's own host threads, not the program's processes.** At 64, about 20
   sleeping child processes exhausted it and the sandbox died with exit 2 and no output (any program using ~20
   workers would have failed unexplained). gVisor applies `--ulimit nproc`, so that is now the limit the program
   meets (a clean `fork` failure, result still returned); `pids_limit` rose to 256 as the host backstop.
2. **Cleanup hung forever after the output cap tripped.** `docker rm -f` was called while the attached client still
   held a pipe the program was blocked writing to; it never returned, so the one-run lock was never released — ONE
   hostile program would have disabled the tool until RAICA restarted. Now: detach the client first, then remove,
   every step time-bounded; `reap_leftovers()` bounded the same way. Guard: the bypass test asserts it ends in < 30 s
   with no container left; with the old cleanup planted it fails ("did not finish within 58s").
3. Four tests initially passed for the wrong reason (a second layer — file permissions, the image's `nobody` user,
   the runner rebuilding the environment — blocked the attack). Each was retargeted so that only its own protection
   can stop it, and each plant now turns it red.
4. Full sandboxed run of the solar-sail program: 3.05 s including gVisor start-up (local).

## 10. Decisions

1. **DECIDED (owner, 2026-10-24): Docker on sabawi.net and local, for now** — not a separate VM. gVisor (`runsc`)
   is the Docker runtime for these containers; Docker's default runtime and the existing containers are unchanged.
2. **Run limits — DECIDED (owner, 2026-10-24): ceilings, not reservations.** 60 s / 512 MB / 1 CPU are kill limits;
   the container is removed the moment the program ends. Measured: the solar-sail program runs 1.3 s at ~115 MB
   peak (local, no gVisor; 3 runs). Writing it took 72 s, so code generation, not execution, dominates the wait.
3. **DECIDED (owner, 2026-10-24): Ask first;** other bots later, only if needed — each one is added to its own
   `allowed_tools` deliberately, never by default.
4. Quota: each code run is 1–2 `deepseek-v4-pro` calls (~10 k output tokens measured) on the shared account.

## 11. P1 results (local, 2026-10-24) — real path: NewX `build_context_messages` + `call_raica`, Ask's whitelist
plus `run_python_analysis` (in memory; Ask.yaml unchanged until P3), RAICA 1.0.0.347 with the tool enabled locally.

| Prompt (3 runs each) | Chart in answer | Figures vs independent result | Time |
|---|---|---|---|
| Soccer ball with/without drag | 3/3 | 3/3 correct (51.4 m / 90.35 m, 3.31 s / 3.93 s) | 24–70 s |
| Rabbits and foxes (Lotka-Volterra) | 3/3 | 3/3 correct (42.80, 21.40, 83.1-month cycle) | 33–130 s |
| Solar sail (NewX post 9010) | 3/3 | 3/3 correct for a Sun-facing sail (β 0.153, never escapes); 0/3 also covered a tilted sail | 53–130 s |

Found and fixed during P1 (each a named test that fails on the earlier code):
1. **The shared code-generation client drops `system_prompt` on Ollama** — every program called `plt.show()` and saved
   no chart. The rules now travel in the message. (SI-110 logs the client defect itself.)
2. **The same client does not resolve `code_generation.selected_model`** and, with no explicit provider, walks its whole
   fallback list including PAID providers whatever `fallback_enabled` says. The tool names its provider and model
   (`writer_provider` / `writer_model`) and turns fallback off; verified offline that only that model is tried.
3. **The gate was blind to this tool's output.** `describe_reference` described any text containing a "table" as ONLY
   that table — and three lines of the program's source sharing a comma count qualified — so the gate saw neither the
   results nor the chart and re-ran the tool every round (155 s, 4 runs). A table that is a minority of the text is
   now shown as before AND followed by the text (`_TABLE_DOMINANT_SHARE`); 370 reference/gate tests unchanged.

Open (quality, not safety): the ambiguity rule did not make any run cover the tilted-sail reading; chart titles are
written by the program before it knows the result ("Spiral Outward" over a closed orbit); two runs quoted a later of
several equal peaks. NewX's citation guard was not part of this path and must be checked at P3 through a real post.

## 12. P2 security audit (2026-10-24) — recorded in NewX `docs/SECURITY_SPEC_AND_AUDIT.md` §5

Found and fixed:
1. **The server could be starved.** Production has ~1 GB available with swap in use; a program at its 512 MB limit
   costs ~575 MB of host memory (measured: empty program +65 MB, 450 MB program +560 MB). `check_host_memory` refuses to
   start unless `min_host_available_mb` (default 400) remains after the program's whole limit, and answers "busy". It
   runs after the one-program lock is taken and inside the `try`, so a refusal releases the lock (planted: red).
2. **A program killed for memory was reported as "no readable result".** The sandbox's own exit status is now in the
   notes (137 → "most often the memory limit"), so the repair attempt knows why. Red-team memory-bomb test asserts it.
3. **The writer was not told the memory or image-size limits** — charts over `max_image_pixels` were silently dropped.
   Both are now in its instructions, from config.
4. NewX (1.0.0.463): chart links could climb out of the media folder (`../`); a link must now name one file.

Measured for P3: the reference solar-sail program runs at 192 MB; a deliberately heavy program (2 M-point solution, three
2400×1800 charts) needs more than 256 MB. Production cannot afford 512 MB + 400 MB margin at its usual ~0.85–1.1 GB
available, so P3 must choose `memory` (e.g. 384m) and `min_host_available_mb` for that host, or accept "busy" answers.

Smoke after the instruction change (one run per prompt, real path): chart 3/3, figures correct 3/3 for the reading each
run chose. The rabbits-and-foxes run read "fox growth per rabbit eaten 0.01" as 0.01 × the predation rate (rabbit peak
2,134.7 — matches an independent computation of that reading) where the 9 P1 runs used 0.01 directly (42.8). Both
readings are reasonable; neither run said the other existed. Surfacing ambiguity remains the open quality item.
