"""Regression (SI-048 / SI-051 / SI-052): arbitrator regeneration must not discard prior results.

FAILURE THIS PREVENTS
---------------------
The arbitrator's regeneration step used to do:

    tools_results_list = regenerated_tools_results
    tools_called = [tc['function']['name'] for tc in regeneration_response['tool_calls']]

Both lists REPLACED, not merged — so the first regeneration attempt threw away every result
gathered before it: phase-1 fetches, all of the gather-gate's compute outputs, and plot_data's
chart marker.

Measured on a US Treasury run (v1.0.0.286):
  * the gate computed `np.mean(y10)` = 4.29321 and `np.max(y10)` = 4.79 correctly, over all 249 rows
  * plot_data published a real chart (2 series x 249 points, HTTP 200 image/jpeg)
  * regeneration then returned ['lookup_website'] and BOTH lists collapsed to that one entry
  * synthesis received `TOOLS EXECUTED: lookup_website` and ONE tool entry — the raw CSV

Consequences, all three user-visible and all from the same discarded list:
  * SI-048 the answer eyeballed the statistics: 4.27 and 4.62 instead of 4.29321 and 4.79
  * SI-051 no chart marker reached the answer, though the chart was rendered and served
  * SI-052 with no marker the model hand-drew an ASCII chart: 2.9 MB, 99.8% whitespace

These tests FAIL on the pre-fix code.
"""
import pytest

from fastapi_server_complete import _entry_tool_name, _merge_regenerated_results


def _entry(tool, result):
    return f"Tool: {tool}\nResult: {result}\n\n"


PRIOR = [
    _entry("lookup_website", "Date,10 Yr\n2025-01-02,4.79\n"),
    _entry("compute", "mean of 10 Yr yields: 4.29321\ncomputed as: np.mean(y10)"),
    _entry("compute", "maximum of 10 Yr yields: 4.79\ncomputed as: np.max(y10)"),
    _entry("plot_data", "[[chart:/static/images/media/abc123.jpg|Yields]]"),
]


def test_regenerating_one_tool_keeps_every_other_result():
    """THE bug: regenerating `lookup_website` must not delete compute and plot_data."""
    regenerated = [_entry("lookup_website", "Date,10 Yr\n2025-01-02,4.79\n(refetched)")]
    merged, names = _merge_regenerated_results(PRIOR, regenerated, ["lookup_website"])

    assert "compute" in names, "the gate's compute results were discarded by regeneration"
    assert "plot_data" in names, "the chart marker was discarded by regeneration"
    assert names.count("compute") == 2
    blob = "".join(merged)
    assert "4.29321" in blob and "4.79" in blob, "the correct computed values were lost"
    assert "[[chart:/static/images/media/abc123.jpg" in blob, "the chart marker was lost"


def test_the_regenerated_tool_is_replaced_not_duplicated():
    """Regeneration exists to supersede a failed call, so the old one must go."""
    regenerated = [_entry("lookup_website", "refetched")]
    merged, names = _merge_regenerated_results(PRIOR, regenerated, ["lookup_website"])
    assert names.count("lookup_website") == 1
    assert "refetched" in "".join(merged)


def test_the_two_lists_are_parallel_by_construction():
    """`arbitrator_validate_tasks` pairs them with zip(), which truncates silently.

    Deriving names FROM the entries makes a skew impossible rather than merely unlikely.
    """
    merged, names = _merge_regenerated_results(PRIOR, [_entry("compute", "x")], ["compute"])
    assert len(merged) == len(names)
    for entry, name in zip(merged, names):
        assert entry.startswith(f"Tool: {name}\n")


def test_regenerating_a_repeated_tool_replaces_all_of_its_entries():
    """`compute` runs many times; regenerating it supersedes that tool's results as a group."""
    regenerated = [_entry("compute", "redone A"), _entry("compute", "redone B")]
    merged, names = _merge_regenerated_results(PRIOR, regenerated, ["compute"])
    assert names.count("compute") == 2
    assert "4.29321" not in "".join(merged)          # superseded
    assert "plot_data" in names and "lookup_website" in names   # untouched


def test_empty_regeneration_changes_nothing():
    """A regeneration that produced no calls must not empty the accumulated results."""
    merged, names = _merge_regenerated_results(PRIOR, [], [])
    assert len(merged) == len(PRIOR)
    assert names == ["lookup_website", "compute", "compute", "plot_data"]


@pytest.mark.parametrize("entry,expected", [
    ("Tool: compute\nResult: 5\n\n", "compute"),
    ("Tool: lookup_website\nResult: x", "lookup_website"),
    ("no prefix at all", ""),
    ("", ""),
    (None, ""),
])
def test_entry_tool_name_is_total(entry, expected):
    """Malformed entries must degrade to '' rather than raising mid-merge."""
    assert _entry_tool_name(entry) == expected
