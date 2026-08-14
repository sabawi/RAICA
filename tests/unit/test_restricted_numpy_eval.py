"""SI-028 P2b — the restricted numpy evaluator, attacked.

A restricted-eval escape is a well-populated genre, so the design doc (P2b) pre-registered 12
attack vectors and required that each become a named test that FAILS on a permissive
implementation. That list is reproduced here one-for-one, plus the correctness cases from the
production failure that motivated the tool.

The bar being defended: nothing an LLM writes may read a file, import a module, reach an
interpreter internal, invoke a caller-supplied callable, or exhaust the worker.
"""
import sys
import time
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from utils.restricted_numpy_eval import (  # noqa: E402
    ALLOWED_NUMPY, MAX_ELEMENTS_PER_ARRAY, RestrictedEvalError, evaluate)

DATA = {"y30": [4.64, 4.20, 3.99], "y10": [3.97, 3.80, 3.81]}


def blocked(expr, data=None):
    """An expression must be REJECTED. Returns the message for inspection."""
    with pytest.raises(RestrictedEvalError) as ei:
        evaluate(expr, data if data is not None else DATA)
    return str(ei.value)


# ============================================================ the 12 pre-registered attack vectors

class TestEscapeVectors:

    def test_v1_dunder_traversal(self):
        """V1. The classic sandbox escape: walk from any object to the class hierarchy and pick a
        subclass that can open files or spawn processes."""
        blocked("().__class__.__bases__[0].__subclasses__()")
        blocked("y30.__class__")
        blocked("y30.__class__.__mro__")

    def test_v2_globals_reach_through_on_an_allowed_callable(self):
        """V2. np.min is permitted, so its __globals__ would hand back numpy's module namespace —
        and from there os, sys and builtins. Allow-listing the FUNCTION is not enough; the
        attribute rule has to stop the traversal.

        NOTE ON DISCRIMINATION: in numpy 2.3.2 the allowed functions are all
        `_ArrayFunctionDispatcher` objects with no `__globals__`, so THIS payload currently fails
        on a permissive evaluator too — by raising AttributeError, not by being blocked. It is
        kept as defence in depth (numpy has exposed plain functions before and may again), but the
        discriminating assertion is the chained-attribute one below, which IS reachable today:
        `y30.dtype` resolves fine under plain eval and must not resolve here."""
        blocked("np.min.__globals__")
        blocked("np.min.__globals__['__builtins__']")
        # reachable on a permissive build today -> this is what proves the rule is enforced
        blocked("y30.dtype")
        blocked("y30.data")

    def test_v3_getattr_vars_globals_eval_exec_by_name(self):
        """V3. Reaching the same places through builtins rather than attributes."""
        for expr in ("getattr(np, 'load')", "vars(np)", "globals()",
                     "eval('1+1')", "exec('x=1')", "__builtins__"):
            blocked(expr)

    def test_v4_import_smuggling(self):
        """V4. __import__ is a builtin, so an empty __builtins__ is the control — but the name
        rule must reject it before evaluation regardless."""
        blocked("__import__('os')")
        blocked("__import__('os').system('id')")

    def test_v5_file_access_and_pickle_execution(self):
        """V5. np.load executes pickles, which is arbitrary code execution with a file path as the
        only prerequisite. This is exactly why the numpy list is an ALLOW-list."""
        blocked("open('/etc/passwd')")
        blocked("np.load('/tmp/x.npy')")
        blocked("np.loadtxt('/etc/passwd')")
        blocked("np.fromfile('/etc/passwd')")
        assert "load" not in ALLOWED_NUMPY
        assert "fromfile" not in ALLOWED_NUMPY

    def test_v6_callable_injection(self):
        """V6. numpy functions that TAKE a callable would let an attacker supply the code to run."""
        blocked("np.vectorize(len)(y30)")
        blocked("np.apply_along_axis(min, 0, y30)")
        blocked("np.fromfunction(lambda i: i, (3,))")
        for name in ("vectorize", "apply_along_axis", "fromfunction", "piecewise"):
            assert name not in ALLOWED_NUMPY

    def test_v7_comprehension_generator_lambda(self):
        """V7. Any construct that introduces a new scope or defers execution."""
        blocked("[x for x in y30]")
        blocked("(x for x in y30)")
        blocked("np.min([x*2 for x in y30])")

    def test_v8_fstring_and_format(self):
        """V8. f-strings evaluate arbitrary expressions inside a string literal, which would slip
        straight past a validator that only inspects the outer nodes."""
        blocked("f'{y30}'")
        blocked("f'{().__class__}'")

    def test_v9_subscript_on_a_non_data_object(self):
        """V9. Indexing is needed for np.corrcoef(...)[0][1], but it must not become a path to
        objects other than the caller's data."""
        blocked("np.min.__globals__['os']")
        blocked("().__class__.__bases__[0]")

    def test_v10_resource_exhaustion(self):
        """V10. Two distinct shapes: allocate-by-size, and expand-small-input.

        The broadcast case is the subtle one — `y30[:, None] * y10` needs no function at all, so
        the function allow-list cannot see it. On 200k-element inputs that is a 4x10^10-element
        outer product: an OOM kill of the whole worker, not a slow query."""
        blocked("np.zeros(10**12)")
        blocked("np.arange(10**12)")
        blocked("np.ones(10**10)")
        blocked("y30[:, None] * y10")          # the broadcast bomb
        blocked("y30[:, np.newaxis] * y10")
        blocked("np.outer(y30, y10)")
        blocked("np.tile(y30, 10**9)")
        big = {"a": list(range(MAX_ELEMENTS_PER_ARRAY + 1))}
        assert "cap" in blocked("np.min(a)", big)

    def test_v11_name_shadowing_through_data(self):
        """V11. Binding `np` (or a dunder) through the data dict would let the caller replace the
        module the allow-list is written against."""
        assert "not be 'np'" in blocked("np.min(y30)", {"np": [1, 2, 3]})
        blocked("np.min(y30)", {"__builtins__": [1]})

    def test_v12_unicode_homoglyph_attribute_names(self, tmp_path):
        """V12. Python NFKC-normalises identifiers at PARSE time, so a lookalike spelling can
        resolve to a forbidden attribute while reading as something else in the source.

        The vector has to be chosen with care: Cyrillic 'а' does NOT normalise to Latin 'a', so
        `np.loаd` is merely a nonexistent attribute and would fail on ANY implementation — a test
        that proves nothing. Mathematical-bold and fullwidth forms DO normalise to `load`, so on a
        permissive evaluator they reach the real np.load (pickle execution). Here they arrive at
        the validator already normalised and are caught by the allow-list.
        A REAL file is written first, deliberately: pointing the attack at a missing path makes it
        fail with FileNotFoundError on a permissive build too, which would once again be a test
        that passes for the wrong reason. With the file present, plain eval genuinely succeeds —
        so only a real fence makes these expressions fail.
        """
        assert "\U0001d425\U0001d428\U0001d41a\U0001d41d".isidentifier()
        target = tmp_path / "payload.npy"
        np.save(target, np.array([1.0, 2.0, 3.0]))
        p = str(target)
        assert np.load(p) is not None          # the escape genuinely works when unguarded

        blocked(f"np.\U0001d425\U0001d428\U0001d41a\U0001d41d('{p}')")   # math-bold 'load'
        blocked(f"np.ｌｏａｄ('{p}')")                                      # fullwidth 'load'
        blocked(f"np.load('{p}')")
        blocked(f"np.loаd('{p}')")   # Cyrillic 'а' — nonexistent either way, kept for the record


