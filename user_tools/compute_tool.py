"""`compute` — arithmetic over retrieved data (SI-028 P2b).

Derived figures must be CALCULATED, not read off a table. The production failure that motivated
this tool quoted two Treasury yields correctly and then reported their minimum spread as +0.19
when the two quoted numbers give +0.67 — self-refuting on its face. The model was eyeballing
extrema over 401 rows.

The value of this tool is as much PROVENANCE as correctness: because the expression is returned
alongside the number, an answer can say "minimum spread, computed as `np.min(y30 - y10)`, = 0.18
over n=401" — auditable in a way "the model read the table" never is.

The security fence lives in utils/restricted_numpy_eval.py; read the module docstring there before
changing anything here. This wrapper adds the one layer the evaluator deliberately delegates: a
WALL-CLOCK timeout, since a permitted expression over permitted data can still be slow and no
amount of AST validation can predict that.
"""

import asyncio
import json
import logging
from typing import Any, Dict

import numpy as np

try:
    from .base_user_tool import BaseUserTool
except ImportError:
    from base_user_tool import BaseUserTool

try:
    from utils.restricted_numpy_eval import RestrictedEvalError, evaluate
except ImportError:  # tool loaded outside the server process
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from utils.restricted_numpy_eval import RestrictedEvalError, evaluate

logger = logging.getLogger(__name__)

# Layer 6 of the fence. A validated expression can still be slow (a large permitted reduction, a
# pathological but legal broadcast within the element caps), and a timeout is the only defence
# that does not require predicting intermediate sizes.
_TIMEOUT_SECONDS = 5.0

# An expression may legitimately return a SERIES (np.diff, y30 - y10). Returning 200k numbers into
# an LLM context would be its own denial of service, so long results are summarised and the
# truncation is DISCLOSED rather than silently applied (SI-027's lesson).
_MAX_RETURNED_ELEMENTS = 200

# Expressions per call when `expr` is a list. Enough for a full descriptive-statistics
# request (n, mean, median, std, min, max, percentiles) without becoming a batch job.
_MAX_EXPRESSIONS = 12



# FAIL-CLOSED NOTICE (SI-036). Appended to EVERY compute failure.
#
# Production, 2026-08-14: a single-figure request ("the average 10-year yield in 2025") called
# compute once; it was rejected 4/4 (comprehension). No result ever existed — the log shows zero
# "over n=... data point" strings. The answer nonetheless stated "4.30% ... computed as the
# arithmetic mean of all available daily DGS10 observations", which was RIGHT BY LUCK and
# indistinguishable from a grounded figure.
#
# The standing directive already forbade exactly this ("NEVER CLAIM A CALCULATION YOU DID NOT
# PERFORM", NewX v1.0.0.178) and was ignored. A general system-prompt rule is evidently too far
# from the moment of failure, so the prohibition now travels WITH the failure, inside the tool
# result the model actually reads. Multi-figure requests hid the problem because 3-12 compute calls
# meant some other attempt usually succeeded; with a single figure there is no cushion.
_FAIL_CLOSED = (
    "\n\nNO FIGURE WAS CALCULATED. You do NOT have a computed value for this quantity. You are "
    "therefore FORBIDDEN to state it \u2014 do not report the mean, minimum, maximum, total, "
    "correlation or any other derived number this call was for, and do not write \"computed as\", "
    "an expression, or an observation count for it. Say plainly that the calculation could not be "
    "completed, and why. If you can correct the expression, call compute again instead."
)


# The parameters `compute` actually declares. Anything else arriving at the top level is a
# misplaced argument, not a setting (SI-069).
_DECLARED_PARAMS = ("expr", "data", "label")


