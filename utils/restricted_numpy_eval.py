"""Restricted numpy expression evaluator (SI-028 P2b).

WHY THIS EXISTS
---------------
A 2026-08-11 production answer fetched 401 real daily Treasury rows and then reported the minimum
30Y-10Y spread as +0.19 while quoting the two yields that produce +0.67, and named a maximum of
+0.53 when the true maximum is +0.69 — a year earlier. Every value it QUOTED was exact; only the
values it DERIVED were wrong. The model was eyeballing extrema over a 401-row table.

The alternative — a `series_stats` tool — would fix min/max and leave correlation, percentiles,
diffs, normalisation and rolling windows to be added one at a time, which is the per-case
proliferation the Generalization Directive forbids. So numpy is exposed and the LLM picks the
function.

WHAT THIS IS, AND IS NOT
------------------------
This is NOT sandboxed Python and NOT code execution. It is a restricted EXPRESSION LANGUAGE that
happens to use Python syntax: the AST is validated in full BEFORE anything is evaluated, and the
permitted node set is small enough to audit by eye. `sandboxed_executor` was explicitly rejected as
a substrate — it is a command whitelist over subprocess with no seccomp, no container and no
isolation boundary, so routing LLM-authored code through it on a user-facing path is real RCE
surface.

Defence in depth (docs/RAICA_GENERALIZED_EXTRACT_CHART.md P2b):
  1. AST allow-list      — validated before eval; everything not named is rejected
  2. Attribute rule      — `np.<name>` only, <name> in the function allow-list, no chaining, no dunder
  3. Name binding        — a Name must be `np` or a key of the caller's data dict
  4. Builtins            — eval runs with {"__builtins__": {}}
  5. numpy ALLOW-list    — pure math only, never a deny-list: numpy ships np.load (executes
                           pickles), np.frombuffer, np.vectorize (takes a callable), np.memmap
  6. Resource caps       — input size, and a wall-clock timeout enforced by the caller

The allow-list is an ALLOW-list on purpose. A deny-list would miss whatever numpy adds next.
"""

from __future__ import annotations

import ast
from typing import Any, Dict, Iterable

import numpy as np

__all__ = ["RestrictedEvalError", "evaluate", "ALLOWED_NUMPY", "MAX_ELEMENTS_PER_ARRAY",
           "MAX_TOTAL_ELEMENTS"]


class RestrictedEvalError(ValueError):
    """Raised when an expression is rejected. The message is safe to show a caller."""


# --------------------------------------------------------------------------- resource caps
# A 50k x 50k float64 broadcast is 20 GB, so caps are a memory-safety control, not tidiness.
MAX_ELEMENTS_PER_ARRAY = 200_000
MAX_TOTAL_ELEMENTS = 1_000_000
MAX_EXPR_CHARS = 500


# --------------------------------------------------------------------------- numpy allow-list
# PURE MATH OVER SUPPLIED DATA ONLY.
#
# Deliberately EXCLUDED, with reasons — do not add without re-reading these:
#   load, loadtxt, genfromtxt, save, savez, fromfile, frombuffer, memmap  -> I/O; np.load executes pickles
#   vectorize, apply_along_axis, apply_over_axes, fromfunction, piecewise -> take a CALLABLE
#   zeros, ones, full, empty, eye, identity, arange, linspace, logspace   -> allocate BY SIZE
#   repeat, tile, outer, meshgrid, kron                                   -> expand small input into a bomb
# Statistics over data the caller already supplied need none of them.
ALLOWED_NUMPY = frozenset({
    # reductions
    "min", "max", "mean", "median", "sum", "prod", "std", "var", "ptp",
    "percentile", "quantile", "argmin", "argmax", "average", "count_nonzero",
    # `np.size` was rejected on production while answering "how many events are in the file" —
    # a pure shape query with no I/O, no callable and no allocation. Same for the sort/select
    # helpers, which are how a caller reaches the row an extremum lives in.
    "size", "amin", "amax", "argsort", "take",
    # nan-aware equivalents (real series have gaps)
    "nanmin", "nanmax", "nanmean", "nanmedian", "nansum", "nanstd", "nanvar",
    "nanpercentile", "nanquantile", "nanargmin", "nanargmax",
    # elementwise maths
    "abs", "absolute", "sqrt", "exp", "log", "log2", "log10", "log1p", "expm1",
    "power", "square", "sign", "round", "floor", "ceil", "trunc", "clip",
    "maximum", "minimum", "mod", "remainder", "reciprocal",
    # trigonometry
    "sin", "cos", "tan", "arcsin", "arccos", "arctan", "arctan2",
    "sinh", "cosh", "tanh", "degrees", "radians",
    # series shape / ordering (no size arguments)
    "diff", "cumsum", "cumprod", "gradient", "sort", "unique", "flip",
    "concatenate", "ravel", "flatten", "transpose",
    # relationships
    "corrcoef", "cov", "dot", "inner", "cross",
    # selection / predicates
    "where", "isnan", "isfinite", "isinf", "isclose", "allclose",
    "any", "all", "nonzero", "searchsorted",
    # conversion
    "array", "asarray", "float64", "int64",
    # SIZE-TAKING, permitted with an argument bound (see _SIZE_TAKING below). Blocked outright
    # until v1.0.0.275, which cost a request 47 rejections and produced no chart: building the
    # x-axis of a fitted distribution curve is precisely what these are for. The memory concern is
    # real but is about the SIZE ARGUMENT, not the function.
    "linspace", "arange",
})

