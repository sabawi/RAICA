"""Topic-agnostic response-quality metrics.

These exist because the first cut of the S9 instruments was topic-locked: a hardcoded
700-1000 BC window, a list of ancient Near East inscriptions, and a speech-vs-writing
vocabulary. Baselining on those and then "improving" would have tuned RAICA for one
question about one century and called it a quality gain.

Every metric here derives its parameters from the PROMPT and the ANSWER, never from a
subject the author had in mind. Each is usable by any scenario in the suite.

TWO BIASES DELIBERATELY NOT ENCODED
-----------------------------------
* **Disagreement is not scored.** A "does the answer show scholarly debate" metric scored
  higher-is-better rewards manufacturing controversy, and the topics where that does most
  damage — settled science, loaded political premises — are exactly the ones RAICA is
  already weakest on. `debate_markers` is reported as DIAGNOSTIC only, with no direction,
  because its correct value depends entirely on whether the field actually disagrees.
* **Subdivision is not scored higher-is-better.** An answer covering a span that genuinely
  IS uniform should say so, not invent phases. `span_subdivisions` is likewise diagnostic;
  what is scored is the falsifiable error — asserting out-of-bounds material as in-bounds.
"""
import re
import statistics

# ---------------------------------------------------------------- citation structure

_CITE_RE = re.compile(r"\]\((https?://[^)\s]+)\)")

_ACADEMIC = re.compile(
    r"doi\.org|core\.ac\.uk|arxiv\.org|ncbi\.nlm\.nih\.gov|/pmc/|jstor\.org|openalex|"
    r"cambridge\.org|brill\.com|degruyter|oup\.com|springer|wiley\.com|tandfonline|"
    r"sciencedirect|academia\.edu|ssrn\.com|researchgate", re.I)
_ENCYCLOPEDIC = re.compile(r"wikipedia\.org|britannica\.com|wikiwand", re.I)
_OFFICIAL = re.compile(r"\.gov(/|$|\.)|\.gov\.[a-z]{2}|europa\.eu|\.int(/|$)|worldbank\.org|"
                       r"imf\.org|oecd\.org|un\.org|federalreserve|treasury", re.I)


def cited_urls(text):
    """Every inline markdown citation URL, in order (duplicates preserved)."""
    return _CITE_RE.findall(text or "")


def citation_mix(text):
    """Composition of DISTINCT cited URLs by source class.

    Works on any topic: the classes are structural (scholarly publisher, encyclopedia,
    official body) rather than subject vocabulary. Shares are of distinct URLs, so an
    answer cannot improve its mix by citing the same page more often.
    """
    urls = set(cited_urls(text))
    n = len(urls)
    if not n:
        return {"unique": 0, "academic": 0.0, "encyclopedic": 0.0, "official": 0.0}
    return {
        "unique": n,
        "academic":     round(sum(1 for u in urls if _ACADEMIC.search(u)) / n, 3),
        "encyclopedic": round(sum(1 for u in urls if _ENCYCLOPEDIC.search(u)) / n, 3),
        "official":     round(sum(1 for u in urls if _OFFICIAL.search(u)) / n, 3),
    }


def citation_reuse(text):
    """Total citations / distinct URLs. 1.0 = every citation is a different source.

    RAICA's own PRIMARY-FIRST directive already forbids restating one citation across many
    claims. This measures compliance without reference to any subject.
    """
    all_c = cited_urls(text)
    uniq = len(set(all_c))
    return round(len(all_c) / uniq, 2) if uniq else 0.0


# ---------------------------------------------------------------- attribution substance

_ANCHOR = re.compile(
    r"\d"                                   # any figure, year, percentage, quantity
    r"|[“\"'][^”\"']{12,}[”\"']"   # a quotation of some length
    r"|\b[A-Z][a-z]{2,}\s+[A-Z][a-z]{2,}\b"      # a multi-word proper noun
)


def unanchored_citation_ratio(text):
    """Share of citation-bearing sentences carrying NO factual anchor.

    Replaces a phrase-list detector for name-dropping ("X addresses this phenomenon"),
    which was both English-specific and defeated by any paraphrase. This asks a structural
    question instead: does the sentence that cites a source actually state something —
    a figure, a date, a quotation, a named entity — or does it only assert that the source
    is on-topic? A source whose content was never absorbed can only produce the latter,
    in any language and on any subject.

    Lower is better. Note the counterweight: an answer cannot game this by inserting
    figures, because unsupported figures raise `claims_unsupported_ratio` in the same run.
    """
    sentences = re.split(r"(?<=[.!?])\s+", text or "")
    citing = [s for s in sentences if _CITE_RE.search(s)]
    if not citing:
        return 0.0
    bare = 0
    for s in citing:
        # Strip the WHOLE markdown link — link text AND url. Removing only the "](" left the
        # url in the sentence, and virtually every url contains a digit, so the numeric
        # anchor matched almost always and the metric read ~0.0 on every input.
        stripped = re.sub(r"\[[^\]]*\]\(\s*https?://[^)\s]*\s*\)", " ", s)
        if not _ANCHOR.search(stripped):
            bare += 1
    return round(bare / len(citing), 3)


