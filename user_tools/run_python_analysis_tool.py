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
    "- When the task asks to SOLVE an equation that has a known exact solution under the stated conditions, give "
    "that solution first: print it (sympy where it helps), compute and plot from it, and use a numerical scheme only "
    "where no exact solution applies or as a check against it, reporting the difference.\n"
    "- State each physical or modelling assumption as a comment, and print it too.\n"
    "- If the question can reasonably be read in more than one way, or its literal premise makes the asked-for "
    "outcome impossible, compute each reasonable reading and say which is which.\n"
    "- When the task comes with THE USER'S OWN REQUEST, the user's words win wherever the two differ: the task is "
    "another model's summary, and it may have fixed a setting, simplified the physics or dropped a reading the user "
    "left open. Compute what the user asked for.\n"
    "- Anything the task or the user's words say can be adjusted, controlled, steered or chosen is a decision "
    "variable, not a fixed value — even when the task suggests one setting. Search or optimise over it (including "
    "letting it change during the process when it can), and report the best result it achieves next to the "
    "fixed-setting case. Do not conclude that a goal is impossible until that search has failed.\n"
    "- Check your own result before reporting it: quantities your model conserves (energy, angular momentum, mass) "
    "must stay constant to within the integration tolerance, every value must stay physically possible (no distance "
    "through zero, no speed beyond light, no negative population), and the integration must reach its intended end. "
    "If any check fails, the program is wrong, not the physics: write what failed to sys.stderr and exit with status 1 "
    "(sys.exit(1)) so the program can be corrected. Never print, explain away or plot a result that failed its check. "
    "Measure a conserved quantity the way the scheme conserves it (the same time level for every term), print the "
    "tolerance you check against and the drift you measured. Decide BEFORE checking whether your model conserves a "
    "quantity: a force that depends only on position has a potential, and energy is conserved once that potential is "
    "included; a force that does work along the motion (thrust, drag) changes it, so check the balance instead "
    "(energy change = work done). A check that fails is a failure, never a warning. "
    "A check verifies the COMPUTATION, never the outcome the question hopes for: whether something escapes, arrives, "
    "reaches a distance or meets a goal is a result to report either way, never a condition to assert or exit on.\n"
    "- When the direction of a force can be chosen, derive how its size and its direction depend on that choice from "
    "how the force is produced, and state that law in a comment. Never assume a force can point anywhere at full "
    "strength.\n"
    "- Describe only what the code does: name each boundary condition, source and loss term as implemented (a fixed "
    "zero boundary reflects; it does not absorb), and never attribute a result to an effect the code does not model.\n"
    "- Print the step-by-step results, each with its units, in the order a reader should follow them. Print the "
    "final answers last, clearly labelled.\n"
    "- Save each requested chart as a PNG in the working directory (at most {max_images}, each at most "
    "{max_pixels} pixels in total, e.g. figsize=(10, 7) at dpi=150 — a larger image is discarded), with a title, labelled "
    "axes with units, and a legend. For spatial paths and orbits use an equal axis scale, set the limits so the "
    "computed path fills most of the chart, and mark only the reference objects that fall within that view. When "
    "several surfaces share one 3D chart, a reader must be able to follow each one on its own. Transparency does not "
    "achieve that — overlapping translucent surfaces blend into one tangle. Either lift each surface by a constant "
    "larger than the others' range (stacked layers, the offset stated in the legend), or draw each as a wireframe in "
    "one solid colour; draw each at the full grid resolution (rcount and ccount equal to the grid) and give the "
    "legend each surface's own colour. This holds even when the task names colormaps or transparency. Print the file name of each chart you saved.\n"
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


