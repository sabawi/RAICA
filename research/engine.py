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


async def _collect_stream(generate_stream: GenerateStream, prompt: str, **kwargs) -> str:
    """Run an injected streaming LLM call and return the full text."""
    chunks: List[str] = []
    async for chunk in generate_stream(prompt, **kwargs):
        chunks.append(chunk)
    return "".join(chunks)


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
        return list(self._cfg.get("sources", {}).get("allowed", []))

    @property
    def _max_sub_questions(self) -> int:
        return int(self._cfg.get("planner", {}).get("max_sub_questions", 6))

    @property
    def _max_rounds_ceiling(self) -> int:
        return int(self._cfg.get("loop", {}).get("max_rounds_ceiling", 4))

    def _build_prompt(self, user_request: str) -> tuple[str, str]:
        """Returns (system_prompt, user_prompt). Instructions go in system; data in user."""
        allowed = ", ".join(self._allowed_sources) or "search_web"
        system = (
            "You are the planner for a deep-research engine. Decompose the user's request "
            "into focused, non-overlapping SUB-QUESTIONS that, answered together, fully "
            "satisfy the request. For each sub-question, choose which research SOURCES are "
            "most appropriate, picking ONLY from this allowed list:\n"
            f"  {allowed}\n\n"
            "Guidance:\n"
            f"- Produce at most {self._max_sub_questions} sub-questions (fewer if that suffices).\n"
            "- Prefer academic sources (published_papers_search) for scholarly/scientific claims, "
            "news for current events, wikipedia for background, search_web for general/web coverage, "
            "get_sec_filings for company filings, document_search for the user's own documents.\n"
            "- Assign each sub-question a priority (1 = highest).\n"
            "- Propose max_rounds (1-" f"{self._max_rounds_ceiling}" ") for an iterative gather loop, "
            "and a clear stop_condition describing when research is sufficient.\n\n"
            "Respond with STRICT JSON only, no prose, in exactly this shape:\n"
            '{"sub_questions": [{"id": "q1", "question": "...", "sources": ["search_web"], '
            '"priority": 1}], "max_rounds": 3, "stop_condition": "..."}'
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
            normalized.append({
                "id": str(sq.get("id") or f"q{idx}"),
                "question": question,
                "sources": srcs,
                "priority": priority,
            })

        if not normalized:
            raise ValueError("planner sub_questions did not survive normalization")

        normalized.sort(key=lambda q: q["priority"])

        try:
            max_rounds = int(plan.get("max_rounds", 3))
        except (TypeError, ValueError):
            max_rounds = 3
        max_rounds = max(1, min(max_rounds, self._max_rounds_ceiling))

        return {
            "sub_questions": normalized,
            "max_rounds": max_rounds,
            "stop_condition": str(plan.get("stop_condition", "")).strip()
                              or "All sub-questions have at least two corroborating sources.",
        }

    async def plan(self, user_request: str) -> Dict[str, Any]:
        """Produce a validated research plan. Raises on planner failure (fail loud, no guessing)."""
        system_prompt, prompt = self._build_prompt(user_request)
        raw = await _collect_stream(
            self._generate_stream, prompt, system_prompt=system_prompt,
            temperature=0.1, max_tokens=1200, stream=False
        )
        plan = extract_json_object(raw)
        normalized = self._normalize(plan)
        logger.info(
            "🧭 Research plan: %d sub-questions, max_rounds=%d",
            len(normalized["sub_questions"]), normalized["max_rounds"],
        )
        return normalized


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
        return set(self._cfg.get("sources", {}).get("allowed", []))

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
            lines.append(
                f"[{e['sub_question_id']} | {e['source']} | r{e['round']} | "
                f"{e['chars']} chars | {len(e['urls'])} urls] {snippet}"
            )
        return "\n".join(lines)

    async def _assess(self, user_request: str, plan: Dict[str, Any],
                      evidence: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Ask the LLM whether coverage is sufficient and, if not, what to search next."""
        allowed = ", ".join(sorted(self._allowed_sources)) or "search_web"
        sq_list = "\n".join(f"- {sq['id']}: {sq['question']}" for sq in plan["sub_questions"])
        system_prompt = (
            "You are the coverage assessor for a deep-research engine. Given the user's request, "
            "the planned sub-questions, the stop_condition, and a summary of evidence gathered so "
            "far, decide whether research is SUFFICIENT or NEEDS_MORE.\n\n"
            f"If NEEDS_MORE, propose targeted next_queries using ONLY these sources: {allowed}. "
            "Each next query must address a specific gap (an unanswered sub-question or a claim "
            "with too few independent sources). Do not repeat queries already run.\n\n"
            "Respond with STRICT JSON only, no prose:\n"
            '{"status": "sufficient" | "needs_more", "gaps": ["..."], '
            '"next_queries": [{"sub_question_id": "q1", "source": "search_web", "query": "..."}]}'
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
        await emit(f"Planned {len(plan['sub_questions'])} sub-questions (up to {max_rounds} rounds).")
        gather_start = time.monotonic()

        evidence: List[Dict[str, Any]] = []
        executed: set = set()

        # Round 1 tasks come straight from the plan (sub-question text is the query).
        tasks = [
            {"sub_question_id": sq["id"], "question": sq["question"],
             "source": src, "query": sq["question"]}
            for sq in plan["sub_questions"] for src in sq["sources"]
        ]

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

            assessment = await self._assess(user_request, plan, evidence)
            if assessment["status"] == "sufficient":
                stop_reason = "sufficient"
                break

            next_queries = assessment.get("next_queries") or []
            tasks = [
                {"sub_question_id": q.get("sub_question_id"),
                 "question": q.get("query", ""),
                 "source": q.get("source"), "query": q.get("query", "")}
                for q in next_queries
                if q.get("source") in self._allowed_sources and (q.get("query") or "").strip()
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
