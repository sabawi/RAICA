"""SI-023 — the three synthesis-integrity directives must reach the model.

From a user review of a real NVDA/AAPL report. Three defects, none about data accuracy
(the figures were verified exact against live yfinance) and all about how the analysis
PRESENTED itself:

  (a) low-credibility sources carried load-bearing numbers ($740B capex, KPMG survey
      percentages) as bare facts. RAICA graded them weak and disclosed the grade in a
      footer, then cited them as if they were solid.
  (b) "30%/50%/20%" and "60% confidence" were presented with the precision of a computed
      output. No calibration model exists; they are LLM judgements.
  (c) the DCF said -62.6% overvalued while the price target implied upside, side by side,
      unreconciled. The LLM papered over it in prose ("structurally conservative by
      design") — which is a tell that the tool is wrong, not a reconciliation.

These are POLICY, expressed in language, per the LLM-policy gate — no keyword lists, no
regex, no if/elif deciding meaning. The tests below guard PRESENCE and FORM: that the
directives are still shipped to the model, and that they did not decay into pattern
matching. Behavioural compliance is verified by real end-to-end runs, not here.
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
_RAW = (ROOT / "research" / "synthesis.py").read_text()

# Join adjacent string literals so we assert against the text the MODEL receives, not the
# source layout. A phrase that happens to straddle a line continuation ("...structurally "
# "conservative") is present at runtime but invisible to a raw-source search — the first
# version of this test failed for exactly that reason, which would have read as a missing
# directive rather than a broken assertion.
SRC = re.sub(r'"\s*\n\s*"', "", _RAW)

BLOCK = SRC[SRC.index("SI-023 (a)"):SRC.index("QUANTITATIVE DATA")]


def test_weak_source_directive_is_shipped():
    assert "SOLE SUPPORT FOR A LOAD-BEARING NUMBER" in SRC
    assert "according to <site>" in SRC, "must tell the model HOW to attribute, not just to"


def test_weak_source_directive_permits_rather_than_bans():
    """Blanket exclusion would cut real coverage — a broker page can carry a real consensus.

    The rule is attribution, not suppression. It must also align with the verifier, which
    treats `attributed_to_low_credibility` as a FEATURE (research/pipeline.py).
    """
    assert "may still use it" in BLOCK
    assert "remain welcome for context" in BLOCK


def test_probability_directive_requires_basis_not_removal():
    """Scenario weights are standard analyst practice; the defect is false precision."""
    assert "MUST NOT IMPERSONATE A CALCULATION" in SRC
    assert "SHOULD give them when the request" in BLOCK, "must not read as a ban"
    assert "never '62.4%'" in BLOCK, "must pin the precision failure concretely"


def test_reconciliation_directive_rejects_the_observed_dodge():
    """The exact evasion seen in production must be named, or it will recur."""
    assert "RECONCILE MODEL OUTPUT WITH YOUR CONCLUSION" in SRC
    assert "structurally conservative" in BLOCK, \
        "the directive must name the observed hand-wave as NOT a reconciliation"
    assert "is NOT a reconciliation" in BLOCK


def test_directives_are_policy_language_not_pattern_matching():
    """LLM-policy gate: RAICA states the RULE; the model decides what matches it."""
    assert not re.search(r"re\.(match|search|compile|findall)", BLOCK)
    assert not re.search(r"\bif\b.+\bin \[", BLOCK)
    for banned in ("KEYWORDS", "PATTERNS", "startswith", "endswith"):
        assert banned not in BLOCK


def test_all_three_reach_the_same_prompt_the_model_sees():
    """A directive in a block the model never receives is worse than none."""
    i = SRC.index("SI-023 (a)")
    tail = SRC[i:i + 6000]
    assert tail.count('"- ') >= 3 or BLOCK.count("- ") >= 3
    # they must sit inside the same concatenated system-prompt literal as existing rules
    assert "PRIMARY-FIRST" in SRC and "Do NOT overstate your sourcing" in SRC
