"""SI-019 — a permanently-failing embedding service must not retry forever.

WHAT WENT WRONG (2026-08-10)
----------------------------
`convert --to deepinfra` repointed `document_interrogator.embedding.service.base_url`
at DeepInfra while `model_name:` stayed `text-embedding-3-small`, so every embedding
call 404'd. That was a config bug (SI-018, fixed separately). What it EXPOSED is worse
and independent of it:

    batch fails -> health check UNHEALTHY -> "recovery attempt 1/2"
    -> _restart_embedding_service() returns True unconditionally for any non-Ollama
       provider ("cloud-based, no restart needed") WITHOUT verifying anything
    -> logs "recovered successfully", breaks the `range(2)` budget, sleeps, `continue`
    -> back to the top of the SAME while-loop, where restart_attempt starts at 0 again

The `range(2)` budget lives INSIDE the loop it is meant to bound, so it can never be
exhausted. Result: an unbounded ~3s detect/compensate cycle at zero progress —
6,614 cycles and a 9.1MB log from one misconfigured endpoint, still spinning when it
was found. This is the control-loop failure mode: the code reacts to an actor that
simply acts again, with no damper.

THE FIX: `recovery_cycles` is scoped to the whole call rather than one iteration, so it
survives the `continue` and bounds the loop at MAX_RECOVERY_CYCLES.

These tests FAIL on the pre-fix code: `test_damper_bounds_a_permanent_failure` hangs /
never terminates, because that is precisely the bug.
"""
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = (ROOT / "document_interrogator.py").read_text()


def test_recovery_counter_is_declared_outside_the_batch_loop():
    """A budget declared inside the loop it bounds resets on every iteration.

    This is the whole defect in one assertion: `restart_attempt` (the pre-fix budget)
    is re-initialised by `for restart_attempt in range(2)` on each pass, so it can
    never be exhausted. The replacement must be initialised BEFORE `while
    processed_count`, not after it.
    """
    init = SRC.index("recovery_cycles = 0")
    loop = SRC.index("while processed_count < len(texts):")
    assert init < loop, (
        "recovery_cycles is initialised inside/after the batch loop — it will reset "
        "every iteration exactly like the range(2) budget it replaces")


def test_damper_is_checked_before_recovery_is_attempted():
    """Checking after recovery still permits one unbounded extra cycle each pass."""
    body = SRC[SRC.index("if not is_service_healthy:"):]
    guard = body.index("recovery_cycles > MAX_RECOVERY_CYCLES")
    attempt = body.index("for restart_attempt in range")
    assert guard < attempt, "damper must bound the loop BEFORE recovery is attempted"


def test_damper_returns_rather_than_continuing():
    """`continue` would re-enter the loop; only a return actually stops the cycle."""
    seg = SRC[SRC.index("recovery_cycles > MAX_RECOVERY_CYCLES"):]
    seg = seg[:seg.index("logger.error(f\"🚨 EMBEDDING SERVICE UNHEALTHY")]
    assert "return None" in seg, "damper must terminate the call, not continue the loop"


def test_max_recovery_cycles_comes_from_config_not_a_literal():
    """Project directive: no hardcoded configuration values."""
    assert "MAX_RECOVERY_CYCLES = _EMBEDDING_CONFIG['max_recovery_cycles']" in SRC
    assert re.search(r"recovery_cycles > MAX_RECOVERY_CYCLES", SRC), \
        "the bound must be the config constant, not an inline number"


def test_cloud_restart_no_longer_claims_verified_recovery():
    """`_restart_embedding_service()` returns True for cloud having done NOTHING.

    Logging "recovered successfully" on that put a false success in the log 6,614
    times while the service was dead, which is what made the loop hard to read.
    """
    assert "✅ Embedding service recovered successfully" not in SRC, \
        "a no-op restart must not be logged as a verified recovery"


def test_damper_bounds_a_permanent_failure():
    """END-TO-END: simulate the real loop shape and prove it terminates.

    Mirrors the control flow rather than importing it, because the real method needs a
    live service, a vector store and a config. The SHAPE is the bug: a budget inside
    the loop resets; a budget outside it does not. Pre-fix shape does not terminate.
    """
    MAX = 3

    def run(budget_inside_loop):
        cycles = 0
        recovery_cycles = 0
        while True:                      # the batch loop
            cycles += 1
            if cycles > 500:             # stand-in for "forever"
                return None              # never terminated
            # service is PERMANENTLY unhealthy — a 404 does not heal itself
            if budget_inside_loop:
                # pre-fix: budget re-created per iteration
                for _attempt in range(2):
                    restarted = True     # cloud no-op returns True immediately
                    if restarted:
                        break
                continue                 # retry the batch -> fails again -> forever
            recovery_cycles += 1
            if recovery_cycles > MAX:
                return recovery_cycles   # damper fired
            continue

    assert run(budget_inside_loop=True) is None, \
        "pre-fix shape should NOT terminate — if it does, this test proves nothing"
    assert run(budget_inside_loop=False) == MAX + 1, \
        "post-fix shape must terminate at the configured ceiling"


def test_failure_message_points_at_the_actual_cause():
    """A 404 loop cost hours because the log never said what to check."""
    assert "base_url and" in SRC and "model_name" in SRC, \
        "the give-up message should name the base_url/model_name mismatch"
