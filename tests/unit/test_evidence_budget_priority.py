"""SI-025 — computed tool output must survive evidence budgeting on multi-entity queries.

WHAT THE USER SAW (2026-08-10)
-----------------------------
An 8-stock `@Ask` query returned "No technical chart markers were provided in the evidence"
for ALL EIGHT stocks and contained ZERO DCF intrinsic values — while the log showed the
tools had SUCCEEDED: 8/8 `Calculating DCF for …` and 8/8 `chart marker EMITTED`.

The output was produced and then thrown away by evidence budgeting:

    10:33  2-stock run: 28 items / 136,763 chars -> under budget -> markers survived
    11:21  8-stock run: 78 items / 824,053 chars -> 50/78 truncated -> evidence=0 markers

THREE COMPOUNDING DEFECTS

1. A DUPLICATE YAML KEY. `verification:` sat at synthesis-child depth with its own five
   children at the SAME depth, so YAML made them synthesis siblings — and the verifier's
   `evidence_token_budget: 87000` silently overrode `synthesis.evidence_token_budget:
   160000` (last key wins). Synthesis ran at 87k instead of 160k for its whole life, in
   prod as well. Fixed by dedenting ONE line.

2. The gap-assessment loop was revived (SI-015/SI-021). Correct, but it lifted gathering
   from 2 rounds to 4 — from ~34k tokens to ~206k — overflowing a budget that was already
   46% smaller than intended. Prod's BROKEN assessor had been an accidental safeguard.

3. Flat fair-share truncation cuts the wrong thing. Web prose is redundant (five articles
   say much the same); a tool block is not — its DCF, ratios and rendered chart exist in
   exactly one place. Under fair-share the analyzer blocks, being LARGEST, were cut hardest,
   and because the analyzer appends its `[[chart:…]]` marker LAST, head-truncation destroyed
   precisely the irreplaceable part.

The model was honest: "no chart markers were provided" was TRUE of the evidence it got.
"""
import pathlib
import sys

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from research.synthesis import ResearchSynthesizer, _tok_count, _ARTIFACT_MARKER_RE  # noqa: E402

MARKER = '[[chart:/static/images/media/abc.jpg|align=center|caption="X — daily chart"]]'
ANALYZER = "COMPANY OVERVIEW " * 4000 + "\nDCF … INTRINSIC VALUE PER SHARE: $179.44\n" + MARKER
WEB = "web article prose " * 520


def _cfg():
    return yaml.safe_load((ROOT / "config" / "llm_config.yaml").read_text())["deep_research"]["engine"]


def _engine():
    return ResearchSynthesizer(lambda *a, **k: None, _cfg())


def _profile(n_analyzer=8, n_web=70):
    ev = [{"source": "comprehensive_stock_analyzer", "content": ANALYZER, "urls": []}
          for _ in range(n_analyzer)]
    ev += [{"source": "search_web", "content": WEB, "urls": []} for _ in range(n_web)]
    return ev


