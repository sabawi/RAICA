"""
RAICA Deep Research Engine — Stage 1
====================================

LLM-driven, minimally-scaffolded research engine. RAICA's role here is strictly:
  1) ask the LLM to PLAN (decompose the request into sub-questions + source strategy),
  2) DISPATCH the sources the LLM chose to RAICA's existing tools,
  3) ask the LLM to ASSESS coverage and decide whether to continue,
  4) loop until the LLM says "sufficient" or config ceilings are hit.

The LLM decides *what* to research and *when it's done*; RAICA only executes JSON.
No keyword lists, no hardcoded source routing, no fallback guessing.

Design notes
------------
- Fully DEPENDENCY-INJECTED so it never imports the server (no circular import) and is
  unit-testable in isolation:
    * `generate_stream`: async callable(prompt: str, **kwargs) -> async iterator[str]
      (in production: llm_manager.generate_stream — the Primary model)
    * `dispatch_tool`:   async callable(tool_name: str, args: str) -> str
      (in production: a thin wrapper over AsyncToolManager.available_functions)
- All limits come from config (config/llm_config.yaml -> deep_research.engine). The LLM
  may propose values; RAICA clamps them to the configured ceilings.

This module implements Stage 1 piece #1 (the planner) first; the dispatcher and the
iterative gather loop build on top of it.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import re
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Extract URLs from tool output for coverage signals + dedup (structural, not semantic).
_URL_RE = re.compile(r'https?://[a-zA-Z0-9./_%?=&:+~#-]+')

# Type aliases for the injected dependencies
GenerateStream = Callable[..., Any]          # async generator: (prompt, **kwargs) -> AsyncIterator[str]
DispatchTool = Callable[[str, str], Awaitable[str]]

# ── Transient-5xx retry policy (resilience for upstream LLM-provider blips) ───────────────────────
# Deep research is long and resource-heavy; a single transient provider 500 shouldn't fail the run.
# The pipeline sets this from config (deep_research.engine.retry). Default = no retry (1 attempt), so
# non-deep-research callers are unaffected. Applies ONLY to 5xx; all other errors fail fast.
_RETRY_MAX_ATTEMPTS = 1
_RETRY_DELAY_SECONDS = 0.0


def configure_retry(max_attempts: int, delay_seconds: float) -> None:
    """Set the transient-5xx retry policy for pipeline LLM calls (called by the pipeline from config)."""
    global _RETRY_MAX_ATTEMPTS, _RETRY_DELAY_SECONDS
    try:
        _RETRY_MAX_ATTEMPTS = max(1, int(max_attempts))
        _RETRY_DELAY_SECONDS = max(0.0, float(delay_seconds))
    except Exception:  # noqa: BLE001 — never let a bad config value break the call path
        _RETRY_MAX_ATTEMPTS, _RETRY_DELAY_SECONDS = 1, 0.0


def _is_transient_5xx(err: Exception) -> bool:
    """True if the error looks like a transient upstream provider 5xx (retryable). Conservative:
    only HTTP 5xx status codes / their standard phrases — never 4xx (client/request errors)."""
    s = str(err).lower()
    if re.search(r'\b(500|502|503|504)\b', s):
        return True
    return any(k in s for k in (
        "internal server error", "bad gateway", "service unavailable", "gateway timeout"))


# Per-run async callback (contextvar so concurrent runs don't cross-talk) used to STREAM keepalive
# notices to the client during retry waits, so the stream doesn't go silent (and the client read
# timeout doesn't trip) while we wait out a provider blip. Set by the server's DR branch BEFORE it
# creates the pipeline task, so the task's copied context includes it. Separate from normal progress
# (which clients can suppress) — retry notices are exceptional and always worth showing.
_retry_notice_var: "contextvars.ContextVar" = contextvars.ContextVar("dr_retry_notice", default=None)


def set_retry_notice_callback(cb) -> None:
    """Register the per-run retry-notice callback (async callable(str)). Call before creating the
    deep-research task. None disables notices."""
    _retry_notice_var.set(cb)


def extract_json_object(text: str) -> Dict[str, Any]:
    """
    Parse a JSON object from an LLM response (handles markdown fences and surrounding prose).

    Structural parsing only — extracts JSON the LLM emitted; does not interpret meaning.
    """
    s = (text or "").strip()
    if s.startswith("```json"):
        s = s[7:]
    elif s.startswith("```"):
        s = s[3:]
    if s.endswith("```"):
        s = s[:-3]
    s = s.strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        # Grab the outermost {...} block if the model wrapped it in prose.
        m = re.search(r'\{.*\}', s, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise


def salvage_json_map(raw: str) -> Dict[str, Any]:
    """Best-effort recovery of a flat {key: value} JSON map when the whole object won't parse (e.g. ONE
    entry has an unescaped quote in a string, or the output was truncated). Scans for top-level
    `"key": <json-value>` pairs and decodes each value INDEPENDENTLY with json.JSONDecoder.raw_decode,
    skipping any entry that won't parse. Structural only (no meaning interpretation) — lets a caller keep
    the entries that DID parse instead of collapsing the whole batch. Never raises; returns {} on total loss.

    Note: this also recovers nested keys (e.g. 'tier'/'reason' inside a value object) as spurious top-level
    entries — harmless to callers that look up only their known keys and ignore the rest."""
    out: Dict[str, Any] = {}
    if not raw or not isinstance(raw, str):
        return out
    dec = json.JSONDecoder()
    for m in re.finditer(r'"((?:[^"\\]|\\.)*)"\s*:\s*', raw):
        try:
            value, _ = dec.raw_decode(raw, m.end())
        except Exception:
            continue
        out[m.group(1)] = value
    return out


async def _collect_stream(generate_stream: GenerateStream, prompt: str, **kwargs) -> str:
    """
    Run an injected streaming LLM call and return the full text.

    Maps our `max_tokens` intent to `num_predict` as well: the Ollama provider reads ONLY
    `num_predict` (it ignores `max_tokens`), so without this our output-length config would be
    silently dropped and every call would fall back to the model default. OpenAI/Gemini providers
    read `max_tokens` and ignore the extra `num_predict`, so this is safe across providers.
    """
    if "max_tokens" in kwargs and "num_predict" not in kwargs:
        kwargs["num_predict"] = kwargs["max_tokens"]
    # Retry transient upstream 5xx (e.g. Ollama-cloud "500 Internal Server Error") per the configured
    # policy, waiting between tries to let the provider recover. Partial chunks from a failed attempt
    # are discarded — we restart the call. 4xx/other errors are NOT retried (re-raised immediately).
    attempt = 0
    while True:
        attempt += 1
        try:
            chunks: List[str] = []
            async for chunk in generate_stream(prompt, **kwargs):
                chunks.append(chunk)
            return "".join(chunks)
        except Exception as e:  # noqa: BLE001
            if attempt < _RETRY_MAX_ATTEMPTS and _is_transient_5xx(e):
                logger.warning(
                    "🔁 Transient provider 5xx (attempt %d/%d): %s — retrying in %ss",
                    attempt, _RETRY_MAX_ATTEMPTS, str(e)[:160], _RETRY_DELAY_SECONDS)
                _notify = _retry_notice_var.get()

                async def _emit(msg: str):
                    if _notify:
                        try:
                            await _notify(msg)
                        except Exception:  # noqa: BLE001 — a notice failure must never break the run
                            pass

                await _emit(f"⏳ The research model host returned a temporary error — retrying "
                            f"(attempt {attempt + 1}/{_RETRY_MAX_ATTEMPTS}) in ~{int(_RETRY_DELAY_SECONDS)}s…")
                # Sleep in steps, sending a periodic heartbeat so the stream stays warm and the user
                # sees it's still working — but not so often it spams the live view. 40s keeps each
                # gap well under client read-timeouts while emitting only a couple of lines per wait.
                waited = 0.0
                while waited < _RETRY_DELAY_SECONDS:
                    step = min(40.0, _RETRY_DELAY_SECONDS - waited)
                    await asyncio.sleep(step)
                    waited += step
                    if waited < _RETRY_DELAY_SECONDS:
                        await _emit(f"⏳ still waiting for the model host… retrying in "
                                    f"~{int(_RETRY_DELAY_SECONDS - waited)}s")
                continue
            raise


# ── data-charting feature hooks (deep_research.data_charts sibling config; see docs/DESIGN_data_charts.md) ──
def _data_charts_cfg() -> Dict[str, Any]:
    """Delegate to the SINGLE source of truth (datasources.data_charts_cfg) so planner + tool never diverge."""
    from datasources import data_charts_cfg
    return data_charts_cfg()


def _data_charts_enabled() -> bool:
    """Delegate to the SINGLE source of truth (datasources.data_charts_enabled) — env override + config."""
    from datasources import data_charts_enabled
    return data_charts_enabled()


def _data_source_catalogs() -> List[Dict[str, Any]]:
    """Registry catalogs, filtered to data_charts.sources.allowed — what the planner shows the LLM."""
    try:
        from datasources.registry import all_catalogs
        allowed = set(_data_charts_cfg().get("sources", {}).get("allowed", []) or [])
        return [c for c in all_catalogs() if (not allowed or c.get("name") in allowed)]
    except Exception:  # noqa: BLE001
        return []


class ResearchPlanner:
    """
    Stage 1, piece #1: turn a user research request into a structured plan.

    Output schema (what the LLM must return, what RAICA acts on):
        {
          "sub_questions": [
             {"id": "q1", "question": "...", "sources": ["search_web", ...], "priority": 1}
          ],
          "max_rounds": <int>,
          "stop_condition": "<plain-language completion criterion>"
        }

    RAICA validates/normalizes the plan: clamps breadth to max_sub_questions, drops any
    source not in the configured allow-list, clamps max_rounds to the ceiling, and ensures
    stable ids. It never invents sub-questions — if the LLM returns none, that's an error.
    """

    def __init__(self, generate_stream: GenerateStream, engine_config: Dict[str, Any]):
        self._generate_stream = generate_stream
        self._cfg = engine_config or {}

    @property
    def _allowed_sources(self) -> List[str]:
        base = list(self._cfg.get("sources", {}).get("allowed", []))
        # data-charting: offer search_datasets ONLY when enabled (and per-source queries are on, since the
        # tool needs a JSON arg via the queries map). Off by default → prod source list unchanged.
        if _data_charts_enabled() and self._per_source_queries and "search_datasets" not in base:
            base.append("search_datasets")
        # compare_datasets = the CROSS-SOURCE variant (2+ indicators, possibly different sources, on ONE
        # chart) — offered under the same gate so relationship questions can be answered with one visual.
        if _data_charts_enabled() and self._per_source_queries and "compare_datasets" not in base:
            base.append("compare_datasets")
        return base

    @property
    def _max_sub_questions(self) -> int:
        return int(self._cfg.get("planner", {}).get("max_sub_questions", 6))

    @property
    def _max_rounds_ceiling(self) -> int:
        return int(self._cfg.get("loop", {}).get("max_rounds_ceiling", 4))

    @property
    def _per_source_queries(self) -> bool:
        """v1.0.0.157: allow the planner to emit a per-source `queries` map so a source whose
        argument is NOT a natural-language search string (e.g. comprehensive_stock_analyzer wants
        {"ticker":"PLTR","detailed":true}) receives the EXACT arg it expects instead of the
        sub-question text. Inherently backward-safe (absent entry → sub-question text). Default
        true; set deep_research.engine.planner.per_source_queries=false for a one-line rollback to
        v1.0.0.155 behavior (prompt never mentions `queries`, normalize sets {}, Round 1 uses the
        sub-question text for every source)."""
        return bool(self._cfg.get("planner", {}).get("per_source_queries", True))

    def _build_prompt(self, user_request: str) -> tuple[str, str]:
        """Returns (system_prompt, user_prompt). Instructions go in system; data in user."""
        allowed = ", ".join(self._allowed_sources) or "search_web"
        # v1.0.0.157: optional per-source `queries` map (see _per_source_queries). Backward-safe:
        # when disabled (or the LLM omits it) Round 1 uses the sub-question text exactly as before.
        _psq = self._per_source_queries
        _queries_guidance = (
            "- PER-SOURCE QUERY (optional `queries` map per sub-question): MOST sources take a "
            "natural-language search string as their argument — for those (search_web, "
            "get_news_summaries, wikipedia_query, published_papers_search, get_sec_filings, "
            "document_search) OMIT the queries entry; the sub-question text is the correct query "
            "and is used by default. ONLY for sources whose argument is NOT a natural-language "
            "search string, add a `queries` entry mapping that source name to the EXACT argument "
            "string the tool expects:\n"
            "  * comprehensive_stock_analyzer -> a JSON string {\"ticker\":\"PLTR\",\"detailed\":true} "
            "(single ticker; detailed=true for fundamentals/DCF/ratios/projections).\n"
            "  * get_stock_and_company_data -> \"PLTR\" (bare ticker) or {\"symbol\":\"PLTR\"}.\n"
            "  * MULTIPLE stocks/instances under one sub-question: make the value a LIST of those "
            "arg strings, e.g. {\"comprehensive_stock_analyzer\": "
            "[\"{\\\"ticker\\\":\\\"PLTR\\\",\\\"detailed\\\":true}\", "
            "\"{\\\"ticker\\\":\\\"MSFT\\\",\\\"detailed\\\":true}\"]} — each is dispatched as a "
            "separate call. (Alternatively, split multi-stock into one sub-question per stock.)\n"
        ) if _psq else ""
        _queries_schema = (
            ', "queries": {"<source_name>": "<arg_string> or [<arg_string>, ...]"}'
        ) if _psq else ""
        # Cluster B (docs/RAICA_DR_ADVERSARIAL_BALANCE.md, Phase 2) — reach PRIMARY peer-reviewed scholarship,
        # not tertiary wikis/SEO, on scholarly/historical/humanities questions; seek competing models +
        # historiography + the opposing side. Gated + reversible; policy language, LLM-judged (no topic lists).
        _gq_on = bool(self._cfg.get("planner", {}).get("gather_quality", {}).get("enabled", True))
        _source_strategy = (
            "- SOURCE STRATEGY — REACH PRIMARY, PEER-REVIEWED SCHOLARSHIP; do NOT settle for tertiary "
            "summaries:\n"
            "  * For any SCHOLARLY / HISTORICAL / SCIENTIFIC / HUMANITIES claim — or any request asking for "
            "evidence-based, researched, or peer-reviewed grounding — route the LOAD-BEARING sub-questions to "
            "published_papers_search: it reaches the peer-reviewed AND humanities/cross-disciplinary "
            "literature (OpenAlex, Crossref, CORE, DOAJ, DOAB, Semantic Scholar, Internet Archive, "
            "arXiv/PubMed). That is the citation of record for such claims.\n"
            "  * Use wikipedia / search_web only for ORIENTATION, terminology, or where the scholarly "
            "literature is genuinely thin — NEVER as the source of record for a claim the academic "
            "literature covers. A tertiary wiki or an advocacy/SEO page is not acceptable ground for a "
            "load-bearing scholarly claim.\n"
            "  * SEEK THE COMPETING MODELS AND THE HISTORIOGRAPHY: for a debated topic add sub-questions that "
            "surface the rival scholarly models/schools (who argues what, on what evidence) and how the "
            "debate itself developed — not just the current topline finding.\n"
            "  * ADVERSARIAL DECOMPOSITION: for a contested / prove-or-disprove / worldview question, add "
            "sub-question(s) that deliberately seek the STRONGEST OPPOSING and critical scholarship, so the "
            "evidence pool is not one-sided from the start.\n"
            "  * news for current events, get_sec_filings for filings, document_search for the user's own "
            "documents.\n"
        ) if _gq_on else (
            "- Prefer academic sources (published_papers_search) for scholarly/scientific claims, "
            "news for current events, wikipedia for background, search_web for general/web coverage, "
            "get_sec_filings for company filings, document_search for the user's own documents.\n"
        )
        # Data-charting (deep_research.data_charts): when enabled, teach the planner to route explicit
        # chart/plot requests to search_datasets and hand it the catalog to pick a real source+measure
        # (numbers-by-reference). Empty string when the feature is off → planner prompt is unchanged.
        _dc_guidance = ""
        if _data_charts_enabled() and _psq:
            _cats = _data_source_catalogs()
            if _cats:
                _cat_lines = "\n".join(
                    f"    - {c['name']} (tier {c.get('source_tier')}, geo {c.get('geo')}, "
                    f"{c.get('coverage_years', '')}; value_kind ∈ {c.get('value_kinds')}): "
                    f"measures = {', '.join(sorted(c.get('measures', {}).keys()))}"
                    + (f"\n        {c['note'].strip()}" if c.get('note') else "")
                    for c in _cats)
                _dc_guidance = (
                    "- CHART / PLOT / GRAPH REQUESTS — REAL DATA VIA search_datasets: if the user asks to "
                    "chart/plot/graph numeric data (a trend over time, a comparison, or a relationship), add a "
                    "sub-question routed to search_datasets. It fetches a REAL series from a curated "
                    "authoritative source and renders the chart itself — it NEVER invents numbers. Choose the "
                    "SINGLE best-matching source+measure from the DATA SOURCES CATALOG below (prefer a keyless "
                    "source at comparable quality). Put a search_datasets entry in that sub-question's "
                    "`queries` map whose value is a JSON request: {\"source\":\"<catalog source>\","
                    "\"measure\":\"<catalog measure>\",\"geo\":\"<code, optional>\",\"from_year\":<int opt>,"
                    "\"to_year\":<int opt>,\"value_kind\":\"<rate|count|value>\",\"chart_kind\":"
                    "\"line|bar|scatter|auto\"}. `source` and `measure` MUST be COPIED VERBATIM from the "
                    "catalog below — do NOT pluralize, append (e.g. '-total'), abbreviate, or reword a measure "
                    "code. `geo` is the source's geography code (see each source's geo note; for world_bank an "
                    "ISO-3166 country code such as USA, EGY, CHN — WLD = world). If no listed source/measure "
                    "fits, do NOT route to search_datasets (the chart is omitted, never faked):\n"
                    f"{_cat_lines}\n"
                    "- MULTI-INDICATOR / RELATIONSHIP QUESTIONS — USE compare_datasets INSTEAD: when the "
                    "question is about how indicators MOVE TOGETHER, or is a socioeconomic/sociopolitical "
                    "issue that several indicators illuminate (e.g. 'did crime track unemployment and "
                    "inequality?', 'compare growth with poverty'), route ONE sub-question to "
                    "compare_datasets rather than several separate search_datasets calls. It puts 2-6 real "
                    "series — ACROSS DIFFERENT SOURCES if useful — on ONE chart with a shared time axis "
                    "(auto-indexing them when their units differ), which is what makes the relationship "
                    "readable. Its `queries` value is a JSON request: {\"series\":[{\"source\":\"<catalog "
                    "source>\",\"measure\":\"<catalog measure>\",\"geo\":\"<code opt>\",\"value_kind\":"
                    "\"<rate|count|value>\"}, ...],\"title\":\"<short title, <55 chars>\","
                    "\"from_year\":<int opt>,\"to_year\":<int opt>}. The same VERBATIM source/measure rule "
                    "applies to every entry.\n")
        system = (
            "You are the planner for a deep-research engine. Decompose the user's request "
            "into focused, non-overlapping SUB-QUESTIONS that, answered together, fully "
            "satisfy the request. For each sub-question, choose which research SOURCES are "
            "most appropriate, picking ONLY from this allowed list:\n"
            f"  {allowed}\n\n"
            "Guidance:\n"
            f"- Produce at most {self._max_sub_questions} sub-questions (fewer if that suffices).\n"
            + _source_strategy +
            "- STOCK / VALUATION / COMPANY-FINANCIALS topics (a named ticker or company whose price, "
            "valuation multiples — P/E, P/S, EV/EBITDA, P/B, PEG — fundamentals, financial statements, "
            "DCF, analyst targets, or prospects are wanted): route the DATA sub-questions to "
            "comprehensive_stock_analyzer FIRST (it returns structured real-time price + fundamentals + "
            "ratios + statements via yfinance; pass detailed=true when fundamental analysis/DCF/projections "
            "are requested) and get_stock_and_company_data for quick quotes. Use these BEFORE search_web — "
            "they return the exact figures search_web can only scrape for (and often can't reach). Reserve "
            "search_web/news for QUALITATIVE context the structured tools don't cover (recent news, analyst "
            "commentary, insider trading, product/partnership developments).\n"
            "- QUANTITATIVE / DATA-DRIVEN topics (economics, energy, markets, prices, demographics, climate, "
            "public health): the answer needs CONCRETE FIGURES and time-series (prices, production, shares, "
            "rates, before/after and by-region/by-year values), not just commentary. Add sub-questions that "
            "HUNT specific numbers; route them to structured_data_search (official statistics / datasets — "
            "e.g. World Bank, energy/economic data) when it is in the allowed list, and ALSO write search_web "
            "queries that NAME the specific figure/series and target sources that PUBLISH data (statistical "
            "agencies, datasets, data portals) rather than pure news narrative.\n"
            + _dc_guidance +
            "- Assign each sub-question a priority (1 = highest).\n"
            "- ENUMERATION REQUESTS: if the request asks to LIST/TABULATE/ENUMERATE a set of items "
            "(a table, 'all the …', 'the earliest/oldest/first …', a catalog), make sure the "
            "sub-questions will surface the COMPLETE set of qualifying items — not just the famous ones. "
            "Include a sub-question aimed at discovering the full roster of items that fit the request's "
            "qualifier (especially boundary cases, e.g. for 'earliest' the genuinely oldest/least-famous "
            "items), plus sub-questions for the per-item attributes the request asks for.\n"
            "- Propose max_rounds (1-" f"{self._max_rounds_ceiling}" ") for an iterative gather loop, "
            "and a clear stop_condition describing when research is sufficient.\n"
            "- Propose min_rounds (1-" f"{self._max_rounds_ceiling}" "): the MINIMUM rounds to run before "
            "the loop may stop early. For ENUMERATION requests set min_rounds to at least 2 (ideally 3) — "
            "a single round rarely surfaces the COMPLETE set of items, so enumeration must keep gathering "
            "across multiple rounds before concluding. For simple/single-fact requests, min_rounds 1 is fine. "
            "Also make the stop_condition enumeration-aware: for a list/table, research is NOT sufficient "
            "until the full roster of qualifying items appears corroborated across sources.\n"
            + _queries_guidance
            + "\nRespond with STRICT JSON only, no prose, in exactly this shape:\n"
            '{"sub_questions": [{"id": "q1", "question": "...", "sources": ["search_web"], '
            '"priority": 1' + _queries_schema + '}], "max_rounds": 3, "min_rounds": 1, "stop_condition": "..."}'
        )
        user = f"USER REQUEST:\n{user_request}"
        return system, user

    def _normalize(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        """Validate + clamp the LLM's plan to configured limits. RAICA owns the limits."""
        raw_sqs = plan.get("sub_questions") or []
        if not isinstance(raw_sqs, list) or not raw_sqs:
            raise ValueError("planner returned no sub_questions")

        allowed = set(self._allowed_sources)
        normalized: List[Dict[str, Any]] = []
        for idx, sq in enumerate(raw_sqs[: self._max_sub_questions], start=1):
            if not isinstance(sq, dict):
                continue
            question = str(sq.get("question", "")).strip()
            if not question:
                continue
            # Keep only sources RAICA can actually dispatch; default to search_web if none survive.
            srcs = [s for s in (sq.get("sources") or []) if s in allowed]
            if not srcs:
                srcs = ["search_web"] if "search_web" in allowed or not allowed else [next(iter(allowed))]
            try:
                priority = int(sq.get("priority", idx))
            except (TypeError, ValueError):
                priority = idx
            # v1.0.0.157: optional per-source query override. Backward-safe: {} when disabled or
            # absent → Round 1 uses the sub-question text for every source (v1.0.0.155 behavior).
            # Value may be a string (one call) or a list of strings (one call per entry — e.g. one
            # sub-question spanning PLTR+MSFT dispatches comprehensive_stock_analyzer twice). Only
            # entries for sources actually assigned to this sub-question are kept.
            queries: Dict[str, List[str]] = {}
            if self._per_source_queries and isinstance(sq.get("queries"), dict):
                for src, val in sq["queries"].items():
                    if src not in srcs:
                        continue
                    vals = val if isinstance(val, list) else [val]
                    clean = [str(v).strip() for v in vals if str(v).strip()]
                    if clean:
                        queries[str(src)] = clean
            normalized.append({
                "id": str(sq.get("id") or f"q{idx}"),
                "question": question,
                "sources": srcs,
                "priority": priority,
                "queries": queries,
            })

        if not normalized:
            raise ValueError("planner sub_questions did not survive normalization")

        normalized.sort(key=lambda q: q["priority"])

        try:
            max_rounds = int(plan.get("max_rounds", 3))
        except (TypeError, ValueError):
            max_rounds = 3
        max_rounds = max(1, min(max_rounds, self._max_rounds_ceiling))

        # min_rounds: floor before the loop may stop early (planner sets ≥2 for enumeration).
        try:
            min_rounds = int(plan.get("min_rounds", 1))
        except (TypeError, ValueError):
            min_rounds = 1
        min_rounds = max(1, min(min_rounds, max_rounds))  # never exceed max_rounds

        return {
            "sub_questions": normalized,
            "min_rounds": min_rounds,
            "max_rounds": max_rounds,
            "stop_condition": str(plan.get("stop_condition", "")).strip()
                              or "All sub-questions have at least two corroborating sources.",
        }

    def _fallback_plan(self, user_request: str) -> Dict[str, Any]:
        """
        Minimal plan used when the planner LLM returns empty/unparseable output twice.
        Keeps deep research alive (gather still runs) instead of crashing the whole request.
        Searches the request directly across the broadly-useful sources.
        """
        allowed = set(self._allowed_sources)
        srcs = [s for s in ("search_web", "wikipedia_query", "published_papers_search") if s in allowed] \
            or ([next(iter(allowed))] if allowed else ["search_web"])
        logger.warning("🧭 Planner unavailable — using fallback single-sub-question plan")
        return {
            "sub_questions": [{"id": "q1", "question": user_request[:500], "sources": srcs, "priority": 1}],
            "min_rounds": 1,
            "max_rounds": min(2, self._max_rounds_ceiling),
            "stop_condition": "Sufficient relevant sources gathered for the request.",
        }

    async def plan(self, user_request: str) -> Dict[str, Any]:
        """
        Produce a validated research plan. The planner LLM call can transiently return empty/
        garbage (observed: deepseek-v4-pro:cloud failing twice in a ~30s window, yet 4/4 reliable
        minutes later — a transient cloud blip, NOT a model-quality issue, so we do NOT swap models).
        Defense: up to 3 attempts with backoff between them (so a retry doesn't land in the same
        failure window), then a minimal fallback plan rather than crashing the whole run.
        """
        system_prompt, prompt = self._build_prompt(user_request)
        max_attempts = 3
        backoffs = [3, 6]  # seconds to wait before retry 2 and retry 3
        for attempt in range(1, max_attempts + 1):
            try:
                raw = await _collect_stream(
                    self._generate_stream, prompt, system_prompt=system_prompt,
                    temperature=0.1, max_tokens=1200, stream=False
                )
                plan = extract_json_object(raw)
                normalized = self._normalize(plan)
                logger.info(
                    "🧭 Research plan: %d sub-questions, rounds=%d-%d",
                    len(normalized["sub_questions"]), normalized["min_rounds"], normalized["max_rounds"],
                )
                return normalized
            except Exception as e:  # noqa: BLE001 — empty/garbage planner output is transient
                if attempt < max_attempts:
                    wait = backoffs[attempt - 1]
                    logger.warning("🧭 Planner attempt %d/%d failed (%s) — retrying in %ds",
                                   attempt, max_attempts, e, wait)
                    await asyncio.sleep(wait)
                else:
                    logger.warning("🧭 Planner attempt %d/%d failed (%s) — using fallback",
                                   attempt, max_attempts, e)
        return self._fallback_plan(user_request)


