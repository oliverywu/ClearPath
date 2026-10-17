from datetime import date, datetime, timezone

import audit_log
import decision_agent
from impact_analyzer import SIMULATED_DISRUPTION_EVENT

SHIP_001 = {
    "shipment_id": "SHIP-001",
    "drug_name": "Investigational Insulin Glargine",
    "origin": "Indianapolis, US",
    "destination": "Berlin, DE",
    "shipping_date": "2026-10-01",
    "estimated_transit_days": 5,
    "required_delivery_date": "2026-10-10",
}
SHIPMENTS = [SHIP_001]
EVENT = SIMULATED_DISRUPTION_EVENT  # additional_delay_days=6, affects SHIP-001

AUTHORIZED_ROLES = {
    "pho_usr_maya": {"name": "Maya", "role": "supply_lead", "can_approve": True},
    "pho_usr_kenji": {"name": "Kenji", "role": "affiliate", "can_approve": False},
}

FIXED_NOW = datetime(2026, 10, 5, 9, 6, tzinfo=timezone.utc)


def _paths(tmp_path):
    return tmp_path / "conversations.json", tmp_path / "audit.jsonl"


def _start(tmp_path, space_id="pho_spc_maya"):
    state_path, _audit_path = _paths(tmp_path)
    message = decision_agent.start_conversation(
        space_id,
        EVENT["event_id"],
        "SHIP-001",
        shipments=SHIPMENTS,
        state_path=state_path,
        now=FIXED_NOW,
    )
    return message, state_path


# --- requirement 1: mobile-first plain-text alert ---------------------------


def test_build_initial_alert_contains_required_fields():
    message = decision_agent.build_initial_alert(SHIP_001, EVENT, decision_agent.CUSTOMS_HOLD_OPTIONS)

    assert "SIMULATED" in message
    assert EVENT["description"] in message  # what changed
    assert "SHIP-001" in message  # affected shipment
    assert "2026-10-12" in message  # revised ETA
    assert "2026-10-10" in message  # deadline
    assert "1." in message and "2." in message and "3." in message  # 1-3 numbered options


def test_build_initial_alert_has_no_markdown():
    message = decision_agent.build_initial_alert(SHIP_001, EVENT, decision_agent.CUSTOMS_HOLD_OPTIONS)
    for forbidden in ("**", "##", "```", "* ", "- ["):
        assert forbidden not in message


def test_options_without_cost_data_request_verification_not_invented_benefit():
    message = decision_agent.build_initial_alert(SHIP_001, EVENT, decision_agent.CUSTOMS_HOLD_OPTIONS)
    assert "needs verification" in message
    assert "$" not in message  # no invented dollar figure anywhere


def test_compute_option_preview_reuses_existing_shipment_calculation():
    from shipment_planner import calculate_shipment

    option = decision_agent.CUSTOMS_HOLD_OPTIONS[0]  # reduction 4 -> effective delay 2
    preview = decision_agent.compute_option_preview(SHIP_001, EVENT, option)
    expected = calculate_shipment(SHIP_001, delay_days=2)

    assert preview["estimated_arrival_date"] == expected["estimated_arrival_date"]
    assert preview["buffer_days"] == expected["buffer_days"]
    assert preview["at_risk"] == expected["at_risk"]
    assert preview["estimated_arrival_date"] == date(2026, 10, 8)
    assert preview["at_risk"] is False


# --- requirement 2: conversation state machine, scoped per space+event ------


def test_start_conversation_seeds_awaiting_option_state(tmp_path):
    message, state_path = _start(tmp_path)
    convos = decision_agent.load_conversations(state_path)
    key = decision_agent.conversation_key("pho_spc_maya", EVENT["event_id"])

    assert convos[key]["status"] == decision_agent.STATUS_AWAITING_OPTION
    assert convos[key]["selected_option"] is None
    assert convos[key]["shipment_id"] == "SHIP-001"
    assert "Pick a fix" in message


def test_invalid_option_number_is_rejected_without_changing_state(tmp_path):
    _message, state_path = _start(tmp_path)
    reply = decision_agent.handle_reply(
        "pho_spc_maya", EVENT["event_id"], "pho_usr_maya", "9",
        shipments=SHIPMENTS, state_path=state_path,
    )
    convo = decision_agent.get_conversation("pho_spc_maya", EVENT["event_id"], state_path=state_path)

    assert "valid option" in reply
    assert convo["status"] == decision_agent.STATUS_AWAITING_OPTION


