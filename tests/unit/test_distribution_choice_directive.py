"""SI-046 — the distribution family must be chosen from the measured shape, by policy not lookup.

WHY. A production request asked for "the appropriate probability distribution curve" and got a
Normal PDF overlaid on manifestly exponential data. The tool-calling model (glm-5.2) held the
shape at the moment it chose — mean 5.88 vs median 5.80, max 7.8 against a 5.5 floor, and
`np.histogram(mag, bins=15)[0] = [74,62,17,32,11,8,5,6,0,2,1,2,2,2,1]` — and chose a bell curve
anyway, because NOTHING in any prompt layer connected those numbers to the choice of family. All
chart guidance answered provenance (where do the numbers come from), never modelling.

THE TRAP THIS TEST GUARDS. The tempting fix is a lookup: earthquakes → Gutenberg-Richter, incomes
→ lognormal, arrivals → Poisson. That is precisely the hardcoded knowledge the project forbids, and
it breaks on the first dataset not on the list. The directive must state a rule about EVIDENCE —
which measurements contradict which kinds of family — and let the model name the distribution.
"""
import re
from pathlib import Path


def _flat(text: str) -> str:
    """Collapse whitespace. The directive is hard-wrapped in the prompt file and split across
    adjacent string literals in code, so a contiguous match would fail on formatting alone —
    which says nothing about whether the model receives the words."""
    return " ".join(text.split())

REPO = Path(__file__).resolve().parents[2]
SYSTEM_PROMPT = REPO / "pre_tool_model_system_prompt.txt"


def test_the_directive_reaches_the_tool_selection_system_prompt():
    text = _flat(SYSTEM_PROMPT.read_text())
    assert "A FITTED CURVE IS A CLAIM ABOUT THE DATA" in text
    for requirement in ("MEASURE THE SHAPE BEFORE YOU FIT ONE",
                        "LET THE MEASUREMENTS RULE OUT FAMILIES",
                        "IF NO FAMILY IS DEFENSIBLE, PLOT THE OBSERVED DATA ALONE"):
        assert requirement in text, f"missing clause: {requirement}"


def test_the_directive_also_reaches_the_per_round_selector():
    """The round that actually chose plot_data on prod was a gather round, whose prompt is built
    in code — the system prompt alone would have missed it."""
    # flatten FIRST: adjacent literals are separated by a newline + indent, so the
    # `" "` seam only exists once whitespace has been collapsed.
    src = _flat((REPO / "fastapi_server_complete.py").read_text()).replace('" "', "")
    assert "If that chart carries a FITTED CURVE" in src
    assert "plot the observed data alone if no family is defensible" in src


def test_NO_subject_to_distribution_lookup_was_introduced():
    """The no-hardcoding invariant. Naming a family in guidance is how a rule table starts: once
    'earthquakes → Gutenberg-Richter' exists, the next dataset is wrong and nobody notices."""
    text = _flat(SYSTEM_PROMPT.read_text()).lower()
    for family in (r"gaussian", r"gutenberg", r"lognormal", r"log-normal", r"poisson",
                   r"weibull", r"pareto", r"normal distribution", r"exponential distribution"):
        assert not re.search(rf"\b{family}\b", text), (
            f"{family!r} named in the tool-selection prompt — the directive must describe which "
            f"MEASUREMENTS contradict a family, never which subject gets which curve")


def test_the_rule_is_stated_as_evidence_not_as_a_recipe():
    """It must survive a dataset nobody anticipated: the criteria are properties of the numbers
    (mode position, mean-median gap, tail decay), not properties of the subject matter."""
    text = _flat(SYSTEM_PROMPT.read_text())
    for criterion in ("mode sitting at the edge", "mean noticeably displaced from the median",
                      "fall away", "assign almost no probability"):
        assert criterion in text, f"missing evidence criterion: {criterion}"


def test_every_diagnostic_the_directive_asks_for_is_actually_computable():
    """LLM-Policy Gate, no-inconsistency clause: a directive telling the model to measure something
    its calculation tool REJECTS would be defeated silently by the code gate. numpy has no skew
    function, so the phrasing must stay within what the allow-list can express."""
    from utils.restricted_numpy_eval import evaluate
    d = {"v": [5.5, 5.6, 5.5, 6.0, 7.8, 5.5, 6.4, 5.9, 5.5, 6.1]}
    for expr in ("np.mean(v) - np.median(v)",
                 "np.mean(((v - np.mean(v))/np.std(v))**3)",
                 "np.histogram(v, bins=5)[1][np.argmax(np.histogram(v, bins=5)[0])]",
                 "np.histogram(v, bins=5)[0]",
                 "np.max(v) - np.percentile(v, 95)"):
        evaluate(expr, d)      # raises RestrictedEvalError if the gate contradicts the policy
