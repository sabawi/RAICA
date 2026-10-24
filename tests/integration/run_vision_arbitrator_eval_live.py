#!/usr/bin/env python3
"""
Vision + arbitrator model comparison through RAICA's REAL code paths (owner 2026-10-23).

  vision      user_tools/image_to_text.ImageToTextTool.get_image_processing_results — RAICA's system prompt, its JSON
              output contract (format=schema, image_received) and its reply check; fallback OFF so each model stands
              alone. ollama.Client.chat is wrapped only to RECORD tokens/durations.
  arbitrator  the exact `arbitrator_system_prompt` string from fastapi_server_complete.py (read with ast), the same
              prompt layout (request[:200], each result[:500]), RAICA's OllamaProvider.generate_stream with the
              arbitrator's kwargs (temperature 0.1, max_tokens from config, stream False), and RAICA's parse steps.

Arms alternate inside each case (time-of-day affects every arm alike). Paced; stops at the first rate-limit error.
Usage: python tests/integration/run_vision_arbitrator_eval_live.py <outdir> [--runs 3] [--only vision|arbitrator]
       [--vision-arms m1,m2,...] [--arb-arms m1,m2,...]
COSTS REAL MODEL CALLS on the account production shares: 12 vision cases x arms x runs + 16 arbitrator cases x
arms x runs (the 2026-10-23 run: 240 calls). Write the estimate down and agree it with the owner first.
Results: docs/LLM_MODEL_SELECTION_STUDY.md section 4.6.
"""
import argparse
import ast
import asyncio
import base64
import io
import json
import os
import re
import sys
import time

RAICA = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, RAICA)
os.chdir(RAICA)

VISION_ARMS = ['glm-5.3-flash:cloud', 'deepseek-v4.1-flash:cloud', 'minimax-m3:cloud', 'minimax-m3.1-flash:cloud']
ARB_ARMS = ['glm-5.3-flash:cloud', 'deepseek-v4.1-flash:cloud']
PACE_S = 4.0
STOP = {'why': None}


def rate_limited(text):
    t = (text or '').lower()
    return any(k in t for k in ('429', 'rate limit', 'usage limit', 'too many requests', 'quota'))


# ── vision cases: images with exactly known content ───────────────────────────────────────────────────────────────
def _font(size):
    from PIL import ImageFont
    for p in ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'):
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _png(img):
    buf = io.BytesIO(); img.save(buf, 'PNG'); return base64.b64encode(buf.getvalue()).decode()