def test_unrecognized_reply_text_is_rejected_gracefully(tmp_path):
    _message, state_path = _start(tmp_path)
    reply = decision_agent.handle_reply(
        "pho_spc_maya", EVENT["event_id"], "pho_usr_maya", "banana",
        shipments=SHIPMENTS, state_path=state_path,
    )
    convo = decision_agent.get_conversation("pho_spc_maya", EVENT["event_id"], state_path=state_path)

    assert "didn't understand" in reply
    assert convo["status"] == decision_agent.STATUS_AWAITING_OPTION


def test_cancel_stops_the_conversation(tmp_path):
    _message, state_path = _start(tmp_path)
    reply = decision_agent.handle_reply(
        "pho_spc_maya", EVENT["event_id"], "pho_usr_maya", "CANCEL",
        shipments=SHIPMENTS, state_path=state_path,
    )
    convo = decision_agent.get_conversation("pho_spc_maya", EVENT["event_id"], state_path=state_path)

    assert "Cancelled" in reply
    assert convo["status"] == decision_agent.STATUS_CANCELLED

    # Further replies after cancellation don't resurrect it.
    second = decision_agent.handle_reply(
        "pho_spc_maya", EVENT["event_id"], "pho_usr_maya", "1",
        shipments=SHIPMENTS, state_path=state_path,
    )
    assert "cancelled" in second.lower()


def test_details_reply_does_not_change_status(tmp_path):
    _message, state_path = _start(tmp_path)
    reply = decision_agent.handle_reply(
        "pho_spc_maya", EVENT["event_id"], "pho_usr_maya", "DETAILS",
        shipments=SHIPMENTS, state_path=state_path,
    )
    convo = decision_agent.get_conversation("pho_spc_maya", EVENT["event_id"], state_path=state_path)

    assert EVENT["description"] in reply
    assert convo["status"] == decision_agent.STATUS_AWAITING_OPTION


def test_source_reply_for_logistics_event_explains_no_citation(tmp_path):
    _message, state_path = _start(tmp_path)
    reply = decision_agent.handle_reply(
        "pho_spc_maya", EVENT["event_id"], "pho_usr_maya", "SOURCE",
        shipments=SHIPMENTS, state_path=state_path,
    )
    assert "simulated logistics event" in reply.lower()
    assert "DETAILS" in reply


# --- requirement 4: option selection is NOT approval; approval needs auth ---


def test_selecting_option_moves_to_awaiting_approval_never_approved(tmp_path):
    _message, state_path = _start(tmp_path)
    audit_path = _paths(tmp_path)[1]

    reply = decision_agent.handle_reply(
        "pho_spc_maya", EVENT["event_id"], "pho_usr_maya", "1",
        shipments=SHIPMENTS, state_path=state_path, audit_path=audit_path,
    )
    convo = decision_agent.get_conversation("pho_spc_maya", EVENT["event_id"], state_path=state_path)

    assert convo["status"] == decision_agent.STATUS_AWAITING_APPROVAL
    assert convo["status"] != decision_agent.STATUS_APPROVED
    assert "Reply APPROVE" in reply
    assert audit_log.load_entries(audit_path) == []  # no mutation yet


def test_approve_before_selecting_an_option_is_rejected(tmp_path):
    _message, state_path = _start(tmp_path)
    audit_path = _paths(tmp_path)[1]

    reply = decision_agent.handle_reply(
        "pho_spc_maya", EVENT["event_id"], "pho_usr_maya", "APPROVE",
        shipments=SHIPMENTS, state_path=state_path, audit_path=audit_path,
        roles=AUTHORIZED_ROLES,
    )
    convo = decision_agent.get_conversation("pho_spc_maya", EVENT["event_id"], state_path=state_path)

    assert "Pick an option first" in reply
    assert convo["status"] == decision_agent.STATUS_AWAITING_OPTION
    assert audit_log.load_entries(audit_path) == []


# --- requirement 4: authorization ---------------------------------------


