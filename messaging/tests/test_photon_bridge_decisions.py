"""Tests for photon_bridge.poll_once's routing between decision_agent
(pending decision replies) and the concise regulatory Q&A fallback.

All state/log paths are explicit tmp_path overrides so these tests never
touch the default `.conversation_state.json` / `.audit_log.jsonl` /
`.qa_context_state.json` files, and never exercise an existing
tests/test_photon_bridge.py scenario (which relies on there being NO
active conversation for its fixture space).
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import audit_log
import decision_agent
import photon_bridge
from impact_analyzer import SIMULATED_DISRUPTION_EVENT

SHIPMENTS = [
    {
        "shipment_id": "SHIP-001",
        "drug_name": "Investigational Insulin Glargine",
        "origin": "Indianapolis, US",
        "destination": "Berlin, DE",
        "shipping_date": "2026-10-01",
        "estimated_transit_days": 5,
        "required_delivery_date": "2026-10-10",
    }
]
AUTHORIZED_ROLES = {"pho_usr_maya": {"name": "Maya", "role": "supply_lead", "can_approve": True}}


def make_message(id_, text, sent_by_id="pho_usr_maya", space_id="pho_spc_1"):
    content = SimpleNamespace(type="text", text=text)
    return SimpleNamespace(
        id=id_,
        createdAt="2026-01-01T00:00:01.000Z",
        content=content,
        space=SimpleNamespace(id=space_id),
        sentBy=SimpleNamespace(kind="human", id=sent_by_id),
        receivedBy=SimpleNamespace(id="pho_usr_agent"),
        addressedTo=None,
    )


def make_client(messages):
    client = MagicMock()
    client.projects.list_messages.return_value = SimpleNamespace(items=messages)
    return client


def fresh_state():
    return {"cursor": None, "processed_ids": []}


def _sent_text(client):
    sent_input = client.projects.send_message.call_args.args[0]
    return sent_input.model_dump(by_alias=True, exclude_unset=True)["body"]["content"]["text"]


# --- routes to decision_agent when a conversation is pending ----------------


def test_numeric_reply_routes_to_decision_agent_not_qa(tmp_path, monkeypatch):
    state_path = tmp_path / "conversations.json"
    audit_path = tmp_path / "audit.jsonl"
    decision_agent.start_conversation(
        "pho_spc_1", SIMULATED_DISRUPTION_EVENT["event_id"], "SHIP-001",
        shipments=SHIPMENTS, state_path=state_path,
    )

    monkeypatch.setattr(
        photon_bridge, "answer_question",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("Q&A must not run while a decision is pending")),
    )

    msg = make_message("pho_msg_opt1", "1")
    client = make_client([msg])

    photon_bridge.poll_once(
        client, "proj1", [], MagicMock(), fresh_state(),
        conversation_state_path=state_path, audit_log_path=audit_path, roles=AUTHORIZED_ROLES,
    )

    assert "Option 1 selected" in _sent_text(client)


def test_approve_routes_to_decision_agent_and_logs_with_authorized_actor(tmp_path, monkeypatch):
    state_path = tmp_path / "conversations.json"
    audit_path = tmp_path / "audit.jsonl"
    decision_agent.start_conversation(
        "pho_spc_1", SIMULATED_DISRUPTION_EVENT["event_id"], "SHIP-001",
        shipments=SHIPMENTS, state_path=state_path,
    )
    monkeypatch.setattr(photon_bridge, "answer_question", lambda *a, **k: "should not be called")

    client = make_client([make_message("pho_msg_opt", "1")])
    state = photon_bridge.poll_once(
        client, "proj1", [], MagicMock(), fresh_state(),
        conversation_state_path=state_path, audit_log_path=audit_path, roles=AUTHORIZED_ROLES,
    )

    client2 = make_client([make_message("pho_msg_approve", "APPROVE")])
    photon_bridge.poll_once(
        client2, "proj1", [], MagicMock(), state,
        conversation_state_path=state_path, audit_log_path=audit_path, roles=AUTHORIZED_ROLES,
    )

    assert "Recorded" in _sent_text(client2)
    entries = audit_log.load_entries(audit_path)
    assert len(entries) == 1
    assert entries[0]["authorized_actor"]["id"] == "pho_usr_maya"


def test_approve_from_unauthorized_actor_is_rejected_and_not_logged(tmp_path, monkeypatch):
    state_path = tmp_path / "conversations.json"
    audit_path = tmp_path / "audit.jsonl"
    decision_agent.start_conversation(
        "pho_spc_1", SIMULATED_DISRUPTION_EVENT["event_id"], "SHIP-001",
        shipments=SHIPMENTS, state_path=state_path,
    )
    monkeypatch.setattr(photon_bridge, "answer_question", lambda *a, **k: "should not be called")

    client = make_client([make_message("pho_msg_opt", "1")])
    state = photon_bridge.poll_once(
        client, "proj1", [], MagicMock(), fresh_state(),
        conversation_state_path=state_path, audit_log_path=audit_path, roles=AUTHORIZED_ROLES,
    )

    client2 = make_client([make_message("pho_msg_approve", "APPROVE", sent_by_id="pho_usr_random")])
    photon_bridge.poll_once(
        client2, "proj1", [], MagicMock(), state,
        conversation_state_path=state_path, audit_log_path=audit_path, roles=AUTHORIZED_ROLES,
    )

    assert "can't approve" in _sent_text(client2)
    assert audit_log.load_entries(audit_path) == []


# --- falls back to concise Q&A when there's no pending decision -------------


def test_falls_back_to_concise_qa_when_no_active_conversation(tmp_path, monkeypatch):
    state_path = tmp_path / "conversations.json"
    qa_path = tmp_path / "qa.json"
    captured = {}

    def fake_answer_question(client, question, regulations, jurisdiction=None, concise=False):
        captured["question"] = question
        captured["concise"] = concise
        return "Short concise answer. Sources: US 21 CFR 312.6. Reply SOURCE for full citations."

    monkeypatch.setattr(photon_bridge, "answer_question", fake_answer_question)

    client = make_client([make_message("pho_msg_q", "What must appear on the label?")])
    photon_bridge.poll_once(
        client, "proj1", [], MagicMock(), fresh_state(),
        conversation_state_path=state_path, qa_state_path=qa_path,
    )

    assert captured["concise"] is True
    assert captured["question"] == "What must appear on the label?"
    assert "Reply SOURCE" in _sent_text(client)


def test_details_reply_replays_full_answer_for_last_cached_question(tmp_path, monkeypatch):
    state_path = tmp_path / "conversations.json"
    qa_path = tmp_path / "qa.json"
    calls = []

    def fake_answer_question(client, question, regulations, jurisdiction=None, concise=False):
        calls.append({"question": question, "concise": concise})
        return "concise answer" if concise else "FULL cited answer with sources"

    monkeypatch.setattr(photon_bridge, "answer_question", fake_answer_question)

    first_client = make_client([make_message("pho_msg_q1", "What must appear on the label?")])
    state = photon_bridge.poll_once(
        first_client, "proj1", [], MagicMock(), fresh_state(),
        conversation_state_path=state_path, qa_state_path=qa_path,
    )

    second_client = make_client([make_message("pho_msg_q2", "DETAILS")])
    photon_bridge.poll_once(
        second_client, "proj1", [], MagicMock(), state,
        conversation_state_path=state_path, qa_state_path=qa_path,
    )

    assert calls[0]["concise"] is True
    assert calls[1]["concise"] is False
    assert calls[1]["question"] == "What must appear on the label?"  # replayed, not re-asked
    assert "FULL cited answer" in _sent_text(second_client)


# --- duplicate inbound events across distinct message ids / process restarts --


def test_duplicate_approve_via_distinct_message_ids_logs_exactly_once(tmp_path, monkeypatch):
    """Two different inbound messages (different ids, so photon_bridge's own
    processed_ids dedup wouldn't catch this) both say APPROVE. Only
    decision_agent's state-based idempotency protects against a duplicate
    audit entry / conflicting plan update here.
    """
    state_path = tmp_path / "conversations.json"
    audit_path = tmp_path / "audit.jsonl"
    decision_agent.start_conversation(
        "pho_spc_1", SIMULATED_DISRUPTION_EVENT["event_id"], "SHIP-001",
        shipments=SHIPMENTS, state_path=state_path,
    )
    monkeypatch.setattr(photon_bridge, "answer_question", lambda *a, **k: "should not be called")

    state = photon_bridge.poll_once(
        make_client([make_message("pho_msg_opt", "1")]), "proj1", [], MagicMock(), fresh_state(),
        conversation_state_path=state_path, audit_log_path=audit_path, roles=AUTHORIZED_ROLES,
    )

    first_approve_client = make_client([make_message("pho_msg_approve_1", "APPROVE")])
    state = photon_bridge.poll_once(
        first_approve_client, "proj1", [], MagicMock(), state,
        conversation_state_path=state_path, audit_log_path=audit_path, roles=AUTHORIZED_ROLES,
    )

    second_approve_client = make_client([make_message("pho_msg_approve_2", "APPROVE")])
    photon_bridge.poll_once(
        second_approve_client, "proj1", [], MagicMock(), state,
        conversation_state_path=state_path, audit_log_path=audit_path, roles=AUTHORIZED_ROLES,
    )

    assert "Recorded" in _sent_text(first_approve_client)
    assert "Already recorded" in _sent_text(second_approve_client)
    entries = audit_log.load_entries(audit_path)
    assert len(entries) == 1
    assert decision_agent.find_approved_decision("SHIP-001", SIMULATED_DISRUPTION_EVENT["event_id"], state_path=state_path) is not None


def test_pending_decision_survives_restart_across_separate_poll_once_calls(tmp_path, monkeypatch):
    """Each poll_once call below gets its own brand-new `state` dict (as if
    the bridge process restarted between polls) and relies purely on the
    on-disk conversation_state_path to carry the pending decision forward.
    """
    state_path = tmp_path / "conversations.json"
    audit_path = tmp_path / "audit.jsonl"
    decision_agent.start_conversation(
        "pho_spc_1", SIMULATED_DISRUPTION_EVENT["event_id"], "SHIP-001",
        shipments=SHIPMENTS, state_path=state_path,
    )
    monkeypatch.setattr(photon_bridge, "answer_question", lambda *a, **k: "should not be called")

    # "Process restart" #1: option selection with a fresh poll cursor state.
    photon_bridge.poll_once(
        make_client([make_message("pho_msg_opt", "1")]), "proj1", [], MagicMock(), fresh_state(),
        conversation_state_path=state_path, audit_log_path=audit_path, roles=AUTHORIZED_ROLES,
    )
    convo = decision_agent.get_conversation("pho_spc_1", SIMULATED_DISRUPTION_EVENT["event_id"], state_path=state_path)
    assert convo["status"] == decision_agent.STATUS_AWAITING_APPROVAL

    # "Process restart" #2: approval, again with a brand-new fresh_state().
    approve_client = make_client([make_message("pho_msg_approve", "APPROVE")])
    photon_bridge.poll_once(
        approve_client, "proj1", [], MagicMock(), fresh_state(),
        conversation_state_path=state_path, audit_log_path=audit_path, roles=AUTHORIZED_ROLES,
    )

    assert "Recorded" in _sent_text(approve_client)
    convo = decision_agent.get_conversation("pho_spc_1", SIMULATED_DISRUPTION_EVENT["event_id"], state_path=state_path)
    assert convo["status"] == decision_agent.STATUS_APPROVED
    assert len(audit_log.load_entries(audit_path)) == 1


def test_details_after_approval_still_routes_to_decision_agent(tmp_path, monkeypatch):
    state_path = tmp_path / "conversations.json"
    audit_path = tmp_path / "audit.jsonl"
    decision_agent.start_conversation(
        "pho_spc_1", SIMULATED_DISRUPTION_EVENT["event_id"], "SHIP-001",
        shipments=SHIPMENTS, state_path=state_path,
    )
    decision_agent.handle_reply(
        "pho_spc_1", SIMULATED_DISRUPTION_EVENT["event_id"], "pho_usr_maya", "1",
        shipments=SHIPMENTS, state_path=state_path, audit_path=audit_path,
    )
    decision_agent.handle_reply(
        "pho_spc_1", SIMULATED_DISRUPTION_EVENT["event_id"], "pho_usr_maya", "APPROVE",
        shipments=SHIPMENTS, state_path=state_path, audit_path=audit_path, roles=AUTHORIZED_ROLES,
    )
    monkeypatch.setattr(
        photon_bridge, "answer_question",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("DETAILS on a resolved decision must not hit Q&A")),
    )

    client = make_client([make_message("pho_msg_details", "DETAILS")])
    photon_bridge.poll_once(
        client, "proj1", [], MagicMock(), fresh_state(),
        conversation_state_path=state_path, audit_log_path=audit_path, roles=AUTHORIZED_ROLES,
    )

    assert "full detail" in _sent_text(client)


def test_ordinary_question_after_resolved_decision_still_falls_back_to_qa(tmp_path, monkeypatch):
    """The routing gate gave a resolved conversation first claim on
    decision-shaped replies (1/2/3, DETAILS, SOURCE, CANCEL, APPROVE) --
    this proves it does NOT also swallow unrelated free-text questions
    asked afterward in the same space.
    """
    state_path = tmp_path / "conversations.json"
    qa_path = tmp_path / "qa.json"
    audit_path = tmp_path / "audit.jsonl"
    decision_agent.start_conversation(
        "pho_spc_1", SIMULATED_DISRUPTION_EVENT["event_id"], "SHIP-001",
        shipments=SHIPMENTS, state_path=state_path,
    )
    decision_agent.handle_reply(
        "pho_spc_1", SIMULATED_DISRUPTION_EVENT["event_id"], "pho_usr_maya", "1",
        shipments=SHIPMENTS, state_path=state_path, audit_path=audit_path,
    )
    decision_agent.handle_reply(
        "pho_spc_1", SIMULATED_DISRUPTION_EVENT["event_id"], "pho_usr_maya", "APPROVE",
        shipments=SHIPMENTS, state_path=state_path, audit_path=audit_path, roles=AUTHORIZED_ROLES,
    )

    captured = {}

    def fake_answer_question(client, question, regulations, jurisdiction=None, concise=False):
        captured["question"] = question
        return "Short concise answer. Sources: US 21 CFR 312.6. Reply SOURCE for full citations."

    monkeypatch.setattr(photon_bridge, "answer_question", fake_answer_question)

    client = make_client([make_message("pho_msg_q", "What must appear on the label?")])
    photon_bridge.poll_once(
        client, "proj1", [], MagicMock(), fresh_state(),
        conversation_state_path=state_path, qa_state_path=qa_path, audit_log_path=audit_path,
    )

    assert captured.get("question") == "What must appear on the label?"
    assert "Reply SOURCE" in _sent_text(client)
