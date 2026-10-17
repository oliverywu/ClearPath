import json
from unittest.mock import MagicMock

from extract_regulations import extract_from_file, build_regulations, FILES


def make_structured_response(items: list[dict]):
    block = MagicMock()
    block.type = "text"
    block.text = json.dumps({"items": items})
    response = MagicMock()
    response.content = [block]
    return response


def test_extract_from_file_empty_text_skips_api_call():
    client = MagicMock()
    result = extract_from_file(client, "Canada", "   \n  ")
    assert result == []
    client.messages.create.assert_not_called()


def test_extract_from_file_parses_structured_response():
    client = MagicMock()
    client.messages.create.return_value = make_structured_response(
        [
            {
                "article": "21 CFR 312.6",
                "title": "Labeling of an investigational new drug",
                "text": "Caution: New Drug.",
                "source_url": "https://www.ecfr.gov/example",
                "effective_date": "October 15, 2026",
                "source_type": "verbatim_regulation",
                "topic": "mandatory label content",
                "notes": None,
            }
        ]
    )

    result = extract_from_file(client, "US", "some raw source text")
    assert len(result) == 1
    assert result[0]["article"] == "21 CFR 312.6"

    # The system prompt + jurisdiction + raw text must actually reach the model.
    call_kwargs = client.messages.create.call_args.kwargs
    assert "US" in call_kwargs["messages"][0]["content"]
    assert "some raw source text" in call_kwargs["messages"][0]["content"]
    assert call_kwargs["output_config"]["format"]["type"] == "json_schema"


def test_build_regulations_skips_empty_files(tmp_path, monkeypatch):
    # Point DATA_DIR at a temp dir with only an EU file populated.
    import extract_regulations as mod

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "us.txt").write_text("")
    (data_dir / "eu.txt").write_text("Annex VI requires storage conditions on the label.")
    (data_dir / "japan.txt").write_text("")
    (data_dir / "canada.txt").write_text("")

    monkeypatch.setattr(mod, "DATA_DIR", data_dir)

    fake_client = MagicMock()
    fake_client.messages.create.return_value = make_structured_response(
        [
            {
                "article": "Annex VI",
                "title": None,
                "text": "Storage conditions must appear on the label.",
                "source_url": None,
                "effective_date": None,
                "source_type": "secondary_summary",
                "topic": "storage conditions",
                "notes": "Verify against official text.",
            }
        ]
    )
    monkeypatch.setattr(mod.anthropic, "Anthropic", lambda: fake_client)

    regulations = mod.build_regulations()

    jurisdictions = {r.jurisdiction for r in regulations}
    assert jurisdictions == {"EU"}  # only EU had content; others yielded zero records
    assert regulations[0].source_type == "secondary_summary"
    assert set(FILES.values()) == {"US", "EU", "Japan", "Canada"}