async def _unreadable_charts(images, purpose):
    """The vision model's problems for every chart it judged unreadable, as text; '' when all are readable or no
    verdict could be obtained (fails open — see utils/chart_check.py)."""
    from utils.chart_check import check_chart
    try:
        verdicts = await asyncio.gather(*(asyncio.to_thread(check_chart, img, purpose, 30.0) for img in images))
    except Exception as e:  # noqa: BLE001 — the check must never cost the answer
        logger.warning("📊 chart check failed (%s) — publishing unchecked", e)
        return ""
    lines = []
    for i, v in enumerate(verdicts, 1):
        logger.info("📊 chart check %d/%d: %s", i, len(images),
                    "no verdict" if v is None else ("readable" if v['readable'] else "UNREADABLE") +
                    (f" ({v['model']})" if v else ""))
        if v is not None and not v['readable']:
            lines.append(f"chart {i}: {v['problems'] or 'unreadable'}")
    return "\n".join(lines)


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
            "marker yourself. Explain the results only with what the program printed or modelled; where it did not "
            "establish a cause, do not supply one. Each run is one attempt at its task: when several ran, present "
            "the one that answers the request, and do not describe the others as a designed comparison unless the "
            "task set one up. When the user asks to SOLVE an equation with a known exact solution, say so in the "
            "task, so the program gives that solution before any numerical scheme. Describe WHAT to plot, not how to "
            "style it: the program's writer chooses colours, transparency and layout so that superimposed 3D "
            "surfaces stay readable."
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

        # The user's own words travel with the task: the selector's paraphrase can fix what the user left open.
        try:
            from utils.request_context import get_request_text
            req = (get_request_text() or '').strip()
        except Exception:  # noqa: BLE001
            req = ''
        if req:
            task = (f"{task}\n\nTHE USER'S OWN REQUEST (the end of the text the platform sent — any platform or system "
                    f"instructions in it govern the conversation, not your program):\n<<<\n{req[-4000:]}\n>>>")
            logger.info("🧪 run_python_analysis: the user's request travels with the task (%d chars)",
                        min(len(req), 4000))

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

        # SI-115: look at the charts before publishing; when a reader could not read them, redraw — at most
        # `chart_redraws` times (default 2). The counter is the damper: no check runs after the last redraw, so a
        # check can never trigger an unbounded check→redraw cycle. A redraw replaces the charts only if it ran and drew
        # charts; otherwise the last good run is published, exactly as before.
        # OFF unless chart_check: true — measured 2026-10-25: detection agreed with a human 17/18, but a redraw made a
        # flagged chart readable only 1 time in 4, at 1-2 extra writer calls each (SI-115).
        if result['images'] and cfg.get('chart_check') is True:
            reports = []
            redraws = max(0, int(cfg.get('chart_redraws', 2)))
            for n in range(1, redraws + 1):
                problems = await _unreadable_charts(result['images'], f"{caption}. Task: {task[:400]}")
                if not problems:
                    break
                reports.append(f"Draw {n}:\n{problems}")
                logger.info("📊 run_python_analysis: chart(s) judged unreadable — redraw %d/%d: %s", n, redraws,
                            problems[:300].replace('\n', ' | '))
                failure = ("The program RAN and its numbers are correct — keep every computation and every printed "
                           "line exactly as they are. Only its chart(s) failed. A reviewer looked at each draw so far "
                           "and reported:\n" + "\n".join(reports) +
                           "\nRedraw so that a reader can follow every element on its own; do not repeat a layout "
                           "the reviewer already rejected.")
                prompt = f"{system}\n\n" + REPAIR_POLICY.format(task=task, program=program, failure=failure)
                resp = await asyncio.to_thread(client.generate, prompt, provider=cfg['writer_provider'],
                                               model=cfg['writer_model'], temperature=0,
                                               max_tokens=int(cfg.get('writer_max_tokens') or 16384))
                redrawn = _extract_program(resp.content) if resp.success else ''
                new = None
                if redrawn:
                    try:
                        new = await py_sandbox.run_program(redrawn, cfg)
                    except py_sandbox.SandboxRefused as e:
                        logger.warning("📊 run_python_analysis: redraw refused (%s)", e)
                if not (new and new['ok'] and new['stdout'].strip() and new['images']):
                    logger.info("📊 run_python_analysis: redraw %d drew no charts — publishing the previous draw", n)
                    break
                program, result = redrawn, new
                logger.info("📊 run_python_analysis: redraw %d used (%d chart(s))", n, len(new['images']))

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
