"""run_python_analysis — when no ready tool answers a question but code can, write a program, run it, answer from it.

Owner request 2026-10-24 (NewX post 9010, a solar-sail escape question): Ask had only `compute` (one expression per
value, no time-stepping) and `plot_data` (sorts by x, cannot draw a path), and across 7 runs gave escape times from
157 days to 88 years with no trajectory. The same model, asked to write a program, produced a correct simulation in
one call. Design, threat model and every limit: docs/DESIGN_run_python_analysis.md.

Flow: `task` (plain language) → the code_generation model writes ONE Python program → utils/py_sandbox runs it in a
throwaway gVisor container with no network and nothing from the host → on failure the model gets ONE repair attempt
with the error → printed results come back as text, every image is re-encoded and published by THIS tool, and only
this tool writes the [[chart:…]] markers for them.

Every program is hostile (anyone who can post @Ask, or whose text reaches the model, can make it write anything);
the boundary is the container, never this file. Disabled unless user_tools.run_python_analysis.enabled is true.
"""
import asyncio
import logging
import time
from typing import Any, Dict

try:
    from .base_user_tool import BaseUserTool
except ImportError:
    from base_user_tool import BaseUserTool

try:
    from utils import py_sandbox
    from utils.chart_publisher import publish_chart
    from datasources.data_chart_builder import _marker
except ImportError:  # loaded outside the server process
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from utils import py_sandbox
    from utils.chart_publisher import publish_chart
    from datasources.data_chart_builder import _marker

logger = logging.getLogger(__name__)

# Policy for the model that WRITES the program (plain language — RAICA decides meaning with the LLM, not with code).
WRITER_POLICY = (
    "You answer a quantitative question by writing ONE complete, self-contained Python 3 program. It runs in a "
    "sandbox with numpy, scipy, sympy, pandas and matplotlib (Agg backend), no network, no input, no files except "
    "the ones it creates in its working directory, a time limit of {timeout} seconds and a memory limit of {memory} "
    "— keep well inside both (store only what you print or plot, not every integration step).\n"
    "Rules:\n"
    "- Derive every number in the code. Where the answer depends on how a system evolves over time, integrate the "
    "equations numerically; do not use a closed-form shortcut whose assumptions do not hold.\n"
    "- State each physical or modelling assumption as a comment, and print it too.\n"
    "- If the question can reasonably be read in more than one way, or its literal premise makes the asked-for "
    "outcome impossible, compute each reasonable reading and say which is which.\n"
    "- Anything the task or the user's words say can be adjusted, controlled, steered or chosen is a decision "
    "variable, not a fixed value — even when the task suggests one setting. Search or optimise over it (including "
    "letting it change during the process when it can), and report the best result it achieves next to the "
    "fixed-setting case. Do not conclude that a goal is impossible until that search has failed.\n"
    "- Check your own result before reporting it: quantities your model conserves (energy, angular momentum, mass) "
    "must stay constant to within the integration tolerance, every value must stay physically possible (no distance "
    "through zero, no speed beyond light, no negative population), and the integration must reach its intended end. "
    "If any check fails, the program is wrong, not the physics: write what failed to sys.stderr and exit with status 1 "
    "(sys.exit(1)) so the program can be corrected. Never print, explain away or plot a result that failed its check.\n"
    "- Print the step-by-step results, each with its units, in the order a reader should follow them. Print the "
    "final answers last, clearly labelled.\n"
    "- Save each requested chart as a PNG in the working directory (at most {max_images}, each at most "
    "{max_pixels} pixels in total, e.g. figsize=(10, 7) at dpi=150 — a larger image is discarded), with a title, labelled "
    "axes with units, and a legend. For spatial paths and orbits use an equal axis scale, set the limits so the "
    "computed path fills most of the chart, and mark only the reference objects that fall within that view. Print "
    "the file name of each chart you saved.\n"
    "- Return only the program, in one ```python block."
)

REPAIR_POLICY = (
    "The program below failed in the sandbox. Fix it so it runs to completion within the limits, keeping the same "
    "task. Return only the corrected program, in one ```python block.\n\nTASK:\n{task}\n\nPROGRAM:\n```python\n"
    "{program}\n```\n\nWHAT HAPPENED:\n{failure}"
)


def _extract_program(text):
    from agents.coding_agent.llm_client import extract_best_code_block, strip_thinking_content
    return (extract_best_code_block(strip_thinking_content(text or ''), 'py') or '').strip()


def _failure_report(result):
    parts = []
    if result.get('timed_out'):
        parts.append('It was stopped at the time limit.')
    if result.get('exit') not in (0, None):
        parts.append(f"It exited with status {result['exit']}.")
    parts += result.get('notes') or []
    if result.get('stderr'):
        parts.append('Error output (last part):\n' + result['stderr'][-3000:])
    if not result.get('stdout', '').strip() and result.get('ok'):
        parts.append('It printed nothing.')
    return '\n'.join(parts) or 'It produced no usable result.'


