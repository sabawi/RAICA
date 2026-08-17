"""A transport failure must remove a source, never become one.

FAILURE THIS PREVENTS
---------------------
Traced down to the transport layer on 2026-08-17, after a 41-minute silent DR stall on
production. Three layers each turned a failure into something that looked like success:

    sync_pooled_get          catches EVERYTHING -> {'status_code': 0, 'ok': False,
                                                    'error': 'Connection reset by peer'}
    raise_for_status()       correctly raises            <- the only honest layer
    get_text_from_url_...    catches it and returns
                             f"Error extracting content: {e}"    <- prose, as page content

The failure signal was created at the bottom and destroyed at the top. The `error` field was
never read by anything -- the same dead-write shape as `article['pub_date']`.

MEASURED ON PRODUCTION: 211 occurrences of "Error extracting content" in a single log, and
**13 of them reached the model** inside the `"prompt"` payload under "DATA AND INFORMATION
GATHERED". 403s, 401 paywalls, 429s and TCP resets were served to the LLM as research
evidence.

Consequences, all silent:
  * nothing could RETRY -- there was no failure to react to
  * evidence/citation/source counts included fetches that never returned a page, corrupting
    the benchmark used to judge answer quality
  * "page had little text" was indistinguishable from "connection was reset"
  * the response was never closed on the error path (see the CLOSE-WAIT caveat below)

CLOSE-WAIT CAVEAT — an attribution that did NOT survive testing. Production showed 43 sockets
in CLOSE-WAIT and this file originally claimed the unclosed response caused them. A harness
driving 30 peer-closed responses leaked ZERO fds both WITH and WITHOUT the close() fix, so
the reproduction does not discriminate. Those sockets may just be pooled keep-alive
connections the remote closed. Closing explicitly is correct hygiene; it is not a proven
fix, and the tests below assert only that close() HAPPENS, never that it fixed a leak.

`None` was ALREADY the convention for an unusable source (dead links, ten lines above) and
the caller already skipped on it. The fix is to use it.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

import http_helpers as HH  # noqa: E402

SERVER_SRC = open(os.path.join(ROOT, "fastapi_server_complete.py")).read()


def _extractor_body():
    """Source of get_text_from_url_simplified — the function under audit.

    Sliced to the statement that FOLLOWS the function rather than a fixed character count:
    a fixed 4000-char window truncated mid-handler and failed two of these tests against
    correct code. A window that can silently cut off the thing under test is not a test.
    """
    i = SERVER_SRC.index("def get_text_from_url_simplified(")
    end = SERVER_SRC.index("# Perform the search", i)
    return SERVER_SRC[i:end]


def _extractor_code():
    """The extractor with COMMENTS STRIPPED — assertions about behaviour belong here.

    The comment above the fix quotes the old line verbatim (`return f"Error extracting
    content: {e}"`) to explain what went wrong. A test grepping raw source therefore matched
    the DOCUMENTATION and failed on correct code. Strip comments, then assert.
    """
    out = []
    for line in _extractor_body().splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        out.append(line)
    return "\n".join(out)


# ───────────────────────────────────────── 1. failures must not become content
def test_a_failed_fetch_no_longer_returns_prose_as_page_content():
    """FAILS PRE-FIX: the handler was `return f"Error extracting content: {str(e)}"`."""
    code = _extractor_code()
    handler = code[code.index("except Exception as e:"):]
    assert 'return f"Error extracting content' not in handler, \
        "a transport failure is still being returned as page content"


def test_the_failure_path_returns_the_none_sentinel():
    """`None` is the convention the caller already honours for an unusable source."""
    code = _extractor_code()
    handler = code[code.index("except Exception as e:"):]
    assert re.search(r"return None", handler), "the failure path does not return the sentinel"


def test_the_caller_drops_a_none_source_instead_of_citing_it():
    """A dropped source must never reach _format_source_block."""
    i = SERVER_SRC.index("extracted_content = get_text_from_url_simplified(")
    seg = SERVER_SRC[i:i + 1200]
    assert "if extracted_content is None:" in seg
    assert "continue" in seg[seg.index("if extracted_content is None:"):]


def test_the_callers_own_except_also_drops_rather_than_describes():
    """The caller had a SECOND copy of the same bug; both had to go."""
    i = SERVER_SRC.index("extracted_content = get_text_from_url_simplified(")
    seg = SERVER_SRC[i:i + 1200]
    assert 'extracted_content = f"Error extracting content' not in seg, \
        "the caller still converts an exception into content"


# ───────────────────────────────────────── 2. the socket must be released
def test_the_response_is_closed_on_every_path():
    """FAILS PRE-FIX: no finally -- the error path dropped the response entirely.

    Asserts the close HAPPENS. Deliberately does NOT claim it fixed the production
    CLOSE-WAIT sockets: that attribution failed to reproduce (see the caveat in the module
    docstring), and a test whose name implies a fix it cannot demonstrate is worse than none.
    """
    src = open(os.path.join(ROOT, "http_helpers.py")).read()
    i = src.index("def sync_pooled_get(")
    fn = src[i:src.index("def sync_pooled_post(", i)]
    assert "finally:" in fn, "no finally block — the connection is not released on failure"
    assert "response.close()" in fn, "the response is never closed"


def test_close_failure_cannot_break_the_request():
    """Releasing a socket is best-effort; it must never mask the real result."""
    src = open(os.path.join(ROOT, "http_helpers.py")).read()
    i = src.index("def sync_pooled_get(")
    fn = src[i:src.index("def sync_pooled_post(", i)]
    tail = fn[fn.index("finally:"):]
    assert "try:" in tail and "except Exception" in tail, \
        "close() is unguarded — a broken socket would raise out of finally"


def test_a_transport_failure_still_reports_ok_false_and_an_error():
    """The bottom layer's signal must survive — it is what everything else keys on."""
    r = HH.PooledResponse({'status_code': 0, 'text': '', 'content': b'', 'headers': {},
                           'url': 'https://x.test', 'ok': False,
                           'error': 'Connection reset by peer'})
    assert r.ok is False
    try:
        r.raise_for_status()
        raise AssertionError("raise_for_status() swallowed a transport failure")
    except Exception as e:
        assert "Connection reset by peer" in str(e)