def _fig_png(fig):
    buf = io.BytesIO(); fig.savefig(buf, format='png', dpi=100, bbox_inches='tight')
    import matplotlib.pyplot as plt
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def vision_cases():
    from PIL import Image, ImageDraw
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    cases = []

    # 1 receipt (dense text + numbers)
    img = Image.new('RGB', (420, 360), 'white'); d = ImageDraw.Draw(img); f = _font(20)
    lines = ['CORNER CAFE', 'Date: 2026-03-14', '', 'Latte           4.75', 'Bagel           2.40',
             'Orange juice    3.15', '', 'TOTAL          10.30', 'Card ****8812']
    for i, l in enumerate(lines):
        d.text((20, 15 + i * 36), l, fill='black', font=f)
    cases.append(('receipt', _png(img), 'What is the total on this receipt and what is the date?',
                  [['10.30'], ['2026-03-14', 'march 14', '14 march', '3/14', '14/03']]))

    # 2 table screenshot
    img = Image.new('RGB', (460, 230), 'white'); d = ImageDraw.Draw(img); f = _font(19)
    rows = [('City', 'High °C'), ('Lisbon', '24'), ('Oslo', '11'), ('Cairo', '33'), ('Lima', '19')]
    for i, (a, b) in enumerate(rows):
        d.text((25, 15 + i * 40), a, fill='black', font=f); d.text((260, 15 + i * 40), b, fill='black', font=f)
        d.line((15, 50 + i * 40, 445, 50 + i * 40), fill='gray')
    cases.append(('table', _png(img), 'Which city in this table has the highest temperature, and what is it?',
                  [['cairo'], ['33']]))

    # 3 bar chart, values NOT printed on the bars
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar(['North', 'South', 'East', 'West', 'Central'], [42, 17, 65, 30, 51], color='steelblue')
    ax.set_ylabel('Units sold'); ax.set_ylim(0, 80); ax.set_title('Q3 sales by region')
    cases.append(('bar_chart', _fig_png(fig), 'Which region sold the most in this chart, and approximately how many units?',
                  [['east'], ['NUM:60-70']]))

    # 4 line chart, peak month
    fig, ax = plt.subplots(figsize=(6, 4))
    months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug']
    ax.plot(months, [12, 15, 21, 28, 35, 31, 24, 18], marker='o'); ax.set_title('Website visitors (thousands)')
    cases.append(('line_chart', _fig_png(fig), 'In which month does this chart peak?', [['may']]))

    # 5 counting
    img = Image.new('RGB', (500, 300), 'white'); d = ImageDraw.Draw(img)
    for (x, y) in [(40, 40), (180, 70), (330, 30), (90, 190), (250, 170), (410, 200), (360, 110)]:
        d.ellipse((x, y, x + 45, y + 45), fill='green')
    for (x, y) in [(150, 230), (440, 40)]:
        d.rectangle((x, y, x + 40, y + 40), fill='orange')
    cases.append(('count', _png(img), 'How many green circles are in this image?', [['7', 'seven']]))

    # 6 small text
    img = Image.new('RGB', (520, 120), 'white'); d = ImageDraw.Draw(img)
    d.text((10, 50), 'Return the package to warehouse dock 12 before Thursday noon.', fill='black', font=_font(12))
    cases.append(('small_text', _png(img), 'What does the text in this image say?',
                  [['dock 12', 'dock twelve'], ['thursday']]))

    # 7 rotated serial number
    txt = Image.new('RGB', (420, 70), 'white'); ImageDraw.Draw(txt).text((10, 15), 'SERIAL 48-AXQ-209', fill='black', font=_font(30))
    img = Image.new('RGB', (200, 460), 'white'); img.paste(txt.rotate(90, expand=True), (60, 20))
    cases.append(('rotated', _png(img), 'What is the serial number shown in this image?', [['48-axq-209', '48 axq 209']]))

    # 8 flow diagram
    img = Image.new('RGB', (640, 200), 'white'); d = ImageDraw.Draw(img); f = _font(20)
    for i, label in enumerate(['Ingest', 'Validate', 'Publish']):
        x = 30 + i * 210
        d.rectangle((x, 60, x + 150, 130), outline='black', width=3); d.text((x + 20, 82), label, fill='black', font=f)
        if i < 2:
            d.line((x + 150, 95, x + 210, 95), fill='black', width=3); d.polygon([(x + 210, 95), (x + 198, 88), (x + 198, 102)], fill='black')
    cases.append(('diagram', _png(img), 'List the steps of this flow diagram in order.', [['ORDER:ingest,validate,publish']]))

    # 9 memo: phone + time
    img = Image.new('RGB', (560, 260), 'white'); d = ImageDraw.Draw(img); f = _font(17)
    memo = ['MEMO - Facilities', 'The quarterly review moves to Room 4B.', 'Start time: 2:45 PM on Wednesday.',
            'Questions? Call Dana at 555-0187.', 'Bring the signed inventory sheets.']
    for i, l in enumerate(memo):
        d.text((20, 20 + i * 44), l, fill='black', font=f)
    cases.append(('memo', _png(img), 'What is the phone number and what time does the review start?',
                  [['555-0187'], ['2:45']]))

    # 10 pie chart with legend
    fig, ax = plt.subplots(figsize=(5, 4))
    ax.pie([18, 46, 22, 14], labels=['Rent', 'Payroll', 'Marketing', 'Other'], startangle=90)
    ax.set_title('Monthly costs')
    cases.append(('pie_chart', _fig_png(fig), 'Which category is the largest slice of this pie chart?', [['payroll']]))

    # 11 calendar: which date is circled
    img = Image.new('RGB', (420, 300), 'white'); d = ImageDraw.Draw(img); f = _font(18)
    d.text((150, 8), 'June 2026', fill='black', font=f)
    for n in range(1, 31):
        r, c = divmod(n - 1, 7); x, y = 20 + c * 56, 50 + r * 46
        d.text((x + 10, y + 10), str(n), fill='black', font=f)
        if n == 17:
            d.ellipse((x - 2, y - 2, x + 46, y + 42), outline='red', width=4)
    cases.append(('calendar', _png(img), 'Which date is circled on this calendar?', [['17']]))

    # 12 nothing there: a near-blank image and a leading question (must not invent a chart)
    img = Image.new('RGB', (400, 300), (247, 247, 247))
    cases.append(('blank', _png(img), 'What are the numbers in this chart?', [['NONE']]))
    return cases


