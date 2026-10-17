from types import SimpleNamespace
from unittest.mock import MagicMock

import photon_bridge


def make_message(
    id_,
    text="What must appear on the label?",
    created_at="2026-01-01T00:00:01.000Z",
    sent_by_kind="human",
    received_by_id="pho_usr_agent",
    content_type="text",
):
    content = SimpleNamespace(type=content_type, text=text) if content_type else None
    return SimpleNamespace(
        id=id_,
        createdAt=created_at,
        content=content,
        space=SimpleNamespace(id="pho_spc_1"),
        sentBy=SimpleNamespace(kind=sent_by_kind, id="pho_usr_human"),
        receivedBy=SimpleNamespace(id=received_by_id) if received_by_id else None,
        addressedTo=None,
    )


def make_client(messages):
    client = MagicMock()
    client.projects.list_messages.return_value = SimpleNamespace(items=messages)
    return client


def fresh_state():
    return {"cursor": None, "processed_ids": []}


# --- Requirement 1: only respond to incoming user messages ----------------


def test_answers_human_message(monkeypatch):
    msg = make_message("pho_msg_1")
    client = make_client([msg])
    monkeypatch.setattr(photon_bridge, "answer_question", lambda *a, **k: "US: label must bear a caution statement (21 CFR 312.6).")

    state = photon_bridge.poll_once(client, "proj1", [], MagicMock(), fresh_state())

    client.projects.send_message.assert_called_once()
    assert "pho_msg_1" in state["processed_ids"]


def test_ignores_message_sent_by_agent(monkeypatch):
    msg = make_message("pho_msg_2", sent_by_kind="agent")
    client = make_client([msg])
    monkeypatch.setattr(photon_bridge, "answer_question", lambda *a, **k: "should not be called")

    state = photon_bridge.poll_once(client, "proj1", [], MagicMock(), fresh_state())

    client.projects.send_message.assert_not_called()
    # Marked seen so it isn't re-evaluated on every future poll.
    assert "pho_msg_2" in state["processed_ids"]


def test_ignores_non_text_content(monkeypatch):
    msg = make_message("pho_msg_3", content_type="reaction")
    client = make_client([msg])
    monkeypatch.setattr(photon_bridge, "answer_question", lambda *a, **k: "should not be called")

    state = photon_bridge.poll_once(client, "proj1", [], MagicMock(), fresh_state())

    client.projects.send_message.assert_not_called()
    assert "pho_msg_3" in state["processed_ids"]


def test_query_filters_to_received_direction():
    client = make_client([])
    photon_bridge.poll_once(client, "proj1", [], MagicMock(), fresh_state())

    sent_input = client.projects.list_messages.call_args.args[0]
    dumped = sent_input.model_dump(by_alias=True, exclude_unset=True)
    assert dumped["query"]["direction"] == "received"
    assert dumped["query"]["platform"] == "imessage"


# --- Requirement 2: prevent duplicate replies, including after restart ----


def test_same_message_not_answered_twice_in_one_run(monkeypatch):
    msg = make_message("pho_msg_4")
    client = make_client([msg])
    monkeypatch.setattr(photon_bridge, "answer_question", lambda *a, **k: "answer")

    state = photon_bridge.poll_once(client, "proj1", [], MagicMock(), fresh_state())
    # Second poll returns the same message again (e.g. createdSince boundary overlap).
    state = photon_bridge.poll_once(client, "proj1", [], MagicMock(), state)

    assert client.projects.send_message.call_count == 1


def test_restart_resumes_from_persisted_state(tmp_path, monkeypatch):
    msg = make_message("pho_msg_5")
    client = make_client([msg])
    monkeypatch.setattr(photon_bridge, "answer_question", lambda *a, **k: "answer")

    state_path = tmp_path / "state.json"
    state = photon_bridge.load_state(state_path)
    state = photon_bridge.poll_once(client, "proj1", [], MagicMock(), state)
    photon_bridge.save_state(state, state_path)

    # Simulate a fresh process: reload state from disk, poll again with the
    # same message still returned by the (mocked) API.
    reloaded_state = photon_bridge.load_state(state_path)
    client.projects.send_message.reset_mock()
    photon_bridge.poll_once(client, "proj1", [], MagicMock(), reloaded_state)

    client.projects.send_message.assert_not_called()