class DeepResearchEngine:
    """
    Stage 1 orchestrator: PLAN -> (DISPATCH -> ASSESS) loop -> evidence pool.

    Dependency-injected (no server import, no hot-path touch):
      * generate_stream(prompt, **kwargs) -> async iterator[str]   (Primary LLM)
      * dispatch_tool(tool_name, query)   -> awaitable[str]        (existing tools)

    The LLM owns the research decisions (plan, when to stop, what to search next).
    RAICA owns only execution + the config-enforced budget ceilings.
    """

    def __init__(self, generate_stream: GenerateStream, dispatch_tool: DispatchTool,
                 engine_config: Dict[str, Any]):
        self._gen = generate_stream
        self._dispatch = dispatch_tool
        self._cfg = engine_config or {}
        self._planner = ResearchPlanner(generate_stream, engine_config)

    @property
    def _allowed_sources(self) -> set:
        base = set(self._cfg.get("sources", {}).get("allowed", []))
        if _data_charts_enabled():          # dispatch filter must also allow search_datasets when enabled
            base.add("search_datasets")
            base.add("compare_datasets")    # …and its cross-source multi-series counterpart
        return base

    @property
    def _wall_clock(self) -> float:
        return float(self._cfg.get("loop", {}).get("wall_clock_seconds", 240))

    async def _safe_dispatch(self, source: str, query: str) -> str:
        """Run one tool; never raise — a failed source must not abort the round."""
        try:
            out = await self._dispatch(source, query)
            return out if isinstance(out, str) else str(out)
        except Exception as e:  # noqa: BLE001 — a single source failure is non-fatal
            logger.warning("🔎 source '%s' failed for %r: %s", source, query[:60], e)
            return f"[source '{source}' returned no usable result: {e}]"

    async def _dispatch_round(self, tasks: List[Dict[str, Any]], round_num: int,
                              executed: set) -> List[Dict[str, Any]]:
        """Dispatch a round's (source, query) tasks concurrently; return new evidence items."""
        pending: List[Tuple[Dict[str, Any], Any]] = []
        for t in tasks:
            source = t.get("source")
            query = (t.get("query") or "").strip()
            if source not in self._allowed_sources or not query:
                continue
            key = (source, query.lower())
            if key in executed:
                continue
            executed.add(key)
            pending.append((t, self._safe_dispatch(source, query)))

        if not pending:
            return []

        outputs = await asyncio.gather(*[c for _, c in pending], return_exceptions=True)
        items: List[Dict[str, Any]] = []
        for (t, _), out in zip(pending, outputs):
            content = out if isinstance(out, str) else f"[dispatch error: {out}]"
            items.append({
                "sub_question_id": t.get("sub_question_id"),
                "question": t.get("question", ""),
                "source": t.get("source"),
                "query": t.get("query"),
                "round": round_num,
                "content": content,
                "urls": sorted(set(_URL_RE.findall(content))),
                "chars": len(content),
            })
        logger.info("🔎 Round %d: dispatched %d source(s), gathered %d evidence item(s)",
                    round_num, len(pending), len(items))
        return items

    def _coverage_summary(self, evidence: List[Dict[str, Any]], per_item_chars: int = 280) -> str:
        """Compact signal of what's been gathered — NOT the full content (keeps assess prompt small)."""
        lines = []
        for e in evidence:
            snippet = re.sub(r'\s+', ' ', e["content"])[:per_item_chars]
            # Cluster B (#1): expose the source DOMAINS so the assessor can judge source QUALITY
            # (journals/edu/gov vs wikis/blogs/advocacy), not just the tool. Compact — up to 4 distinct.
            _doms = sorted({re.sub(r'^https?://(www\.)?([^/]+).*$', r'\2', u) for u in (e.get("urls") or []) if u})
            _dom_tag = (", ".join(_doms[:4]) + ("…" if len(_doms) > 4 else "")) if _doms else "no-url"
            lines.append(
                f"[{e['sub_question_id']} | {e['source']} | r{e['round']} | "
                f"{e['chars']} chars | src: {_dom_tag}] {snippet}"
            )
        return "\n".join(lines)

    async def _assess(self, user_request: str, plan: Dict[str, Any],
                      evidence: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Ask the LLM whether coverage is sufficient and, if not, what to search next."""
        allowed = ", ".join(sorted(self._allowed_sources)) or "search_web"
        sq_list = "\n".join(f"- {sq['id']}: {sq['question']}" for sq in plan["sub_questions"])
        _chase = bool(self._cfg.get("synthesis", {}).get("source_provenance", {}).get("chase_primary", False))
        system_prompt = (
            "You are the coverage assessor for a deep-research engine. Given the user's request, "
            "the planned sub-questions, the stop_condition, and a summary of evidence gathered so "
            "far, decide whether research is SUFFICIENT or NEEDS_MORE.\n\n"
            "Reason from the user's ACTUAL question backward: what must be established to REACH A "
            "VERIFIABLE ANSWER? Evidence is SUFFICIENT only when it can support that answer end to end. "
            "A genuine gap is an unanswered part of that reasoning — or a load-bearing claim with too few "
            "independent sources — NOT merely more material on a point already settled.\n\n"
            f"If NEEDS_MORE, propose targeted next_queries using ONLY these sources: {allowed}. "
            "Each next query must address a specific gap (an unanswered sub-question or a claim "
            "with too few independent sources). Do not repeat queries already run.\n\n"
            "Respond with STRICT JSON only, no prose:\n"
            '{"status": "sufficient" | "needs_more", "gaps": ["..."], '
            '"next_queries": [{"sub_question_id": "q1", "source": "search_web", "query": "..."}]}'
        )
        if _chase:
            # chase_primary (docs/RAICA_SOURCE_PROVENANCE.md Phase 2 / RAICA_DR_SOURCE_RELEVANCE.md): drive the
            # gather loop to find the ORIGIN, not settle for secondary restatements. Semantic — the LLM judges
            # primary-vs-secondary from the evidence (no hardcoded source lists).
            system_prompt += (
                "\n\nPRIMARY-SOURCE CHASE (priority): For EACH sub-question, judge whether the evidence already "
                "includes a PRIMARY source (an original document/record/chronicle, first-hand account, dataset, "
                "court ruling/legislation/filing, or peer-reviewed study) — or ONLY SECONDARY coverage "
                "(encyclopedias, news write-ups, aggregators, explainers). For any sub-question resting ONLY on "
                "secondary sources, set status=\"needs_more\" and add a targeted next_query aimed specifically at "
                "locating the PRIMARY source (name the likely document/author/record/dataset where you can). "
                "Prefer chasing the ORIGIN over adding more secondary restatements — but do NOT invent or force a "
                "primary that does not exist; if none is plausibly findable, say so in gaps and move on."
            )
        # Cluster B / #1 — SOURCE-QUALITY breakout (reuses the gather_quality flag). Mid-gather, upgrade the
        # source quality when a scholarly topic came back tertiary/low-quality (the Nicaea residual). Policy
        # language, LLM-judged from the source tool + domains; bounded by max_rounds; reversible via the flag.
        if bool(self._cfg.get("planner", {}).get("gather_quality", {}).get("enabled", True)):
            system_prompt += (
                "\n\nSOURCE-QUALITY BREAKOUT: for a SCHOLARLY / HISTORICAL / SCIENTIFIC / HUMANITIES topic, also "
                "judge the QUALITY of the sources behind each load-bearing sub-question (use the source tool and "
                "the domains shown). If a sub-question's evidence rests on POPULAR or low-quality tertiary sources "
                "(general-web snippets, wikis, personal blogs, advocacy/apologetics sites) and LACKS peer-reviewed "
                "or reputable scholarship — in particular if NOTHING was gathered via published_papers_search for "
                "it — set status=\"needs_more\" and add a next_query that UPGRADES quality: route it to "
                "published_papers_search, or a search_web query NAMING reputable/academic targets (university-"
                "press works, period reference encyclopedias, named scholars/journals). Prefer upgrading source "
                "QUALITY over adding more of the same tier — no hardcoded source lists. Do NOT apply this to "
                "current-events, quantitative-data, or company-financials topics, where web/structured sources "
                "are the correct sources."
            )
        prompt = (
            f"USER REQUEST:\n{user_request}\n\n"
            f"STOP CONDITION:\n{plan.get('stop_condition', '')}\n\n"
            f"SUB-QUESTIONS:\n{sq_list}\n\n"
            f"EVIDENCE GATHERED (compact signals only):\n{self._coverage_summary(evidence)}"
        )
        # On ANY assessment failure (call or parse), stop the loop gracefully — we already
        # have the evidence gathered so far; never lose a round to a transient assess error.
        try:
            raw = await _collect_stream(self._gen, prompt, system_prompt=system_prompt,
                                        temperature=0.1, max_tokens=900, stream=False)
            data = extract_json_object(raw)
        except Exception as e:  # noqa: BLE001
            logger.warning("🧪 Gap-assessment failed (%s) → treating as sufficient", e)
            return {"status": "sufficient", "gaps": [], "next_queries": []}
        status = "needs_more" if str(data.get("status", "")).lower() == "needs_more" else "sufficient"
        return {"status": status, "gaps": data.get("gaps", []),
                "next_queries": data.get("next_queries", [])}

    async def run(self, user_request: str, on_progress: Optional[Callable] = None) -> Dict[str, Any]:
        """
        Execute the full Stage 1 flow and return the evidence pool + plan + metadata.
        Fail loud on planner failure; individual source failures are tolerated.

        on_progress: optional async callable(str) for streaming status updates.
        """
        async def emit(msg: str):
            if on_progress:
                await on_progress(msg)

        start = time.monotonic()
        await emit("Planning sub-questions…")
        plan = await self._planner.plan(user_request)
        plan_seconds = round(time.monotonic() - start, 1)
        max_rounds = plan["max_rounds"]
        min_rounds = plan.get("min_rounds", 1)
        await emit(f"Planned {len(plan['sub_questions'])} sub-questions "
                   f"(rounds: {min_rounds}-{max_rounds}).")
        gather_start = time.monotonic()

        evidence: List[Dict[str, Any]] = []
        executed: set = set()

        # Round 1 tasks come straight from the plan. v1.0.0.157: if the planner emitted a
        # per-source `queries` override for a source, dispatch one task per provided arg string
        # (list → multiple calls, e.g. several tickers under one sub-question); otherwise the
        # sub-question text is the query (unchanged v1.0.0.155 behavior). _dispatch_round de-dupes
        # by (source, query) so duplicate arg strings never run twice.
        tasks = []
        for sq in plan["sub_questions"]:
            _sq_queries = sq.get("queries", {}) or {}
            for src in sq["sources"]:
                _arg_strings = _sq_queries.get(src)
                if _arg_strings:
                    for _q in _arg_strings:
                        tasks.append({"sub_question_id": sq["id"], "question": sq["question"],
                                      "source": src, "query": _q})
                else:
                    tasks.append({"sub_question_id": sq["id"], "question": sq["question"],
                                  "source": src, "query": sq["question"]})

        round_num = 1
        stop_reason = "max_rounds"
        while True:
            await emit(f"Round {round_num}: searching {len(tasks)} source(s)…")
            new_items = await self._dispatch_round(tasks, round_num, executed)
            evidence.extend(new_items)
            await emit(f"Round {round_num}: gathered {len(new_items)} result(s) "
                       f"({sum(e['chars'] for e in evidence):,} chars total).")

            if round_num >= max_rounds:
                stop_reason = "max_rounds"
                break
            if time.monotonic() - start > self._wall_clock:
                stop_reason = "wall_clock"
                break

            # Always ask the assessor what to search next; but honor the min_rounds floor —
            # for enumeration the planner sets ≥2 so a single round's thin evidence can't end
            # gathering before the full roster is surfaced. Below the floor, a "sufficient"
            # verdict is overridden and we keep gathering.
            assessment = await self._assess(user_request, plan, evidence)
            below_floor = round_num < min_rounds
            if assessment["status"] == "sufficient" and not below_floor:
                stop_reason = "sufficient"
                break
            if assessment["status"] == "sufficient" and below_floor:
                logger.info("🧭 Round %d: assessor said sufficient but below min_rounds=%d — continuing",
                            round_num, min_rounds)

            next_queries = assessment.get("next_queries") or []
            tasks = [
                {"sub_question_id": q.get("sub_question_id"),
                 "question": q.get("query", ""),
                 "source": q.get("source"), "query": q.get("query", "")}
                for q in next_queries
                if q.get("source") in self._allowed_sources and (q.get("query") or "").strip()
            ]
            # Below the floor with no proposed queries: re-issue the plan's sub-questions to
            # broaden the pool (dedup skips already-run source+query pairs) rather than stopping.
            if not tasks and below_floor:
                tasks = [
                    {"sub_question_id": sq["id"], "question": sq["question"],
                     "source": src, "query": sq["question"]}
                    for sq in plan["sub_questions"] for src in sq["sources"]
                ]
            if not tasks:
                stop_reason = "no_further_queries"
                break
            round_num += 1

        elapsed = round(time.monotonic() - start, 1)
        gather_seconds = round(time.monotonic() - gather_start, 1)
        total_chars = sum(e["chars"] for e in evidence)
        all_urls = sorted({u for e in evidence for u in e["urls"]})
        logger.info(
            "🧭 Deep research complete: %d rounds, %d evidence items, %d chars, %d unique URLs, "
            "%.1fs (plan %.1fs + gather %.1fs, stop: %s)",
            round_num, len(evidence), total_chars, len(all_urls), elapsed,
            plan_seconds, gather_seconds, stop_reason,
        )
        return {
            "plan": plan,
            "evidence": evidence,
            "metadata": {
                "rounds": round_num,
                "evidence_items": len(evidence),
                "total_chars": total_chars,
                "unique_urls": len(all_urls),
                "elapsed_seconds": elapsed,
                "plan_seconds": plan_seconds,
                "gather_seconds": gather_seconds,
                "stop_reason": stop_reason,
            },
        }