# ============================================================ the fence's own rules

class TestFenceRules:

    def test_only_np_attribute_access(self):
        blocked("y30.min()")            # method call on data, not np.<fn>
        blocked("np.random.rand(3)")    # chained attribute

    def test_call_target_must_be_an_np_attribute(self):
        """A call target must be an `np.<fn>` attribute — never a bare name, never a subscript
        result, never another call's return value.

        `(np.min)(y30)` is deliberately NOT in this list: parentheses are syntactic only and it
        parses to a byte-identical AST to `np.min(y30)`, so rejecting it would be a rule the
        validator cannot actually express. Asserted as ALLOWED below so the distinction is
        recorded rather than rediscovered."""
        blocked("min(y30)")
        blocked("np.corrcoef(y30, y10)[0](y30)")
        assert evaluate("(np.min)(y30)", DATA) == pytest.approx(3.99)

    def test_unknown_names_rejected_with_a_helpful_message(self):
        msg = blocked("np.min(y99)")
        assert "y99" in msg and "y30" in msg   # names the caller's actual keys

    def test_builtins_are_empty_at_eval_time(self):
        """Layer 4 is the backstop if a node ever slips past layer 1."""
        blocked("len(y30)")
        blocked("sum(y30)")

    def test_expression_length_is_capped(self):
        assert "characters" in blocked("np.min(y30) + " * 200 + "0")

    def test_arithmetic_on_a_text_column_fails_cleanly(self):
        """PREMISE CHANGED 2026-08-14 (see TestTextSeries). This asserted that non-numeric data was
        REJECTED — correct when compute was numbers-only, and wrong now: a text column is
        legitimate input, because `place[np.argmax(mag)]` is how you name the row an extremum is
        in. What must still hold is that ARITHMETIC over text fails as a clean rejection rather
        than a traceback."""
        msg = blocked("np.mean(a) + 1", {"a": ["x", "y"]})
        assert "evaluation failed" in msg or "could not be read" in msg

    def test_evaluation_errors_do_not_crash(self):
        """A numpy error is the caller's problem and must surface as a rejection, not a traceback."""
        assert "evaluation failed" in blocked("np.corrcoef(y30, y10)[5][5]")


