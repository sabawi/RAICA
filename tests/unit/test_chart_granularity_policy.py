"""SI-027 — a dataset chart must be described at the resolution it actually has.

FROM PRODUCTION 2026-08-11. A user asked for "the past two years" of 30/20/10/5-year Treasury
yields. The DATA was perfect — all 12 annual averages matched FRED to the basis point, and the
four series resolved to the correct identifiers (DGS30/20/10/5). The DESCRIPTION was not:

  * three annual points per line were narrated as a two-year "path", so the user reasonably
    read two lines rising in parallel as "diverging" (the 30y-10y gap was in fact flat:
    0.52 -> 0.54 over 13 months);
  * the 2026 point was labelled an "annual average" while covering 151 trading days
    (Jan-Aug), understating the present materially — 30y showed 4.93% against an actual
    latest of 5.19%;
  * a "trend correlation of +1.00" was reported from THREE observations, which carries no
    information however precise it looks.

POLICY, NOT CODE. `shape: fred_observations` aggregates every FRED series to ANNUAL MEANS and
exposes no frequency parameter, so a directive telling the model to fetch daily data would be
silently defeated by the code — the LLM-policy gate's exact trap. These directives therefore
ask only for what the system CAN do: disclose the granularity, label a partial year, and
refrain from claims the sample cannot support.

Two surfaces, because the model needs it at different moments:
  * the TOOL DESCRIPTION, read when choosing/using the tool — sets expectations before writing
  * the ANSWER directive, read when composing — governs how the chart is described
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "user_tools"))

SERVER = re.sub(r'"\s*\n\s*"', "", (ROOT / "fastapi_server_complete.py").read_text())


def _policy_block():
    """JUST the SI-027 directive text — bounded by its own start and end.

    The first version sliced a fixed 2600 chars, which ran past the directive into the
    module code that follows it (legitimately containing `re.compile`) and failed the
    no-pattern-matching check on code that is not policy at all.
    """
    start = SERVER.index("STATE THE GRANULARITY")
    end = SERVER.index("not earned.", start) + len("not earned.")
    return SERVER[start:end]


def _tool_description():
    from user_tools.compare_datasets_tool import CompareDatasetsTool
    return CompareDatasetsTool().description


def test_tool_description_states_annual_granularity():
    """The model must know the resolution BEFORE it writes, not after."""
    d = _tool_description()
    assert "ANNUAL MEANS" in d
    assert "PARTIAL-year" in d


def test_tool_description_makes_the_point_count_concrete():
    """'Annual means' is abstract; 'three points, not a daily path' is actionable."""
    d = _tool_description()
    assert "THREE points" in d and "daily path" in d


def test_answer_policy_requires_stating_granularity():
    assert "STATE THE GRANULARITY" in SERVER
    assert "annual averages; 3 points per series" in SERVER


def test_answer_policy_names_the_exact_misreading_that_occurred():
    """The parallel-rise-read-as-divergence error must be named, or it recurs."""
    assert "are NOT diverging" in SERVER
    assert "check the gap before you call it one" in SERVER


def test_answer_policy_requires_labelling_a_partial_year():
    assert "LABEL AN INCOMPLETE PERIOD" in SERVER
    assert "latest actual observation" in SERVER


def test_answer_policy_bars_statistics_the_sample_cannot_support():
    assert "DO NOT REPORT A STATISTIC THE SAMPLE CANNOT SUPPORT" in SERVER
    assert "number of observations" in SERVER


def test_policy_does_not_promise_data_the_tool_cannot_serve():
    """LLM-policy gate B: a directive the CODE defeats is worse than none.

    The FRED shape aggregates to annual means with no frequency parameter, so the policy must
    never instruct the model to request daily/weekly/monthly observations.
    """
    seg = _policy_block()
    for forbidden in ("request daily", "ask for daily", "fetch daily", "use daily data",
                      "request weekly", "request monthly"):
        assert forbidden.lower() not in seg.lower(), \
            f"policy promises {forbidden!r}, which fred_observations cannot deliver"


def test_policy_is_language_not_pattern_matching():
    """Same constraint as SI-023: RAICA states the rule; the model decides what matches."""
    seg = _policy_block()
    assert not re.search(r"re\.(match|search|compile)", seg)
    assert "KEYWORDS" not in seg and "startswith" not in seg
