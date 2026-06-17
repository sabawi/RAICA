"""
Tests for the Deep-Research document-title fix (email subject / filename).

Bug: a DR document that opened with an enumerated SECTION heading ("# 1. The Deep Roots …") had that
section grabbed as the document title → the email subject + filename read like a section, and the section
lost its heading in the PDF. Fix = (1) synthesis emits a top-level "# <Title>" first; (2) delivery skips an
enumerated first heading and derives the title from the research request instead.

These tests cover the two deterministic pieces: the enumerated-section discriminator regex, and the
request-derived title helper (`_llm_title_from_request`, with a mocked stream).

Run: python -m pytest tests/integration/test_dr_title_extraction.py -q
 or: python tests/integration/test_dr_title_extraction.py
"""
import asyncio
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

# The SAME discriminator used in _run_dr_delivery to reject enumerated section headings as the title.
_SECTION_RE = re.compile(r'^(\d+\s*[\.\):]|part\s+\d+|section\s+\d+|chapter\s+\d+)', re.IGNORECASE)


def _is_section_heading(cand: str) -> bool:
    return bool(_SECTION_RE.match(cand.strip()))


def test_enumerated_headings_are_rejected_as_title():
    # These are SECTION headings — must NOT be used as the document title.
    for h in ("1. The Deep Roots: Slavery and Reconstruction",
              "2) Origins of the Movement",
              "3 . Spaced Number",
              "Part 1: Background",
              "Section 4 — Findings",
              "Chapter 2 The Early Years"):
        assert _is_section_heading(h), f"should be detected as a section: {h!r}"


def test_real_titles_are_accepted():
    # These are real document TITLES — must be accepted.
    for t in ("History of African American Street Gangs in the United States",
              "The Deep Roots of Reconstruction",          # 'The …', not numbered
              "2026 Iran War: Timeline and Analysis",      # leading number is part of a year, not 'N.'
              "Climate Policy and Its Discontents",
              "U.S. Government Surveillance Programs"):
        assert not _is_section_heading(t), f"should be accepted as a title: {t!r}"


def test_llm_title_from_request_uses_stream_not_heading():
    """The helper must derive a title from the REQUEST via the stream — never echo the content's first
    (section) heading. We mock the stream to return a clean title and assert it's used + cleaned."""
    import fastapi_server_complete as srv

    async def _fake_stream(*args, **kwargs):
        # mimic an async generator yielding chunks like llm_manager.generate_stream
        for chunk in ('"History of ', 'Street Gangs in ', 'the United States"\n'):
            yield chunk

    title = asyncio.get_event_loop().run_until_complete(
        srv._llm_title_from_request(
            "Deep research the history of street gangs... Email results as PDF and HTML.",
            "# 1. The Deep Roots: Slavery, Reconstruction, and the First Black Communities\n\nText…",
            _fake_stream,
        )
    )
    assert title == "History of Street Gangs in the United States", repr(title)
    assert not _is_section_heading(title)


def test_llm_title_from_request_none_stream_is_safe():
    import fastapi_server_complete as srv
    out = asyncio.get_event_loop().run_until_complete(
        srv._llm_title_from_request("q", "content", None))
    assert out == ""   # no stream → empty, caller applies its own generic fallback


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS: {fn.__name__}")
    print("ALL TESTS PASSED")