# Builtins whose numpy equivalent has a DIFFERENT name. Everything else that shares a name with an
# allowed numpy function maps to itself, so this stays two entries rather than a list to maintain.
# This is error-message help text only — it changes no decision, and the call is rejected either way.
_BUILTIN_TO_NUMPY = {"len": "size", "sorted": "sort"}

# --------------------------------------------------------------------------- AST allow-list
_ALLOWED_NODES = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Call, ast.Name, ast.Load,
    ast.Constant, ast.Attribute, ast.Subscript, ast.Slice, ast.Tuple, ast.List,
    ast.Compare, ast.keyword, ast.Index if hasattr(ast, "Index") else ast.Load,
    # operators
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
    ast.USub, ast.UAdd, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    # Boolean-array masking. `~`, `&` and `|` are how numpy skips gaps —
    # `np.min(s[~np.isnan(s)])` is THE idiom for an extremum over a series with missing
    # observations, and referenced real-world data has gaps. Rejecting `~` made `compute` fail on
    # exactly the expressions a careful caller writes, and the model then fell back to reading the
    # table by eye: a wrong minimum quoted beside values that contradict it. These are pure
    # value operators — they grant no attribute access, no calls and no names, so the fence
    # (attribute rule, name binding, empty builtins, numpy allow-list) is untouched.
    ast.Invert, ast.BitAnd, ast.BitOr, ast.BitXor,
)

# Everything below is REJECTED by omission, but these are named in the error message because they
# are the shapes an escape attempt actually takes (see the 12-vector checklist).
_NAMED_REJECTIONS = {
    ast.Lambda: "lambda", ast.ListComp: "comprehension", ast.SetComp: "comprehension",
    ast.DictComp: "comprehension", ast.GeneratorExp: "generator", ast.JoinedStr: "f-string",
    ast.FormattedValue: "f-string", ast.Starred: "starred argument", ast.Await: "await",
    ast.NamedExpr: "walrus assignment", ast.IfExp: "conditional expression",
    ast.Dict: "dict literal", ast.Set: "set literal", ast.BoolOp: "boolean operator",
}


# What to write INSTEAD, per rejected construct. Help text only — the construct stays rejected.
_REJECTION_HINTS = {
    "comprehension": " — numpy works on whole arrays, so you do not need one: missing values are "
                     "already parsed as gaps, so use `np.nanmean(x)` / `np.nanmin(x)`, or mask "
                     "with `x[~np.isnan(x)]`",
    "generator": " — use a whole-array numpy call such as `np.mean(x)` instead",
    "lambda": " — no callable can be passed; use a numpy function directly, e.g. `np.mean(x)`",
    "conditional expression": " — use `np.where(cond, a, b)`",
    "boolean operator": " — use `&` and `|` on arrays, e.g. `x[(x > 1) & (x < 5)]`",
}


# Functions whose arguments determine an allocation SIZE. Permitted, but any numeric literal they
# are given must stay under the element cap — `np.arange(10**12)` is 8 TB, `np.linspace(0, 1, 10**10)`
# likewise. A literal check catches the realistic case; the post-evaluation size check below catches
# what a computed argument slips through.
_SIZE_TAKING = frozenset({"linspace", "arange"})


