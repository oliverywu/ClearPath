import fcntl
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


def test_answers_human_message(monkeypatch, tmp_path):
    msg = make_message("pho_msg_1")
    client = make_client([msg])
    monkeypatch.setattr(photon_bridge, "answer_question", lambda *a, **k: "US: label must bear a caution statement (21 CFR 312.6).")

    state = photon_bridge.poll_once(
        client, "proj1", [], MagicMock(), fresh_state(), qa_state_path=tmp_path / "qa.json"
    )

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


def test_same_message_not_answered_twice_in_one_run(monkeypatch, tmp_path):
    msg = make_message("pho_msg_4")
    client = make_client([msg])
    monkeypatch.setattr(photon_bridge, "answer_question", lambda *a, **k: "answer")
    qa_path = tmp_path / "qa.json"

    state = photon_bridge.poll_once(client, "proj1", [], MagicMock(), fresh_state(), qa_state_path=qa_path)
    # Second poll returns the same message again (e.g. createdSince boundary overlap).
    state = photon_bridge.poll_once(client, "proj1", [], MagicMock(), state, qa_state_path=qa_path)

    assert client.projects.send_message.call_count == 1


def test_restart_resumes_from_persisted_state(tmp_path, monkeypatch):
    msg = make_message("pho_msg_5")
    client = make_client([msg])
    monkeypatch.setattr(photon_bridge, "answer_question", lambda *a, **k: "answer")

    qa_path = tmp_path / "qa.json"
    state_path = tmp_path / "state.json"
    state = photon_bridge.load_state(state_path)
    state = photon_bridge.poll_once(client, "proj1", [], MagicMock(), state, qa_state_path=qa_path)
    photon_bridge.save_state(state, state_path)

    # Simulate a fresh process: reload state from disk, poll again with the
    # same message still returned by the (mocked) API.
    reloaded_state = photon_bridge.load_state(state_path)
    client.projects.send_message.reset_mock()
    photon_bridge.poll_once(client, "proj1", [], MagicMock(), reloaded_state, qa_state_path=qa_path)

    client.projects.send_message.assert_not_called()


def test_reply_uses_idempotency_key_derived_from_message_id(monkeypatch, tmp_path):
    msg = make_message("pho_msg_6")
    client = make_client([msg])
    monkeypatch.setattr(photon_bridge, "answer_question", lambda *a, **k: "answer")

    photon_bridge.poll_once(
        client, "proj1", [], MagicMock(), fresh_state(), qa_state_path=tmp_path / "qa.json"
    )

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


def test_send_message_failure_leaves_message_unprocessed(monkeypatch, tmp_path):
    msg = make_message("pho_msg_7")
    client = make_client([msg])
    client.projects.send_message.side_effect = RuntimeError("API error")
    monkeypatch.setattr(photon_bridge, "answer_question", lambda *a, **k: "answer")

    state = photon_bridge.poll_once(
        client, "proj1", [], MagicMock(), fresh_state(), qa_state_path=tmp_path / "qa.json"
    )

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


def test_mark_message_read_includes_required_idempotency_key(monkeypatch, tmp_path):
    """Regression test: MarkMessageReadInput's headers model requires
    idempotency-key (same shape as SendMessageHeader). Previously this was
    built as `{"headers": {}}`, which pydantic rejects with a
    ValidationError raised before client.projects.mark_message_read is
    ever actually called -- silently swallowed by the surrounding
    try/except as if it were a remote failure. Asserting on the call
    itself (not just that failure is non-fatal) is what catches that.
    """
    msg = make_message("pho_msg_9b")
    client = make_client([msg])
    monkeypatch.setattr(photon_bridge, "answer_question", lambda *a, **k: "answer")

    photon_bridge.poll_once(
        client, "proj1", [], MagicMock(), fresh_state(), qa_state_path=tmp_path / "qa.json"
    )

    client.projects.mark_message_read.assert_called_once()
    sent_input = client.projects.mark_message_read.call_args.args[0]
    dumped = sent_input.model_dump(by_alias=True, exclude_unset=True)
    assert dumped["headers"]["idempotency-key"] == "mark-read:pho_msg_9b"


def test_mark_message_read_failure_does_not_prevent_marking_processed(monkeypatch, tmp_path):
    msg = make_message("pho_msg_9")
    client = make_client([msg])
    client.projects.mark_message_read.side_effect = RuntimeError("read API down")
    monkeypatch.setattr(photon_bridge, "answer_question", lambda *a, **k: "answer")

    state = photon_bridge.poll_once(
        client, "proj1", [], MagicMock(), fresh_state(), qa_state_path=tmp_path / "qa.json"
    )

    # The reply already went out successfully -- a failed mark-read is not
    # a reason to retry (and re-answer) the message.
    client.projects.send_message.assert_called_once()
    assert "pho_msg_9" in state["processed_ids"]


# --- Requirement 4: preserve citations/warnings in the reply ---------------


