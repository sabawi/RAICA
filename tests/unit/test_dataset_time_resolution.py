"""Dataset time resolution — docs/DESIGN_data_charts_time_resolution.md.

FROM THE MODEL STUDY, 2026-10-25. "@Ask plot the monthly changes in Brent oil prices … since the US/Israel made their
first attack on Iran this year": 0 charts in 7 runs. FRED's daily Brent series WAS fetched each time it was asked
for, and `shape: fred_observations` averaged it to one value per year, so the model got two points (2025, 2026).

Offline: every fetch is a stand-in (`fetch_json`, or a stubbed requests.Session); nothing reaches FRED or a model.
Failures each test prevents are named in its docstring.
"""
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "user_tools"))

import yaml  # noqa: E402

from datasources.base import DatasetRequest  # noqa: E402
from datasources.declarative_adapter import DeclarativeAdapter  # noqa: E402
from utils.dataset_block import DatasetError, format_digest  # noqa: E402

CATALOG = yaml.safe_load((ROOT / "config" / "llm_config.defaults.yaml").read_text())[
    "deep_research"]["data_charts"]["sources"]["catalog"]

# FRED's reply to frequency=m&aggregation_method=avg for DCOILBRENTEU, 2026-10-25 (the real values).
FRED_MONTHLY = {"observations": [
    {"date": "2026-01-01", "value": "66.60"}, {"date": "2026-02-01", "value": "70.89"},
    {"date": "2026-03-01", "value": "103.13"}, {"date": "2026-04-01", "value": "117.29"},
    {"date": "2026-05-01", "value": "107.14"}, {"date": "2026-06-01", "value": "85.40"},
    {"date": "2026-07-01", "value": "83.76"}, {"date": "2026-08-01", "value": "91.08"},
    {"date": "2026-09-01", "value": "114.16"}, {"date": "2026-10-01", "value": "."}]}

# A daily series as FRED returns it without a frequency (the annual path averages it).
FRED_DAILY = {"observations": [
    {"date": "2025-01-02", "value": "70"}, {"date": "2025-06-02", "value": "80"},
    {"date": "2026-01-02", "value": "90"}, {"date": "2026-06-01", "value": "110"}, {"date": "2026-06-02", "value": "."}]}


def fred():
    cfg = dict(CATALOG["fred"])
    cfg["measures"] = {**cfg["measures"],
                       "brent": {"path": "DCOILBRENTEU", "label": "Brent crude oil price", "unit": "$ per barrel"}}
    return DeclarativeAdapter("fred", cfg)


def _req(**kw):
    return DatasetRequest(measure="brent", **kw)


class TestMonthly:

    def test_a_monthly_request_keeps_every_month(self):
        """The Brent failure: the daily series was averaged to two yearly points. Asked for monthly, every
        published month must arrive as its own point, with FRED's own values."""
        s = fred().extract(_req(frequency="monthly", start="2026-02"), fetch_json=lambda r: FRED_MONTHLY)
        assert s.resolution == "monthly"
        assert s.series[0]["y"] == [70.89, 103.13, 117.29, 107.14, 85.40, 83.76, 91.08, 114.16]
        assert len(s.x) == 8 and all(2026 <= x < 2027 for x in s.x)

    def test_an_unpublished_period_is_a_gap_not_a_zero(self):
        """FRED marks a period not yet published with "."; a zero there would draw a crash that never happened."""
        s = fred().extract(_req(frequency="monthly"), fetch_json=lambda r: FRED_MONTHLY)
        assert 0.0 not in s.series[0]["y"] and len(s.x) == 9

    def test_the_digest_names_each_period(self):
        """The model reads the digest: months must read as 2026-03, not as decimal years like 2026.16."""
        s = fred().extract(_req(frequency="monthly", start="2026-02"), fetch_json=lambda r: FRED_MONTHLY)
        d = format_digest(s, "ds_x")
        assert "(2026-03, 103.13)" in d and "monthly" in d
        assert "for a period ONLY if it is listed" in d
        assert "2026.1" not in d

    def test_the_request_carries_the_resolution_and_window(self):
        """FRED aggregates on its own side only if asked: frequency, method and the window must be sent."""
        p = fred()._build_params(_req(frequency="monthly", start="2026-02", end="2026-09-30"))
        assert p["frequency"] == "m" and p["aggregation_method"] == "avg"
        assert p["observation_start"] == "2026-02-01" and p["observation_end"] == "2026-09-30"


