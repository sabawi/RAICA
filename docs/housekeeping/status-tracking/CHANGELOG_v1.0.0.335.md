# CHANGELOG v1.0.0.335 — 2026-10-18

## RAICA installs and starts on a clean server (found by the NewX installer test)

**Why:** NewX 1.1 installs RAICA as a dependency with one command (NewX `docs/DESIGN_installer.md`). The first
installs into clean Ubuntu 24.04 containers found three things that only worked on machines that already had them.
Owner approved the fixes 2026-10-18 ("go ahead with the RAICA fixes").

### Fixed
- **`/images` was mounted from a hardcoded developer path** (`/home/<developer>/Development/flaskserver/sandbox_workspace`).
  - On a clean server, StaticFiles refused to start without that folder, and RAICA crash-looped.
  - Production worked only because that exact path exists there as a symlink to `/home/ubuntu/sandbox_workspace`.
  - A developer machine served an unrelated old project folder.
  - Now: the mount uses `_delivery_sandbox_dir()`, the config-driven resolver the delivery code already writes
    through (`user_tools.sandboxed_executor` in `llm_config.yaml`). The folder is created if missing.
  - On production that resolves to the symlink's target, so production behaviour is unchanged. No `/images/`
    requests appear in production's kept logs.
- **`scripts/install_raica_service.sh` creates `logs/`, `logs/archive/`, `runtime/` and `document_store/`.**
  - The unit sends its output to `logs/server_complete.log`.
  - systemd opens that file BEFORE `ExecStartPre` (which would make the folder) runs, so on a fresh clone every start
    failed with `status=209/STDOUT`.
- **`install_raica_service.sh` no longer mistakes the systemd-run RAICA for a "hand-started" one.**
  - `pgrep` matched both, and `pkill` stopped the unit's own process.
  - Now: the unit's MainPID is excluded, and only the hand-started PIDs are signalled.

### Changed — dependencies: a server set, a development set, and a lock
- `requirements.txt` is the **server** set: `easyocr` removed.
  - EasyOCR is what pulled torch, torchvision and opencv (~1.1 GB).
  - OCR falls back to tesseract automatically (`document_interrogator.py`).
  - Measured on production: all 350 indexed documents are `.md`, so OCR is not used to index them.
  - PyQt6 (256 MB in production's venv) was never in the file: nothing requires it.
- New `requirements-dev.txt` = `-r requirements.txt` + `easyocr`, for development machines.
- New `requirements.lock`: production's exact versions (`pip freeze`), used as constraints:
  `pip install -r requirements.txt -c requirements.lock`.

### Measured
- Clean Ubuntu 24.04 container, slim set + lock: venv **1.6 GB** (production 2.7 GB).
- RAICA starts and logs "Tesseract initialized as primary OCR engine", `/v1/models` 200, `/health` 200, on-box
  `/v1/embeddings` (all-minilm, 384 dims) works.
- A dry-run resolve of the slim set against the lock installs none of torch, torchvision, PyQt6, easyocr, opencv.

### Tests
- `tests/unit/test_images_mount.py` (3):
  - exactly one `/images` mount;
  - its directory is `_delivery_sandbox_dir()`, not a literal;
  - the mount comes after the resolver is defined (a module-level call above it would be a NameError at import).
- Planted the old line back: 2 red. Restored: 3 green.

### Breaking changes / migration
- A development machine that relies on EasyOCR must install `requirements-dev.txt`. An existing venv keeps
  whatever it has: nothing is uninstalled.
- On a developer machine, `/images` now serves `~/sandbox_workspace` (where RAICA writes) instead of the old
  `flaskserver/sandbox_workspace`.
