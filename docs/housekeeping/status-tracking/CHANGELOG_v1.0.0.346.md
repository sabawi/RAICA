# CHANGELOG v1.0.0.346 — 2026-10-24

## Python sandbox for model-written programs — phase P0 (runner + red-team suite; not wired to any tool, OFF)

Owner request (2026-10-24, NewX post 9010, solar-sail prompt): when no ready tool fits but the problem is solvable
in code, the bot should write the program, run it, and answer from its results and chart. Design, threat model and
decisions: `docs/DESIGN_run_python_analysis.md` (owner approved: Docker + gVisor on sabawi.net and local; Ask first).

### Added
- `deploy/pysandbox/` — `raica-pysandbox:1` image: python:3.12-slim pinned by digest, numpy/scipy/matplotlib/sympy/
  pandas pinned to RAICA's versions, no pip, `nobody` user; `runner.py` runs one program and prints a JSON envelope.
- `utils/py_sandbox.py` — runs a program in a throwaway gVisor container: `--runtime runsc`, `--network none`, no
  mounts, read-only root, noexec tmpfs, nobody, all caps dropped, no-new-privileges, nproc/pids/nofile/memory/CPU
  limits, wall clock, `--rm` + label reaping, one run at a time. Refuses to run unless runtime is runsc and network is
  none (checked every call). Treats the envelope as hostile: size-capped while read, type-checked, chart markers
  disabled, images re-encoded from pixels.
- `config/llm_config.defaults.yaml` — `user_tools.run_python_analysis` (all limits; `enabled: false`).
- `tests/integration/test_pysandbox_redteam.py` (25 attacks, all blocked; real containers, fails if Docker/runsc is
  missing) and `tests/integration/run_pysandbox_plants.py` (removes each protection in memory: 16/16 tests go red).

### Found and fixed during P0
- Under gVisor `--pids-limit` counts gVisor's host threads: ~20 sleeping children killed the sandbox with no output.
  `--ulimit nproc` (applied by gVisor) is now the program's limit; `pids_limit` 256 is the host backstop.
- Cleanup called `docker rm -f` while the client was attached to a blocked pipe and hung forever, holding the
  one-run lock (one hostile program would disable the tool until restart). Now detach first, then remove; every
  step bounded; the reaper bounded too. Guard fails in 58 s with the old cleanup planted.

### Requires on a host that enables it (P3, not yet)
Docker with the gVisor `runsc` runtime (official apt repository) and `docker build -t raica-pysandbox:1 deploy/pysandbox`.
No Python dependency added on the host (Pillow and PyYAML already required).

### Migration
None. The new configuration keys are added to a site's config at start-up with `enabled: false`.
