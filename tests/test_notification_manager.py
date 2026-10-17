import json
from unittest.mock import MagicMock

import decision_agent
import notification_manager
from impact_analyzer import SIMULATED_DISRUPTION_EVENT, analyze_disruption_impact

SHIPMENTS = [
    {
        "shipment_id": "SHIP-001",
        "drug_name": "Investigational Insulin Glargine",
        "shipping_date": "2026-10-01",
        "estimated_transit_days": 5,
        "required_delivery_date": "2026-10-10",
    },
    {
        "shipment_id": "SHIP-002",
        "drug_name": "Investigational Insulin Glargine",
        "shipping_date": "2026-10-03",
        "estimated_transit_days": 6,
        "required_delivery_date": "2026-10-08",
    },
]


# --- find_newly_at_risk / generate_alerts -----------------------------------


def test_find_newly_at_risk_only_includes_on_track_to_at_risk_transition():
    results = analyze_disruption_impact(SHIPMENTS, SIMULATED_DISRUPTION_EVENT)
    newly_at_risk = notification_manager.find_newly_at_risk(results)

    shipment_ids = {r["shipment_id"] for r in newly_at_risk}
    assert shipment_ids == {"SHIP-001"}  # SHIP-002 is unaffected, so excluded


def test_generate_alerts_contains_one_alert_for_affected_shipment():
    alerts = notification_manager.generate_alerts(SHIPMENTS, SIMULATED_DISRUPTION_EVENT)

    assert len(alerts) == 1
    assert alerts[0]["key"] == "SIM-DISRUPTION-001:SHIP-001"


def test_generate_alerts_skips_already_sent_key():
    already_sent = {"SIM-DISRUPTION-001:SHIP-001"}
    alerts = notification_manager.generate_alerts(SHIPMENTS, SIMULATED_DISRUPTION_EVENT, already_sent)

    assert alerts == []


# --- build_alert_message -----------------------------------------------------


def test_build_alert_message_contains_required_fields():
    results = analyze_disruption_impact(SHIPMENTS, SIMULATED_DISRUPTION_EVENT)
    ship_001 = next(r for r in results if r["shipment_id"] == "SHIP-001")

    message = notification_manager.build_alert_message(ship_001)

    assert "SIMULATED" in message
    assert "SIM-DISRUPTION-001" in message
    assert "SHIP-001" in message
    assert "Investigational Insulin Glargine" in message
    assert ship_001["event_description"] in message
    assert "2026-10-06" in message  # original arrival
    assert "2026-10-12" in message  # revised arrival
    assert "2026-10-10" in message  # required delivery
    assert "Days late:          2" in message


# --- run(): dry-run default --------------------------------------------------