class TestAnnualIsUnchanged:

    def test_annual_params_are_exactly_as_before(self):
        """Every existing chart is annual; its request must not change by one parameter."""
        p = fred()._build_params(_req(from_year=2023, to_year=2025))
        assert p == {"series_id": "DCOILBRENTEU", "file_type": "json",
                     "observation_start": "2023-01-01", "observation_end": "2025-12-31"}

    def test_annual_values_are_the_yearly_means_as_before(self):
        """The annual path still averages by year, and labels no resolution change."""
        s = fred().extract(_req(), fetch_json=lambda r: FRED_DAILY)
        assert s.x == [2025, 2026] and s.series[0]["y"] == [75.0, 100.0]
        d = format_digest(s, "ds_y")
        assert "for a year ONLY if it is listed" in d


class TestRefusals:

    def test_a_declared_resolution_without_its_code_is_refused(self):
        """Audit find: a resolution declared without the code to send would fetch the source's NATIVE data and
        label it with the requested resolution — wrong data with no error."""
        cfg = dict(CATALOG["fred"])
        cfg["frequencies"] = {**cfg["frequencies"], "monthly": {}}
        cfg["measures"] = {"brent": {"path": "DCOILBRENTEU", "label": "Brent"}}

        def must_not_fetch(r):
            raise AssertionError("fetched with no resolution code")
        with pytest.raises(DatasetError, match="without a param_value"):
            DeclarativeAdapter("fred", cfg).extract(_req(frequency="monthly"), fetch_json=must_not_fetch)

    def test_a_source_without_the_resolution_refuses_before_fetching(self):
        """World Bank publishes annual data only; a monthly request must be refused with what it has, and must
        not spend a fetch."""
        wb = DeclarativeAdapter("world_bank", CATALOG["world_bank"])

        def must_not_fetch(r):
            raise AssertionError("fetched although the resolution is unpublished")
        with pytest.raises(DatasetError, match=r"publishes \['annual'\]"):
            wb.extract(DatasetRequest(measure="SL.UEM.TOTL.ZS", frequency="monthly"), fetch_json=must_not_fetch)

    def test_a_source_refusal_is_not_retried_and_its_reason_is_kept(self, monkeypatch):
        """FRED answers a resolution finer than a series publishes with HTTP 400 and the list it has. That was
        retried five times and the model was told only "400 Bad Request"."""
        import requests
        calls = []

        class Resp:
            status_code = 400
            content = b"x"
            text = "Bad Request"

            def json(self):
                return {"error_code": 400,
                        "error_message": "Bad Request.  Value of frequency is not one of: 'm', 'q', 'sa', 'a'."}

        class Sess:
            def get(self, *a, **k):
                calls.append(1)
                return Resp()

            def close(self):
                pass
        monkeypatch.setattr(requests, "Session", Sess)
        monkeypatch.setenv("FRED_API_KEY", "test-not-a-key")
        a = DeclarativeAdapter("fred", CATALOG["fred"])
        with pytest.raises(DatasetError, match="Value of frequency is not one of"):
            a._http_get(DatasetRequest(measure="UNRATE", frequency="daily"))
        assert len(calls) == 1


