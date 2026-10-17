from models import Regulation
from change_detector import detect_changes


def reg(id, text="original text", **overrides) -> Regulation:
    base = dict(
        id=id,
        jurisdiction="US",
        article="X",
        title="Title",
        text=text,
        source_url=None,
        effective_date=None,
        source_type="verbatim_regulation",
        topic=None,
        notes=None,
    )
    base.update(overrides)
    return Regulation(**base)


def test_detects_added():
    old = [reg("A")]
    new = [reg("A"), reg("B")]
    report = detect_changes(old, new)
    assert [r.id for r in report.added] == ["B"]
    assert report.removed == []
    assert report.modified == []
    assert report.has_changes


def test_detects_removed():
    old = [reg("A"), reg("B")]
    new = [reg("A")]
    report = detect_changes(old, new)
    assert report.added == []
    assert [r.id for r in report.removed] == ["B"]
    assert report.modified == []


def test_detects_modified_text():
    old = [reg("A", text="old text")]
    new = [reg("A", text="new text")]
    report = detect_changes(old, new)
    assert report.added == []
    assert report.removed == []
    assert len(report.modified) == 1
    old_reg, new_reg = report.modified[0]
    assert old_reg.text == "old text"
    assert new_reg.text == "new text"


def test_no_changes():
    old = [reg("A")]
    new = [reg("A")]
    report = detect_changes(old, new)
    assert not report.has_changes
    assert report.format() == "No changes detected since the last snapshot."