def _rewrite_builtin_calls(expr):
    """Rewrite `len(x)` -> `np.size(x)` and `sorted(x)` -> `np.sort(x)` (SI-069).

    The evaluator permits only `np.<function>(...)` calls and already names these equivalences
    in its own `_BUILTIN_TO_NUMPY` table — it just reports them as an error instead of applying
    them. The model writes the natural spelling repeatedly and pays a round-trip each time.

    Purely syntactic, done on the AST so it cannot corrupt a string literal or a name that
    merely CONTAINS "len". The fence still validates the rewritten expression, so nothing is
    relaxed: an expression that was unsafe before is still rejected after.

    Accepts a str or a list of str (the SI-067 batch form) and returns the same shape.
    """
    import ast

    _MAP = {"len": "size", "sorted": "sort"}

    class _Rewriter(ast.NodeTransformer):
        def visit_Call(self, node):
            self.generic_visit(node)
            if isinstance(node.func, ast.Name) and node.func.id in _MAP:
                node.func = ast.Attribute(value=ast.Name(id="np", ctx=ast.Load()),
                                          attr=_MAP[node.func.id], ctx=ast.Load())
            return node

    def _one(e):
        if not isinstance(e, str) or not e.strip():
            return e
        try:
            tree = ast.parse(e, mode="eval")
        except SyntaxError:
            return e                      # let the evaluator report it
        if not any(isinstance(n, ast.Name) and n.id in _MAP for n in ast.walk(tree)):
            return e                      # nothing to do — leave the text byte-identical
        try:
            return ast.unparse(_Rewriter().visit(tree))
        except Exception:                 # noqa: BLE001 — never let a rewrite break a call
            return e

    if isinstance(expr, (list, tuple)):
        return [_one(e) for e in expr]
    return _one(expr)


def _looks_like_multiple_statements(expr: str) -> bool:
    """True when `expr` is a SCRIPT rather than a single expression (SI-067).

    Detected structurally by asking Python, not by pattern-matching text: if it fails to parse
    in `eval` mode but parses in `exec` mode, it is statements. That covers assignments,
    semicolon chains and newlines without enumerating their spellings, and it cannot
    misclassify a valid expression — a valid expression always parses in eval mode.
    """
    import ast
    if not isinstance(expr, str) or not expr.strip():
        return False
    try:
        ast.parse(expr, mode="eval")
        return False                      # a genuine single expression
    except SyntaxError:
        pass
    try:
        ast.parse(expr, mode="exec")
        return True                       # parses as statements -> it is a script
    except SyntaxError:
        return False                      # simply invalid; let the evaluator report it