class TestWindow:

    def test_a_date_window_bounds_an_annual_request(self):
        """Audit find: an annual request with only `start`/`end` ignored the window and returned every year —
        and asked the source for its whole history (FRED: from 1947)."""
        a = fred()
        sent = {}

        def fetch(r):
            sent.update(a._build_params(r))
            return FRED_DAILY
        s = a.extract(_req(start="2025-03", end="2026-12"), fetch_json=fetch)
        assert s.x == [2025, 2026]
        assert sent["observation_start"] == "2025-01-01" and sent["observation_end"] == "2026-12-31"


class TestAdvertised:

    def test_each_source_advertises_its_resolutions_from_config(self):
        """The model can only choose a resolution it is told exists; the list comes from each source's config."""
        assert fred().frequencies() == ["annual", "quarterly", "monthly", "weekly", "daily"]
        assert DeclarativeAdapter("world_bank", CATALOG["world_bank"]).frequencies() == ["annual"]

    def test_the_tool_passes_the_resolution_through(self, monkeypatch):
        """Reachability: the parameter is worthless unless search_datasets puts it on the request."""
        import asyncio
        import search_datasets_tool as tool
        seen = {}

        def fake_build(source, req, chart_kind="auto"):
            seen["req"] = req
            return {"ok": True, "content": "x"}
        monkeypatch.setattr(tool, "build_data_chart", fake_build)
        monkeypatch.setattr(tool, "_feature_enabled", lambda: True)
        asyncio.run(tool.SearchDatasetsTool().execute(source="fred", measure="Brent", frequency="monthly",
                                                      start="2026-02", end="2026-10"))
        r = seen["req"]
        assert (r.frequency, r.start, r.end) == ("monthly", "2026-02", "2026-10")


class TestAxis:

    def test_a_monthly_axis_names_its_months(self):
        """Live find (A+B run 2, 2026-10-25): the monthly Brent chart's axis read "25 Feb, 21 Apr, 14 Jun" — day
        labels between the points, naming days the data does not have. Ticks must sit on the months and name them."""
        import matplotlib
        matplotlib.use("Agg")
        from matplotlib.figure import Figure
        from utils.data_chart_generator import _apply_temporal_ticks
        from utils.dataset_block import to_decimal_year
        x = [to_decimal_year("2026-%02d-01" % m) for m in range(2, 10)]
        ax = Figure().subplots()
        ax.plot(x, range(8))
        assert _apply_temporal_ticks(ax, x, "monthly")
        ax.figure.canvas.draw()
        labels = [t.get_text() for t in ax.get_xticklabels()]
        assert labels == ["Feb 2026", "Mar 2026", "Apr 2026", "May 2026", "Jun 2026", "Jul 2026", "Aug 2026", "Sep 2026"]


class TestSeriesIdIsLookedUp:

    def _adapter(self, monkeypatch, lookup, search):
        import datasources.discovery as disc
        monkeypatch.setattr(disc, "fred_series_lookup", lookup)
        monkeypatch.setattr(disc, "fred_search", search)
        monkeypatch.setenv("FRED_API_KEY", "test-not-a-key")
        return DeclarativeAdapter("fred", CATALOG["fred"])

    def test_an_exact_series_id_resolves_without_a_search(self, monkeypatch):
        """A+B run 3, 2026-10-25: the model gave `DCOILBRENTEU`; FRED's full-text SEARCH for an id timed out
        (12 s, reproduced 3/3) and the answer said "unknown measure". FRED's series lookup answers in ~0.4 s."""
        def lookup(sid, key, d):
            return {"path": sid, "label": "Crude Oil Prices: Brent - Europe", "unit": "$ per Barrel"} \
                if sid == "DCOILBRENTEU" else None

        def search(*a, **k):
            raise AssertionError("searched although FRED knows the id")
        a = self._adapter(monkeypatch, lookup, search)
        s = a.extract(DatasetRequest(measure="DCOILBRENTEU", frequency="monthly"), fetch_json=lambda r: FRED_MONTHLY)
        assert "DCOILBRENTEU" in a._discovered and s.series[0]["y"][0] == 66.60

    def test_a_description_still_goes_to_search(self, monkeypatch):
        """FRED refuses a description as an id (HTTP 400 → None); search must still run."""
        seen = []
        a = self._adapter(monkeypatch, lambda sid, key, d: None,
                          lambda text, *a: seen.append(text) or {"path": "DCOILBRENTEU", "label": "Brent"})
        a.extract(DatasetRequest(measure="Brent crude oil", frequency="monthly"), fetch_json=lambda r: FRED_MONTHLY)
        assert seen == ["Brent crude oil"]

    def test_a_miss_tells_the_model_how_the_search_works(self, monkeypatch):
        """A+B run 3: two descriptions ("Brent crude oil spot price Europe") matched nothing because FRED's search
        needs EVERY word; the model was told only "discovery found nothing" and gave up on the source."""
        a = self._adapter(monkeypatch, lambda sid, key, d: None, lambda *a: None)
        with pytest.raises(DatasetError, match="EVERY word"):
            a.extract(DatasetRequest(measure="Brent crude oil spot price Europe"), fetch_json=lambda r: FRED_MONTHLY)