NEG_WORDS = ('blank', 'empty', 'no chart', 'no numbers', 'no data', 'nothing', 'no text', 'no visible', 'plain',
             'solid', 'uniform', 'does not contain', "doesn't contain", 'not contain', 'no content', 'no discernible')


def score_vision(expected, answer):
    """(facts_hit, facts_total). Each expected fact is a list of acceptable forms."""
    # Score the MODEL's report only: RAICA wraps it in a sentence carrying the date and time, whose digits
    # otherwise fail the 'no numbers' check on a blank image (seen in the first scoring, 2026-10-23).
    a = (answer or '').split("response to the user's prompt:", 1)[-1].lower()
    hit = 0
    for alts in expected:
        alt0 = alts[0]
        if alt0 == 'NONE':
            ok = any(w in a for w in NEG_WORDS) and not re.search(r'\b\d{2,}\b', a)
        elif alt0.startswith('NUM:'):
            lo, hi = map(float, alt0[4:].split('-'))
            ok = any(lo <= float(x) <= hi for x in re.findall(r'\d+(?:\.\d+)?', a))
        elif alt0.startswith('ORDER:'):
            # The steps must appear IN ORDER somewhere — not by first mention: a model that describes the
            # boxes first and then lists the steps mentions the last step before the first (2026-10-23).
            words, at, ok = alt0[6:].split(','), 0, True
            for w in words:
                at = a.find(w, at)
                if at < 0:
                    ok = False
                    break
                at += len(w)
        else:
            ok = any(x in a for x in alts)
        hit += ok
    return hit, len(expected)


def run_vision(arm, case, rec):
    from user_tools.image_to_text import ImageToTextTool
    import ollama
    name, b64, question, expected = case
    tool = ImageToTextTool()
    tool.vision_config = dict(tool.vision_config, model=arm, fallback_model=None)
    captured = {}
    orig = ollama.Client.chat

    def spy(self, *a, **k):
        r = orig(self, *a, **k)
        try:
            captured.update(prompt_tokens=r.get('prompt_eval_count'), output_tokens=r.get('eval_count'),
                            total_ms=int((r.get('total_duration') or 0) / 1e6))
        except Exception:
            pass
        return r
    ollama.Client.chat = spy
    t0 = time.time()
    try:
        res = tool.get_image_processing_results({'prompt': question, 'image': b64})
    except Exception as e:
        res = {'success': False, 'error': '%s: %s' % (type(e).__name__, e)}
    finally:
        ollama.Client.chat = orig
    wall = time.time() - t0
    ok = bool(res.get('success'))
    ans = res.get('description', '') if ok else ''
    hit, tot = score_vision(expected, ans) if ok else (0, len(expected))
    row = {'kind': 'vision', 'arm': arm, 'case': name, 'ok': ok, 'facts': hit, 'facts_total': tot,
           'wall_s': round(wall, 2), 'error': None if ok else str(res.get('error'))[:300],
           'answer': ans[:4000], **captured}
    rec(row)
    if not ok and rate_limited(row['error']):
        STOP['why'] = row['error']


