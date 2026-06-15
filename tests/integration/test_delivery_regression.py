#!/usr/bin/env python3
"""
END-TO-END DELIVERY REGRESSION HARNESS for RAICA.

Drives the REAL entry points and asserts on the live server log delta — no UI needed:
  • POST /v1                      ← NewX "@Ask" (restricted client: allowed_tools + allow_delivery +
                                    delivery_recipient → server LOCKS the recipient to the actor's account)
  • POST /v1/chat/completions     ← OpenWebUI / Deep Research (auto-trusted: deep_research flag, prompt-
                                    specified recipient honored)

Lanes:
  • FAST  (default)  : T1, T2, Tnew  — NewX /v1, seconds each
  • SLOW  (--slow)   : T3, T4        — Deep Research, minutes each

Recipients come from ENV (no PII committed):
  DELIVERY_TEST_RECIPIENT     locked account email for NewX tests (T1/T2/Tnew)
  DELIVERY_TEST_THIRD_PARTY   3rd-party email for the DR test (T4); defaults to RECIPIENT if unset

Usage:
  export DELIVERY_TEST_RECIPIENT=you@example.com
  python3 tests/integration/test_delivery_regression.py            # fast lane
  python3 tests/integration/test_delivery_regression.py --slow     # + DR tests
  python3 tests/integration/test_delivery_regression.py --only T1,Tnew
  python3 tests/integration/test_delivery_regression.py --list

NOTE: tests actually SEND email (the recipient is your own locked account, so mail lands in your inbox).
"""
import argparse
import os
import sys
import time

import requests

RAICA_URL = os.environ.get("RAICA_URL", "http://localhost:5000")
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOG_PATH = os.environ.get("RAICA_LOG", os.path.join(REPO_ROOT, "logs", "server_complete.log"))

# Restricted-client tool whitelist exactly as NewX sends it (research tools only; delivery is governed
# by allow_delivery, not by exposing delivery tools).
NEWX_ALLOWED_TOOLS = ["search_web", "lookup_website", "wikipedia_query",
                      "get_news_summaries", "get_stock_and_company_data"]

RECIPIENT = os.environ.get("DELIVERY_TEST_RECIPIENT", "").strip()
THIRD_PARTY = os.environ.get("DELIVERY_TEST_THIRD_PARTY", "").strip() or RECIPIENT


# ── log helpers ──────────────────────────────────────────────────────────────────────────────────
def log_line_count() -> int:
    try:
        with open(LOG_PATH, "r", encoding="utf-8", errors="replace") as f:
            return sum(1 for _ in f)
    except FileNotFoundError:
        return 0


def log_delta(baseline: int) -> str:
    try:
        with open(LOG_PATH, "r", encoding="utf-8", errors="replace") as f:
            return "".join(f.readlines()[baseline:])
    except FileNotFoundError:
        return ""


# ── request drivers ──────────────────────────────────────────────────────────────────────────────
# Realistic NewX envelope: a long system-instructions preamble FIRST, with the actual user directive at
# the END as 'user posted: …'. This reproduces the REAL prompt shape (directive NOT at offset 0, buried
# past the first ~1.5k chars) so truncation / format-detection bugs are actually exercised by the harness.
NEWX_SYSTEM_PREAMBLE = (
    "\n\n=== SYSTEM INSTRUCTIONS ===\n"
    "You are a knowledge-seeking AI Agent residing on the NewX platform. Your absolute priority is truth "
    "and accuracy. Before answering ANY factual question, you MUST use your available search tools to "
    "research the topic and verify the information. Do not rely solely on your internal training data. "
    "Once you have the facts, provide a thorough, comprehensive, and well-structured answer. Synthesize "
    "the information you found into a clear and highly detailed response. Tell the user as much relevant "
    "context as you can find. If you cannot find the answer, simply state that you do not know. CRITICAL: "
    "BE AWARE OF THE TIME AND DATE WHILE FORMULATING YOUR RESPONSE. SUPER CRITICAL — SOURCE CITATION "
    "REQUIREMENT (NON-NEGOTIABLE): Every factual claim, statistic, quote, headline, price, date, name, or "
    "piece of information you obtained from a web tool MUST be accompanied by an ACCURATE, VERIFIABLE, "
    "CLICKABLE source URL. Cite using Markdown link syntax: [Source Name](https://full-canonical-url). "
    "ONLY use URLs that were actually returned by the tool results in THIS session. NEVER fabricate, "
    "guess, hallucinate, paraphrase, shorten, or invent URLs. NEVER use placeholder, example, redirect, "
    "or bare-domain URLs. Uncited web-sourced claims, broken links, or fabricated URLs are an ABSOLUTE "
    "FAILURE. HASHTAGS: Always end your response with 2-4 relevant hashtags on a new line.\n"
    "===========================\n\n"
)