def test_approve_by_unauthorized_actor_is_rejected_and_not_logged(tmp_path):
    _message, state_path = _start(tmp_path)
    audit_path = _paths(tmp_path)[1]

    decision_agent.handle_reply(
        "pho_spc_maya", EVENT["event_id"], "pho_usr_kenji", "1",
        shipments=SHIPMENTS, state_path=state_path, audit_path=audit_path,
    )
    reply = decision_agent.handle_reply(
        "pho_spc_maya", EVENT["event_id"], "pho_usr_kenji", "APPROVE",
        shipments=SHIPMENTS, state_path=state_path, audit_path=audit_path,
        roles=AUTHORIZED_ROLES,
    )
    convo = decision_agent.get_conversation("pho_spc_maya", EVENT["event_id"], state_path=state_path)

    assert "can't approve" in reply
    assert convo["status"] == decision_agent.STATUS_AWAITING_APPROVAL  # unchanged
    assert audit_log.load_entries(audit_path) == []
    assert decision_agent.get_approved_plan("pho_spc_maya", EVENT["event_id"], state_path=state_path) is None


def test_unknown_actor_is_never_authorized_by_default():
    assert decision_agent.is_authorized_to_approve("pho_usr_nobody", roles=AUTHORIZED_ROLES) is None
    assert decision_agent.is_authorized_to_approve(None, roles=AUTHORIZED_ROLES) is None


def test_default_authorized_roles_file_grants_maya_not_kenji():
    maya = decision_agent.is_authorized_to_approve("pho_usr_maya")
    kenji = decision_agent.is_authorized_to_approve("pho_usr_kenji")
    assert maya is not None and maya["role"] == "supply_lead"
    assert kenji is None


# --- requirements 3, 5, 6: preview, approval, audit logging -----------------


def test_approve_by_authorized_actor_logs_exactly_one_entry_with_required_fields(tmp_path):
    _message, state_path = _start(tmp_path)
    audit_path = _paths(tmp_path)[1]

    decision_agent.handle_reply(
        "pho_spc_maya", EVENT["event_id"], "pho_usr_maya", "1",
        shipments=SHIPMENTS, state_path=state_path, audit_path=audit_path,
    )
    reply = decision_agent.handle_reply(
        "pho_spc_maya", EVENT["event_id"], "pho_usr_maya", "APPROVE",
        shipments=SHIPMENTS, state_path=state_path, audit_path=audit_path,
        roles=AUTHORIZED_ROLES, now=FIXED_NOW,
    )

    entries = audit_log.load_entries(audit_path)
    assert len(entries) == 1
    entry = entries[0]

    assert entry["event_id"] == EVENT["event_id"]
    assert entry["shipment_id"] == "SHIP-001"
    assert entry["selected_option"]["option_id"] == 1
    assert entry["authorized_actor"] == {"id": "pho_usr_maya", "name": "Maya", "role": "supply_lead"}
    assert entry["timestamp"] == FIXED_NOW.isoformat()
    assert entry["channel"] == "iMessage"
    assert entry["before_plan"]["estimated_arrival_date"] == "2026-10-12"  # full 6-day disruption
    assert entry["after_plan"]["estimated_arrival_date"] == "2026-10-08"  # option 1 preview
    assert entry["before_plan"] != entry["after_plan"]

    # no secrets leak into the audit trail
    serialized = str(entry)
    assert "PHOTON_API_KEY" not in serialized
    assert "Bearer" not in serialized

    convo = decision_agent.get_conversation("pho_spc_maya", EVENT["event_id"], state_path=state_path)
    assert convo["status"] == decision_agent.STATUS_APPROVED
    assert decision_agent.get_approved_plan("pho_spc_maya", EVENT["event_id"], state_path=state_path) == entry["after_plan"]
    assert "Recorded" in reply
    assert "Maya" in reply


def test_duplicate_approve_is_idempotent_logs_once(tmp_path):
    _message, state_path = _start(tmp_path)
    audit_path = _paths(tmp_path)[1]

    decision_agent.handle_reply(
        "pho_spc_maya", EVENT["event_id"], "pho_usr_maya", "1",
        shipments=SHIPMENTS, state_path=state_path, audit_path=audit_path,
    )
    first = decision_agent.handle_reply(
        "pho_spc_maya", EVENT["event_id"], "pho_usr_maya", "APPROVE",
        shipments=SHIPMENTS, state_path=state_path, audit_path=audit_path, roles=AUTHORIZED_ROLES,
    )
    second = decision_agent.handle_reply(
        "pho_spc_maya", EVENT["event_id"], "pho_usr_maya", "APPROVE",
        shipments=SHIPMENTS, state_path=state_path, audit_path=audit_path, roles=AUTHORIZED_ROLES,
    )

    assert "Recorded" in first
    assert "Already recorded" in second
    assert len(audit_log.load_entries(audit_path)) == 1


