from unittest.mock import MagicMock

from models import Regulation
from compare import compare_topic, _format_passages


def make_text_response(text: str):
    block = MagicMock()
    block.type = "text"
    block.text = text
    response = MagicMock()
    response.content = [block]
    return response


def test_format_passages_reports_missing_jurisdiction_explicitly():
    formatted = _format_passages("Canada", [])
    assert "No matching passages found in the dataset" in formatted


def test_format_passages_flags_secondary_summary():
    reg = Regulation(
        id="EU-1",
        jurisdiction="EU",
        article="Annex VI",
        title=None,
        text="Storage conditions must appear on the label.",
        source_url=None,
        effective_date=None,
        source_type="secondary_summary",
        topic="storage conditions",
        notes="Verify against official text.",
    )
    formatted = _format_passages("EU", [reg])
    assert "secondary_summary" in formatted
    assert "Verify against official text." in formatted


def test_compare_topic_sends_per_jurisdiction_context_and_returns_model_text():
    client = MagicMock()
    client.messages.create.return_value = make_text_response("comparison result")

    regs = [
        Regulation(
            id="US-1", jurisdiction="US", article="312.6", title=None,
            text="Label must bear caution statement.", source_url=None,
            effective_date=None, source_type="verbatim_regulation",
            topic="mandatory label content", notes=None,
        ),
    ]

    result = compare_topic("mandatory label content", client=client, regulations=regs)

    assert result == "comparison result"
    call_kwargs = client.messages.create.call_args.kwargs
    user_message = call_kwargs["messages"][0]["content"]
    # US passage should be included; jurisdictions with nothing retrieved
    # (regs fixture only has US data) must still be explicitly mentioned as missing.
    assert "US" in user_message
    assert "No matching passages found in the dataset" in user_message
