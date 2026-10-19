# CHANGELOG v1.0.0.337 — 2026-10-19

## `scripts/deploy.sh --rollback` really goes back (it never could)

**Why:** found 2026-10-19 while testing the v1.0.0.336 transition for the NewX installer.
- `deploy.sh --rollback` printed "ROLLBACK requested -> 07ebd7a" and then "✓ DEPLOYED 04a1c7b": it **stayed on the newer
  code** and reported success.
- `--to <an older commit>` did the same. Both have been like this since v1.0.0.323.
- The NewX installer's upgrade rollback calls `deploy.sh --to <previous>`, so a NewX rollback left RAICA forward
  while reporting a full rollback.

**Cause (read in the code):** the apply step did `git checkout <target>` (detached), then `git checkout <branch>`
and `git merge --ff-only <target>`. For a rollback the branch tip is the NEWER commit, so the second checkout went
straight back to it; the fast-forward to an older commit is a no-op.

### Fixed
- New `move_tree TARGET`:
  - forward = `merge --ff-only`;
  - backward = `reset --hard` on the branch (safe: a dirty tree is refused earlier);
  - then it **verifies HEAD equals the target**, and fails loudly otherwise;
  - used by the apply step AND the failure path.
- Rolling back across v1.0.0.336 (to a commit that tracks `config/llm_config.yaml`) replaces the site's file with the
  old tracked one. A copy is kept first, `config/llm_config.yaml.site-before-rollback-<time>`, and announced.

### Tests
- `tests/unit/test_deploy_move_tree.py` (3, on the function extracted from deploy.sh itself): forward, backward
  really goes back (on the branch, not detached), back across the config change keeps the site's file.
- The old checkout-then-branch logic planted back: 2 red; restored (cmp): 3 green.
- The real path, on a VM: forward to this release with deploy.sh, then `--rollback` across the config change.
