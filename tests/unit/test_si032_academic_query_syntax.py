"""SI-032 — academic catalogues parse the query as an EXPRESSION, not as free text.

FOUND IN PRODUCTION 2026-08-12 across 12 retained Deep Research runs: 158 academic-source
failures, of which OpenAlex **11 ok / 47 x HTTP 400 (81% failing)** and DOAJ **4 ok / 51 x
HTTP 400 (93% failing)**.

CAUSE — confirmed by falsification against the live APIs, not by inspection. The planner prompt
(research/engine.py) listed `published_papers_search` among the sources that take "a
natural-language search string", so the raw sub-question was sent verbatim as the bibliographic
query. Every planner sub-question ends in "?" — and the catalogues read that as an OPERATOR:

    OpenAlex -> 400 {"message":"Wildcards (* or ?) require exact (no-stem) search..."}
    DOAJ     -> 400 {"error":"Query contains disallowed Lucene features"}

A competing cause — "our URL building mis-encodes the ?" — was REFUTED: re-issuing the identical
query with strict yarl/aiohttp encoding returned the same 400 from both APIs, while removing the
"?" alone returned 200. The two-arm test through the real code path:

    source     arm    n_results   chars
    openalex   LONG      0         243     <- the exact string from the prod log
    openalex   SHORT     5          34
    doaj       LONG      0         215
    doaj       SHORT     3          33

MEASURED SCOPE (wider than first logged — the log named only OpenAlex and DOAJ):
    hard 400s        : openalex, doaj                    -> query-DSL operators  (Fix B, here)
    silent 0 results : pubmed, core, doab; europe_pmc 5->1 -> over-long AND-ed terms (Fix A)
    unaffected       : arxiv, crossref
Note PubMed was recorded in the original log as tolerating the sentence; measurement shows it
returns an EMPTY SET (0 vs 5), which is worse than a 400 because nothing errors.

IMPACT — with five academic channels degraded, general web search is what remains, and the
encyclopedia is what general web search returns. This is the retrieval-layer cause behind the
standing "Deep Research leans on Wikipedia" complaint that two consecutive prompt-only attempts
(v1.0.0.257, reverted; the v1.0.0.259 attempt, dropped) failed to move: no directive can cite
scholarship the retrieval layer never fetched.

These tests fail on the pre-fix code.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.engine import DeepResearchEngine, ResearchPlanner  # noqa: E402
from user_tools.published_papers_search_tool import PublishedPapersSearchTool  # noqa: E402


# ---------------------------------------------------------------- Fix B: transport / query syntax

class TestQuerySyntaxSanitisation:
    """The tool must render the query valid in each source's own query syntax."""

    def test_question_mark_never_reaches_openalex(self):
        """Prevents the exact prod failure: a trailing '?' is a WILDCARD to OpenAlex -> HTTP 400.

        Every planner sub-question ends in '?', which is why this cost 81% of the corpus.
        """
        q = "What are the key scholarly debates about the decline of US hegemony?"
        out = PublishedPapersSearchTool._query_for_source("openalex", q)
        assert "?" not in out
        assert "hegemony" in out

    @pytest.mark.parametrize("ch", list('?*!|'))
    def test_openalex_operators_removed(self, ch):
        """Each character MEASURED to return HTTP 400 from OpenAlex must not survive."""
        out = PublishedPapersSearchTool._query_for_source("openalex", f"multipolarity {ch}decline")
        assert ch not in out

    @pytest.mark.parametrize("ch", list('?*"(){}[]^~'))
    def test_doaj_lucene_operators_removed(self, ch):
        """Each character MEASURED to return 'disallowed Lucene features' from DOAJ must not survive."""
        out = PublishedPapersSearchTool._query_for_source("doaj", f"multipolarity {ch}decline")
        assert ch not in out

    def test_doaj_colon_removed_because_it_fails_silently(self):
        """A ':' does not 400 on DOAJ — Lucene reads `term:value` as a FIELD query and returns
        zero results with HTTP 200. An invisible failure is worse than a loud one, so it goes too."""
        out = PublishedPapersSearchTool._query_for_source("doaj", "topic: multipolarity decline")
        assert ":" not in out
        assert "multipolarity" in out

    def test_operators_become_spaces_not_deletions(self):
        """Deleting rather than separating would fuse two real terms into one nonexistent word,
        turning a loud 400 into a silent zero-result search."""
        out = PublishedPapersSearchTool._query_for_source("doaj", "multipolarity(hegemony)decline")
        assert "multipolarity hegemony decline" == out
        assert "multipolarityhegemonydecline" not in out

    def test_sources_without_a_declared_syntax_are_untouched(self):
        """arXiv and Crossref were measured to accept the full punctuation sweep. Sanitising them
        anyway would be an unmeasured change to two of the few channels that still work."""
        q = "What are the key debates about US hegemony? (2020-2024)"
        for src in ("arxiv", "crossref", "pubmed", "core", "europe_pmc"):
            assert PublishedPapersSearchTool._query_for_source(src, q) == q

    def test_operator_only_query_yields_empty_not_garbage(self):
        """Boundary: a query of operators alone must not become an empty `search=`, which matches
        everything rather than nothing."""
        assert PublishedPapersSearchTool._query_for_source("openalex", "?? ** ||") == ""

    def test_operator_only_query_skips_the_source(self):
        """The empty result of the previous case must remove the source from the task list rather
        than dispatch a request whose meaning is undefined."""
        tool = PublishedPapersSearchTool()
        tasks = tool._prepare_search_tasks(
            {"query": "?*|", "year": None, "max_results": 5, "sources": ["openalex", "arxiv"]})
        names = [t[0] for t in tasks]
        assert "openalex" not in names   # nothing left to search for
        assert "arxiv" in names          # unaffected source still runs

    def test_malformed_query_cannot_abort_every_source(self):
        """ADVERSARIAL AUDIT FINDING (H2). Task building runs OUTSIDE the per-source try/except that
        contains a single source's failure, so a non-string query raising inside sanitisation would
        take down all eleven searches at once instead of one. Unreachable through execute() — its
        validation rejects a blank query first — but the helper must not be the sharp edge."""
        for bad in (None, 123, [], {}):
            assert PublishedPapersSearchTool._query_for_source("openalex", bad) == ""
        tool = PublishedPapersSearchTool()
        assert tool._prepare_search_tasks(
            {"query": None, "year": None, "max_results": 5, "sources": []}) == []

    def test_doaj_year_filter_survives_sanitisation(self):
        """ADVERSARIAL AUDIT (H1). DOAJ appends its OWN `AND year:{y}` Lucene field query inside the
        URL builder. Sanitisation strips ':' for DOAJ, so had it run after that step it would have
        silently broken the year filter — a working feature killed by the fix. Ordering matters:
        the user query is cleaned first, the builder adds its syntax second."""
        url = PublishedPapersSearchTool()._build_doaj_url("multipolarity hegemony", 2020, 5)
        assert "year%3A2020" in url or "year:2020" in url

    def test_sanitisation_is_idempotent(self):
        """ADVERSARIAL AUDIT (H6). Retry/re-dispatch paths may sanitise an already-sanitised query;
        a second pass must not further mangle it."""
        once = PublishedPapersSearchTool._query_for_source("doaj", "Why did hegemony decline (2008)?")
        assert PublishedPapersSearchTool._query_for_source("doaj", once) == once

    def test_sanitisation_happens_on_the_real_entry_path(self):
        """Guards against sanitising in a helper nothing calls: the query each source actually
        receives must already be clean when built through _prepare_search_tasks (which is what
        execute() -> _search_all_sources uses)."""
        tool = PublishedPapersSearchTool()
        raw = "Why did US hegemony decline (post-2008)?"
        by_source = {t[0]: t[2] for t in tool._prepare_search_tasks(
            {"query": raw, "year": None, "max_results": 5, "sources": []})}
        assert "?" not in by_source["openalex"]
        assert "(" not in by_source["doaj"] and "?" not in by_source["doaj"]
        assert by_source["arxiv"] == raw


