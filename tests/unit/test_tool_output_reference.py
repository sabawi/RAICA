"""SI-036 — pass data BY REFERENCE, because re-transcribing it is impossible and unwise.

THE MEASUREMENT. `compute` and `plot_data` took their data as inline arrays. On 404 daily Treasury
rows the tool-calling model had to emit thousands of numbers as arguments, and the selector came
back empty every time:

    truncated=True  completion_tokens=4096 (= the cap)  tool_calls=[]  content=''

Raising the cap to 32,768 against the same 43,013-char prompt changed nothing but latency
(33s -> 439s). Shrinking the prompt to a schema preview (10,612 chars) AND raising the cap to
16,384 produced 5 tool calls with truncated=False — both were needed.

Beyond fitting the budget: a transcribed series can be transcribed WRONG, which would defeat the
purpose of computing rather than eyeballing. Referenced values are the ones the tool actually
returned.

Two defects found by testing against REAL tool output rather than a fixture, both fixed here:
  * the parser read RAICA's formatted preamble as the header, reporting columns like
    'As of [Current Date and Time: Thursday' — a tool result is not a bare file
  * a Date column requested numerically became a list of None, and plot_data then refused the
    chart with "temporal x value None is neither a number nor a recognised date"
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from utils.tool_output_reference import (  # noqa: E402
    ReferenceError_, build_reference_index, describe_reference, extract_column, resolve_references)

# A tool result as lookup_website ACTUALLY returns it: RAICA's wrapper around the file.
WRAPPED = """
As of [Current Date and Time: Thursday, August 13, 2026 11:30:52 PM] here are the website lookup results:

───────────────────────────────────────────────────────
[CSV file: 250 lines retrieved (complete)]
Date,1 Mo,10 Yr,20 Yr,30 Yr
12/31/2025,3.74,4.18,4.79,4.84
12/30/2025,3.65,4.14,4.76,4.81
12/29/2025,3.69,4.16,4.78,4.83
12/26/2025,3.70,4.20,4.80,4.88
───────────────────────────────────────────────────────
Source: home.treasury.gov
"""


class TestFindsTheTableInsideAToolResult:

    def test_preamble_is_not_mistaken_for_the_header(self):
        """THE regression. Parsing from line 0 made the dated preamble the header, so every
        reference failed with "column '10 Yr' not found" while listing columns like
        'As of [Current Date and Time: Thursday'."""
        desc = describe_reference("lookup_website#1", WRAPPED)
        assert "'Date'" in desc and "'30 Yr'" in desc
        assert "As of" not in desc.split("columns:")[1].split("\n")[0]

    def test_columns_resolve_from_the_wrapped_output(self):
        assert extract_column(WRAPPED, "30 Yr") == [4.84, 4.81, 4.83, 4.88]
        assert extract_column(WRAPPED, "10 Yr") == [4.18, 4.14, 4.16, 4.20]

    def test_missing_column_names_what_is_available(self):
        """A wrong guess must be correctable, not silently answered with the wrong series."""
        with pytest.raises(ReferenceError_) as e:
            extract_column(WRAPPED, "30Y")
        assert "30 Yr" in str(e.value)

    def test_column_lookup_is_case_insensitive(self):
        assert extract_column(WRAPPED, "30 yr") == [4.84, 4.81, 4.83, 4.88]


class TestTheSelectorSeesAPreviewNotTheFile:

    def test_preview_is_far_smaller_than_the_data(self):
        """43,013 chars of prompt pushed the model into emitting the dataset back and truncating.
        The preview must carry the column SPELLINGS and the row count, not the rows."""
        # Rows must extend the SAME table (contiguous with its header), not sit after the closing
        # separator — two disjoint tabular blocks is a different situation, and the longest-run
        # heuristic would rightly pick the bigger one.
        extra = "\n".join(f"01/{i:02d}/2025,3.7,4.1,4.7,4.8" for i in range(1, 300))
        big = WRAPPED.replace("12/26/2025,3.70,4.20,4.80,4.88",
                              "12/26/2025,3.70,4.20,4.80,4.88\n" + extra)
        desc = describe_reference("lookup_website#1", big)
        assert len(desc) < len(big) / 5
        assert "'30 Yr'" in desc and "data rows" in desc

    def test_reference_ids_keep_two_fetches_apart(self):
        """The request needs 2025 AND 2026. Collapsing them would silently answer over one year."""
        idx = build_reference_index([("lookup_website", "a,b\n1,2\n3,4", 0, False, None),
                                     ("lookup_website", "a,b\n5,6\n7,8", 0, False, None)])
        assert sorted(idx) == ["lookup_website#1", "lookup_website#2"]


class TestResolution:

    IDX = {"lookup_website#1": WRAPPED}

    def test_nested_references_are_substituted(self):
        """Same shape as _dr_inject_research_output: the model marks which argument carries the
        data, wherever it appears."""
        args = {"expr": "np.min(y30 - y10)",
                "data": {"y30": {"from": "lookup_website#1", "column": "30 Yr"},
                         "y10": {"from": "lookup_website#1", "column": "10 Yr"}}}
        out = resolve_references(args, self.IDX)
        assert out["data"]["y30"] == [4.84, 4.81, 4.83, 4.88]
        assert out["expr"] == "np.min(y30 - y10)"          # untouched

    def test_a_date_column_comes_back_as_text_not_none(self):
        """SECOND regression. Requested numerically, a date column became [None, None, …] and
        plot_data rejected the chart with "temporal x value None is neither a number nor a
        recognised date". The column's own content decides the type."""
        out = resolve_references({"x": {"from": "lookup_website#1", "column": "Date"}}, self.IDX)
        assert out["x"][0] == "12/31/2025"
        assert all(v for v in out["x"])

    def test_gaps_stay_gaps_in_a_numeric_column(self):
        """A missing observation must not become zero — that would draw a plunge that never
        happened and drag any average toward it."""
        text = "Date,v\n2025-01-01,1.5\n2025-01-02,N/A\n2025-01-03,2.5"
        assert extract_column(text, "v") == [1.5, None, 2.5]

    def test_unknown_reference_is_refused_by_name(self):
        with pytest.raises(ReferenceError_) as e:
            resolve_references({"x": {"from": "nope#1", "column": "a"}}, self.IDX)
        assert "lookup_website#1" in str(e.value)

    def test_non_reference_arguments_pass_through_untouched(self):
        args = {"title": "t", "x": [1, 2, 3], "n": 5, "flag": True}
        assert resolve_references(args, self.IDX) == args