def test_reply_text_is_passed_through_unmodified(monkeypatch, tmp_path):
    msg = make_message("pho_msg_10")
    client = make_client([msg])
    full_answer = (
        "[US] 21 CFR 312.6: verbatim regulation. [EU] Annex VI: secondary_summary -- "
        "verify before relying on it. No matching passages for Canada."
    )
    monkeypatch.setattr(photon_bridge, "answer_question", lambda *a, **k: full_answer)

    photon_bridge.poll_once(
        client, "proj1", [], MagicMock(), fresh_state(), qa_state_path=tmp_path / "qa.json"
    )

    sent_input = client.projects.send_message.call_args.args[0]
    dumped = sent_input.model_dump(by_alias=True, exclude_unset=True)
    assert dumped["body"]["content"]["text"] == full_answer


# --- RootModel unwrapping (real SDK responses wrap items in nested RootModels) --


def test_unwrap_passes_through_plain_objects():
    plain = SimpleNamespace(id="x")
    assert photon_bridge._unwrap(plain) is plain


def test_unwrap_strips_nested_root_wrappers():
    inner = SimpleNamespace(id="pho_msg_1")
    wrapped_once = SimpleNamespace(root=inner)
    wrapped_twice = SimpleNamespace(root=wrapped_once)
    assert photon_bridge._unwrap(wrapped_twice) is inner


def test_unwrap_handles_none():
    assert photon_bridge._unwrap(None) is None


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


# --- Requirement 5: one reply per message even with overlapping poll_once calls --


def test_overlapping_poll_once_calls_do_not_double_answer(monkeypatch, tmp_path):
    """Regression test for a live incident: one inbound message received 4
    outbound replies within ~1.2 seconds -- far faster than
    POLL_INTERVAL_SECONDS (3s) allows from a single process's loop. That
    pattern only happens when two poll_once calls overlap and each loads
    the same on-disk processed_ids before either has replied, so both
    independently decide the message is new and both answer it.

    This asserts the fix: a second poll_once call for the same project,
    while a first one is still "in flight" (lock held), is skipped
    entirely rather than racing to answer the same message.
    """
    msg = make_message("pho_msg_14")
    client = make_client([msg])
    monkeypatch.setattr(photon_bridge, "answer_question", lambda *a, **k: "answer")
    lock_path = tmp_path / "bridge.lock"
    qa_path = tmp_path / "qa.json"

    # Simulate a second, concurrently-running poll_once already holding the
    # lock (e.g. another instance of the bridge started by mistake).
    held_lock_file = open(lock_path, "a+")
    fcntl.flock(held_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        state_in = fresh_state()
        state_out = photon_bridge.poll_once(
            client, "proj1", [], MagicMock(), state_in, qa_state_path=qa_path, lock_path=lock_path
        )

        client.projects.send_message.assert_not_called()
        assert state_out == state_in  # unchanged -- retried once the lock is free
    finally:
        fcntl.flock(held_lock_file, fcntl.LOCK_UN)
        held_lock_file.close()

    # Once the lock is released, a normal poll proceeds and answers exactly once.
    state_out = photon_bridge.poll_once(
        client, "proj1", [], MagicMock(), state_in, qa_state_path=qa_path, lock_path=lock_path
    )
    client.projects.send_message.assert_called_once()
    assert "pho_msg_14" in state_out["processed_ids"]


# --- Reliability: incremental checkpointing (crash between messages) ------


def test_on_progress_checkpoints_after_each_message_not_once_per_batch(monkeypatch, tmp_path):
    """A crash between message 1 and message 2 of a batch must not cause
    message 1 to be re-fetched and re-sent on the next start. on_progress
    is how messaging_link.py's bridge loop checkpoints to disk after each
    message completes, instead of once at the end of the whole poll."""
    msg1 = make_message("pho_msg_20", created_at="2026-01-01T00:00:01.000Z")
    msg2 = make_message("pho_msg_21", created_at="2026-01-01T00:00:02.000Z")
    client = make_client([msg1, msg2])
    monkeypatch.setattr(photon_bridge, "answer_question", lambda *a, **k: "answer")

    snapshots = []
    state_out = photon_bridge.poll_once(
        client, "proj1", [], MagicMock(), fresh_state(),
        qa_state_path=tmp_path / "qa.json",
        on_progress=lambda s: snapshots.append(dict(s)),
    )

    assert len(snapshots) == 2
    # After message 1 alone, it must already be checkpointed -- without waiting for message 2.
    assert set(snapshots[0]["processed_ids"]) == {"pho_msg_20"}
    assert set(snapshots[1]["processed_ids"]) == {"pho_msg_20", "pho_msg_21"}
    assert set(state_out["processed_ids"]) == {"pho_msg_20", "pho_msg_21"}


def test_on_progress_defaults_to_none_and_is_optional(monkeypatch, tmp_path):
    """Backward compatible: the standalone CLI bridge never passes on_progress."""
    msg = make_message("pho_msg_22")
    client = make_client([msg])
    monkeypatch.setattr(photon_bridge, "answer_question", lambda *a, **k: "answer")

    state = photon_bridge.poll_once(client, "proj1", [], MagicMock(), fresh_state(), qa_state_path=tmp_path / "qa.json")

    assert "pho_msg_22" in state["processed_ids"]