# ── arbitrator cases ─────────────────────────────────────────────────────────────────────────────────────────────
def arbitrator_system_prompt():
    tree = ast.parse(open(os.path.join(RAICA, 'fastapi_server_complete.py')).read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(getattr(t, 'id', None) == 'arbitrator_system_prompt' for t in node.targets):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                return node.value.value
    raise SystemExit('arbitrator_system_prompt not found as a plain string')


W = ('Weather for {c}: {d}. Temperature {t}°C, humidity {h}%, wind {w} km/h. Forecast: {f}. Source: Open-Meteo, '
     'retrieved 2026-10-23 17:55 UTC.')
G_WEATHER = W.format(c='Paris, France', d='Partly cloudy', t=14, h=71, w=12, f='light rain after 21:00')
G_WEATHER_LON = W.format(c='London, United Kingdom', d='Overcast', t=12, h=80, w=18, f='showers overnight')
WRONG_PARIS = W.format(c='Paris, Texas, United States', d='Sunny', t=27, h=40, w=9, f='clear')
G_STOCK = ('AAPL (Apple Inc.) — last price $231.48 (+1.12%, +$2.56) as of 2026-10-23 15:59 ET. Day range 228.90–232.10, '
           'volume 48.2M, market cap $3.51T, P/E 35.6. Source: Yahoo Finance.')
BAD_STOCK = 'Error: symbol lookup returned no data for "TSLAA" — no matching ticker. No quote available.'
STALE_STOCK = ('MSFT (Microsoft Corp.) — last price $106.20 as of 2019-01-04 16:00 ET. Day range 103.0–106.9. '
               'Source: cached quote.')
G_NEWS = ('1. "EU agrees on AI liability rules" — Reuters, 2026-10-23. 2. "Chipmakers rally on demand outlook" — '
          'Bloomberg, 2026-10-23. 3. "New battery plant opens in Nevada" — AP, 2026-10-22.')
EMPTY_NEWS = 'No results found.'
OLD_NEWS = ('1. "Markets slide on trade fears" — Reuters, 2021-03-02. 2. "Tech stocks rebound" — CNBC, 2021-03-01. '
            '3. "Oil prices climb" — AP, 2021-02-26.')
G_WIKI = ('Eiffel Tower — wrought-iron lattice tower in Paris, France. Height: 330 m (1,083 ft) including antennas. '
          'Completed 1889 for the Exposition Universelle. Source: Wikipedia.')
G_COMPUTE = 'Result: 36'
BAD_COMPUTE = 'Error: invalid expression "15% of" — could not evaluate.'
RATE = 'HTTP 429 Too Many Requests — the search provider rate-limited this request. Try again later.'
TIMEOUT = 'Request timed out after 30 s while contacting api.open-meteo.com.'
PARTIAL = W.format(c='Rome, Italy', d='Clear', t=19, h=55, w=7, f='clear')    # asked for 3 cities, got 1

# (name, user request, [(tool, result, expected GOOD|BAD)])
ARB_CASES = [
    ('weather_ok', 'What is the weather in Paris right now?', [('get_weather', G_WEATHER, 'GOOD')]),
    ('weather_wrong_place', 'What is the weather in Paris, France right now?', [('get_weather', WRONG_PARIS, 'BAD')]),
    ('stock_ok', 'What is Apple stock trading at?', [('get_stock_and_company_data', G_STOCK, 'GOOD')]),
    ('stock_bad_symbol', 'What is Tesla stock trading at today?', [('get_stock_and_company_data', BAD_STOCK, 'BAD')]),
    ('news_empty', 'What are the top technology news stories today?', [('get_news_summaries', EMPTY_NEWS, 'BAD')]),
    ('wiki_ok', 'How tall is the Eiffel Tower?', [('wikipedia_query', G_WIKI, 'GOOD')]),
    ('compute_ok', 'What is 15% of 240?', [('compute', G_COMPUTE, 'GOOD')]),
    ('compute_bad', 'What is 15% of 240?', [('compute', BAD_COMPUTE, 'BAD')]),
    ('batch3_one_bad', 'Give me the Paris weather, today\'s tech news, and Tesla\'s stock price.',
     [('get_weather', G_WEATHER, 'GOOD'), ('get_news_summaries', G_NEWS, 'GOOD'), ('get_stock_and_company_data', BAD_STOCK, 'BAD')]),
    ('batch4_all_ok', 'Eiffel Tower height, 15% of 240, Paris weather, and Apple\'s price please.',
     [('wikipedia_query', G_WIKI, 'GOOD'), ('compute', G_COMPUTE, 'GOOD'), ('get_weather', G_WEATHER, 'GOOD'),
      ('get_stock_and_company_data', G_STOCK, 'GOOD')]),
    ('batch4_rate_limited', 'Tech news, Paris weather, Apple price and the Eiffel Tower height.',
     [('get_news_summaries', RATE, 'BAD'), ('get_weather', G_WEATHER, 'GOOD'), ('get_stock_and_company_data', G_STOCK, 'GOOD'),
      ('wikipedia_query', G_WIKI, 'GOOD')]),
    ('batch5_two_bad', 'Microsoft\'s price today, today\'s tech news, London weather, 15% of 240, and the Eiffel Tower height.',
     [('get_stock_and_company_data', STALE_STOCK, 'BAD'), ('get_news_summaries', EMPTY_NEWS, 'BAD'),
      ('get_weather', G_WEATHER_LON, 'GOOD'), ('compute', G_COMPUTE, 'GOOD'), ('wikipedia_query', G_WIKI, 'GOOD')]),
    ('batch6_all_ok', 'Paris and London weather, Apple price, tech news, Eiffel Tower height, 15% of 240.',
     [('get_weather', G_WEATHER, 'GOOD'), ('get_weather', G_WEATHER_LON, 'GOOD'), ('get_stock_and_company_data', G_STOCK, 'GOOD'),
      ('get_news_summaries', G_NEWS, 'GOOD'), ('wikipedia_query', G_WIKI, 'GOOD'), ('compute', G_COMPUTE, 'GOOD')]),
    ('batch6_hidden_timeout', 'Paris and London weather, Apple price, tech news, Eiffel Tower height, 15% of 240.',
     [('get_weather', G_WEATHER, 'GOOD'), ('get_stock_and_company_data', G_STOCK, 'GOOD'), ('get_news_summaries', G_NEWS, 'GOOD'),
      ('wikipedia_query', G_WIKI, 'GOOD'), ('get_weather', TIMEOUT, 'BAD'), ('compute', G_COMPUTE, 'GOOD')]),
    ('partial_cities', 'What is the weather in Rome, Madrid and Athens today?', [('get_weather', PARTIAL, 'BAD')]),
    ('stale_news', 'What is the latest market news today?', [('get_news_summaries', OLD_NEWS, 'BAD')]),
]


def parse_like_raica(text):
    """RAICA's parse steps (fastapi_server_complete.py arbitrator): strip ```json fences, json.loads, then its two
    regex fallbacks. Returns the dict or None."""
    clean = (text or '').strip()
    if clean.startswith('```json'):
        clean = clean[7:]
    if clean.endswith('```'):
        clean = clean[:-3]
    clean = clean.strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        pass
    for pattern in (r'\{[^{}]*"tasks"[^{}]*\[[^\]]*\][^{}]*\}', r'\{.*?"tasks"\s*:\s*\[.*?\].*?\}'):
        for m in re.findall(pattern, text or '', re.DOTALL):
            try:
                return json.loads(m)
            except json.JSONDecodeError:
                continue
    return None


async def run_arbitrator(arm, case, system_prompt, provider_cfg, rec):
    from llm_providers.factory import LLMProviderFactory
    name, request, tasks = case
    details = ''.join('\nTask %d: %s\nResult: %s%s\n' % (i + 1, t, r[:500], '...' if len(r) > 500 else '')
                      for i, (t, r, _e) in enumerate(tasks))
    prompt = ('User Request: %s\n\nTask Results to Validate:\n%s\n\nPlease validate each task result and respond with '
              'JSON analysis.' % (request[:200], details))
    p = LLMProviderFactory.create_provider('ollama', dict(provider_cfg, model=arm))
    kwargs = {'system_prompt': system_prompt, 'temperature': 0.1, 'max_tokens': p.get_max_tokens(), 'stream': False}
    t0 = time.time(); out = ''; err = None
    try:
        async for chunk in p.generate_stream(prompt, arm, **kwargs):
            out += chunk or ''
    except Exception as e:
        err = '%s: %s' % (type(e).__name__, str(e)[:300])
    finally:
        if getattr(p, 'session', None) is not None and not p.session.closed:
            await p.session.close()
    wall = time.time() - t0
    parsed = parse_like_raica(out) if not err else None
    got = {}
    retry_ok = True
    if isinstance(parsed, dict):
        for t in parsed.get('tasks') or []:
            try:
                got[int(str(t.get('task_id')).split()[-1])] = (str(t.get('status', '')).upper(), t.get('retry_strategy'))
            except Exception:
                pass
    correct = 0
    for i, (_t, _r, exp) in enumerate(tasks, 1):
        st = (got.get(i) or ('', None))[0]
        st = 'BAD' if st in ('BAD', 'FATAL', 'FAIL', 'FAILED') else ('GOOD' if st in ('GOOD', 'OK') else st)
        correct += st == exp
        if exp == 'BAD' and st == 'BAD' and not (got.get(i) or ('', None))[1]:
            retry_ok = False
    row = {'kind': 'arbitrator', 'arm': arm, 'case': name, 'batch': len(tasks), 'parsed': parsed is not None,
           'tasks_correct': correct, 'tasks_total': len(tasks), 'case_correct': correct == len(tasks),
           'retry_given_for_bad': retry_ok, 'wall_s': round(wall, 2), 'out_chars': len(out),
           'think_chars': len(out.split('</think>')[0]) if '<think>' in out else 0, 'error': err, 'raw_tail': out[-400:]}
    rec(row)
    if err and rate_limited(err):
        STOP['why'] = err


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('outdir'); ap.add_argument('--runs', type=int, default=3)
    ap.add_argument('--only', choices=['vision', 'arbitrator'])
    ap.add_argument('--vision-arms', help='comma-separated models (default: the 2026-10-23 arms)')
    ap.add_argument('--arb-arms', help='comma-separated models (default: the 2026-10-23 arms)')
    a = ap.parse_args()
    global VISION_ARMS, ARB_ARMS
    if a.vision_arms:
        VISION_ARMS = [m.strip() for m in a.vision_arms.split(',') if m.strip()]
    if a.arb_arms:
        ARB_ARMS = [m.strip() for m in a.arb_arms.split(',') if m.strip()]
    os.makedirs(a.outdir, exist_ok=True)
    path = os.path.join(a.outdir, 'rows.jsonl')
    fh = open(path, 'a')

    def rec(row):
        row['at'] = time.strftime('%H:%M:%S')
        fh.write(json.dumps(row) + '\n'); fh.flush()
        brief = {k: row.get(k) for k in ('kind', 'arm', 'case', 'ok', 'facts', 'parsed', 'tasks_correct', 'wall_s', 'error')}
        print(json.dumps(brief), flush=True)

    calls = 0
    if a.only in (None, 'vision'):
        cases = vision_cases()
        for run in range(a.runs):
            for case in cases:
                order = VISION_ARMS if run % 2 == 0 else list(reversed(VISION_ARMS))
                for arm in order:
                    if STOP['why']:
                        break
                    run_vision(arm, case, rec); calls += 1      # MAIN thread: the tool uses signal.alarm, like RAICA
                    await asyncio.sleep(PACE_S)
    if a.only in (None, 'arbitrator') and not STOP['why']:
        from utils import llm_admin
        cfg = llm_admin.raw_config()
        node = cfg['arbitrator']['config']
        provider_cfg = llm_admin.provider_config(cfg, cfg['arbitrator'].get('type', 'ollama'), node)
        sp = arbitrator_system_prompt()
        print('arbitrator system prompt: %d chars; provider num_predict=%s max_tokens=%s think=%s' % (
            len(sp), provider_cfg.get('num_predict'), provider_cfg.get('max_tokens'), provider_cfg.get('think')), flush=True)
        for run in range(a.runs):
            for case in ARB_CASES:
                order = ARB_ARMS if run % 2 == 0 else list(reversed(ARB_ARMS))
                for arm in order:
                    if STOP['why']:
                        break
                    await run_arbitrator(arm, case, sp, provider_cfg, rec); calls += 1
                    await asyncio.sleep(PACE_S)
    fh.close()
    print('DONE calls=%d stop=%s rows=%s' % (calls, STOP['why'], path), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
