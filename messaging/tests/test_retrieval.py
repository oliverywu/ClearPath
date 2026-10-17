from models import Regulation
from retrieval import search, search_all_jurisdictions


def make_fixture() -> list[Regulation]:
    return [
        Regulation(
            id="US-312.6-1",
            jurisdiction="US",
            article="21 CFR 312.6",
            title="Labeling of an investigational new drug",
            text="The immediate package shall bear a label with the statement "
                 "'Caution: New Drug-Limited by Federal law to investigational use.'",
            source_url="https://www.ecfr.gov/example",
            effective_date="October 15, 2026",
            source_type="verbatim_regulation",
            topic="mandatory label content",
            notes=None,
        ),
        Regulation(
            id="EU-ANNEXVI-1",
            jurisdiction="EU",
            article="Articles 66-70 and Annex VI",
            title=None,
            text="Annex VI addresses storage conditions and period of use on the label.",
            source_url="https://eur-lex.europa.eu/example",
            effective_date=None,
            source_type="secondary_summary",
            topic="storage conditions",
            notes="Summary extracted from a secondary source; verify against official text.",
        ),
        Regulation(
            id="Japan-ART16-1",
            jurisdiction="Japan",
            article="Article 16, Paragraph 1",
            title="Mandatory Labeling Requirements",
            text="The sponsor shall indicate the storage conditions and validity period "
                 "on the container of an investigational drug.",
            source_url="https://laws.e-gov.go.jp/example",
            effective_date="April 30, 2026",
            source_type="translation",
            topic="storage conditions",
            notes="Working translation; verify against the official Japanese text.",
        ),
    ]


def test_search_returns_relevant_jurisdiction_only():
    regs = make_fixture()
    results = search("storage conditions", regs, jurisdiction="Japan")
    assert len(results) == 1
    assert results[0].jurisdiction == "Japan"


def test_search_scores_keyword_overlap():
    regs = make_fixture()
    results = search("caution new drug label", regs)
    assert results
    assert results[0].jurisdiction == "US"


def test_search_returns_empty_when_nothing_matches():
    regs = make_fixture()
    results = search("unrelated topic about spaceships", regs)
    assert results == []


def test_search_unknown_jurisdiction_raises():
    regs = make_fixture()
    try:
        search("storage", regs, jurisdiction="Mars")
    except ValueError:
        pass
    else:
        assert False, "expected ValueError for unknown jurisdiction"


def test_search_all_jurisdictions_includes_empty_ones():
    regs = make_fixture()
    results = search_all_jurisdictions("storage conditions", regs)
    assert set(results.keys()) == {"US", "EU", "Japan", "Canada"}
    assert results["Canada"] == []  # no data for Canada -- must show up as empty, not omitted
    assert results["EU"]
    assert results["Japan"]
