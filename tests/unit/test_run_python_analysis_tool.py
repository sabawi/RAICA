"""run_python_analysis — the tool's own logic (docs/DESIGN_run_python_analysis.md). No model, no container.

The writer model and the sandbox are replaced by stand-ins; anything that would reach a real model or Docker fails
the test. The sandbox's own security is tested against real containers in
tests/integration/test_pysandbox_redteam.py.

Failures each test prevents are named in its docstring.
"""
import asyncio

import pytest

import user_tools.run_python_analysis_tool as tool_mod
from agents.coding_agent import llm_client
from utils import py_sandbox

CFG = {'enabled': True, 'timeout_seconds': 60, 'max_images': 3, 'max_attempts': 2, 'writer_max_tokens': 100,
       'memory': '512m', 'max_image_pixels': 4000000,
       'writer_provider': 'ollama', 'writer_model': 'deepseek-v4-pro:cloud', 'writer_fallback': False}


class _Resp:
    def __init__(self, content, success=True, error=None):
        self.content, self.success, self.error, self.model = content, success, error, 'stand-in'


class _Writer:
    """Stand-in for CodeGenLLMClient. Records every call; never reaches a model."""
    instances = []

    def __init__(self, *a, **k):
        self.fallback_enabled = True
        self.calls = []
        self.replies = list(_Writer.next_replies)
        _Writer.instances.append(self)

    def generate(self, prompt, **kw):
        self.calls.append({'prompt': prompt, **kw, 'fallback_enabled': self.fallback_enabled})
        return self.replies.pop(0)


def _ok(stdout='answer 42\n', images=()):
    return {'ok': True, 'exit': 0, 'timed_out': False, 'stdout': stdout, 'stderr': '', 'images': list(images),
            'notes': []}


@pytest.fixture
def env(monkeypatch):
    """Fail-closed: the real client and the real sandbox are unreachable from every test."""
    monkeypatch.setattr(py_sandbox, 'load_settings', lambda: dict(CFG))
    monkeypatch.setattr(llm_client, 'CodeGenLLMClient', _Writer)
    runs, published = [], []
    state = {'results': []}

    async def fake_run(program, cfg):
        runs.append(program)
        return state['results'].pop(0)
    monkeypatch.setattr(py_sandbox, 'run_program', fake_run)

    def fake_publish(png, filename_hint='chart'):
        published.append(png)
        return f'/static/images/media/pub{len(published)}.png'
    monkeypatch.setattr(tool_mod, 'publish_chart', fake_publish)
    _Writer.instances.clear()
    return {'runs': runs, 'published': published, 'state': state}


def _execute(**kw):
    return asyncio.run(tool_mod.RunPythonAnalysisTool().execute(**kw))


def test_disabled_tool_runs_nothing(env, monkeypatch):
    """With enabled:false (the shipped default) no model is called and no program runs."""
    monkeypatch.setattr(py_sandbox, 'load_settings', lambda: {**CFG, 'enabled': False})
    _Writer.next_replies = []
    r = _execute(task='simulate it')
    assert r['success'] is False and 'not enabled' in r['error']
    assert _Writer.instances == [] and env['runs'] == []


def test_writer_is_pinned_and_never_falls_back_to_paid_providers(env):
    """The shared client's fallback list includes paid OpenAI/Anthropic; a public bot must try ONLY its model."""
    _Writer.next_replies = [_Resp("```python\nprint(42)\n```")]
    env['state']['results'] = [_ok()]
    _execute(task='simulate it')
    call = _Writer.instances[0].calls[0]
    assert call['provider'] == 'ollama' and call['model'] == 'deepseek-v4-pro:cloud'
    assert call['fallback_enabled'] is False


def test_success_returns_output_program_and_only_tool_made_markers(env):
    """Markers come only from images this tool published; the answer gets output AND the program to cite."""
    _Writer.next_replies = [_Resp("```python\nprint('answer 42')\n```")]
    env['state']['results'] = [_ok('answer 42\n', images=[b'png-a', b'png-b'])]
    r = _execute(task='simulate it', chart_caption='Orbit')
    assert r['success'] is True
    assert r['result'].count('[[chart:') == 2 and 'pub1.png' in r['result'] and 'pub2.png' in r['result']
    assert 'answer 42' in r['result'] and "print('answer 42')" in r['result']
    assert env['published'] == [b'png-a', b'png-b']


def test_writer_rules_are_in_the_message_itself(env):
    """The shared client's Ollama path DROPS system_prompt; rules passed only there never reached the model
    (2026-10-24: every program called plt.show() and saved no chart). They must be in the prompt text."""
    _Writer.next_replies = [_Resp("```python\nprint(1)\n```")]
    env['state']['results'] = [_ok()]
    _execute(task='simulate the orbit')
    prompt = _Writer.instances[0].calls[0]['prompt']
    assert 'Save each requested chart as a PNG' in prompt and 'simulate the orbit' in prompt
    # the limits the sandbox enforces are told to the writer (2026-10-24: 2400x1800 charts were silently discarded)
    assert '512m' in prompt and '4,000,000 pixels' in prompt


def test_one_repair_attempt_gets_the_error(env):
    """A failed program gets ONE repair, and the writer sees the actual error output."""
    _Writer.next_replies = [_Resp("```python\n1/0\n```"), _Resp("```python\nprint('fixed')\n```")]
    env['state']['results'] = [{'ok': False, 'exit': 1, 'timed_out': False, 'stdout': '',
                                'stderr': 'ZeroDivisionError: division by zero', 'images': [], 'notes': []},
                               _ok('fixed\n')]
    r = _execute(task='simulate it')
    assert r['success'] is True and 'fixed' in r['result']
    repair = _Writer.instances[0].calls[1]['prompt']
    assert 'ZeroDivisionError' in repair and '1/0' in repair


def test_repeated_failure_is_reported_never_invented(env):
    """After max_attempts the tool fails loudly and tells the model not to invent results."""
    bad = {'ok': False, 'exit': 1, 'timed_out': False, 'stdout': '', 'stderr': 'boom', 'images': [], 'notes': []}
    _Writer.next_replies = [_Resp("```python\nraise SystemExit(1)\n```")] * 2
    env['state']['results'] = [dict(bad), dict(bad)]
    r = _execute(task='simulate it')
    assert r['success'] is False and 'do NOT invent' in r['error'] and len(env['runs']) == 2


def test_writer_failure_is_reported(env):
    _Writer.next_replies = [_Resp('', success=False, error='quota')]
    r = _execute(task='simulate it')
    assert r['success'] is False and 'quota' in r['error'] and env['runs'] == []


def test_unpublished_chart_yields_no_marker(env, monkeypatch):
    """No URL, no marker — the model must not be handed a marker that points nowhere."""
    monkeypatch.setattr(tool_mod, 'publish_chart', lambda png, filename_hint='chart': None)
    _Writer.next_replies = [_Resp("```python\nprint(1)\n```")]
    env['state']['results'] = [_ok('1\n', images=[b'png'])]
    r = _execute(task='simulate it')
    assert r['success'] is True and '[[chart:' not in r['result'] and 'could not be published' in r['result']


def test_sandbox_refusal_is_reported(env, monkeypatch):
    async def refuse(program, cfg):
        raise py_sandbox.SandboxRefused('sandbox busy: another program is running; try again shortly')
    monkeypatch.setattr(py_sandbox, 'run_program', refuse)
    _Writer.next_replies = [_Resp("```python\nprint(1)\n```")]
    r = _execute(task='simulate it')
    assert r['success'] is False and 'busy' in r['error']