# ============================================================ it must still do the job

class TestCorrectness:
    """The reason the tool exists: derived values were wrong in production."""

    # The real 2026-08-11 series that produced the wrong answer.
    Y30 = [4.64, 4.55, 4.40, 4.22, 4.10, 4.66, 4.71, 4.80]
    Y10 = [3.97, 3.95, 3.90, 3.80, 3.92, 4.10, 4.15, 4.11]
    REAL = {"y30": Y30, "y10": Y10}

    def test_reproduces_the_true_minimum_spread(self):
        """The production answer said the minimum 30Y-10Y spread was +0.19 while quoting two
        yields that give +0.67. Arithmetic, not the model, decides this."""
        got = evaluate("np.min(np.array(y30) - np.array(y10))", self.REAL)
        assert got == pytest.approx(min(a - b for a, b in zip(self.Y30, self.Y10)))

    def test_reproduces_the_true_maximum_spread(self):
        got = evaluate("np.max(np.array(y30) - np.array(y10))", self.REAL)
        assert got == pytest.approx(max(a - b for a, b in zip(self.Y30, self.Y10)))

    def test_elementwise_arithmetic_on_two_series(self):
        out = evaluate("y30 - y10", self.REAL)
        assert np.allclose(out, np.array(self.Y30) - np.array(self.Y10))

    def test_correlation_with_indexing(self):
        """np.corrcoef(...)[0][1] is the documented idiom, so subscripting must still work."""
        got = evaluate("np.corrcoef(y30, y10)[0][1]", self.REAL)
        assert got == pytest.approx(float(np.corrcoef(self.Y30, self.Y10)[0][1]))

    def test_percentile_and_nan_aware_variants(self):
        assert evaluate("np.percentile(y30, 50)", self.REAL) == pytest.approx(
            float(np.percentile(self.Y30, 50)))
        gappy = {"a": [1.0, float("nan"), 3.0]}
        assert evaluate("np.nanmean(a)", gappy) == pytest.approx(2.0)

    def test_keyword_arguments_are_permitted(self):
        assert evaluate("np.round(np.mean(y30), 2)", self.REAL) == pytest.approx(
            round(float(np.mean(self.Y30)), 2))

    def test_diff_and_cumulative_series(self):
        assert np.allclose(evaluate("np.diff(y30)", self.REAL), np.diff(self.Y30))

    def test_a_legitimate_expression_is_fast(self):
        """The caps must not make ordinary work slow: a full-size series is the normal case."""
        big = {"a": list(np.linspace(0, 1, 100_000))}
        t0 = time.time()
        evaluate("np.std(a)", big)
        assert time.time() - t0 < 2.0