class RunPythonAnalysisTool(BaseUserTool):

    @property
    def name(self) -> str:
        return "run_python_analysis"

    @property
    def description(self) -> str:
        return (
            "Write and run a Python program to answer a question that NO other tool can answer and that needs real "
            "computation: a simulation, a quantity that evolves over time (motion, growth, decay, orbits, "
            "populations, finance over many periods), an equation or system that must be solved numerically, an "
            "optimisation, or a trajectory or other path to draw. A capable model writes the program; it runs in an "
            "isolated sandbox (numpy, scipy, sympy, pandas, matplotlib; no internet); you get its printed results "
            "and [[chart:…]] markers for the charts it drew. Describe the task COMPLETELY in `task`: every given "
            "number with its units, what to compute, what to plot, and any data already gathered that the program "
            "needs (the program cannot fetch anything). Where the request is ambiguous or its literal premise may make "
            "the asked-for outcome impossible, quote the user's own words and ask for each reasonable reading — do "
            "not settle the ambiguity yourself in the task. Prefer a ready tool when one answers the question — "
            "`compute` for a single formula, `plot_data` for charting fetched data. Present the program's printed "
            "results as the source of the figures, place its markers in your answer as given, and never write a "
            "marker yourself."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task": {"type": "string",
                         "description": "The complete problem: every given value with units, what to compute, "
                                        "what to plot, and any data the program needs."},
                "chart_caption": {"type": "string",
                                  "description": "Short caption saying WHAT is plotted, e.g. 'Probe trajectory "
                                                 "in the ecliptic plane'. Never state the outcome — the "
                                                 "result is not known when you write this."},
            },
            "required": ["task"],
        }

    async def execute(self, **kwargs) -> Dict[str, Any]:
        try:
            cfg = py_sandbox.load_settings()
        except Exception as e:  # noqa: BLE001 — a missing section is a configuration fault, reported as such
            return {"success": False, "error": f"run_python_analysis: not configured ({e})"}
        if cfg.get('enabled') is not True:
            return {"success": False, "error": "run_python_analysis is not enabled on this server. Answer with "
                                               "the other tools and say the calculation could not be run."}
        task = str(kwargs.get('task') or '').strip()
        if not task:
            return {"success": False, "error": "run_python_analysis: `task` is required — describe the problem."}
        caption = str(kwargs.get('chart_caption') or '').strip()[:120] or 'Computed result'
        # The task is written by the tool selector, and it decides which readings get computed (2026-10-24: every
        # solar-sail task said "always face-on", so no run could cover the steered sail the user's words allowed).
        logger.info("🧪 run_python_analysis: task (%d chars): %s", len(task), task[:600].replace('\n', ' '))

        from agents.coding_agent.llm_client import CodeGenLLMClient
        client = CodeGenLLMClient()
        client.fallback_enabled = bool(cfg.get('writer_fallback'))   # no paid fallback for a public bot
        system = WRITER_POLICY.format(timeout=cfg['timeout_seconds'], max_images=cfg['max_images'],
                                      memory=cfg['memory'], max_pixels=f"{cfg['max_image_pixels']:,}")

        program, result, history = '', None, []
        for attempt in range(1, int(cfg.get('max_attempts') or 1) + 1):
            # The rules travel IN the message: CodeGenLLMClient's Ollama path drops `system_prompt` (it sends the
            # user message only — found 2026-10-24 when every program called plt.show() and saved no chart).
            prompt = (f"{system}\n\nTASK:\n{task}" if attempt == 1 else
                      f"{system}\n\n" + REPAIR_POLICY.format(task=task, program=program,
                                                             failure=_failure_report(result)))
            t0 = time.monotonic()
            resp = await asyncio.to_thread(client.generate, prompt, provider=cfg['writer_provider'],
                                           model=cfg['writer_model'], temperature=0,
                                           max_tokens=int(cfg.get('writer_max_tokens') or 16384))
            if not resp.success:
                logger.warning("🧪 run_python_analysis: writer failed (%s)", resp.error)
                return {"success": False, "error": "run_python_analysis: the program could not be written "
                                                   f"({resp.error}). Answer without it and say so."}
            program = _extract_program(resp.content)
            logger.info("🧪 run_python_analysis: attempt %d — %s wrote %d lines in %.1fs", attempt, resp.model,
                        len(program.splitlines()), time.monotonic() - t0)
            if not program:
                history.append(f"attempt {attempt}: the model returned no program")
                continue
            try:
                result = await py_sandbox.run_program(program, cfg)
            except py_sandbox.SandboxRefused as e:
                return {"success": False, "error": f"run_python_analysis: {e}"}
            if result['ok'] and result['stdout'].strip():
                break
            history.append(f"attempt {attempt}: {_failure_report(result)[:300]}")

        if not result or not (result['ok'] and result['stdout'].strip()):
            return {"success": False,
                    "error": "run_python_analysis: the program did not run successfully. "
                             + " | ".join(history)[-1500:]
                             + " — say the calculation could not be completed; do NOT invent its results."}

        markers = []
        for i, png in enumerate(result['images'], 1):
            url = publish_chart(png, filename_hint=f"analysis_{i}")
            if url:
                markers.append(_marker(url, caption if len(result['images']) == 1 else f"{caption} ({i})"))
            else:
                result['notes'].append(f"chart {i} was drawn but could not be published")
        logger.info("🧪 run_python_analysis: success — %d chars of results, %d/%d chart(s) published",
                    len(result['stdout']), len(markers), len(result['images']))
        body = [*markers,
                "PROGRAM OUTPUT (computed in RAICA's sandbox by the program below — cite it as the source of these "
                "figures):", "```", result['stdout'].strip(), "```"]
        if result['notes']:
            body.append("NOTES: " + "; ".join(result['notes']))
        body += ["PROGRAM:", "```python", program, "```"]
        return {"success": True, "result": "\n".join(body)}