# ───────────────────────────────────────── 3. the loss must be visible
def test_dropped_sources_are_recorded():
    """FAILS PRE-FIX: nothing counted anything, so a wholly-failed search looked normal."""
    assert "_extraction_failures" in SERVER_SRC, "failures are not recorded"
    i = SERVER_SRC.index("def sync_web_search(")
    assert "_extraction_failures" in SERVER_SRC[i:i + 1500], \
        "the failure list is not initialised per search"


def test_a_failure_is_classified_transient_or_permanent():
    """A retry policy needs to know WHICH failures are worth retrying (429/5xx/reset)."""
    body = _extractor_body()
    assert "transient" in body
    for code in ("429", "503", "Connection reset"):
        assert code in body, f"{code} is not classified"


def test_the_search_reports_how_much_it_lost():
    """A thin result must be distinguishable from a result that was never fetched."""
    assert "DROPPED on fetch failure" in SERVER_SRC, \
        "search_web does not report dropped sources"


def test_each_dropped_source_is_logged_with_its_url_and_reason():
    """Silent loss is what made the production stall undiagnosable."""
    body = _extractor_body()
    handler = body[body.index("except Exception as e:"):]
    assert "logger.warning" in handler, "a dropped source is not logged"


# ───────────────────────────────────────── 4. BEHAVIOURAL: real sockets, real failures
def _open_fds():
    return len(os.listdir(f"/proc/{os.getpid()}/fd"))


def test_a_real_refused_connection_reports_failure_not_empty_success():
    """Exercise the ACTUAL transport layer against a port nothing is listening on.

    Not a mock: this is the code path that produced 43 CLOSE-WAIT sockets in production.
    """
    out = HH.sync_pooled_get("http://127.0.0.1:9/never", timeout=2)
    assert out["ok"] is False, "a refused connection reported success"
    assert out["status_code"] == 0
    assert out.get("error"), "the failure carried no error — the signal is lost here"
    assert out["text"] == ""


def test_repeated_transport_failures_do_not_leak_file_descriptors():
    """A REGRESSION GUARD, not evidence of a fix.

    Measured honestly: this passes on pre-fix code too, because a REFUSED connection never
    establishes a socket and so cannot reproduce CLOSE-WAIT. It is kept to catch a future
    change that starts leaking on the failure path -- it proves nothing about the past.
    """
    HH.sync_pooled_get("http://127.0.0.1:9/warmup", timeout=2)   # ignore one-off setup fds
    before = _open_fds()
    for _ in range(25):
        HH.sync_pooled_get("http://127.0.0.1:9/never", timeout=2)
    after = _open_fds()
    assert after - before <= 2, (
        f"leaked {after - before} fds across 25 failed fetches "
        f"({before} -> {after}) — connections are not being released")


def test_a_successful_fetch_also_releases_its_connection():
    """CONTROL: the fix must not only cover the error path.

    A success that never closes leaks just as surely, and would make the test above pass
    while production still bled sockets.
    """
    import http.server, socketserver, threading
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"<html><body><p>" + b"x" * 200 + b"</p></body></html>"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *a):
            pass

    with socketserver.TCPServer(("127.0.0.1", 0), H) as srv:
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{port}/page"
        HH.sync_pooled_get(url, timeout=5)                        # warm up
        before = _open_fds()
        for _ in range(25):
            r = HH.sync_pooled_get(url, timeout=5)
            assert r["ok"] is True and "xxx" in r["text"]
        after = _open_fds()
        srv.shutdown()
    assert after - before <= 2, (
        f"leaked {after - before} fds across 25 SUCCESSFUL fetches ({before} -> {after})")