class TestOneChartPerSeries:

    @staticmethod
    def _content(window, url):
        from utils.dataset_block import DatasetSeries, register_dataset
        s = DatasetSeries(title=f"Brent, {window}", source="FRED", url="https://fred.stlouisfed.org/",
                          x_name="date", x_type="temporal", x=[2026.1, 2026.2],
                          series=[{"name": "Crude Oil Prices: Brent - Europe", "unit": "$ per Barrel", "y": [70.0, 80.0]}],
                          resolution="monthly")
        m = f'[[chart:/static/images/media/{url}.jpg|align=center|caption="Brent, {window}"]]'
        return m, f"{m}\n\n{format_digest(s, register_dataset(s))}"

    def test_the_repair_does_not_append_a_second_drawing_of_a_shown_series(self):
        """A+B run 2: the writer kept one Brent chart; the repair appended the other two windows of the SAME
        series, so the answer showed Brent three times."""
        import fastapi_server_complete as srv
        from utils.dataset_block import marker_series_keys
        m1, c1 = self._content("2025-06–2026-09", "a" * 32)
        m2, c2 = self._content("2026-02–2026-09", "b" * 32)
        tools = c1 + "\n\n" + c2
        out, _ = srv._repair_answer_chart_markers(f"Here:\n{m2}\nDone.", [m1, m2],
                                                   marker_series_keys(tools, [m1, m2]))
        assert m2 in out and m1 not in out

    def test_distinct_charts_are_still_restored(self):
        """The append exists for a reason: the writer dropped 1–3 of the 4 DISTINCT stock charts in 4 of 6 study
        runs. Charts without a dataset digest, or of different series, must still be restored."""
        import fastapi_server_complete as srv
        from utils.dataset_block import marker_series_keys
        a = '[[chart:/static/images/media/' + "c" * 32 + '.jpg|caption="price"]]'
        b = '[[chart:/static/images/media/' + "d" * 32 + '.jpg|caption="MACD"]]'
        tools = f"{a}\nanalysis\n{b}\nmore"
        out, n = srv._repair_answer_chart_markers(f"x {a}", [a, b], marker_series_keys(tools, [a, b]))
        assert b in out and n == 1

    def test_when_none_is_shown_one_drawing_of_the_series_is_appended(self):
        """A chart at the end still beats no chart — but once, not once per attempt."""
        import fastapi_server_complete as srv
        from utils.dataset_block import marker_series_keys
        m1, c1 = self._content("2025-06–2026-09", "e" * 32)
        m2, c2 = self._content("2026-02–2026-09", "f" * 32)
        out, _ = srv._repair_answer_chart_markers("no chart here", [m1, m2],
                                                   marker_series_keys(c1 + "\n\n" + c2, [m1, m2]))
        assert out.count("[[chart:") == 1
