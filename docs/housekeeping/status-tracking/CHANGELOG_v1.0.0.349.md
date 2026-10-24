# CHANGELOG v1.0.0.349 — 2026-10-24

## Deploy scripts: unit detection failed at random under `pipefail`

Found while deploying 1.0.0.348. `scripts/deploy.sh` printed `systemd=no` on production with `raica.service`
installed and running.

### Fixed
- `scripts/deploy.sh` `systemd_managed`: `systemctl list-unit-files … | grep -q` under `set -o pipefail` FAILS when
  grep exits at its match while systemctl is still writing (SIGPIPE). Measured on production: the old check answered
  "no" 17 times in 30, the new one "yes" 30/30. A "no" mid-deploy sends the restart to the hand-start scripts, which
  defer to the unit, so the process never cycles. The output is now captured, then matched.
- `scripts/install_raica_service.sh`: the same pattern guarded `systemd-analyze verify` — a REJECTED unit could read as
  clean and be installed. Same fix, plus the `--check` listing.

### Tests
`tests/unit/test_deploy_pipefail_detection.py` (2): stand-in commands print the match first and then more than a pipe
buffer; both tests fail on the old scripts ("no", "clean") and pass on the new.

### Migration
None.