class ComputeTool(BaseUserTool):
    """Evaluate a numpy expression over caller-supplied numeric series."""

    @property
    def name(self) -> str:
        return "compute"

    @property
    def description(self) -> str:
        return (
            "Calculate a numeric result from data you have already retrieved — minimum, maximum, "
            "mean, median, percentile, correlation, spread, difference, growth rate, cumulative "
            "sum, standard deviation, or any arithmetic combination of series. Use this for EVERY "
            "derived figure instead of reading values off a table: reading a long table is "
            "unreliable, and this returns the exact result together with the expression that "
            "produced it, so the calculation can be cited. Supply the series as `data` and a numpy "
            "expression as `expr` (e.g. \"np.min(y30 - y10)\" or "
            "\"np.corrcoef(revenue, spend)[0][1]\"). Only pure-maths numpy functions are available."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "expr": {
                    "description": (
                        "A numpy expression over the names in `data`. Examples: "
                        "\"np.min(y30 - y10)\", \"np.max(prices)\", \"np.mean(np.diff(gdp))\", "
                        "\"np.corrcoef(a, b)[0][1]\", \"np.percentile(x, 90)\". "
                        "Use `np.` for functions; refer to series by their key in `data`. "
                        "ONE EXPRESSION ONLY — assignments and `;` are not evaluated. For several "
                        "figures over the same data, pass a LIST and each is computed separately "
                        "in a single call: [\"len(mag)\", \"np.mean(mag)\", \"np.median(mag)\", "
                        "\"np.std(mag, ddof=1)\"]."
                    ),
                },
                "data": {
                    "type": "object",
                    "description": (
                        "Named numeric series. Each value is EITHER a list of numbers, e.g. "
                        "{\"y30\": [4.64, 4.55, ...]}, OR — for data another tool already "
                        "fetched — a reference to that output and a column, e.g. "
                        "{\"y30\": {\"from\": \"lookup_website#1\", \"column\": \"30 Yr\"}}. "
                        "`from` may be a LIST to span several outputs — "
                        "{\"from\": [\"lookup_website#1\", \"lookup_website#2\"]} — which is how "
                        "you cover a period split across files. "
                        "PREFER THE REFERENCE for anything longer than a few points: retyping a "
                        "table does not fit in one reply and risks transcription errors. Keys must "
                        "be valid identifiers and are the names usable in `expr`."
                    ),
                },
                "label": {
                    "type": "string",
                    "description": (
                        "What this quantity is, in plain words (e.g. \"minimum 30Y-10Y spread\"). "
                        "Returned verbatim so the answer can state what was computed."
                    ),
                },
            },
            "required": ["expr", "data"],
        }

    async def execute(self, **kwargs) -> Dict[str, Any]:
        # SI-036: a data reference that could not be resolved fails the call HERE, with the real
        # reason, rather than reaching the evaluator as a raw dict and surfacing as a confusing
        # type error.
        if kwargs.get("_reference_error"):
            return {"success": False,
                    "error": f"compute: could not use the referenced data — "
                             f"{kwargs['_reference_error']}{_FAIL_CLOSED}"}
        expr = kwargs.get("expr")
        data = kwargs.get("data")
        label = kwargs.get("label") or ""

        # SI-067 belt-and-braces: the upstream resolver now decodes JSON-string arguments, but
        # `compute` is also reachable on paths that never pass through it. A string here is
        # unambiguous — decode it rather than rejecting a call the model got right.
        if isinstance(data, str):
            try:
                _decoded = json.loads(data)
                if isinstance(_decoded, dict):
                    data = _decoded
            except (json.JSONDecodeError, TypeError, ValueError):
                pass

        # SI-069: the series passed as TOP-LEVEL arguments instead of inside `data`.
        #
        # Measured on production 2026-08-17, after SI-067 shipped — 30 calls, all rejected:
        #     {'expr': 'np.percentile(mags, 90)',
        #      'mags': '{"from": "lookup_website#1", "column": "mag"}'}
        #                ^ the series, named after itself, at the top level
        # `data` is then absent entirely, so the call dies on "`data` must be a non-empty
        # object mapping names to arrays" — reported to the user as "the data object was not
        # properly formed".
        #
        # A natural mistake: the model treats the series NAME as the parameter name, and the
        # name it chose is the one its own `expr` refers to. The information is all there and
        # unambiguous; only its position is wrong.
        #
        # Structural, not interpretive: `expr`/`data`/`label` are the declared parameters, so
        # ANY other top-level argument carrying a numeric series is one the model meant to put
        # in `data`. Values that are not series are left alone, and an explicit `data` always
        # wins — this only fills a gap, never overrides.
        if not data:
            _strays = {k: v for k, v in kwargs.items()
                       if k not in _DECLARED_PARAMS and not k.startswith("_")
                       and isinstance(v, (list, tuple)) and len(v) > 0}
            if _strays:
                logger.info("compute: %d series passed as top-level argument(s) %s — treating "
                            "them as `data` (SI-069)", len(_strays), sorted(_strays))
                data = {k: list(v) for k, v in _strays.items()}

        # SI-069 (2): `len(x)` rewritten to `np.size(x)`. The evaluator's fence permits only
        # `np.<function>(...)` calls and already tells the model to write `np.size` — but the
        # model keeps writing `len`, which is the natural spelling, and every occurrence costs
        # a whole round-trip. The equivalence is already declared in the evaluator's own
        # _BUILTIN_TO_NUMPY table, so applying it here is mechanical, not interpretive. The
        # fence still validates whatever comes out; nothing is relaxed.
        expr = _rewrite_builtin_calls(expr)

        # SI-067 (2): a BARE reference where a mapping belongs. The model sent
        #     data = {"from": "lookup_website#1", "column": "mag"}
        # instead of {"mag": {...}}. Say exactly what to send rather than guessing a name —
        # inventing one would silently bind the series to a name `expr` does not use, and the
        # model would get a confusing "name not defined" instead of the real problem.
        if isinstance(data, dict) and "from" in data and not any(
                isinstance(v, (list, tuple, dict)) for v in data.values()):
            _col = data.get("column") or "series"
            return {"success": False,
                    "error": (f"`data` must MAP A NAME to each series, and the reference goes "
                              f"inside. You sent the reference itself. Use: "
                              f'{{"{_col}": {json.dumps(data)}}} — then refer to it in `expr` '
                              f'as `{_col}`.{_FAIL_CLOSED}')}

        # SI-067 (3): several statistics in ONE call. The model tried
        #     "n = len(mag); mean_mag = np.mean(mag); std_mag = np.std(mag, ddof=1); ..."
        # because the request asked for four figures at once. That is a script, not an
        # expression: ast.parse(mode="eval") rejects it and it also blows the character cap.
        # Accepting a LIST of expressions turns four round-trips into one and removes the
        # incentive to write a script.
        if isinstance(expr, (list, tuple)):
            return await self._evaluate_many(list(expr), data, label)
        if isinstance(expr, str) and _looks_like_multiple_statements(expr):
            return {"success": False,
                    "error": ("`expr` is ONE expression, not a script — assignments and `;` are "
                              "not evaluated. For several figures, pass a LIST and each is "
                              'computed separately, e.g. `"expr": ["len(mag)", "np.mean(mag)", '
                              '"np.median(mag)", "np.std(mag, ddof=1)"]`.'
                              f"{_FAIL_CLOSED}")}

        try:
            # The evaluator is synchronous and CPU-bound; a thread keeps the event loop responsive
            # and gives the timeout something it can actually interrupt waiting on.
            raw = await asyncio.wait_for(
                asyncio.to_thread(evaluate, expr, data), timeout=_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            logger.warning(f"compute: expression exceeded {_TIMEOUT_SECONDS}s: {str(expr)[:120]}")
            return {"success": False,
                    "error": f"Expression took longer than {_TIMEOUT_SECONDS}s and was stopped. "
                             f"Try a simpler expression or fewer data points.{_FAIL_CLOSED}"}
        except RestrictedEvalError as e:
            # Rejections are EXPECTED traffic, not incidents: the model gets a precise reason so it
            # can correct itself, and the reason never leaks internals.
            return {"success": False, "error": f"Expression rejected: {e}{_FAIL_CLOSED}"}
        except Exception as e:  # noqa: BLE001
            logger.error(f"compute: unexpected failure: {type(e).__name__}: {e}")
            return {"success": False, "error": f"Computation failed: {type(e).__name__}: {e}{_FAIL_CLOSED}"}

        # Several numpy functions return a TUPLE of arrays, and those arrays need not be the
        # same length — np.histogram gives (counts, edges) with edges one longer. np.asarray on
        # that raises "setting an array element with a sequence ... inhomogeneous shape", which
        # surfaced as an opaque tool crash the first time the model wrote a bare
        # np.histogram(mag, bins=15). Say which piece to take rather than guessing: choosing one
        # for the caller would silently chart the wrong series.
        if isinstance(raw, tuple):
            parts = ", ".join(f"[{i}] length {np.asarray(p).size}" for i, p in enumerate(raw))
            return {"success": False,
                    "error": (f"`{expr}` returned {len(raw)} separate arrays ({parts}), not one "
                              f"series. Index the one you need — e.g. `{expr}[0]` — and call again "
                              f"for the other if you need both.{_FAIL_CLOSED}")}
        return {"success": True, "result": self._format(raw, expr, data, label)}

    @staticmethod
    def _n_of(data: Dict[str, Any]) -> int:
        try:
            return max(int(np.asarray(v).size) for v in data.values())
        except Exception:  # noqa: BLE001
            return 0

    async def _evaluate_many(self, exprs, data, label) -> Dict[str, Any]:
        """Evaluate several expressions over the SAME data in one call (SI-067).

        The request that exposed this asked for sample size, mean, median and standard
        deviation at once. With one expression per call the model wrote a script instead —
        rejected as a syntax error and over the character cap — and then kept retrying. Four
        figures should cost one round-trip, not four.

        Each expression is evaluated INDEPENDENTLY: one bad expression reports its own error
        and the others still return their values. Failing the whole batch would reproduce the
        all-or-nothing behaviour this fix exists to remove.
        """
        if not exprs:
            return {"success": False,
                    "error": f"`expr` was an empty list — nothing to compute.{_FAIL_CLOSED}"}
        if len(exprs) > _MAX_EXPRESSIONS:
            return {"success": False,
                    "error": (f"{len(exprs)} expressions requested; the limit is "
                              f"{_MAX_EXPRESSIONS} per call. Split them across calls."
                              f"{_FAIL_CLOSED}")}
        lines, ok_count = [], 0
        for one in exprs:
            if not isinstance(one, str) or not one.strip():
                lines.append(f"- (skipped a non-string entry: {one!r})")
                continue
            try:
                raw = await asyncio.wait_for(
                    asyncio.to_thread(evaluate, one, data), timeout=_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                lines.append(f"- `{one}` -> took longer than {_TIMEOUT_SECONDS}s and was stopped")
                continue
            except RestrictedEvalError as e:
                lines.append(f"- `{one}` -> rejected: {e}")
                continue
            except Exception as e:  # noqa: BLE001
                lines.append(f"- `{one}` -> failed: {type(e).__name__}: {e}")
                continue
            if isinstance(raw, tuple):
                lines.append(f"- `{one}` -> returned {len(raw)} arrays, not one series; "
                             f"index the one you need e.g. `{one}[0]`")
                continue
            lines.append("- " + self._format(raw, one, data, ""))
            ok_count += 1
        head = f"{label}:\n" if label else ""
        body = head + "\n".join(lines)
        if ok_count == 0:
            return {"success": False, "error": f"No expression produced a value.\n{body}{_FAIL_CLOSED}"}
        if ok_count < len(exprs):
            body += ("\n\nNOTE: the entries above marked rejected/failed produced NO figure — "
                     "you are forbidden to state those quantities.")
        return {"success": True, "result": body}

    @classmethod
    def _format(cls, raw, expr, data, label) -> str:
        """Render the result so the ANSWER can cite the calculation, not just the number."""
        arr = np.asarray(raw)
        n = cls._n_of(data)
        head = f"{label}: " if label else ""

        if arr.ndim == 0:
            value = arr.item()
            shown = f"{value:.6g}" if isinstance(value, float) else str(value)
            body = f"{head}{shown}"
        else:
            flat = arr.ravel()
            if flat.size > _MAX_RETURNED_ELEMENTS:
                kept = np.array2string(flat[:_MAX_RETURNED_ELEMENTS], precision=6,
                                       separator=", ", threshold=_MAX_RETURNED_ELEMENTS + 1)
                body = (f"{head}{kept}\n"
                        f"[TRUNCATED: showing the first {_MAX_RETURNED_ELEMENTS} of "
                        f"{flat.size} values]")
            else:
                body = f"{head}{np.array2string(flat, precision=6, separator=', ', threshold=flat.size + 1)}"

        return (f"{body}\n"
                f"computed as: {expr}\n"
                f"over n={n} data point(s); inputs: {', '.join(sorted(data))}\n"
                f"dtype: {arr.dtype}\n"
                f"STATE THE EXPRESSION AND n ALONGSIDE THIS VALUE when you use it, and give an "
                f"extremum its date/label. The figure must be arithmetically consistent with any "
                f"values quoted beside it.")
