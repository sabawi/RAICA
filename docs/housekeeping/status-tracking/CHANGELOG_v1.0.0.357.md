# CHANGELOG v1.0.0.357 — 2026-11-16

## EasyOCR runs on the CPU when the GPU is one PyTorch cannot use

### Problem (measured on the development laptop)
- Every start logged `Failed to initialize easyocr: CUDA error: no kernel image is available for execution on the
  device`, then `OCR system ready: tesseract + 0 fallbacks`: a development machine that installs
  `requirements-dev.txt` for EasyOCR ran without it.
- The machine has an NVIDIA GeForce GTX 860M (compute capability 5.0). PyTorch 2.9.1+cu128 ships kernels for
  sm_70 and up. `torch.cuda.is_available()` is still True (driver present), so `easyocr.Reader(['en'])` chose the GPU
  and failed. EasyOCR on the CPU works on the same machine.
- Production (no GPU) logs `easyocr + 1 fallbacks` and is unaffected.

### Changed
- `document_interrogator.easyocr_can_use_gpu()`: True only when the PyTorch build has a kernel for the device, by
  CUDA's own rules (an `sm_XY` cubin runs on the same major at minor >= Y; `compute_XY` PTX runs on any device at or
  above XY). The answer is read from `torch.cuda.get_arch_list()` and `get_device_capability()`; no GPU list in code,
  no configuration value. Any error during the probe means CPU, never a lost engine.
- `OCREngineManager` passes it as `easyocr.Reader(['en'], gpu=...)` and logs which device it uses.

### Verification
- `tests/unit/test_easyocr_gpu_probe.py`: 7 cases (the laptop's 5.0 under the cu128 arch list; a supported GPU keeps
  the GPU; same-major newer minor; lower minor without PTX; PTX covering a newer device; no CUDA; a failing probe).
  With the old behaviour planted (trust `is_available()`), 3 fail.
- Local server restart: `EasyOCR initialized as primary OCR engine (CPU)`, `OCR system ready: easyocr + 1 fallbacks`
  (was `tesseract + 0 fallbacks`).
- `DocumentProcessor._extract_image_text` on a generated image read `'Invoice 4721 paid in full'` exactly, via EasyOCR
  on CPU. (Not through a server request: the server's indexing path also embeds via the configured provider.)
- `tests/unit`: 1153 passed; 4 failures are pre-existing (identical on a clean 1.0.0.356 worktree, none in OCR),
  logged as SI-118. `tests/smoke/tool_smoke.py` passed. `tests/utilities/run_mu_e2e_verify.py` 5/5 tickers (its chart
  uploads need local NewX, which was not running).

### Dependencies, breaking changes, migration
- None. No new imports, no configuration keys. Servers without EasyOCR (requirements.txt) are unchanged.
