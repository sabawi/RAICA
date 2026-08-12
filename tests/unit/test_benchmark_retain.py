"""retain() must keep EVERY run of an arm, not one arbitrary survivor.

The original wrote one file per (scenario, tag), so an n=3 arm left a single file and the other
two answers were destroyed. That is not a smaller sample but an UNREPRESENTATIVE one, and it
produced a false comparison the first time it mattered: the surviving PRE artifact was a
degenerate run whose evidence included German tea shelf-life pages for a question about the Iron
Age Near East, and it was about to be compared against the LARGEST run of the POST arm.
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "benchmark"))

from lib import spectrum as SP  # noqa: E402


def test_every_run_is_retained_not_just_the_last(tmp_path, monkeypatch):
    monkeypatch.setenv("BENCH_ARTIFACT_DIR", str(tmp_path))
    SP._RETAIN_SEQ.clear()
    for body in ("first answer", "second answer", "third answer"):
        SP.retain("S9_x", body, tag="ARM")
    kept = SP.retained_runs("S9_x", tag="ARM", artifact_dir=str(tmp_path))
    assert kept == ["first answer", "second answer", "third answer"], \
        f"expected all 3 runs in order, got {kept}"


def test_arms_are_kept_separate(tmp_path, monkeypatch):
    monkeypatch.setenv("BENCH_ARTIFACT_DIR", str(tmp_path))
    SP._RETAIN_SEQ.clear()
    SP.retain("S9_x", "pre run", tag="PRE")
    SP.retain("S9_x", "post run", tag="POST")
    assert SP.retained_runs("S9_x", tag="PRE", artifact_dir=str(tmp_path)) == ["pre run"]
    assert SP.retained_runs("S9_x", tag="POST", artifact_dir=str(tmp_path)) == ["post run"]


def test_retain_is_a_noop_without_an_artifact_dir(monkeypatch):
    """Absence of the env var must not raise — the harness runs without artifacts in CI."""
    monkeypatch.delenv("BENCH_ARTIFACT_DIR", raising=False)
    assert SP.retain("S9_x", "body", tag="ARM") is None