def test_reply_uses_idempotency_key_derived_from_message_id(monkeypatch):
    msg = make_message("pho_msg_6")
    client = make_client([msg])
    monkeypatch.setattr(photon_bridge, "answer_question", lambda *a, **k: "answer")

    photon_bridge.poll_once(client, "proj1", [], MagicMock(), fresh_state())

    sent_input = client.projects.send_message.call_args.args[0]
    dumped = sent_input.model_dump(by_alias=True, exclude_unset=True)
    assert dumped["headers"]["idempotency-key"] == "reply:pho_msg_6"


# --- Requirement 3: handle API failures without losing messages -----------


def test_list_messages_failure_does_not_crash_or_lose_cursor():
    client = MagicMock()
    client.projects.list_messages.side_effect = RuntimeError("network down")

    state_in = fresh_state()
    state_out = photon_bridge.poll_once(client, "proj1", [], MagicMock(), state_in)

    assert state_out == state_in  # unchanged, nothing marked processed


def test_send_message_failure_leaves_message_unprocessed(monkeypatch):
    msg = make_message("pho_msg_7")
    client = make_client([msg])
    client.projects.send_message.side_effect = RuntimeError("API error")
    monkeypatch.setattr(photon_bridge, "answer_question", lambda *a, **k: "answer")

    state = photon_bridge.poll_once(client, "proj1", [], MagicMock(), fresh_state())

    assert "pho_msg_7" not in state["processed_ids"]


def test_answer_question_failure_leaves_message_unprocessed(monkeypatch):
    msg = make_message("pho_msg_8")
    client = make_client([msg])

    def boom(*a, **k):
        raise RuntimeError("Claude API down")

    monkeypatch.setattr(photon_bridge, "answer_question", boom)

    state = photon_bridge.poll_once(client, "proj1", [], MagicMock(), fresh_state())

    assert "pho_msg_8" not in state["processed_ids"]
    client.projects.send_message.assert_not_called()


def test_mark_message_read_failure_does_not_prevent_marking_processed(monkeypatch):
    msg = make_message("pho_msg_9")
    client = make_client([msg])
    client.projects.mark_message_read.side_effect = RuntimeError("read API down")
    monkeypatch.setattr(photon_bridge, "answer_question", lambda *a, **k: "answer")

    state = photon_bridge.poll_once(client, "proj1", [], MagicMock(), fresh_state())

    # The reply already went out successfully -- a failed mark-read is not
    # a reason to retry (and re-answer) the message.
    client.projects.send_message.assert_called_once()
    assert "pho_msg_9" in state["processed_ids"]


# --- Requirement 4: preserve citations/warnings in the reply ---------------


def test_reply_text_is_passed_through_unmodified(monkeypatch):
    msg = make_message("pho_msg_10")
    client = make_client([msg])
    full_answer = (
        "[US] 21 CFR 312.6: verbatim regulation. [EU] Annex VI: secondary_summary -- "
        "verify before relying on it. No matching passages for Canada."
    )
    monkeypatch.setattr(photon_bridge, "answer_question", lambda *a, **k: full_answer)

    photon_bridge.poll_once(client, "proj1", [], MagicMock(), fresh_state())

    sent_input = client.projects.send_message.call_args.args[0]
    dumped = sent_input.model_dump(by_alias=True, exclude_unset=True)
    assert dumped["body"]["content"]["text"] == full_answer


# --- Extraction helpers -----------------------------------------------------


def test_extract_text_returns_none_for_missing_content():
    msg = make_message("pho_msg_11", content_type=None)
    assert photon_bridge.extract_text(msg) is None


def test_reply_identity_falls_back_to_addressed_to():
    msg = make_message("pho_msg_12", received_by_id=None)
    msg.addressedTo = SimpleNamespace(id="pho_usr_fallback")
    assert photon_bridge._reply_identity(msg) == "pho_usr_fallback"


def test_reply_identity_none_when_both_missing_leaves_message_unprocessed(monkeypatch):
    msg = make_message("pho_msg_13", received_by_id=None)
    client = make_client([msg])
    monkeypatch.setattr(photon_bridge, "answer_question", lambda *a, **k: "answer")

    state = photon_bridge.poll_once(client, "proj1", [], MagicMock(), fresh_state())

    client.projects.send_message.assert_not_called()
    assert "pho_msg_13" not in state["processed_ids"]