def _flat_share(sizes, budget):
    """The PRE-FIX allocator, verbatim — the control this suite is measured against."""
    if sum(sizes) <= budget:
        return sizes
    n = len(sizes)
    fair = max(1, budget // n)
    caps = [0] * n
    large, rem = [], budget
    for i, s in enumerate(sizes):
        if s <= fair:
            caps[i] = s
            rem -= s
        else:
            large.append(i)
    if large:
        sh = max(1, rem // len(large))
        for i in large:
            caps[i] = sh
    return caps


# ---------------------------------------------------------------- the config defect

def test_synthesis_budget_is_not_shadowed_by_the_verifier_key():
    """The duplicate-key bug: synthesis must read 160000, not the verifier's 87000."""
    e = _cfg()
    assert e["synthesis"]["evidence_token_budget"] == 160000
    assert (e.get("verification") or {}).get("evidence_token_budget") == 87000


def test_verification_settings_are_reachable_where_the_code_reads_them():
    """`self._cfg.get("verification")` is ENGINE-level, and there must be exactly ONE such
    block. The stranded settings were MERGED into the existing engine block rather than
    dedented into a rival one.

    The first attempt at this fix simply dedented the stranded block — which created a
    SECOND engine-level `verification:` and, YAML taking the last, silently downgraded
    max_tokens from 32000 to the stranded 24000. That is the very bug class being fixed, so
    this pins the surviving value at 32000 (the newer engine-block value, which supersedes
    the stranded 24000) and `test_no_duplicate_yaml_keys_under_engine` guards the count.
    """
    e = _cfg()
    v = e.get("verification") or {}
    assert v.get("max_tokens") == 32000, "the stranded 24000 must NOT supersede the engine 32000"
    assert v.get("evidence_token_budget") == 87000
    assert v.get("min_corroborating_sources") == 2
    assert v.get("enabled") is True
    for leaked in ("max_tokens", "verify_model", "min_corroborating_sources"):
        assert leaked not in e["synthesis"], f"{leaked} is still leaking into synthesis"


def test_engine_accessors_return_the_restored_budgets():
    se = _engine()
    assert se._evidence_token_budget == 160000
    assert se._verify_evidence_budget == 87000


# ------------------------------------------------------------ the allocation defect

def test_computed_blocks_survive_where_flat_share_destroyed_them():
    """THE REGRESSION TEST. Reproduces the user's profile: 78 items / ~206k tokens.

    Fails on the pre-fix allocator at BOTH budgets — which is the point: the config fix
    alone was NOT sufficient (it only lifted the analyzer block from 9% to 52%).
    """
    ev = _profile()
    sizes = [_tok_count(e["content"]) for e in ev]
    assert sum(sizes) > 160000, "profile must EXCEED the budget or nothing is being tested"

    assert _flat_share(sizes, 87000)[0] < sizes[0], "control: 87k must truncate the analyzer"
    assert _flat_share(sizes, 160000)[0] < sizes[0], "control: 160k alone must STILL truncate it"

    caps = _engine()._allocate_token_budget(ev)
    assert caps[0] == sizes[0], "analyzer block was truncated — DCF and chart are lost"


def test_web_evidence_is_not_starved_by_the_priority_pass():
    """Protecting computed blocks must not reduce scraped evidence to nothing."""
    ev = _profile()
    caps = _engine()._allocate_token_budget(ev)
    web = [c for c, e in zip(caps, ev) if e["source"] == "search_web"]
    assert min(web) > 0
    assert sum(web) > 0.2 * 160000, "web evidence collapsed — ceiling is too aggressive"


def test_total_allocation_still_respects_the_budget():
    caps = _engine()._allocate_token_budget(_profile())
    assert sum(caps) <= 160000


def test_no_truncation_at_all_when_everything_fits():
    """Small runs must behave EXACTLY as before — this is the common path."""
    ev = _profile(n_analyzer=2, n_web=10)
    sizes = [_tok_count(e["content"]) for e in ev]
    assert _engine()._allocate_token_budget(ev) == sizes


def test_priority_ceiling_prevents_computed_blocks_eating_everything():
    """With enough entities the computed blocks alone exceed the budget; they must be
    bounded rather than consuming it entirely."""
    ev = _profile(n_analyzer=40, n_web=10)
    se = _engine()
    caps = se._allocate_token_budget(ev)
    prio = sum(c for c, e in zip(caps, ev) if e["source"] == "comprehensive_stock_analyzer")
    assert prio <= int(160000 * se._priority_budget_ceiling) + 1
    assert sum(caps) <= 160000


# ------------------------------------------------------- the marker-rescue backstop

def test_artifact_markers_are_rescued_from_a_truncated_block():
    """Last-resort guard: a marker is ~100 chars and sits at the block TAIL, so head
    truncation always destroys it. Re-attaching costs nothing and is the difference
    between a rendered chart and 'no chart markers were provided'."""
    ev = [{"source": "comprehensive_stock_analyzer", "content": ANALYZER, "urls": []}
          for _ in range(40)] + [{"source": "search_web", "content": WEB, "urls": []}]
    doc = _engine()._evidence_document(ev, {})
    assert "truncated to fit context budget" in doc, "test is void unless truncation happened"
    assert _ARTIFACT_MARKER_RE.search(doc), "chart marker did not survive truncation"


def test_marker_regex_matches_all_three_artifact_kinds():
    for kind in ("chart", "image", "file"):
        assert _ARTIFACT_MARKER_RE.search(f'[[{kind}:/static/x.jpg|align=center]]')