def test_approving_keep_current_plan_option_logs_unchanged_before_after(tmp_path):
    """Option 3 ("keep current plan") is a legitimate decision to log even
    though before_plan == after_plan -- approving "no change" is still an
    explicit human decision worth recording.
    """
    _message, state_path = _start(tmp_path)
    audit_path = _paths(tmp_path)[1]

    decision_agent.handle_reply(
        "pho_spc_maya", EVENT["event_id"], "pho_usr_maya", "3",
        shipments=SHIPMENTS, state_path=state_path, audit_path=audit_path,
    )
    decision_agent.handle_reply(
        "pho_spc_maya", EVENT["event_id"], "pho_usr_maya", "APPROVE",
        shipments=SHIPMENTS, state_path=state_path, audit_path=audit_path, roles=AUTHORIZED_ROLES,
    )

    entry = audit_log.load_entries(audit_path)[0]
    assert entry["before_plan"] == entry["after_plan"]
    assert entry["before_plan"]["at_risk"] is True  # still at risk; option 3 fixes nothing


# --- requirement 2: isolation across conversations/users and events --------


def test_conversation_isolation_across_spaces(tmp_path):
    state_path, audit_path = _paths(tmp_path)
    decision_agent.start_conversation(
        "pho_spc_maya", EVENT["event_id"], "SHIP-001", shipments=SHIPMENTS, state_path=state_path,
    )
    decision_agent.start_conversation(
        "pho_spc_kenji", EVENT["event_id"], "SHIP-001", shipments=SHIPMENTS, state_path=state_path,
    )

    decision_agent.handle_reply(
        "pho_spc_maya", EVENT["event_id"], "pho_usr_maya", "1",
        shipments=SHIPMENTS, state_path=state_path, audit_path=audit_path,
    )
    decision_agent.handle_reply(
        "pho_spc_maya", EVENT["event_id"], "pho_usr_maya", "APPROVE",
        shipments=SHIPMENTS, state_path=state_path, audit_path=audit_path, roles=AUTHORIZED_ROLES,
    )

    maya_convo = decision_agent.get_conversation("pho_spc_maya", EVENT["event_id"], state_path=state_path)
    kenji_convo = decision_agent.get_conversation("pho_spc_kenji", EVENT["event_id"], state_path=state_path)

    assert maya_convo["status"] == decision_agent.STATUS_APPROVED
    assert kenji_convo["status"] == decision_agent.STATUS_AWAITING_OPTION  # untouched by Maya's space
    assert kenji_convo["selected_option"] is None
    assert len(audit_log.load_entries(audit_path)) == 1


def test_conversation_isolation_across_events_same_space(tmp_path):
    state_path, audit_path = _paths(tmp_path)
    other_event = {
        "event_id": "SIM-DISRUPTION-002",
        "label": "SIMULATED",
        "description": "Simulated second disruption, unrelated to SIM-DISRUPTION-001",
        "affected_shipment_ids": ["SHIP-001"],
        "additional_delay_days": 3,
    }
    other_options = [
        {"option_id": 1, "label": "Alternate fix", "delay_reduction_days": 3, "cost_known": True},
    ]

    decision_agent.start_conversation(
        "pho_spc_maya", EVENT["event_id"], "SHIP-001", shipments=SHIPMENTS, state_path=state_path,
    )
    decision_agent.start_conversation(
        "pho_spc_maya", other_event["event_id"], "SHIP-001",
        shipments=SHIPMENTS, disruption_event=other_event, options=other_options, state_path=state_path,
    )

    decision_agent.handle_reply(
        "pho_spc_maya", EVENT["event_id"], "pho_usr_maya", "1",
        shipments=SHIPMENTS, state_path=state_path, audit_path=audit_path,
    )

    primary = decision_agent.get_conversation("pho_spc_maya", EVENT["event_id"], state_path=state_path)
    secondary = decision_agent.get_conversation("pho_spc_maya", other_event["event_id"], state_path=state_path)

    assert primary["status"] == decision_agent.STATUS_AWAITING_APPROVAL
    assert secondary["status"] == decision_agent.STATUS_AWAITING_OPTION  # untouched by the other event


