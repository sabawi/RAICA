"""
General data-chart renderer for the data-charting feature (design: docs/DESIGN_data_charts.md).

Renders a validated ``DatasetSeries`` (see dataset_block.py) to a NewX-styled PNG — line / bar / scatter —
deterministically from the STORED payload. Domain-free analog of the stock ``chart_generator``:

  * Thread-safe: matplotlib OO API (Figure + Agg), never pyplot global state.
  * Never raises — returns ``None`` on any failure, so a chart problem can never break a response
    (fail-closed: no chart beats a wrong chart).
  * DISCONTINUITIES ARE SEGMENTED, NEVER BRIDGED — a line is broken at each declared discontinuity (and at
    genuine None gaps) with a labelled marker, honouring the "annotate/segment, never silently bridge" rule
    (e.g. FBI SRS→NIBRS 2021).

This module NEVER invents data — it only plots what ``DatasetSeries`` carries (numbers-by-reference).
"""
import io
import logging
from typing import List, Optional, Tuple

import matplotlib
matplotlib.use("Agg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg

from utils.dataset_block import DatasetSeries

logger = logging.getLogger(__name__)

_BG = "#0f141c"; _AX = "#151b26"; _GRID = "#2a3340"; _TXT = "#e1e7f0"; _SP = "#2d3748"
_MUTE = "#8899a6"
# Distinct, colour-blind-friendly-ish series palette (first two match the stock up/down teal/red).
_SERIES = ["#26a69a", "#ef5350", "#58a6ff", "#f2ca30", "#ab7df8", "#ff8b3d", "#7ee787", "#e06c9f"]


def _style(ax):
    ax.set_facecolor(_AX)
    ax.grid(True, which="major", axis="both", color=_GRID, ls=":", alpha=.7)
    ax.tick_params(colors=_TXT, labelsize=8)
    for s in ax.spines.values():
        s.set_color(_SP)


def _auto_kind(series: DatasetSeries) -> str:
    if series.x_type == "categorical":
        return "bar"
    return "line"                       # temporal / quantitative default to line (scatter is opt-in)


def _cut_values(series: DatasetSeries) -> List[float]:
    """Discontinuity x-positions (numeric axes only) at which the line must break."""
    cuts = []
    for d in series.discontinuities:
        at = d.get("at")
        if isinstance(at, (int, float)) and not isinstance(at, bool):
            cuts.append(float(at))
    return cuts


def _segments(x, y, cuts) -> List[Tuple[list, list]]:
    """Split (x, y) into connected runs, breaking at None gaps and between points straddling a cut.

    A break falls between consecutive points x[i], x[i+1] when a cut c satisfies x[i] < c <= x[i+1]
    (so a cut at 2021 breaks the 2020↔2021 link — SRS↔NIBRS)."""
    segs, cur_x, cur_y = [], [], []
    for i in range(len(x)):
        if y[i] is None:
            if cur_x:
                segs.append((cur_x, cur_y)); cur_x, cur_y = [], []
            continue
        if cur_x:
            prev = cur_x[-1]
            if any(prev < c <= x[i] for c in cuts):        # straddles a discontinuity → break here
                segs.append((cur_x, cur_y)); cur_x, cur_y = [], []
        cur_x.append(x[i]); cur_y.append(y[i])
    if cur_x:
        segs.append((cur_x, cur_y))
    return segs


def _draw_discontinuities(ax, series: DatasetSeries):
    for d in series.discontinuities:
        at = d.get("at")
        if not isinstance(at, (int, float)) or isinstance(at, bool):
            continue
        ax.axvline(at, color="#ffd54f", ls="--", lw=1.1, alpha=.8)
        note = d.get("note")
        label = f"{int(at) if float(at).is_integer() else at}" + (f" · {note}" if note else "")
        ax.annotate(label, xy=(at, 1.0), xycoords=("data", "axes fraction"),
                    xytext=(3, -10), textcoords="offset points",
                    color="#ffd54f", fontsize=7, rotation=90, va="top", ha="left")


def _set_fitted_title(fig, ax, title: str, width_px: int,
                      base_size: float = 10.5, min_size: float = 7.5, max_lines: int = 3) -> None:
    """Set the chart title so it ALWAYS fits the figure width.

    Matplotlib neither wraps nor shrinks a title, so a long one is silently sliced off at BOTH edges
    (observed on a 4-series cross-source chart, and reproducible for any verbose title — an LLM-supplied
    one, or a template with a long measure label + geography). Fixing it only where a title is *composed*
    would leave every other path broken, so the guard lives here at the single point every chart passes
    through: MEASURE the real rendered text, wrap it onto up to ``max_lines``, and only if it still
    overflows step the font down to ``min_size``. Purely cosmetic — never alters the data."""
    title = (title or "").strip()
    if not title:
        return
    import textwrap
    canvas = fig.canvas
    canvas.draw()                      # a renderer is needed to measure text
    r = canvas.get_renderer()
    avail = width_px * 0.94            # keep a small margin inside the figure

    def _fits(text: str, size: float) -> bool:
        t = ax.set_title(text, color=_TXT, fontsize=size, fontweight="bold")
        widest = max((r.get_text_width_height_descent(ln, t.get_fontproperties(), False)[0]
                      for ln in text.split("\n")), default=0)
        return widest <= avail

    size = base_size
    while True:
        # try progressively more lines at this font size
        for lines in range(1, max_lines + 1):
            wrapped = "\n".join(textwrap.wrap(title, max(10, len(title) // lines + 1))) if lines > 1 else title
            if _fits(wrapped, size):
                ax.set_title(wrapped, color=_TXT, fontsize=size, fontweight="bold")
                return
        if size <= min_size:
            break
        size = max(min_size, size - 1.0)

    # still too wide at the smallest size → wrap to max_lines and accept (never leave it unset)
    wrapped = "\n".join(textwrap.wrap(title, max(10, len(title) // max_lines + 1))[:max_lines])
    ax.set_title(wrapped, color=_TXT, fontsize=min_size, fontweight="bold")


def generate_data_chart(series: DatasetSeries, kind: str = "auto",
                        width_px: int = 760, height_px: int = 430, dpi: int = 110) -> Optional[bytes]:
    """Render ``series`` to PNG bytes. ``kind``: 'auto' | 'line' | 'bar' | 'scatter'. None on any failure."""
    try:
        series.validate()
        kind = _auto_kind(series) if kind == "auto" else kind
        if kind not in ("line", "bar", "scatter"):
            return None

        fig = Figure(figsize=(width_px / dpi, height_px / dpi), dpi=dpi, facecolor=_BG)
        FigureCanvasAgg(fig)
        ax = fig.subplots(1, 1)
        _style(ax)

        x = series.x
        multi = len(series.series) > 1

        if kind == "bar" and series.x_type == "categorical":
            n, m = len(x), len(series.series)
            import numpy as np
            base = np.arange(n)
            width = 0.8 / max(1, m)
            for j, s in enumerate(series.series):
                ys = [(v if v is not None else 0) for v in s["y"]]
                ax.bar(base + j * width - 0.4 + width / 2, ys, width=width,
                       color=_SERIES[j % len(_SERIES)], label=s["name"])
            ax.set_xticks(base)
            ax.set_xticklabels([str(c) for c in x], rotation=30, ha="right", fontsize=7)

        else:  # line / scatter on a numeric axis
            cuts = _cut_values(series)
            for j, s in enumerate(series.series):
                col = _SERIES[j % len(_SERIES)]
                if kind == "scatter":
                    xs = [x[i] for i in range(len(x)) if s["y"][i] is not None]
                    ys = [v for v in s["y"] if v is not None]
                    ax.scatter(xs, ys, s=14, color=col, label=s["name"], alpha=.85)
                else:  # line — segmented at discontinuities/gaps
                    first = True
                    for seg_x, seg_y in _segments(x, s["y"], cuts):
                        ax.plot(seg_x, seg_y, color=col, lw=1.6,
                                label=(s["name"] if first else None))
                        first = False
            _draw_discontinuities(ax, series)

        # labels / title / source footer
        _set_fitted_title(fig, ax, series.title, width_px)
        ax.set_xlabel(series.x_name, color=_TXT, fontsize=9)
        ylab = series.series[0].get("unit") or series.series[0]["name"]
        ax.set_ylabel(ylab, color=_TXT, fontsize=9)
        if multi:
            ax.legend(loc="best", framealpha=.3, facecolor=_AX, edgecolor=_SP,
                      labelcolor=_TXT, fontsize=7)
        src = series.source + (f" · retrieved {series.retrieved}" if series.retrieved else "")
        fig.text(0.995, 0.006, f"Source: {src}", color=_MUTE, fontsize=6.5, ha="right", va="bottom")

        # a wrapped (multi-line) title needs more headroom or it collides with the plot
        _title_lines = (ax.get_title() or "").count("\n") + 1
        fig.subplots_adjust(left=0.1, right=0.97, top=0.9 - 0.045 * (_title_lines - 1), bottom=0.16)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", facecolor=_BG)
        return buf.getvalue()
    except Exception as e:  # noqa: BLE001 — never break a response over a chart
        logger.warning("data_chart_generator: render failed: %s", e)
        return None
