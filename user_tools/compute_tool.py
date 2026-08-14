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
                    "type": "string",
                    "description": (
                        "A numpy expression over the names in `data`. Examples: "
                        "\"np.min(y30 - y10)\", \"np.max(prices)\", \"np.mean(np.diff(gdp))\", "
                        "\"np.corrcoef(a, b)[0][1]\", \"np.percentile(x, 90)\". "
                        "Use `np.` for functions; refer to series by their key in `data`."
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
                    "error": f"{'compute'}: could not use the referenced data — "
                             f"{kwargs['_reference_error']}"}
        expr = kwargs.get("expr")
        data = kwargs.get("data")
        label = kwargs.get("label") or ""

        try:
            # The evaluator is synchronous and CPU-bound; a thread keeps the event loop responsive
            # and gives the timeout something it can actually interrupt waiting on.
            raw = await asyncio.wait_for(
                asyncio.to_thread(evaluate, expr, data), timeout=_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            logger.warning(f"compute: expression exceeded {_TIMEOUT_SECONDS}s: {str(expr)[:120]}")
            return {"success": False,
                    "error": f"Expression took longer than {_TIMEOUT_SECONDS}s and was stopped. "
                             f"Try a simpler expression or fewer data points."}
        except RestrictedEvalError as e:
            # Rejections are EXPECTED traffic, not incidents: the model gets a precise reason so it
            # can correct itself, and the reason never leaks internals.
            return {"success": False, "error": f"Expression rejected: {e}"}
        except Exception as e:  # noqa: BLE001
            logger.error(f"compute: unexpected failure: {type(e).__name__}: {e}")
            return {"success": False, "error": f"Computation failed: {type(e).__name__}: {e}"}

        return {"success": True, "result": self._format(raw, expr, data, label)}

    @staticmethod
    def _n_of(data: Dict[str, Any]) -> int:
        try:
            return max(int(np.asarray(v).size) for v in data.values())
        except Exception:  # noqa: BLE001
            return 0

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