# ---------------------------------------------------------------- retrieval depth

def retrieval_depth(text):
    """Median characters of body retrieved per unique source, from the answer's own audit.

    This is the defect that the 200-char `min_body_chars` bar hides: a source returning a
    single abstract is graded `real`, so a clean provenance line can sit above an answer
    that never engaged its sources. Answer-derived, so it needs no log access, and it is
    meaningful for any subject.
    """
    m = re.search(r"(\d[\d,]*)\s+unique sources?\s*\(([\d,]+)\s*chars?\)", text or "", re.I)
    if not m:
        return 0
    sources = int(m.group(1).replace(",", ""))
    chars = int(m.group(2).replace(",", ""))
    return round(chars / sources) if sources else 0


# ---------------------------------------------------------------- declared bounds

_ERA = r"(?:BCE|BC|CE|AD)"


def declared_span(prompt):
    """The explicit time bounds the REQUEST sets, if any — parsed from the prompt.

    Returned as (low, high) on a signed axis where BC/BCE years are negative, so ordinary
    comparison works across the era boundary. Returns None when the request sets no
    temporal bound, and callers must then skip the bounds metrics rather than invent one.
    """
    p = prompt or ""
    m = re.search(rf"(\d{{3,4}})\s*(?:to|[-–—])\s*(\d{{3,4}})\s*{_ERA}\b", p, re.I)
    if m:
        era = re.search(_ERA, p[m.start():m.end() + 6], re.I).group(0).upper()
        a, b = int(m.group(1)), int(m.group(2))
        if era in ("BC", "BCE"):
            a, b = -a, -b
        return (min(a, b), max(a, b))
    m = re.search(r"\b(1\d{3}|20\d{2})\s*(?:to|[-–—])\s*(1\d{3}|20\d{2})\b", p)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        return (min(a, b), max(a, b))
    return None


def _dated_entities(text):
    """(name, low, high) for every 'Some Entity (911-609 BC)' construction in the answer."""
    out = []
    for m in re.finditer(
            rf"([A-Z][A-Za-z\-'’ ]{{3,44}}?)\s*\((?:c\.?\s*)?(\d{{3,4}})\s*[-–—]\s*(\d{{3,4}})\s*({_ERA})?\)",
            text or ""):
        name, a, b, era = m.group(1).strip(), int(m.group(2)), int(m.group(3)), (m.group(4) or "").upper()
        if era in ("BC", "BCE"):
            a, b = -a, -b
        out.append((name, min(a, b), max(a, b)))
    return out


def span_violations(text, span):
    """Entities the answer DATES wholly outside the requested span.

    This is the falsifiable scope error, and the answer convicts itself: it supplies the
    dates that place the entity outside the bounds it was asked about. Deliberately narrow
    — an entity that merely OVERLAPS the span is in scope, and out-of-bounds material
    presented as background is not counted here, because using later or earlier context is
    legitimate and a metric that punished it would make answers worse.
    """
    if not span:
        return []
    lo, hi = span
    return [n for n, a, b in _dated_entities(text) if b < lo or a > hi]


def span_subdivisions(text, span):
    """DIAGNOSTIC, not scored. Distinct sub-ranges asserted inside the requested span.

    Reported so a reviewer can see whether a long span was treated as one undifferentiated
    block, but never scored higher-is-better: a span over which the answer genuinely does
    not change should say so rather than invent phases.
    """
    if not span:
        return 0
    lo, hi = span
    width = hi - lo
    subs = set()
    for _n, a, b in _dated_entities(text):
        if a >= lo and b <= hi and (b - a) < width:
            subs.add((a, b))
    for m in re.finditer(rf"\b(\d{{3,4}})\s*[-–—]\s*(\d{{3,4}})\s*({_ERA})?\b", text or ""):
        a, b, era = int(m.group(1)), int(m.group(2)), (m.group(3) or "").upper()
        if era in ("BC", "BCE"):
            a, b = -a, -b
        a, b = min(a, b), max(a, b)
        if a >= lo and b <= hi and (b - a) < width:
            subs.add((a, b))
    return len(subs)


def debate_markers(text):
    """DIAGNOSTIC ONLY — never scored with a direction. See the module docstring.

    Whether disagreement SHOULD appear depends on whether the field actually disagrees;
    scoring it higher-is-better rewards manufacturing controversy on settled questions.
    """
    return len(re.findall(
        r"\b(?:scholars disagree|debated|contested|controvers\w*|some (?:scholars|researchers) argue"
        r"|others argue|challenged|revisionist|consensus has shifted|remains open|disputed)\b",
        text or "", re.I))


def median_or_zero(values):
    vals = [v for v in values if v is not None]
    return statistics.median(vals) if vals else 0
