"""Topic-agnostic quality metrics — proves they do not encode one subject or one era.

Written after the first cut of the S9 instruments was found to be topic-locked: a hardcoded
700-1000 BC window, a list of ancient Near East inscriptions, and a speech-vs-writing word
list. Baselining on those and then "improving" would have tuned the system for a single
question and reported it as a quality gain.

The suite therefore exercises every metric on FOUR unrelated subjects — ancient history,
equity research, modern public policy, and clinical science — plus the two bias traps the
module deliberately refuses to encode.
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "benchmark"))

from lib.generic_quality import (  # noqa: E402
    citation_mix, citation_reuse, debate_markers, declared_span, retrieval_depth,
    span_subdivisions, span_violations, unanchored_citation_ratio,
)

# --------------------------------------------------------------------- declared bounds

def test_declared_span_reads_bc_ranges():
    """BC years go onto a signed axis so ordinary comparison works across the era line."""
    assert declared_span("How did people communicate around 700 to 1000 BC?") == (-1000, -700)


def test_declared_span_reads_modern_ranges():
    """The same metric must serve a question about recent decades."""
    assert declared_span("How did US manufacturing employment change from 1990 to 2020?") == (1990, 2020)


def test_declared_span_is_none_when_the_request_sets_no_bound():
    """Absence must read as 'not applicable', never as a default window that invents a
    scope error on a question that never asked for one."""
    assert declared_span("Compare NVDA and AMD on valuation and growth.") is None
    assert span_violations("The Roman Empire (27 BC-476 AD) was large.", None) == []


# --------------------------------------------------------------------- scope violations

def test_span_violation_fires_across_unrelated_subjects():
    """Same rule, four subjects: the answer supplies dates that exclude the entity."""
    ancient = "The Neo-Babylonian Empire (626-539 BC) dominated the region."
    assert "Neo-Babylonian Empire" in " ".join(span_violations(ancient, (-1000, -700)))

    modern = "The Dot-com Boom (1995-2000) drove semiconductor demand."
    assert "Dot-com Boom" in " ".join(span_violations(modern, (2010, 2020)))


def test_span_violation_ignores_an_overlapping_entity():
    """Overlap is in scope. A metric that punished partial overlap would be wrong on any
    entity that straddles the boundary, which is most of them."""
    text = "The Neo-Assyrian Empire (911-609 BC) expanded west."
    assert span_violations(text, (-1000, -700)) == []


def test_out_of_bounds_background_without_dates_is_not_penalised():
    """Using later context to explain a bounded period is legitimate scholarship. Only a
    DATED entity placed wholly outside the bounds is counted, so prose background is safe."""
    text = "Aramaic later served the Achaemenid administration, which explains its survival."
    assert span_violations(text, (-1000, -700)) == []


# --------------------------------------------------------------------- citation structure

FINANCE = ("Revenue rose 12% to $30.0B [Q3 filing](https://www.sec.gov/ix?doc=1) while "
           "margins compressed [analysis](https://doi.org/10.1000/x). "
           "The filing is discussed further [here](https://www.sec.gov/ix?doc=1).")

CLINICAL = ("A 2019 trial of 1,204 patients found a 31% reduction "
            "[NEJM trial](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC1). "
            "The topic is examined [in this review](https://en.wikipedia.org/wiki/Statin).")


def test_citation_reuse_is_subject_independent():
    """Three citations over two distinct URLs is 1.5 whatever the subject."""
    assert citation_reuse(FINANCE) == 1.5
    assert citation_reuse("no citations here at all") == 0.0


def test_citation_mix_classifies_structurally_not_by_vocabulary():
    mix = citation_mix(CLINICAL)
    assert mix["unique"] == 2
    assert mix["academic"] == 0.5, "PMC must classify as scholarly"
    assert mix["encyclopedic"] == 0.5
    assert citation_mix(FINANCE)["official"] == 0.5, "sec.gov must classify as official"


def test_citation_mix_cannot_be_improved_by_citing_one_page_more_often():
    """Shares are over DISTINCT urls, so repetition changes reuse, never the mix."""
    once = citation_mix(FINANCE)
    twice = citation_mix(FINANCE + " Again [same](https://www.sec.gov/ix?doc=1).")
    assert once == twice


# --------------------------------------------------------------------- attribution substance

def test_unanchored_ratio_flags_a_contentless_attribution_in_any_wording():
    """The defect is structural, so it survives paraphrase — which the old phrase-list
    detector did not: rewording 'directly addresses' to 'sheds light on' defeated it."""
    for verb in ("directly addresses this phenomenon", "sheds light on the question",
                 "considers these matters", "is devoted to the subject"):
        s = f"A chapter by the author {verb} [Some Chapter](https://doi.org/10.1/a)."
        assert unanchored_citation_ratio(s) == 1.0, f"should flag: {verb}"


def test_unanchored_ratio_passes_a_sentence_that_states_a_finding():
    """A real finding carries a figure, a date, a quotation or a named entity."""
    assert unanchored_citation_ratio(
        "Aramaic displaced Akkadian in provincial records by 700 BC "
        "[The Spread of Aramaic](https://doi.org/10.1/a).") == 0.0
    assert unanchored_citation_ratio(CLINICAL.split(". ")[0] + ".") == 0.0


def test_unanchored_ratio_ignores_uncited_prose():
    """Only citation-bearing sentences are judged; narrative sentences are not the target."""
    assert unanchored_citation_ratio("This paragraph makes a general point with no source.") == 0.0


# --------------------------------------------------------------------- retrieval depth

def test_retrieval_depth_reads_the_audit_line_on_any_topic():
    assert retrieval_depth("Evidence: 30 results across 4 round(s), 98 unique sources (217,207 chars)") == 2216
    assert retrieval_depth("Evidence: 12 results, 10 unique sources (500,000 chars)") == 50000


def test_retrieval_depth_is_zero_when_unmeasurable():
    """Must not fabricate a depth when the audit line is absent."""
    assert retrieval_depth("An answer with no audit footer.") == 0


# --------------------------------------------------------------------- the refused biases

def test_disagreement_is_diagnostic_and_carries_no_direction():
    """Scoring debate higher-is-better rewards manufacturing controversy on settled
    questions — the topics where the system is already weakest. The helper counts; the
    scenario must not attach a direction to it."""
    settled = "Evolution by natural selection is supported by all available evidence."
    assert debate_markers(settled) == 0
    contested = "The dating is disputed and some scholars argue for a later horizon."
    assert debate_markers(contested) >= 2
    import inspect

    import lib.generic_quality as gq
    assert "DIAGNOSTIC ONLY" in inspect.getdoc(gq.debate_markers)


def test_subdivision_is_diagnostic_not_a_target():
    """A span that genuinely does not vary should say so rather than invent phases."""
    import inspect

    import lib.generic_quality as gq
    assert "DIAGNOSTIC" in inspect.getdoc(gq.span_subdivisions)
    assert span_subdivisions("The period from 1000 to 700 BC was the Iron Age.", (-1000, -700)) == 0
    assert span_subdivisions(
        "States formed 1000-900 BC; Assyria expanded 900-800 BC.", (-1000, -700)) == 2
