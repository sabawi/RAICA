"""SI-028 P1 — machine-readable data files must be readable.

FROM PRODUCTION 2026-08-11. An @Ask run was asked to fetch the US Treasury daily-yield CSV and
plot it. The tool chain did everything right up to the last step:

    tool SELECTED    : lookup_website, called TWICE (one file per year, as prompted)   OK
    URLs CONSTRUCTED : both correct                                                     OK
    CONTENT EXTRACTED: "ERROR: Failed to extract content"  (both)                       FAIL
    yield numbers reaching the context: 0

The endpoint was healthy the whole time: HTTP 200, `text/csv; charset=UTF-8`, 12,422 bytes,
153 rows, 15 maturities — fresher than FRED.

CAUSE: `lookup_website` branched on the URL STRING — PDF, else assume HTML — so CSV/JSON/XML
fell into the HTML extractor and failed CLOSED and SILENT. The server's own declared
`Content-Type` was never consulted. This blocked EVERY machine-readable data file on the web;
Treasury was just the one someone asked for.

FIX (Generalization Directive): dispatch on what the SERVER declares. An unrecognised type is
returned as text LABELLED with its content-type so the LLM can decide — never a per-site handler,
never silent rejection.

These tests are OFFLINE (no network): they exercise the dispatch decision and the pass-through
formatting, which is where the defect lived.
"""
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = (ROOT / "fastapi_server_complete.py").read_text()
FLAT = re.sub(r'"\s*\n\s*"', "", SRC)


def _grab(name):
    i = SRC.index(f"    def {name}(")
    nxt = [x for x in (SRC.find("\n    def ", i + 10), SRC.find("\n    async def ", i + 10)) if x > 0]
    return SRC[i:min(nxt)]


def _shim():
    """Rebuild just the two helpers in isolation — importing the server loads models."""
    cls = ("import requests\nclass S:\n"
           "    _DATA_CONTENT_TYPES = "
           + re.search(r"_DATA_CONTENT_TYPES = \{[^}]*\}", SRC).group(0).split("=", 1)[1] + "\n"
           "    _DATA_MAX_BYTES = 2_000_000\n"
           + "\n".join(_grab(n) for n in ("_probe_content_type", "_extract_data_content")))
    ns = {}
    exec(cls, ns)
    return ns["S"]()


# ---------------------------------------------------------------- the dispatch decision

@pytest.mark.parametrize("ctype,is_data", [
    ("text/csv", True),                     # the type that failed in production
    ("application/csv", True),
    ("text/tab-separated-values", True),
    ("application/json", True),
    ("application/xml", True),
    ("text/html", False),                   # must still reach the HTML extractor
    ("application/pdf", False),
    ("", False),                            # unknown -> HTML path, as before
])
def test_dispatch_routes_on_declared_content_type(ctype, is_data):
    s = _shim()
    routed_to_data = ctype in s._DATA_CONTENT_TYPES and ctype != "text/plain"
    assert routed_to_data is is_data


def test_dispatch_is_wired_into_lookup_website():
    """The helper existing is not enough — lookup_website must actually call it.

    Pre-fix the else-branch went straight to _extract_web_content.
    """
    assert "_probe_content_type(url)" in SRC
    assert "_extract_data_content(url, _ct)" in SRC


def test_html_path_is_unchanged():
    """A regression here would break every ordinary web lookup."""
    assert "_extract_web_content(url)" in SRC
    assert 'content_type = "Web Page"' in SRC


def test_non_html_failure_falls_back_to_passthrough():
    """If the HTML extractor fails but the server declared a non-HTML type, return the bytes
    labelled rather than reporting nothing — silent failure is what hid this for months."""
    seg = SRC[SRC.index("_probe_content_type(url)"):SRC.index("_probe_content_type(url)") + 1200]
    assert 'not result.get("success")' in seg and '"html" not in _ct' in seg


# ------------------------------------------------------- pass-through formatting contract

def test_passthrough_labels_type_and_line_count():
    s = _shim()
    import types
    payload = b"Date,10 Yr,30 Yr\n08/10/2026,4.72,5.25\n08/07/2026,4.65,5.19\n"

    class _R:
        status_code = 200
        headers = {"Content-Type": "text/csv"}
        raw = types.SimpleNamespace(read=lambda *_a, **_k: payload)
        def close(self): pass
    import requests
    orig, requests.get = requests.get, lambda *a, **k: _R()
    try:
        out = s._extract_data_content("http://x/data.csv", "text/csv")
    finally:
        requests.get = orig
    assert out["success"] is True
    assert out["lines"] == 3 and out["truncated"] is False
    assert "[CSV file: 3 lines retrieved (complete)]" in out["content"]
    assert "08/10/2026,4.72,5.25" in out["content"], "rows must pass through VERBATIM"