class TestGapMaskingIdioms:
    """FOUND ON PRODUCTION 2026-08-14. `compute` failed intermittently with

        Expression rejected: Invert is not permitted in a compute expression

    `Invert` is `~`. Real referenced series contain gaps (a missing observation stays None), and
    `np.min(s[~np.isnan(s)])` is THE numpy idiom for an extremum that skips them. Rejecting it made
    compute fail on precisely the expressions a careful caller writes — and the model then fell
    back to reading the table by eye, reporting a minimum of 0.10 beside quoted values giving 0.52.

    Simple expressions passed, masking ones did not, which is why the failure looked random.
    """
    S = {"s": [1.0, float("nan"), 3.0, 2.0]}

    def test_tilde_mask_over_a_series_with_gaps(self):
        assert evaluate("np.min(s[~np.isnan(s)])", self.S) == pytest.approx(1.0)
        assert evaluate("np.max(s[~np.isnan(s)])", self.S) == pytest.approx(3.0)

    def test_combined_masks(self):
        assert evaluate("np.max(s[(~np.isnan(s)) & (s < 3)])", self.S) == pytest.approx(2.0)
        assert evaluate("np.min(s[(s > 1) | (s < 0)])", self.S) == pytest.approx(2.0)

    def test_masking_does_not_reopen_the_fence(self):
        """The operators are pure value operations — they must not become a path to attributes,
        calls or names that the allow-lists forbid."""
        blocked("~y30.__class__")
        blocked("np.min(s[~np.isnan(s)]).__class__", {"s": [1.0, 2.0]})
        blocked("s[~np.isnan(s)] & open('/etc/passwd')", {"s": [1.0, 2.0]})


class TestTextSeries:
    """FOUND ON PRODUCTION 2026-08-14 by the USGS earthquake prompt, which asked for the place and
    date of the largest event. The model wrote exactly the right expressions —

        place[np.argmax(mag)]        time[np.argmax(mag)]        np.size(mag)

    — and compute rejected all of them:

        data['place'] is not numeric: could not convert string to float: '226 km ...'   (x12)
        data['time']  is not numeric: could not convert string to float: '2026-...'     (x12)
        np.size is not in the allowed function list                                     (x5)

    A tool built to stop the model eyeballing a table could not answer "which row holds the
    extremum", so the model went back to eyeballing and reported the wrong place and depth.
    """
    D = {"mag": [5.5, 7.8, 6.1], "place": ["Chile", "Philippines", "Japan"],
         "time": ["2026-01-02", "2026-06-07", "2026-03-01"]}

    def test_a_text_column_can_be_indexed_by_an_extremum(self):
        assert evaluate("place[np.argmax(mag)]", self.D) == "Philippines"
        assert evaluate("time[np.argmax(mag)]", self.D) == "2026-06-07"

    def test_np_size_answers_how_many_rows(self):
        assert evaluate("np.size(mag)", self.D) == 3

    def test_numeric_columns_are_still_numeric(self):
        """Coercion is tried FIRST, so arithmetic is unaffected — only genuinely non-numeric
        columns arrive as text."""
        assert evaluate("np.max(mag)", self.D) == pytest.approx(7.8)
        assert evaluate("np.count_nonzero(mag >= 7.0)", self.D) == 1

    def test_text_series_do_not_reopen_the_fence(self):
        blocked("place.__class__", self.D)
        blocked("np.load(place[0])", self.D)


class TestRejectionsAreActionable:
    """A refusal the caller cannot act on wastes the call. Production showed the model writing
    `len(mag)` to count rows and getting only "only `np.<function>(...)` calls are permitted" —
    true, but it never says what to write instead. The run survived only because the model
    happened to also call np.size(mag); a single-figure question would have had no such cushion.

    The bare-name rule itself is unchanged — it is what stops open(), getattr() and __import__().
    """

    def test_len_points_at_np_size(self):
        msg = blocked("len(mag)", {"mag": [1.0, 2.0, 3.0]})
        assert "np.size" in msg and "len" in msg

    def test_a_builtin_sharing_a_numpy_name_points_at_itself(self):
        for name in ("sum", "min", "max", "abs", "round"):
            msg = blocked(f"{name}(mag)", {"mag": [1.0, 2.0]})
            assert f"np.{name}" in msg, msg

    def test_an_unavailable_name_says_so(self):
        msg = blocked("exec('x=1')", {"mag": [1.0, 2.0]})
        assert "exec" in msg

    def test_the_rule_still_rejects_every_bare_call(self):
        """The hint must not become a loophole."""
        for expr in ("len(mag)", "open('/etc/passwd')", "getattr(np,'load')", "eval('1')"):
            blocked(expr, {"mag": [1.0, 2.0]})