def test_find_active_conversation_returns_none_with_no_pending_decision(tmp_path):
    state_path, _audit_path = _paths(tmp_path)
    assert decision_agent.find_active_conversation_for_space("pho_spc_nobody", state_path=state_path) is None


def test_find_active_conversation_ignores_resolved_conversations(tmp_path):
    state_path, audit_path = _paths(tmp_path)
    decision_agent.start_conversation(
        "pho_spc_maya", EVENT["event_id"], "SHIP-001", shipments=SHIPMENTS, state_path=state_path,
    )
    decision_agent.handle_reply(
        "pho_spc_maya", EVENT["event_id"], "pho_usr_maya", "CANCEL",
        shipments=SHIPMENTS, state_path=state_path, audit_path=audit_path,
    )
    assert decision_agent.find_active_conversation_for_space("pho_spc_maya", state_path=state_path) is None


# --- requirement 10: reply to an unknown/non-pending conversation ----------


def test_reply_with_no_pending_conversation_is_handled_gracefully(tmp_path):
    state_path, audit_path = _paths(tmp_path)
    reply = decision_agent.handle_reply(
        "pho_spc_unknown", "SIM-DISRUPTION-001", "pho_usr_maya", "1",
        shipments=SHIPMENTS, state_path=state_path, audit_path=audit_path,
    )
    assert "No pending decision" in reply


# --- find_approved_decision(): the bridge from decision state into "current plan" --


def test_find_approved_decision_is_none_before_approval(tmp_path):
    _message, state_path = _start(tmp_path)
    assert decision_agent.find_approved_decision("SHIP-001", EVENT["event_id"], state_path=state_path) is None


def test_find_approved_decision_returns_the_approved_plan_after_approval(tmp_path):
    _message, state_path = _start(tmp_path)
    audit_path = _paths(tmp_path)[1]

    decision_agent.handle_reply(
        "pho_spc_maya", EVENT["event_id"], "pho_usr_maya", "1",
        shipments=SHIPMENTS, state_path=state_path, audit_path=audit_path,
    )
    decision_agent.handle_reply(
        "pho_spc_maya", EVENT["event_id"], "pho_usr_maya", "APPROVE",
        shipments=SHIPMENTS, state_path=state_path, audit_path=audit_path,
        roles=AUTHORIZED_ROLES, now=FIXED_NOW,
    )

    decision = decision_agent.find_approved_decision("SHIP-001", EVENT["event_id"], state_path=state_path)
    assert decision is not None
    assert decision["selected_option"]["option_id"] == 1
    assert decision["approved_plan"]["estimated_arrival_date"] == "2026-10-08"
    assert decision["approved_plan"]["at_risk"] is False
    assert decision["approved_by"] == {"id": "pho_usr_maya", "name": "Maya", "role": "supply_lead"}

    # unapproved for a DIFFERENT event, or with no event filter it still finds it
    assert decision_agent.find_approved_decision("SHIP-001", "SIM-DISRUPTION-999", state_path=state_path) is None
    assert decision_agent.find_approved_decision("SHIP-001", state_path=state_path) is not None


def test_find_approved_decision_picks_most_recently_approved_when_multiple_spaces_approve(tmp_path):
    state_path, audit_path = _paths(tmp_path)
    decision_agent.start_conversation(
        "pho_spc_a", EVENT["event_id"], "SHIP-001", shipments=SHIPMENTS, state_path=state_path,
    )
    decision_agent.start_conversation(
        "pho_spc_b", EVENT["event_id"], "SHIP-001", shipments=SHIPMENTS, state_path=state_path,
    )

    earlier = datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc)
    later = datetime(2026, 10, 5, 9, 30, tzinfo=timezone.utc)

    decision_agent.handle_reply(
        "pho_spc_a", EVENT["event_id"], "pho_usr_maya", "1",
        shipments=SHIPMENTS, state_path=state_path, audit_path=audit_path, now=earlier,
    )
    decision_agent.handle_reply(
        "pho_spc_a", EVENT["event_id"], "pho_usr_maya", "APPROVE",
        shipments=SHIPMENTS, state_path=state_path, audit_path=audit_path,
        roles=AUTHORIZED_ROLES, now=earlier,
    )
    decision_agent.handle_reply(
        "pho_spc_b", EVENT["event_id"], "pho_usr_maya", "2",
        shipments=SHIPMENTS, state_path=state_path, audit_path=audit_path, now=later,
    )
    decision_agent.handle_reply(
        "pho_spc_b", EVENT["event_id"], "pho_usr_maya", "APPROVE",
        shipments=SHIPMENTS, state_path=state_path, audit_path=audit_path,
        roles=AUTHORIZED_ROLES, now=later,
    )

    decision = decision_agent.find_approved_decision("SHIP-001", EVENT["event_id"], state_path=state_path)
    assert decision["space_id"] == "pho_spc_b"  # the later approval wins, deterministically
    assert decision["selected_option"]["option_id"] == 2