def _static_value(node):
    """Value of a CONSTANT-ONLY subtree, or None.

    `np.arange(10**12)` is not a Constant — it is BinOp(10, Pow, 12) — so a literal-only check
    misses it and the call proceeds to allocate. Observed: `np.arange(0, 10**9)` allocated 8 GB
    before the post-evaluation size check rejected it, which is a denial of service that happens to
    report itself politely. Folding constant arithmetic at validation time stops it BEFORE numpy is
    reached. Only literals and arithmetic operators are folded — never a name, never a call — so
    this evaluates nothing the caller controls beyond numbers.
    """
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, (int, float)) else None
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        v = _static_value(node.operand)
        return None if v is None else (-v if isinstance(node.op, ast.USub) else v)
    if isinstance(node, ast.BinOp):
        a, b = _static_value(node.left), _static_value(node.right)
        if a is None or b is None:
            return None
        try:
            if isinstance(node.op, ast.Pow):
                if abs(a) > 1e6 or abs(b) > 64:      # refuse to fold an absurd power
                    return float("inf")
                return a ** b
            if isinstance(node.op, ast.Add):   return a + b
            if isinstance(node.op, ast.Sub):   return a - b
            if isinstance(node.op, ast.Mult):  return a * b
            if isinstance(node.op, ast.Div):   return a / b if b else None
        except (OverflowError, ZeroDivisionError, ValueError):
            return float("inf")
    return None


def _reject(msg: str):
    raise RestrictedEvalError(msg)


def _check_subscript_slice(node: ast.AST):
    """Reject `None` / `np.newaxis` inside a subscript.

    Vector 10 (pathological broadcast): the function allow-list cannot stop `y30[:, None] * y10`,
    which turns two 200k series into a 4x10^10-element outer product using nothing but permitted
    operators. Blocking the axis-insertion token is the targeted, auditable fix; the alternative
    (guessing intermediate sizes) is not.
    """
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and sub.value is None:
            _reject("`None` is not permitted inside an index (it would insert a broadcast axis)")
        if isinstance(sub, ast.Attribute) and sub.attr == "newaxis":
            _reject("`np.newaxis` is not permitted (it would insert a broadcast axis)")


def _validate(tree: ast.AST, data_names: Iterable[str]):
    allowed_names = set(data_names) | {"np"}

    for node in ast.walk(tree):
        for bad, label in _NAMED_REJECTIONS.items():
            if isinstance(node, bad):
                # Name the idiom that replaces it. Production: the model wrote
                # `np.mean([float(v) for v in dgs10 if v != '.'])` to skip FRED's '.' missing
                # markers, was told only "comprehension is not permitted", and gave up on the tool
                # — then asserted the figure anyway. numpy already handles gaps, so the rejection
                # only needed to say so.
                _reject(f"{label} is not permitted in a compute expression"
                        + (_REJECTION_HINTS.get(label, "")))

        if not isinstance(node, _ALLOWED_NODES):
            _reject(f"{type(node).__name__} is not permitted in a compute expression")

        # Layer 2 — attribute access is ONLY `np.<allowed>`; no chaining, no dunder, ever.
        if isinstance(node, ast.Attribute):
            if node.attr.startswith("_"):
                _reject("attribute names beginning with '_' are never permitted")
            if not isinstance(node.value, ast.Name) or node.value.id != "np":
                _reject("only `np.<function>` attribute access is permitted")
            if node.attr not in ALLOWED_NUMPY:
                _reject(f"np.{node.attr} is not in the allowed function list")

        # Layer 3 — every name is either `np` or caller-supplied data.
        if isinstance(node, ast.Name):
            if node.id not in allowed_names:
                _reject(f"unknown name '{node.id}' — expected `np` or one of: "
                        f"{sorted(set(data_names))}")

        # A call target must be an `np.<fn>` attribute — never a bare name, never a subscript
        # result, never the return value of another call.
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Attribute):
                # The rule stands — a bare-name call is how `open(...)`, `getattr(...)` and
                # `__import__(...)` would arrive, so it stays rejected. What changes is that the
                # refusal now names the form to use instead. Production showed the model writing
                # `len(mag)` to count rows and getting a message that told it only what was
                # forbidden; the run survived only because it happened to also call np.size.
                # A rejection the caller can act on is worth as much as the rejection itself —
                # the same reason the column-not-found error lists the available columns.
                called = getattr(node.func, "id", None)
                equiv = None
                if called:
                    # Generic: any builtin sharing a name with an allowed numpy function maps to
                    # itself. _BUILTIN_TO_NUMPY covers only the few whose numpy name differs.
                    equiv = _BUILTIN_TO_NUMPY.get(called) or (called if called in ALLOWED_NUMPY
                                                              else None)
                _reject("only `np.<function>(...)` calls are permitted"
                        + (f" — write `np.{equiv}(...)` instead of `{called}(...)`" if equiv
                           else f"; `{called}` is not available" if called else ""))

        if isinstance(node, ast.Subscript):
            _check_subscript_slice(node.slice)

        # Bound the size argument of an allocating call.
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in _SIZE_TAKING):
            for arg in list(node.args) + [k.value for k in (node.keywords or [])]:
                v = _static_value(arg)
                if v is not None and abs(v) > MAX_ELEMENTS_PER_ARRAY:
                    _reject(f"np.{node.func.attr} argument {v:g} exceeds the "
                            f"{MAX_ELEMENTS_PER_ARRAY} element cap")