def _newx_envelope(ask: str) -> str:
    return f'{NEWX_SYSTEM_PREAMBLE}user posted: "{ask}"\nReply to the above in <=32000 tokens.'


def post_newx(prompt: str, recipient: str, prior_context: str = "", timeout: int = 180) -> str:
    """POST a NewX @Ask-style request to /v1 (wrapped in the realistic NewX envelope) and return the full
    streamed body (blocks until the request — including POST-LLM delivery — completes)."""
    payload = {
        "prompt": _newx_envelope(prompt),
        "model": os.environ.get("RAICA_TEST_MODEL", "deepseek-v4-pro:cloud"),
        "prompt_context": prior_context,
        "allowed_tools": NEWX_ALLOWED_TOOLS,
        "allow_delivery": True,
        "delivery_recipient": recipient,
        "deep_research": False,
        "stream": False,
    }
    r = requests.post(f"{RAICA_URL}/v1", json=payload, timeout=timeout)
    r.raise_for_status()
    return r.text


def post_openwebui_dr(prompt: str, recipient: str, deep_research: bool = True, timeout: int = 900) -> str:
    """POST an OpenWebUI / Deep-Research style request to /v1/chat/completions (auto-trusted client)."""
    payload = {
        "model": os.environ.get("RAICA_TEST_MODEL", "deepseek-v4-pro:cloud"),
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "deep_research": deep_research,
    }
    r = requests.post(f"{RAICA_URL}/v1/chat/completions", json=payload, timeout=timeout)
    r.raise_for_status()
    return r.text


# ── assertion helper ─────────────────────────────────────────────────────────────────────────────
def check(name: str, delta: str, must_have=(), must_not=(), notes: str = "") -> bool:
    missing = [m for m in must_have if m not in delta]
    present = [m for m in must_not if m in delta]
    ok = not missing and not present
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  — {notes}" if notes else ""))
    if missing:
        print(f"        ✗ expected-but-absent: {missing}")
    if present:
        print(f"        ✗ forbidden-but-present: {present}")
    return ok


def validate_artifacts(since_ts: float, expect=()) -> bool:
    """Validate the ACTUAL delivered files (not log markers). Requires the server to run with
    RAICA_KEEP_DELIVERY_FILES set (so files survive post-send cleanup); otherwise this is a no-op pass
    (log assertions still apply). Checks every file created since `since_ts` in ~/sandbox_workspace:
    PDFs must be real (%PDF-…%%EOF), HTML must look like HTML; and every `expect` format must be present."""
    if not os.environ.get("RAICA_KEEP_DELIVERY_FILES"):
        return True  # can't inspect (files were cleaned) — rely on log assertions
    sb = os.path.join(os.path.expanduser("~"), "sandbox_workspace")
    found = {}
    try:
        for name in os.listdir(sb):
            p = os.path.join(sb, name)
            if not os.path.isfile(p) or os.path.getmtime(p) < since_ts - 1:
                continue
            ext = name.rsplit(".", 1)[-1].lower()
            if ext == "pdf":
                with open(p, "rb") as fh:
                    head = fh.read(5)
                    fh.seek(max(0, os.path.getsize(p) - 8))
                    tail = fh.read()
                found["pdf"] = (head == b"%PDF-") and (b"%%EOF" in tail)
            elif ext == "html":
                import re as _re
                with open(p, "rb") as fh:
                    raw = fh.read()
                txt = raw.decode("utf-8", "replace")
                head = raw[:64].lower()
                is_html = (b"<html" in head) or (b"<!doctype" in head)
                no_fence = "```" not in txt                    # not the source shown as a code block
                one_title = txt.lower().count("<h1") <= 1       # title rendered ONCE, not 2-3×
                no_preamble = not _re.search(                   # no 'Here is the document:' intro
                    r'here is (your|the)\s+(html|pdf|document|comprehensive|briefing|news)', txt, _re.I)
                found["html"] = is_html and no_fence and one_title and no_preamble
                if not (no_fence and one_title and no_preamble):
                    print(f"        ✗ html quality: <h1>×{txt.lower().count('<h1')} "
                          f"fence={'```' in txt} preamble={not no_preamble}")
    except FileNotFoundError:
        print("        ✗ artifact: ~/sandbox_workspace not found")
        return False
    ok = all(found.values()) and all(found.get(f) for f in expect)
    print(f"        {'✓' if ok else '✗'} artifacts validated: {found} (expected {list(expect)})")
    return ok


