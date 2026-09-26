"""analytical_visualizer — config, execution and chart delivery (2026-09-26).

Kept for exactly two jobs (charts of numbers the user typed; data-free diagrams). Each test names a
failure found on live or locally that day:
  * it read ANOTHER project's config by an absolute laptop path, then fell back SILENTLY to a hardcoded
    OpenAI gpt-4o-mini (spending OPENAI_API_KEY outside any config);
  * it ran generated code with whatever "python3" was on PATH (on live: no matplotlib) and an
    interactive matplotlib backend (Qt crash on a headless box);
  * it pasted the image as base64 into its text and never published it, so the answer model invented
    a chart marker ([[chart:quarterly_revenue_chart.png]]) — a broken chart in the post.
No model is called.
"""
import asyncio
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import user_tools.analytical_visualizer as AV  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def _tool_with(tmp_path, monkeypatch, cfg_text):
    cfg = tmp_path / "llm_config.yaml"
    cfg.write_text(cfg_text)
    monkeypatch.setattr(AV, "_PROJECT_CONFIG", cfg, raising=False)
    monkeypatch.setattr(AV, "_workspace_dir", lambda: tmp_path, raising=False)
    return AV.AnalyticalVisualizerTool()


GOOD = """
llm: {providers: {ollama: {base_url: "http://ollama.test:11434"}}}
arbitrator: {enabled: true, type: ollama, config: {model: "arb-model:cloud", timeout: 60}}
"""


def test_uses_the_arbitrator_lane_from_this_repos_config(tmp_path, monkeypatch):
    """FAILS PRE-FIX: the lane came from another project's path, and a hardcoded OpenAI model otherwise."""
    lane = _tool_with(tmp_path, monkeypatch, GOOD).visualization_llm_config
    assert lane["enabled"] and lane["type"] == "ollama"
    assert lane["config"]["model"] == "arb-model:cloud"
    assert lane["config"]["base_url"] == "http://ollama.test:11434"


def test_a_missing_lane_disables_the_tool_instead_of_switching_provider(tmp_path, monkeypatch):
    """FAILS PRE-FIX: no config -> a silent OpenAI gpt-4o-mini fallback. Now: disabled, with the reason."""
    lane = _tool_with(tmp_path, monkeypatch, "llm: {}\n").visualization_llm_config
    assert lane["enabled"] is False and "arbitrator" in lane["error"]
    assert "openai" not in str(lane).lower() and "gpt-4o-mini" not in str(lane)


def test_generated_code_runs_on_raicas_interpreter_headless(tmp_path, monkeypatch):
    """FAILS PRE-FIX: ran "python3" from PATH (live: no matplotlib) with the default (Qt) backend."""
    tool = _tool_with(tmp_path, monkeypatch, GOOD)
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"], seen["env"] = cmd, kw.get("env") or {}
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(AV.subprocess, "run", fake_run)
    asyncio.run(tool.execute_visualization_code({"success": True, "code": "print(1)",
                                                 "output_path": str(tmp_path / "x.png")}))
    assert seen["cmd"][0] == sys.executable, seen.get("cmd")
    assert seen["env"].get("MPLBACKEND") == "Agg"


def _run_with_publish(tmp_path, monkeypatch, url):
    tool = _tool_with(tmp_path, monkeypatch, GOOD)
    out = tmp_path / "chart.png"
    out.write_bytes(PNG)

    async def fake_gen(prompt, data, filename):
        return {"success": True, "output_path": str(out), "base64_image": "data:image/png;base64,AAAA"}
    monkeypatch.setattr(tool, "_generate_and_execute_visualization", fake_gen)
    import utils.chart_publisher as CP
    monkeypatch.setattr(CP, "publish_chart", lambda png, filename_hint="chart", timeout=15.0: url)
    return asyncio.run(tool.execute(prompt="Bar chart: Q1 12, Q2 15"))


def test_a_published_chart_returns_a_real_marker_and_no_inline_image(tmp_path, monkeypatch):
    """FAILS PRE-FIX: the image went into the text as base64 and no marker existed."""
    r = _run_with_publish(tmp_path, monkeypatch, "/static/images/media/abc.jpg")
    assert r["success"] and "[[chart:/static/images/media/abc.jpg" in r["result"]
    assert "base64" not in r["result"] and "<img" not in r["result"]


def test_a_failed_publish_says_there_is_no_marker(tmp_path, monkeypatch):
    """No URL -> no marker, stated plainly, so the answer model does not invent one."""
    r = _run_with_publish(tmp_path, monkeypatch, None)
    assert "[[chart:" not in r["result"] and "NO marker" in r["result"]


def test_each_call_gets_its_own_default_filename(tmp_path, monkeypatch):
    """FAILS PRE-FIX: every call wrote visualization_output.png, so concurrent charts overwrote each other."""
    tool = _tool_with(tmp_path, monkeypatch, GOOD)
    names = []

    async def fake_gen(prompt, data, filename):
        names.append(filename)
        return {"success": False, "error": "stop"}
    monkeypatch.setattr(tool, "_generate_and_execute_visualization", fake_gen)
    for _ in range(2):
        asyncio.run(tool.execute(prompt="x"))
    assert len(set(names)) == 2 and all(n.endswith(".png") for n in names), names
