"""Reference prior tool output by NAME instead of re-transcribing it (SI-036 / SI-028).

THE MEASUREMENT THAT FORCED THIS
--------------------------------
`compute` and `plot_data` take their data as INLINE ARRAYS. On a real dataset — 404 daily Treasury
rows across several maturities — the model must emit thousands of numbers as tool arguments, and it
cannot:

    truncated=True  completion_tokens=4096 (= the cap)   tool_calls_returned=0   narrative=''

Raising the cap 8x to 32,768 changed nothing except latency (33s -> 439s): still truncated, still
zero parseable calls. So this is not a tuning problem. Re-transcribing a dataset into tool arguments
is not viable at any cap — and it was never desirable, because a transcribed series can be
transcribed WRONG, which defeats the point of computing instead of eyeballing.

THE MECHANISM
-------------
The model names a prior tool's output and the column it wants; RAICA substitutes the real values
before dispatch:

    {"from": "lookup_website#1", "column": "30 Yr"}   ->   [4.79, 4.83, 4.85, ...]

This mirrors the pattern already used for Deep Research papers (`{{RESEARCH_OUTPUT}}` /
`_dr_inject_research_output`): the LLM marks WHICH argument carries the content, and RAICA puts the
real thing there. Two consequences beyond fitting in the token budget — the numbers are the ones the
tool actually returned rather than a retyped copy, and the selector prompt shrinks to a schema
preview (columns, row count, a few sample rows) instead of the whole file.

Parsing a CSV column the model NAMED is data-format handling, not interpretation of meaning: the
model decides which column matters, this module only reads it.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

__all__ = ["ReferenceError_", "build_reference_index", "describe_reference",
           "resolve_references", "extract_column", "REFERENCE_HELP"]

# How many sample rows the selector is shown per referenced output. Enough to see the shape and the
# real column spellings; nowhere near enough to tempt transcription.
_PREVIEW_ROWS = 3
_MAX_CELLS = 200_000


class ReferenceError_(ValueError):
    """A reference could not be resolved. The message is safe to hand back to the model."""


REFERENCE_HELP = (
    "REFERENCING DATA YOU ALREADY FETCHED: do NOT retype rows of a table into these arguments — "
    "there are usually far too many and they will not fit. Instead, wherever a list of numbers is "
    "expected, pass a reference to the tool output and the column you want:\n"
    '  {"from": "<output id shown below>", "column": "<exact column name>"}\n'
    "RAICA substitutes the real values from that output before the tool runs, so the numbers are "
    "exactly what the source returned. Column names must match the header exactly as shown.\n"
    "COVER THE WHOLE PERIOD THE USER ASKED ABOUT: when the answer spans several fetched outputs "
    "(one file per year, say), list them all and they are joined in order:\n"
    '  {"from": ["lookup_website#1", "lookup_website#2"], "column": "30 Yr"}\n'
    "Computing over ONE file and describing the result as covering the full period is wrong even "
    "when the number happens to come out right."
)


def _strip_note(text: str) -> str:
    """Drop RAICA's own leading `[csv file: N lines retrieved …]` annotation before parsing."""
    if text.startswith("["):
        nl = text.find("\n")
        if 0 < nl < 400 and "retrieved" in text[:nl]:
            return text[nl + 1:]
    return text


def _locate_table(text: str) -> Tuple[str, str]:
    """Find the tabular REGION inside a tool result, returning (block_text, delimiter).

    A tool result is not a bare file. `lookup_website` wraps content in a formatted block — a
    dated preamble, separators, a source block — and parsing from line 0 made that preamble the
    header: the resolver reported columns like `'As of [Current Date and Time: Thursday'`, and
    every reference failed with "column '10 Yr' not found".

    The table is located STRUCTURALLY: the longest run of consecutive lines sharing the same field
    count under one delimiter. That is a property of the format, not of what the data means.
    """
    lines = (text or "").splitlines()
    best = (0, 0, 0, ",")                      # (length, start, end, delimiter)
    for delim in (",", "\t", ";", "|"):
        i = 0
        while i < len(lines):
            n = lines[i].count(delim)
            if n >= 1:
                j = i + 1
                while j < len(lines) and lines[j].count(delim) == n:
                    j += 1
                if (j - i) > best[0]:
                    best = (j - i, i, j, delim)
                i = max(j, i + 1)
            else:
                i += 1
    if best[0] < 3:                            # need a header and at least two rows
        return "", ","
    return "\n".join(lines[best[1]:best[2]]), best[3]