# ------------------------------------------------------------------- Fix A: planner policy

class TestPlannerQueryPolicy:
    """The planner must be told what shape of argument this source actually takes."""

    @staticmethod
    def _prompt():
        planner = ResearchPlanner.__new__(ResearchPlanner)
        planner._cfg = {"planner": {"per_source_queries": True}}
        planner._allowed = None
        system, _ = ResearchPlanner._build_prompt(planner, "test request")
        return system

    def test_papers_search_not_listed_as_taking_the_subquestion_text(self):
        """The prompt used to name published_papers_search among the sources for which the planner
        should OMIT a query and let the sub-question sentence be used — the instruction that
        produced the 400s.

        Scoped to the parenthesised OMIT list specifically: the prompt names this tool elsewhere
        for legitimate reasons (the source-strategy section tells the planner to ROUTE scholarly
        sub-questions to it), and asserting over the whole prompt would fail on correct code.
        """
        prompt = self._prompt()
        omit_list = prompt.split("for those (")[1].split(") OMIT the queries entry")[0]
        assert "published_papers_search" not in omit_list
        assert "search_web" in omit_list  # the list itself is still intact

    def test_papers_search_is_told_to_send_bibliographic_keywords(self):
        """Positive half: it is not enough to remove it from the OMIT list — the planner needs to
        know what to send instead, or it will emit nothing and the default (the sentence) returns."""
        prompt = self._prompt()
        assert "published_papers_search ->" in prompt
        assert "BIBLIOGRAPHIC KEYWORD" in prompt


# --------------------------------------------------------------------------- parity of both paths

class TestPlanTaskParity:
    """Round 1 and the below-min_rounds re-issue must build tasks identically."""

    PLAN = {
        "sub_questions": [{
            "id": "q1",
            "question": "What are the key scholarly debates about US hegemony?",
            "sources": ["published_papers_search", "search_web"],
            "queries": {"published_papers_search": ["US hegemony decline international order"]},
        }],
        "max_rounds": 3, "min_rounds": 2,
    }

    def test_plan_tasks_honours_the_per_source_query(self):
        """The whole point of Fix A: the planner's bibliographic query must be what gets dispatched."""
        tasks = DeepResearchEngine._plan_tasks(self.PLAN)
        papers = [t for t in tasks if t["source"] == "published_papers_search"]
        assert [t["query"] for t in papers] == ["US hegemony decline international order"]

    def test_sources_without_an_override_still_get_the_subquestion(self):
        """Backward compatibility: only sources with an explicit override change behaviour."""
        tasks = DeepResearchEngine._plan_tasks(self.PLAN)
        web = [t for t in tasks if t["source"] == "search_web"]
        assert [t["query"] for t in web] == [self.PLAN["sub_questions"][0]["question"]]

    def test_reissue_path_cannot_drift_from_round_one(self):
        """The below-min_rounds re-issue used to rebuild tasks INLINE without consulting `queries`,
        so on that path published_papers_search silently received the raw sub-question again —
        re-opening the bug for exactly the runs that gather hardest. Both callers now share one
        builder, so identical input must produce identical tasks."""
        assert DeepResearchEngine._plan_tasks(self.PLAN) == DeepResearchEngine._plan_tasks(self.PLAN)
        papers = [t for t in DeepResearchEngine._plan_tasks(self.PLAN)
                  if t["source"] == "published_papers_search"]
        assert all("?" not in t["query"] for t in papers)