def test_run_dry_run_default_never_touches_photon(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(notification_manager, "load_shipments", lambda: SHIPMENTS)
    monkeypatch.setattr(
        notification_manager, "build_photon_client", lambda: (_ for _ in ()).throw(AssertionError("must not build a real client in dry run"))
    )

    alerts = notification_manager.run(dry_run=True, state_path=tmp_path / "state.json")

    assert len(alerts) == 1
    captured = capsys.readouterr()
    assert "DRY RUN" in captured.out
    assert "SHIP-001" in captured.out
    assert not (tmp_path / "state.json").exists() or json.loads((tmp_path / "state.json").read_text()) == {}


# --- run(): explicit send with a mocked Photon sender ------------------------


def test_run_send_mode_uses_mocked_photon_client_and_records_state(monkeypatch, tmp_path):
    monkeypatch.setattr(notification_manager, "load_shipments", lambda: SHIPMENTS)
    mock_client = MagicMock()
    state_path = tmp_path / "state.json"

    alerts = notification_manager.run(
        dry_run=False,
        state_path=state_path,
        photon_client=mock_client,
        project_id="proj1",
        space_id="spc1",
        sender_id="usr1",
    )

    assert len(alerts) == 1
    mock_client.projects.send_message.assert_called_once()
    sent_input = mock_client.projects.send_message.call_args.args[0]
    dumped = sent_input.model_dump(by_alias=True, exclude_unset=True)
    assert dumped["headers"]["idempotency-key"] == "alert:SIM-DISRUPTION-001:SHIP-001"
    assert dumped["body"]["spaceId"] == "spc1"
    assert dumped["body"]["senderId"] == "usr1"

    saved_state = json.loads(state_path.read_text())
    assert "SIM-DISRUPTION-001:SHIP-001" in saved_state["sent_alert_keys"]


def test_run_send_mode_does_not_resend_already_alerted_shipment(monkeypatch, tmp_path):
    monkeypatch.setattr(notification_manager, "load_shipments", lambda: SHIPMENTS)
    mock_client = MagicMock()
    state_path = tmp_path / "state.json"
    kwargs = dict(
        dry_run=False,
        state_path=state_path,
        photon_client=mock_client,
        project_id="proj1",
        space_id="spc1",
        sender_id="usr1",
    )

    notification_manager.run(**kwargs)
    second_alerts = notification_manager.run(**kwargs)

    assert second_alerts == []
    mock_client.projects.send_message.assert_called_once()  # not called again


def test_run_missing_destination_env_falls_back_to_dry_run_without_sending(monkeypatch, tmp_path):
    monkeypatch.setattr(notification_manager, "load_shipments", lambda: SHIPMENTS)
    monkeypatch.delenv("PHOTON_ALERT_SPACE_ID", raising=False)
    monkeypatch.delenv("PHOTON_ALERT_SENDER_ID", raising=False)
    monkeypatch.setattr(
        notification_manager, "build_photon_client", lambda: (_ for _ in ()).throw(AssertionError("must not build a real client"))
    )

    alerts = notification_manager.run(dry_run=False, state_path=tmp_path / "state.json", project_id="proj1")

    assert len(alerts) == 1  # alert still generated/printed, just not sent


# --- start_customs_hold_conversation(): SHIP-001 decision-conversation kickoff --


def test_start_customs_hold_conversation_dry_run_never_touches_photon(tmp_path, monkeypatch):
    monkeypatch.delenv("PHOTON_ALERT_SPACE_ID", raising=False)
    monkeypatch.setattr(
        notification_manager, "build_photon_client",
        lambda: (_ for _ in ()).throw(AssertionError("must not build a real client in dry run")),
    )
    state_path = tmp_path / "conversations.json"

    message = notification_manager.start_customs_hold_conversation(
        dry_run=True, conversation_state_path=state_path,
    )

    assert "SHIP-001" in message
    assert "Pick a fix" in message
    convos = decision_agent.load_conversations(state_path)
    key = decision_agent.conversation_key("SIMULATED-SPACE", SIMULATED_DISRUPTION_EVENT["event_id"])
    assert convos[key]["status"] == decision_agent.STATUS_AWAITING_OPTION


def test_start_customs_hold_conversation_send_mode_uses_mocked_client_and_matching_space(tmp_path):
    mock_client = MagicMock()
    state_path = tmp_path / "conversations.json"

    notification_manager.start_customs_hold_conversation(
        dry_run=False,
        conversation_state_path=state_path,
        photon_client=mock_client,
        project_id="proj1",
        space_id="pho_spc_maya",
        sender_id="pho_usr_agent",
    )

    mock_client.projects.send_message.assert_called_once()
    sent_input = mock_client.projects.send_message.call_args.args[0]
    dumped = sent_input.model_dump(by_alias=True, exclude_unset=True)
    assert dumped["body"]["spaceId"] == "pho_spc_maya"

    # The conversation is keyed by the SAME space it was actually sent to,
    # so a reply arriving in that real space will find this pending decision.
    convo = decision_agent.get_conversation(
        "pho_spc_maya", SIMULATED_DISRUPTION_EVENT["event_id"], state_path=state_path,
    )
    assert convo is not None
    assert convo["status"] == decision_agent.STATUS_AWAITING_OPTION


def test_start_customs_hold_conversation_missing_destination_env_falls_back_to_dry_run(tmp_path, monkeypatch):
    monkeypatch.delenv("PHOTON_ALERT_SPACE_ID", raising=False)
    monkeypatch.delenv("PHOTON_ALERT_SENDER_ID", raising=False)
    monkeypatch.setattr(
        notification_manager, "build_photon_client",
        lambda: (_ for _ in ()).throw(AssertionError("must not build a real client")),
    )
    state_path = tmp_path / "conversations.json"

    message = notification_manager.start_customs_hold_conversation(
        dry_run=False, conversation_state_path=state_path, project_id="proj1",
    )

    assert "SHIP-001" in message  # conversation still opened, just not sent