class TestJsonSources:
    RECORDS = '[{"date": "2025-01-01", "rate": 4.1}, {"date": "2025-01-02", "rate": 4.3}]'

    def test_json_records_are_a_table_too(self):
        assert extract_column(self.RECORDS, "rate") == [4.1, 4.3]

    def test_json_preview_lists_fields(self):
        d = describe_reference("api#1", self.RECORDS)
        assert "'rate'" in d and "JSON records" in d


class TestSelectorBudgetIsConfigured:
    def test_selector_max_tokens_is_set_and_large_enough(self):
        """4096 was measured to return NOTHING — the model's reasoning consumed the whole budget
        before it reached the tool call. This value is why four earlier fixes looked like failures."""
        import yaml
        sr = yaml.safe_load((ROOT / "config/llm_config.yaml").read_text())["tool_calling"]["second_round"]
        assert sr["selector_max_tokens"] >= 16384


class TestSpanningSeveralOutputs:
    """The n=249 defect: a reference could address only ONE output."""

    IDX = {"y1": "Date,v\n2025-01-02,1.0\n2025-01-03,2.0",
           "y2": "Date,v\n2026-01-02,3.0\n2026-01-03,4.0"}

    def test_a_reference_may_span_outputs(self):
        """Asked for two years, the model computed over 2025 alone (n=249) and called the result
        "over the full period". Both extremes happened to fall in that year so the number was right
        by luck — the next question would not be."""
        out = resolve_references({"v": {"from": ["y1", "y2"], "column": "v"}}, self.IDX)
        assert out["v"] == [1.0, 2.0, 3.0, 4.0]

    def test_a_single_reference_still_works(self):
        assert resolve_references({"v": {"from": "y1", "column": "v"}}, self.IDX)["v"] == [1.0, 2.0]

    def test_one_bad_id_in_a_list_fails_loudly(self):
        """Silently dropping an unreadable half would compute over a period the answer claims to
        cover — the exact failure being fixed."""
        with pytest.raises(ReferenceError_) as e:
            resolve_references({"v": {"from": ["y1", "nope"], "column": "v"}}, self.IDX)
        assert "nope" in str(e.value)


class TestChartOrdering:
    def test_points_joined_from_several_files_are_ordered(self):
        """Source files are usually newest-first. Joining 2025 and 2026, each descending, would
        draw a line running backwards and then jumping — a picture of nothing."""
        from user_tools.plot_data_tool import PlotDataTool
        out = PlotDataTool._coerce({
            "title": "t", "source": "s", "url": "u", "x_name": "Date", "x_type": "temporal",
            "x": ["2025-12-31", "2025-01-01", "2026-06-01", "2026-01-01"],
            "series": [{"name": "a", "y": [4, 1, 6, 5]}]})
        assert out["x"] == sorted(out["x"])
        assert out["series"][0]["y"] == [1, 4, 5, 6], "y must follow x through the sort"

    def test_categorical_order_is_preserved(self):
        """Category order carries meaning — sorting it would silently rearrange the user's data."""
        from user_tools.plot_data_tool import PlotDataTool
        out = PlotDataTool._coerce({
            "title": "t", "source": "s", "url": "u", "x_name": "Region", "x_type": "categorical",
            "x": ["North", "East", "South"], "series": [{"name": "a", "y": [3, 1, 2]}]})
        assert out["x"] == ["North", "East", "South"]