def test_truncation_is_disclosed_not_silent():
    """SI-027's lesson applied here: a silently shortened artifact is read as complete."""
    s = _shim()
    s._DATA_MAX_BYTES = 40
    import types, requests
    payload = b"Date,v\n" + b"".join(b"2026-01-%02d,1.0\n" % i for i in range(1, 20))

    class _R:
        status_code = 200
        headers = {"Content-Type": "text/csv"}
        raw = types.SimpleNamespace(read=lambda *_a, **_k: payload)
        def close(self): pass
    orig, requests.get = requests.get, lambda *a, **k: _R()
    try:
        out = s._extract_data_content("http://x/data.csv", "text/csv")
    finally:
        requests.get = orig
    assert out["truncated"] is True
    assert "TRUNCATED" in out["content"] and "NOT the whole file" in out["content"]


# ------------------------------------------------------------------- the routing guard

def test_policy_routes_securities_to_the_specialized_analyzer():
    """A generic fetch must not displace the stock analyzer — stated as POLICY, not a ticker
    regex (the Cardinal Rule forbids deciding meaning with patterns)."""
    assert "FOR A LISTED SECURITY" in FLAT
    assert "ONLY path that renders" in FLAT
    guard = FLAT[FLAT.index("FOR A LISTED SECURITY"):FLAT.index("FOR A LISTED SECURITY") + 1200]
    assert not re.search(r"\[A-Z\]\{1,5\}", guard), "guard must not pattern-match tickers"
    assert "no specialized tool covers" in guard


def test_policy_requires_naming_the_fetched_source():
    assert "NAME WHAT YOU FETCHED" in FLAT


# ------------------------------------------- the contract the caller actually requires

def test_data_result_satisfies_the_same_contract_as_the_html_extractor():
    """PRODUCTION BUG, 2026-08-11 (v1.0.0.253 first cut).

    The data path fetched the CSV correctly and then died FORMATTING it: the caller builds
    its source block from result['title'] / ['author'] / ['date'] unconditionally, which the
    HTML and PDF extractors supply and the new data path did not. The model saw
    "Website extraction error: 'title'" — a fetch that SUCCEEDED and was then lost.

    A partial return contract is worse than no path at all: the old failure at least named
    the URL. This pins every key the caller reads.
    """
    import types
    import requests
    s = _shim()
    payload = b"Date,10 Yr\n08/10/2026,4.72\n08/07/2026,4.65\n"

    class _R:
        status_code = 200
        headers = {"Content-Type": "text/csv"}
        raw = types.SimpleNamespace(read=lambda *_a, **_k: payload)
        def close(self): pass

    orig, requests.get = requests.get, lambda *a, **k: _R()
    try:
        out = s._extract_data_content("http://x/d.csv", "text/csv")
    finally:
        requests.get = orig

    for key in ("success", "title", "author", "date", "content"):
        assert key in out, f"caller reads result[{key!r}] unconditionally — KeyError otherwise"
    assert out["title"], "title must be non-empty; it labels the source block"


def test_data_and_html_return_the_same_key_set_for_the_caller():
    """Guards the SHAPE rather than one key, so a future field added to the HTML extractor
    and consumed by the caller cannot silently break the data path again."""
    required = re.findall(r'"(success|title|author|date|content)":', _grab("_extract_web_content"))
    data_src = _grab("_extract_data_content")
    for key in set(required):
        assert f'"{key}"' in data_src, f"data path never sets {key!r} that the HTML path returns"


# --------------------------------------------------- timeouts sized from measurement

def test_probe_timeout_is_sized_for_a_slow_origin():
    """PRODUCTION, 2026-08-11: the probe's 10s default TIMED OUT against home.treasury.gov
    from the AWS host, so the data path never ran and every file fell through to the HTML
    extractor as "No content found" — while working perfectly from a residential line.

    Measured from prod: HEAD 10s -> ReadTimeout, HEAD 30s -> 4.2s OK, cold GET 15.2s,
    warm GET 0.4s. A public data endpoint may be slow and highly variable; the timeout must
    have headroom over the SLOW case, not the fast one.
    """
    probe = _grab("_probe_content_type")
    fetch = _grab("_extract_data_content")
    assert "timeout: int = 30" in probe, "probe timeout must clear the measured 15s+ worst case"
    assert "timeout: int = 45" in fetch, "fetch timeout must exceed the measured cold-GET time"


def test_probe_failures_are_logged_not_swallowed():
    """A bare `except: continue` made a prod-only timeout indistinguishable from 'this site
    has no content' — it cost two round-trips to diagnose."""
    probe = _grab("_probe_content_type")
    assert "logger.info" in probe, "a probe failure must leave a trace"
    assert "content-type probe" in probe