# --- no conflicting plan updates after approval -----------------------------


def test_reselecting_an_option_after_approval_is_blocked_plan_stays_consistent(tmp_path):
    _message, state_path = _start(tmp_path)
    audit_path = _paths(tmp_path)[1]

    decision_agent.handle_reply(
        "pho_spc_maya", EVENT["event_id"], "pho_usr_maya", "1",
        shipments=SHIPMENTS, state_path=state_path, audit_path=audit_path,
    )
    decision_agent.handle_reply(
        "pho_spc_maya", EVENT["event_id"], "pho_usr_maya", "APPROVE",
        shipments=SHIPMENTS, state_path=state_path, audit_path=audit_path, roles=AUTHORIZED_ROLES,
    )

    reply = decision_agent.handle_reply(
        "pho_spc_maya", EVENT["event_id"], "pho_usr_maya", "2",
        shipments=SHIPMENTS, state_path=state_path, audit_path=audit_path, roles=AUTHORIZED_ROLES,
    )

    assert "already approved" in reply.lower()
    decision = decision_agent.find_approved_decision("SHIP-001", EVENT["event_id"], state_path=state_path)
    assert decision["selected_option"]["option_id"] == 1  # unchanged -- option 2 never took effect
    assert len(audit_log.load_entries(audit_path)) == 1  # no second entry from the blocked attempt


# --- restart survival: no in-process state is required between steps -------


def test_conversation_and_approval_survive_a_simulated_process_restart(tmp_path):
    """Every step below reloads conversation state fresh from disk and is
    the only reference to it in that call -- there is no Python object
    carried over between steps, simulating the Photon bridge process
    restarting between each inbound message.
    """
    state_path, audit_path = _paths(tmp_path)

    decision_agent.start_conversation(
        "pho_spc_maya", EVENT["event_id"], "SHIP-001", shipments=SHIPMENTS, state_path=state_path,
    )

    # "Restart": a fresh read from disk, with no conversations dict carried over in memory.
    reloaded = decision_agent.get_conversation("pho_spc_maya", EVENT["event_id"], state_path=state_path)
    assert reloaded["status"] == decision_agent.STATUS_AWAITING_OPTION

    decision_agent.handle_reply(
        "pho_spc_maya", EVENT["event_id"], "pho_usr_maya", "1",
        shipments=SHIPMENTS, state_path=state_path, audit_path=audit_path,
    )

    # "Restart": fresh load proves AWAITING_APPROVAL was persisted, not held in memory.
    reloaded_again = decision_agent.load_conversations(state_path)
    key = decision_agent.conversation_key("pho_spc_maya", EVENT["event_id"])
    assert reloaded_again[key]["status"] == decision_agent.STATUS_AWAITING_APPROVAL
    assert reloaded_again[key]["selected_option"]["option_id"] == 1

    decision_agent.handle_reply(
        "pho_spc_maya", EVENT["event_id"], "pho_usr_maya", "APPROVE",
        shipments=SHIPMENTS, state_path=state_path, audit_path=audit_path, roles=AUTHORIZED_ROLES,
    )

    # Final "restart": the approved plan and audit entry are both durable.
    final_state = decision_agent.load_conversations(state_path)
    assert final_state[key]["status"] == decision_agent.STATUS_APPROVED
    assert decision_agent.find_approved_decision("SHIP-001", EVENT["event_id"], state_path=state_path) is not None
    assert len(audit_log.load_entries(audit_path)) == 1
