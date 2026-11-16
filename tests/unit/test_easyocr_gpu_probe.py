"""EasyOCR uses the GPU only when this PyTorch build has kernels for it (v1.0.0.357).

The failure it prevents: on a development laptop with a GTX 860M (compute 5.0) and PyTorch 2.9.1+cu128 (built for
sm_70 and up), torch.cuda.is_available() is True, so easyocr.Reader(['en']) chose the GPU, failed at start with
"CUDA error: no kernel image is available for execution on the device", and RAICA ran without EasyOCR at all
("OCR system ready: tesseract + 0 fallbacks"). The engine works on that machine's CPU.

A fake torch module stands in for the real one, so each case is the exact capability/arch list a machine reports.
Run: ./venv/bin/python -m pytest tests/unit/test_easyocr_gpu_probe.py -q
"""
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from document_interrogator import easyocr_can_use_gpu  # noqa: E402

BUILD_CU128 = ['sm_70', 'sm_75', 'sm_80', 'sm_86', 'sm_90', 'sm_100', 'sm_120']   # measured: torch 2.9.1+cu128


def _torch(available=True, capability=(8, 6), arches=BUILD_CU128, raises=None):
    def cap(_i):
        if raises:
            raise raises
        return capability
    cuda = types.SimpleNamespace(is_available=lambda: available, get_device_capability=cap,
                                 get_arch_list=lambda: list(arches))
    return types.SimpleNamespace(cuda=cuda)


def test_a_gpu_the_build_has_no_kernels_for_runs_on_cpu():
    """The 2026-11-16 laptop: compute 5.0 under a sm_70+ build. GPU chosen = EasyOCR lost entirely."""
    assert easyocr_can_use_gpu(_torch(capability=(5, 0))) is False


def test_a_supported_gpu_still_uses_the_gpu():
    """Machines whose GPU the build supports keep GPU OCR: the fix must not turn the GPU off everywhere."""
    assert easyocr_can_use_gpu(_torch(capability=(8, 6))) is True


def test_a_newer_minor_of_a_built_major_uses_the_gpu():
    """CUDA binary compatibility: an sm_86 cubin runs on compute 8.9 (same major, higher minor)."""
    assert easyocr_can_use_gpu(_torch(capability=(8, 9), arches=['sm_80', 'sm_86'])) is True


def test_a_lower_minor_than_any_built_kernel_runs_on_cpu():
    """An sm_86 cubin does NOT run on compute 8.0; without PTX that device has no kernel."""
    assert easyocr_can_use_gpu(_torch(capability=(8, 0), arches=['sm_86'])) is False


def test_ptx_covers_a_newer_device():
    """PTX (compute_XY) is JIT-compiled for any device at or above XY."""
    assert easyocr_can_use_gpu(_torch(capability=(12, 1), arches=['sm_80', 'compute_90'])) is True


def test_no_cuda_runs_on_cpu():
    """A server with no GPU (production) keeps the CPU path it has always used."""
    assert easyocr_can_use_gpu(_torch(available=False)) is False


def test_a_failing_probe_runs_on_cpu_instead_of_losing_ocr():
    """A driver that errors during the probe must cost the GPU, never the OCR engine."""
    assert easyocr_can_use_gpu(_torch(raises=RuntimeError('driver gone'))) is False