# ── scenarios ────────────────────────────────────────────────────────────────────────────────────
def t1_newx_html_attachment() -> bool:
    """T1 — NewX @Ask: email a write-up as a single HTML attachment to the locked recipient."""
    base, ts = log_line_count(), time.time()
    post_newx("email me a 500 words summary of Aesop's Fables as an HTML attachment", RECIPIENT)
    d = log_delta(base)
    ok = check(
        "T1 NewX → HTML attachment", d,
        must_have=["📦 delivery: created", "Email sent successfully"],
        must_not=["Using fallback detection", "NoneType", "doc_failed", "no_recipient"],
        notes="1 HTML file emailed to locked recipient",
    )
    return validate_artifacts(ts, expect=("html",)) and ok


def t2_newx_pdf_and_html_above_news() -> bool:
    """T2 — NewX @Ask: email 'the above news' as BOTH a PDF and an HTML file in one email."""
    synthetic_news = (
        "RECENT NEWS (context):\n"
        "1. Markets rallied as inflation cooled to 2.1% in May.\n"
        "2. A major chipmaker unveiled a new low-power AI accelerator.\n"
        "3. Talks resumed on the regional trade agreement.\n"
    )
    base, ts = log_line_count(), time.time()
    post_newx("email me the above news in two attachments, a PDF and an HTML file, in one email",
              RECIPIENT, prior_context=synthetic_news)
    d = log_delta(base)
    ok = check(
        "T2 NewX → PDF + HTML (above news)", d,
        must_have=["📦 delivery: created 2 document(s)", ".pdf", ".html", "Email sent successfully"],
        must_not=["Using fallback detection", "NoneType", "doc_failed"],
        notes="2 files (PDF+HTML) in one email to locked recipient",
    )
    return validate_artifacts(ts, expect=("pdf", "html")) and ok


def tabove_newx_html_only_clean() -> bool:
    """Tabove — NewX @Ask 'email the above … in HTML format' must produce EXACTLY ONE html file with
    CLEAN content (no spurious .md/.txt from substring-matched 'context', no leftover ```code fence /
    'Here is the document' preamble)."""
    # Realistic, substantive 'above' content — thin content makes the model reply with a planning
    # statement ("I need to research…") instead of formatting, which is a test artifact, not a delivery bug.
    synthetic = (
        "BREAKING NEWS BRIEFING — Markets & Technology\n\n"
        "## Markets & Finance\n"
        "US equities steadied on Monday as the S&P 500 and Nasdaq edged higher, with investors weighing "
        "cooling inflation against renewed tech-sector volatility. Treasury yields slipped as traders "
        "priced in a more dovish path for rates into the second half of the year.\n\n"
        "## Technology & AI\n"
        "A leading chipmaker began shipping a new low-power AI accelerator aimed at on-device inference, "
        "claiming a 40% efficiency gain over the prior generation. Analysts say it intensifies competition "
        "in the edge-AI silicon market and could pressure incumbents on both price and power draw.\n\n"
        "## Quick Hits\n"
        "- A major cloud provider expanded its european data-center footprint.\n"
        "- Venture funding into AI-infrastructure startups rebounded for a third straight month.\n")
    base, ts = log_line_count(), time.time()
    post_newx("email the above as an attachment to me in HTML format", RECIPIENT, prior_context=synthetic)
    d = log_delta(base)
    ok = check(
        "Tabove NewX → HTML only (1 clean file)", d,
        must_have=["📦 delivery: created 1 document(s)", ".html", "Email sent successfully"],
        must_not=["created 2 document(s)", "created 3 document(s)", ".md'", ".txt'", "NoneType"],
        notes="exactly 1 html file, no spurious formats",
    )
    # content cleanliness: the delivered HTML must NOT still contain a literal ``` code fence
    clean = True
    if os.environ.get("RAICA_KEEP_DELIVERY_FILES"):
        sb = os.path.join(os.path.expanduser("~"), "sandbox_workspace")
        try:
            for name in os.listdir(sb):
                p = os.path.join(sb, name)
                if name.endswith(".html") and os.path.getmtime(p) >= ts - 1:
                    if "```" in open(p, encoding="utf-8", errors="replace").read():
                        print("        ✗ delivered HTML still contains a ``` code fence")
                        clean = False
        except FileNotFoundError:
            pass
        print(f"        {'✓' if clean else '✗'} content fence-free: {clean}")
    return validate_artifacts(ts, expect=("html",)) and ok and clean