def _looks_tabular(text: str) -> bool:
    block, _ = _locate_table(_strip_note(text or ""))
    return bool(block)


def _parse_table(text: str) -> Tuple[List[str], List[List[str]]]:
    """Return (header, rows) for CSV/TSV content. Raises ReferenceError_ if it is not a table."""
    body, delim = _locate_table(_strip_note(text or ""))
    if not body:
        raise ReferenceError_("referenced output does not contain a table with a header and rows")
    reader = csv.reader(io.StringIO(body), delimiter=delim)
    rows = [r for r in reader if any((c or "").strip() for c in r)]
    if len(rows) < 2:
        raise ReferenceError_("referenced output does not contain a table with a header and rows")
    header = [(c or "").strip() for c in rows[0]]
    return header, rows[1:]


def _json_records(text: str) -> Optional[List[Dict[str, Any]]]:
    """A JSON array of objects is a table too; return it as records or None."""
    body = _strip_note(text or "").strip()
    if not body.startswith(("[", "{")):
        return None
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return None
    if isinstance(data, dict):
        for v in data.values():                       # a common {"results": [...]} envelope
            if isinstance(v, list) and v and isinstance(v[0], dict):
                data = v
                break
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data
    return None


def build_reference_index(results) -> Dict[str, str]:
    """Map a stable reference id to each prior tool output: {"lookup_website#1": "<text>", …}.

    Ids are per-tool and 1-based so two fetches by the same tool stay distinguishable — the Treasury
    request needs 2025 AND 2026, and collapsing them would silently answer over one year.
    """
    index: Dict[str, str] = {}
    counts: Dict[str, int] = {}
    for item in results or []:
        if not (isinstance(item, tuple) and len(item) >= 2):
            continue
        name = str(item[0])
        text = item[1] if isinstance(item[1], str) else str(item[1])
        counts[name] = counts.get(name, 0) + 1
        index[f"{name}#{counts[name]}"] = text
    return index


def describe_reference(ref_id: str, text: str, preview_rows: int = _PREVIEW_ROWS) -> str:
    """A compact, honest description of one output: what it is, how big, and its real column names.

    This replaces dumping the file into the selector prompt. The model needs the column SPELLINGS
    and the row count to choose correctly; it does not need — and cannot use — 20,000 characters of
    rows.
    """
    text = text or ""
    if _looks_tabular(text):
        try:
            header, rows = _parse_table(text)
            sample = "\n".join(", ".join(r[:len(header)]) for r in rows[:preview_rows])
            last = ", ".join(rows[-1][:len(header)]) if rows else ""
            return (f"=== {ref_id} === table, {len(rows)} data rows\n"
                    f"columns: {', '.join(repr(h) for h in header)}\n"
                    f"first rows:\n{sample}\n"
                    f"last row:\n{last}")
        except ReferenceError_:
            pass
    records = _json_records(text)
    if records:
        keys = sorted({k for r in records[:20] for k in r})
        return (f"=== {ref_id} === JSON records, {len(records)} entries\n"
                f"fields: {', '.join(repr(k) for k in keys)}\n"
                f"first entry: {json.dumps(records[0])[:300]}")
    head = text.strip()[:400]
    return f"=== {ref_id} === text, {len(text)} characters\n{head}" + ("…" if len(text) > 400 else "")