def _prepare_data(data: Dict[str, Any]) -> Dict[str, np.ndarray]:
    if not isinstance(data, dict) or not data:
        raise RestrictedEvalError("`data` must be a non-empty object mapping names to arrays")

    total = 0
    prepared: Dict[str, np.ndarray] = {}
    for key, values in data.items():
        if not isinstance(key, str) or not key.isidentifier() or key == "np":
            raise RestrictedEvalError(
                f"data key {key!r} must be a valid identifier and must not be 'np'")
        try:
            arr = np.asarray(values, dtype=np.float64)
        except (TypeError, ValueError):
            # A TEXT series is legitimate input, not an error. `place[np.argmax(mag)]` — which row
            # holds the extremum — is exactly the question "where did the largest earthquake
            # occur", and rejecting it forced the model back to reading the table by eye, which is
            # what this tool exists to prevent. Numeric coercion is still tried first, so arithmetic
            # is unaffected; only genuinely non-numeric columns arrive as strings, where indexing
            # and comparison are all that is needed.
            try:
                arr = np.asarray(["" if v is None else str(v) for v in values])
            except (TypeError, ValueError) as e:
                raise RestrictedEvalError(f"data['{key}'] could not be read as numbers or text: "
                                          f"{e}") from e
        if arr.size > MAX_ELEMENTS_PER_ARRAY:
            raise RestrictedEvalError(
                f"data['{key}'] has {arr.size} elements, over the {MAX_ELEMENTS_PER_ARRAY} cap")
        total += arr.size
        if total > MAX_TOTAL_ELEMENTS:
            raise RestrictedEvalError(f"total input exceeds the {MAX_TOTAL_ELEMENTS} element cap")
        prepared[key] = arr
    return prepared


def evaluate(expr: str, data: Dict[str, Any]) -> Any:
    """Evaluate `expr` over `data` and return the raw numpy/scalar result.

    Raises RestrictedEvalError for anything rejected. The caller is responsible for the wall-clock
    timeout — a permitted expression over permitted data can still be slow, and a timeout is the
    only defence against that which does not require predicting intermediate sizes.
    """
    if not isinstance(expr, str) or not expr.strip():
        raise RestrictedEvalError("`expr` must be a non-empty string")
    if len(expr) > MAX_EXPR_CHARS:
        raise RestrictedEvalError(f"expression exceeds {MAX_EXPR_CHARS} characters")

    prepared = _prepare_data(data)

    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise RestrictedEvalError(f"could not parse expression: {e}") from e

    _validate(tree, prepared.keys())

    # Layer 4 — no builtins. `np` is the only non-data binding.
    env = {"__builtins__": {}}
    env.update(prepared)
    env["np"] = np

    try:
        result = eval(compile(tree, "<compute>", "eval"), env)  # noqa: S307 — validated above
        # Defence in depth: a computed size argument can evade the literal check above.
        size = getattr(result, "size", None)
        if isinstance(size, int) and size > MAX_ELEMENTS_PER_ARRAY:
            raise RestrictedEvalError(
                f"result has {size} elements, over the {MAX_ELEMENTS_PER_ARRAY} cap")
        return result
    except RestrictedEvalError:
        raise
    except Exception as e:  # noqa: BLE001 — numpy errors are the caller's problem, not a crash
        raise RestrictedEvalError(f"evaluation failed: {type(e).__name__}: {e}") from e