class TestQuotedFieldsContainingTheDelimiter:
    """FOUND ON PRODUCTION 2026-08-14 by a second test prompt, on the USGS earthquake catalogue.

    A 226-line file was parsed as a 14-line block whose "header" was a data row, so every derived
    figure was computed over 13 of 225 events:

        mean magnitude 5.71  (true 5.883)      mean depth 32.6 km (true 60.461)
        correlation    0.43  (true 0.1214)     deepest    629 km  (true 636.265)

    CAUSE: _locate_table counted RAW delimiters to find rows of equal width. A quoted field may
    legitimately contain the delimiter — USGS place names look like
    "22 km ENE of Baculin, Philippines" — so raw counts vary line to line and the longest matching
    run collapsed to whichever 13 lines happened to agree.

    The Treasury CSV that every earlier test used has NO quoted fields, which is why this stayed
    invisible through five releases. Field counts now come from a CSV parse.

    The model disclosed the subset ("this compute was run on a subset") and reported the numbers
    anyway — a disclosed wrong number is still a wrong number.
    """

    # Shape of the real file: a quoted place name containing a comma, on most rows but not all.
    QUOTED = (
        "time,depth,mag,place,type\n"
        "2026-01-02T00:00:00Z,10.0,5.5,\"12 km N of Somewhere, Chile\",earthquake\n"
        "2026-01-03T00:00:00Z,20.0,6.0,\"Fiji region\",earthquake\n"
        "2026-01-04T00:00:00Z,30.0,6.5,\"5 km SW of Elsewhere, Japan\",earthquake\n"
        "2026-01-05T00:00:00Z,40.0,7.0,\"South Pacific\",earthquake\n"
        "2026-01-06T00:00:00Z,50.0,7.5,\"9 km E of Nowhere, Peru\",earthquake\n"
    )

    def test_every_row_is_parsed_not_just_the_widest_run(self):
        header_desc = describe_reference("lookup_website#1", self.QUOTED)
        assert "5 data rows" in header_desc, header_desc
        assert "'mag'" in header_desc and "'place'" in header_desc

    def test_columns_are_complete_and_correct(self):
        assert extract_column(self.QUOTED, "mag") == [5.5, 6.0, 6.5, 7.0, 7.5]
        assert extract_column(self.QUOTED, "depth") == [10.0, 20.0, 30.0, 40.0, 50.0]

    def test_a_quoted_delimiter_does_not_split_the_field(self):
        places = extract_column(self.QUOTED, "place", numeric=False)
        assert places[0] == "12 km N of Somewhere, Chile"
        assert len(places) == 5

    def test_a_derived_figure_covers_the_whole_file(self):
        """The consequence that mattered: an average over part of a file is simply wrong, and
        nothing downstream can tell."""
        import statistics
        mags = extract_column(self.QUOTED, "mag")
        assert statistics.mean(mags) == pytest.approx(6.5)


class TestProseIsNotSummarisedLikeATable:
    """FOUND IN THE FIRST PHASE-0 SHADOW SAMPLE, in three production requests.

    The gather gate answered `needs_more` to "who is the current UN Secretary-General", explaining:

        "The current Secretary-General's name is not explicitly stated in the truncated tool output"

    It was reasoning correctly about a mutilated input. Prose was previewed at 400 characters, so a
    5,859-char search result reached the gate as 449 chars and the answer was simply not in it.

    The two output kinds are summarised for OPPOSITE reasons and must not share a budget:
      * a TABLE — the answer is not in the rows; columns and a row count suffice, which is why
        20,730 chars reduce to 579 losslessly for this purpose
      * PROSE  — the content IS the answer; truncating it destroys exactly what is being judged

    Reading the verdict alone (3/3 needs_more) looked identical to the model agreeing with
    everything — the opposite failure, needing the opposite fix. Only the REASON separated them.
    """

    PROSE = "Reported today: " + ("context sentence about the topic. " * 200) + "ANSWER=Guterres."
    TABLE = "[CSV file: 250 lines (complete)]\nDate,10 Yr\n" + "\n".join(
        f"01/{i:02d}/2025,4.{i:02d}" for i in range(1, 250))

    def test_the_answer_at_the_end_of_prose_is_visible(self):
        d = describe_reference("wikipedia_query#1", self.PROSE)
        assert "ANSWER=Guterres." in d, "the gate cannot judge what it cannot see"

    def test_tables_are_still_reduced_to_schema(self):
        """The reduction that made references work at all must not regress."""
        d = describe_reference("lookup_website#1", self.TABLE)
        assert len(d) < len(self.TABLE) / 10
        assert "'10 Yr'" in d and "data rows" in d

    def test_prose_truncation_is_disclosed_and_actionable(self):
        d = describe_reference("search_web#1", "x" * 20000)
        assert "TRUNCATED" in d and "20000" in d
        assert "say the retrieved text does not contain it" in d

    def test_short_prose_is_passed_whole_without_a_notice(self):
        d = describe_reference("search_web#1", "A short factual answer.")
        assert "A short factual answer." in d and "TRUNCATED" not in d