def _to_number(raw: Any) -> Optional[float]:
    """Numeric value, or None for a genuine gap. A gap must stay a gap — zero-filling would draw a
    plunge that never happened and drag an average toward zero."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw)
    s = str(raw).strip().replace(",", "")
    if not s or s.upper() in {"NA", "N/A", "NULL", "NONE", "-", "--", "."}:
        return None
    s = re.sub(r"^\$|%$", "", s)
    try:
        return float(s)
    except ValueError:
        return None


def extract_column(text: str, column: str, numeric: bool = True):
    """Values of `column` from a referenced output, in file order.

    Raises ReferenceError_ naming the available columns when the requested one is absent — the model
    can then retry with a real name instead of silently charting the wrong series.
    """
    if not column or not str(column).strip():
        raise ReferenceError_("a reference needs a 'column' naming which values to take")
    column = str(column).strip()

    records = _json_records(text)
    if records is not None:
        keys = sorted({k for r in records[:20] for k in r})
        match = next((k for k in keys if k.lower() == column.lower()), None)
        if match is None:
            raise ReferenceError_(f"field {column!r} not found; available fields: {keys}")
        raw = [r.get(match) for r in records]
    else:
        header, rows = _parse_table(text)
        idx = next((i for i, h in enumerate(header) if h.lower() == column.lower()), None)
        if idx is None:
            raise ReferenceError_(
                f"column {column!r} not found; available columns: {[h for h in header]}")
        raw = [(r[idx] if idx < len(r) else None) for r in rows]

    if len(raw) > _MAX_CELLS:
        raise ReferenceError_(f"column has {len(raw)} values, over the {_MAX_CELLS} limit")
    if not numeric:
        return [("" if v is None else str(v).strip()) for v in raw]

    values = [_to_number(v) for v in raw]
    # A column the caller asked for numerically may simply not BE numeric — a date axis is the
    # common case. Coercing it yielded a list of None, and plot_data then rejected the chart with
    # "temporal x value None is neither a number nor a recognised date". Decide from the DATA:
    # if most cells do not parse as numbers, the column is text, so return it as text and let the
    # consuming tool interpret it (plot_data understands date strings).
    parsed = sum(1 for v in values if v is not None)
    if raw and parsed < len(raw) / 2:
        return [("" if v is None else str(v).strip()) for v in raw]
    return values


def _is_reference(value: Any) -> bool:
    return isinstance(value, dict) and "from" in value and "column" in value


def resolve_references(value: Any, index: Dict[str, str], numeric: bool = True):
    """Recursively replace every {"from": …, "column": …} with the real values from `index`.

    Same shape as `_dr_inject_research_output`: no field-name special-casing — the model marks which
    argument carries the data, RAICA substitutes it wherever that mark appears.
    """
    if _is_reference(value):
        raw_from = value.get("from")
        # `from` may name SEVERAL outputs, concatenated in the order given. Without this the model
        # can only address one file at a time: asked for two years of Treasury rates it computed
        # over 2025 alone (n=249) and reported the result "over the full period". Both extremes
        # happened to fall in that year, so the answer was right by luck — the next question would
        # not be.
        refs = raw_from if isinstance(raw_from, list) else [raw_from]
        refs = [str(r or "").strip() for r in refs]
        if not refs or not any(refs):
            raise ReferenceError_("a reference needs 'from' naming which tool output to read")
        unknown = [r for r in refs if r not in index]
        if unknown:
            raise ReferenceError_(
                f"unknown output reference(s) {unknown}; available: {sorted(index)}")
        want_numeric = value.get("numeric", numeric)
        out = []
        for r in refs:
            out.extend(extract_column(index[r], value.get("column"), numeric=bool(want_numeric)))
        return out
    if isinstance(value, list):
        return [resolve_references(v, index, numeric) for v in value]
    if isinstance(value, dict):
        return {k: resolve_references(v, index, numeric) for k, v in value.items()}
    return value
