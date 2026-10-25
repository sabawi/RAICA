"""SI-115: computed charts are looked at before publishing; an unreadable one is redrawn, at most chart_redraws times.

NewX post 9088 and its re-runs (2026-10-25): translucent 3D surfaces blended into one tangle, a legend matching
nothing, a 1/r spike dwarfing the other surfaces — published as they were. No model or sandbox is called here: the
vision check, the writer and the sandbox are stand-ins; each test names the failure it prevents.
"""
import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import user_tools.run_python_analysis_tool as T  # noqa: E402

CFG = {'enabled': True, 'timeout_seconds': 60, 'max_images': 3, 'memory': '384m', 'max_image_pixels': 4000000,
       'writer_provider': 'ollama', 'writer_model': 'w', 'max_attempts': 1, 'chart_check': True}


class _Resp:
    def __init__(self, text):
        self.success, self.content, self.model, self.error = True, text, 'w', None


@pytest.fixture
def rig(monkeypatch):
    state = {'writes': 0, 'runs': 0, 'checks': [], 'published': [], 'verdict': {'readable': False,
             'problems': 'surfaces blend into one tangle', 'model': 'v'}, 'redraw_images': [b'NEW'], 'cfg': dict(CFG)}

    class Client:
        fallback_enabled = False

        def generate(self, prompt, **kw):
            state['writes'] += 1
            state.setdefault('prompts', []).append(prompt)
            return _Resp("```python\nprint('x = %d')\n```" % state['writes'])

    async def run_program(program, cfg):
        state['runs'] += 1
        imgs = [b'OLD'] if state['runs'] == 1 else [i + b'%d' % (state['runs'] - 1) for i in state['redraw_images']]
        return {'ok': True, 'exit': 0, 'timed_out': False, 'stdout': f'run {state["runs"]}', 'stderr': '',
                'images': imgs, 'notes': []}

    def check_chart(img, purpose, timeout=60.0):
        state['checks'].append(img)
        v = state['verdict']
        if callable(v):
            v = v(img)
        if isinstance(v, Exception):
            raise v
        return v

    import agents.coding_agent.llm_client as L
    import utils.chart_check as C
    monkeypatch.setattr(L, 'CodeGenLLMClient', Client)
    monkeypatch.setattr(T.py_sandbox, 'load_settings', lambda: state['cfg'])
    monkeypatch.setattr(T.py_sandbox, 'run_program', run_program)
    monkeypatch.setattr(C, 'check_chart', check_chart)
    monkeypatch.setattr(T, 'publish_chart', lambda png, filename_hint=None: state['published'].append(png) or
                        '/static/images/media/x.jpg')
    return state


def _go():
    return asyncio.run(T.RunPythonAnalysisTool().execute(task='plot three surfaces', chart_caption='c'))


def test_an_unreadable_chart_is_redrawn_and_the_redraw_published(rig):
    """The 9088 tangle: the check flags it, the program is redrawn, and the REDRAWN chart and its output ship."""
    rig['verdict'] = lambda img: {'readable': img != b'OLD', 'problems': 'surfaces blend into one tangle', 'model': 'v'}
    out = _go()
    assert out['success'] and rig['published'] == [b'NEW1'] and 'run 2' in out['result']
    assert 'surfaces blend into one tangle' in rig['prompts'][-1]


def test_a_readable_redraw_stops_the_loop(rig):
    rig['verdict'] = lambda img: {'readable': img != b'OLD', 'problems': 'tangle', 'model': 'v'}
    _go()
    assert rig['checks'] == [b'OLD', b'NEW1'] and rig['writes'] == 2


def test_redraws_stop_at_the_cap_and_the_last_is_not_checked(rig):
    """Damper: a chart the checker never accepts must not drive an unbounded check→redraw cycle (default cap 2)."""
    _go()
    assert rig['checks'] == [b'OLD', b'NEW1'] and rig['writes'] == 3 and rig['runs'] == 3
    assert rig['published'] == [b'NEW2']


def test_each_redraw_is_told_every_earlier_rejection(rig):
    """Without the history the writer redrew the same rejected layout (real path, 2026-10-25)."""
    rig['verdict'] = lambda img: {'readable': False, 'problems': f'problem with {img.decode()}', 'model': 'v'}
    _go()
    assert 'problem with OLD' in rig['prompts'][-1] and 'problem with NEW1' in rig['prompts'][-1]


def test_zero_redraws_never_redraws(rig):
    rig['cfg']['chart_redraws'] = 0
    _go()
    assert rig['checks'] == [] and rig['writes'] == 1 and rig['published'] == [b'OLD']


def test_a_readable_chart_ships_without_a_redraw(rig):
    rig['verdict'] = {'readable': True, 'problems': '', 'model': 'v'}
    _go()
    assert rig['writes'] == 1 and rig['published'] == [b'OLD']


def test_no_verdict_publishes_the_original(rig):
    """Fail open: the vision model unavailable (quota, outage) must not cost the chart or the answer."""
    rig['verdict'] = None
    out = _go()
    assert out['success'] and rig['writes'] == 1 and rig['published'] == [b'OLD']


def test_a_check_that_raises_publishes_the_original(rig):
    rig['verdict'] = RuntimeError('boom')
    out = _go()
    assert out['success'] and rig['published'] == [b'OLD']


def test_a_redraw_without_charts_keeps_the_original(rig):
    """A redraw that runs but draws nothing must not replace a chart that exists."""
    rig['redraw_images'] = []
    out = _go()
    assert out['success'] and rig['published'] == [b'OLD'] and 'run 1' in out['result'] and rig['writes'] == 2


def test_the_switch_turns_the_check_off(rig):
    rig['cfg']['chart_check'] = False
    _go()
    assert rig['checks'] == [] and rig['writes'] == 1


def test_the_check_is_off_unless_switched_on(rig):
    """Off by default (measured rescue rate 1/4): a config without the key must publish unchecked, as before."""
    del rig['cfg']['chart_check']
    _go()
    assert rig['checks'] == [] and rig['writes'] == 1