def tnew_no_spurious_delivery() -> bool:
    """Tnew — NewX @Ask: a plain question must NOT trigger any file creation or email."""
    base = log_line_count()
    post_newx("what is the capital of France?", RECIPIENT)
    d = log_delta(base)
    return check(
        "Tnew NewX → plain question (no delivery)", d,
        must_have=[],
        must_not=["📦 delivery: created", "Email sent successfully"],
        notes="no file, no email",
    )


def t4_dr_pdf_html_third_party() -> bool:
    """T4 — OpenWebUI Deep Research → email PDF + HTML to a 3rd-party address."""
    base, ts = log_line_count(), time.time()
    post_openwebui_dr(
        f"Deep research the history of the printing press and its impact on literacy. "
        f"Email the research results as attachments to {THIRD_PARTY} in two formats: a PDF and an HTML file in one email.",
        THIRD_PARTY)
    d = log_delta(base)
    ok = check(
        "T4 DR → PDF + HTML to 3rd party", d,
        must_have=["📦 delivery: created 2 document(s)", ".pdf", ".html", "Email sent successfully"],
        must_not=["doc_failed", "No such file"],
        notes="2 DR docs emailed to 3rd party",
    )
    return validate_artifacts(ts, expect=("pdf", "html")) and ok


def t3_dr_format_references() -> bool:
    """T3 — Deep Research output FORMAT: the synthesized report must include a References section + inline
    citations (this shares a DR run's streamed answer; asserts on report structure, not visual layout)."""
    base = log_line_count()
    body = post_openwebui_dr(
        "Deep research the invention of the telescope and its impact on astronomy. Provide a full report.",
        RECIPIENT)
    d = log_delta(base)
    has_refs = ("References" in body) or ("references" in d.lower())
    has_cites = "](http" in body  # clickable [Title](URL) citations
    ok = has_refs and has_cites
    print(f"  [{'PASS' if ok else 'FAIL'}] T3 DR → format (References + citations)"
          f"  — refs={has_refs} citations={has_cites}")
    return ok


SCENARIOS = {
    "T1": ("fast", t1_newx_html_attachment),
    "T2": ("fast", t2_newx_pdf_and_html_above_news),
    "Tabove": ("fast", tabove_newx_html_only_clean),
    "Tnew": ("fast", tnew_no_spurious_delivery),
    "T3": ("slow", t3_dr_format_references),
    "T4": ("slow", t4_dr_pdf_html_third_party),
}


def main():
    ap = argparse.ArgumentParser(description="RAICA delivery regression harness")
    ap.add_argument("--slow", action="store_true", help="include the slow Deep-Research tests (T3, T4)")
    ap.add_argument("--only", default="", help="comma-separated test ids to run (e.g. T1,Tnew)")
    ap.add_argument("--list", action="store_true", help="list scenarios and exit")
    args = ap.parse_args()

    if args.list:
        for tid, (lane, fn) in SCENARIOS.items():
            print(f"  {tid:5} [{lane:4}] {fn.__doc__.splitlines()[0].strip()}")
        return 0

    if not RECIPIENT:
        print("ERROR: set DELIVERY_TEST_RECIPIENT=you@example.com (the locked account email). "
              "Tests send real email; the recipient is your own account.")
        return 2

    # health gate
    try:
        h = requests.get(f"{RAICA_URL}/health", timeout=10).json()
        print(f"RAICA {h.get('version')} — {h.get('status')} (ollama={h.get('services', {}).get('ollama')})")
    except Exception as e:
        print(f"ERROR: RAICA not reachable at {RAICA_URL}: {e}")
        return 2

    if args.only:
        wanted = [t.strip() for t in args.only.split(",") if t.strip()]
    else:
        wanted = [t for t, (lane, _) in SCENARIOS.items() if lane == "fast" or (lane == "slow" and args.slow)]

    print(f"Running: {wanted}\n")
    results = {}
    for tid in wanted:
        if tid not in SCENARIOS:
            print(f"  [SKIP] unknown test id {tid}")
            continue
        lane, fn = SCENARIOS[tid]
        t0 = time.time()
        try:
            results[tid] = fn()
        except Exception as e:  # a thrown test counts as a failure, with the reason
            results[tid] = False
            print(f"  [FAIL] {tid} raised: {e}")
        print(f"        ({time.time() - t0:.1f}s)\n")

    passed = sum(1 for v in results.values() if v)
    total = len(results)
    print(f"==== {passed}/{total} passed ====")
    for tid, ok in results.items():
        print(f"  {'✅' if ok else '❌'} {tid}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
