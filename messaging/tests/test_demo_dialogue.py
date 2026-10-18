"""Unit tests for the PHOTON_DEMO_MODE natural-language demo conversation
(fake planner port, mocked -- no live Photon, no live planner, no
Anthropic calls)."""

import pytest

import demo_dialogue as dd
import planner_conversation as pc

EVENT_ID = dd.DEMO_EVENT_ID


def preview_row(before_slack, after_slack, before_delivery="2026-12-04", after_delivery="2026-11-30"):
    return {
        "shipment_id": "shipment-demo-de",
        "country_name": "Germany",
        "before": {"projected_delivery": before_delivery, "slack_days": before_slack, "risk_band": "blocked"},
        "after": {"projected_delivery": after_delivery, "slack_days": after_slack, "risk_band": "blocked"},
    }


class FakePort:
    """Mirrors messaging_link.PlannerPort's interface exactly (see test_planner_conversation.py)."""

    def __init__(self, approve_error=None, authorized_actor="maya"):
        self.convos, self.decisions, self.approve_error, self.authorized_actor = {}, [], approve_error, authorized_actor
        self.roles = {"maya": {"name": "Maya", "role": "supply_lead", "can_approve": True},
                      "kenji": {"name": "Kenji", "role": "affiliate"}}

    def event(self, event_id):
        return {"id": event_id, "title": "Germany · severe weather on Boston–Frankfurt",
                "description": "Simulated severe weather on the Boston–Frankfurt lane adds 4 business days to German shipments.",
                "warning_id": "wrn-" + event_id, "evidence_status": "synthetic", "country_name": "Germany",
                "jurisdiction": "DE", "transit_delay_days": 4}

    def options(self, event_id):
        return [
            {"number": 1, "key": "reroute", "title": "Reroute through Amsterdam", "proposal_id": "p-reroute",
             "status": "proposed", "feasible": False, "recommended": True, "cost_delta": 715,
             "preview": [preview_row(-38, -34)]},
            {"number": 2, "key": "expedite", "title": "Expedite ground handling at the Frankfurt depot", "proposal_id": "p-expedite",
             "status": "proposed", "feasible": False, "recommended": False, "cost_delta": 270,
             "preview": [preview_row(-38, -36, after_delivery="2026-12-02")]},
            {"number": 3, "key": "accept", "title": "Accept the delay (no mitigation)", "proposal_id": "p-accept",
             "status": "proposed", "feasible": False, "recommended": False, "cost_delta": 0,
             "preview": [preview_row(-38, -42, after_delivery="2026-12-10")]},
        ]

    def primary_shipment(self, event_id):
        return {"ship_by": {"safe": "2026-11-10"}}

    def transitions(self, proposal_id):
        return []

    def role(self, actor_id):
        return self.roles.get(actor_id)

    def decision(self, proposal_id):
        return {"approver": "Maya"}

    def save_conversation(self, convo):
        self.convos[convo["chat_id"]] = dict(convo)

    def latest_conversation(self, chat_id):
        return self.convos.get(chat_id)

    def decide(self, action, proposal_id, **kwargs):
        if self.approve_error:
            raise RuntimeError(self.approve_error)
        if kwargs["actor_id"] != self.authorized_actor:
            exc = Exception("unauthorized")
            exc.code = "unauthorized"
            raise exc
        self.decisions.append((action, proposal_id, kwargs))
        return {"proposalId": proposal_id, "currentPlanVersion": 2, "actor": {"name": "Maya"}}

    def answer_question(self, chat_id, text):
        return {"text": "generic answer: " + text}


@pytest.fixture(autouse=True)
def demo_mode_on(monkeypatch):
    monkeypatch.setenv("PHOTON_DEMO_MODE", "true")


def msg(port, chat_id, actor_id, text, message_id):
    return pc.handle_message(port, chat_id, actor_id, text, channel="photon", message_id=message_id)


def test_demo_disabled_returns_none_and_falls_through(monkeypatch):
    monkeypatch.setenv("PHOTON_DEMO_MODE", "false")
    port = FakePort()
    reply = msg(port, "chat", "kenji", "What's the status of the Germany shipment?", "m0")
    assert reply == [{"text": "generic answer: What's the status of the Germany shipment?"}]
    assert "chat" not in port.convos


def test_unrelated_question_is_not_intercepted():
    port = FakePort()
    reply = msg(port, "chat", "kenji", "What about the Japan shipment?", "m0")
    assert reply == [{"text": "generic answer: What about the Japan shipment?"}]
    assert "chat" not in port.convos


def test_full_multiturn_flow_status_why_options_recommend_prepare():
    port = FakePort()

    status = msg(port, "chat", "kenji", "What's the status of the Germany shipment?", "m1")
    assert "Demo scenario" in status[0]["text"]
    assert "4 business days" in status[0]["text"]
    assert port.convos["chat"]["status"] == pc.STATUS_AWAITING_OPTION
    assert port.convos["chat"]["event_id"] == EVENT_ID

    why = msg(port, "chat", "kenji", "Why is it delayed?", "m2")
    assert "4 business days" in why[0]["text"]
    assert "severe weather" in why[0]["text"].lower()
    assert len(why[0]["text"]) < 300  # short, iMessage-sized

    options = msg(port, "chat", "kenji", "What are my options?", "m3")
    assert "Reroute through Amsterdam" in options[0]["text"]
    assert "Expedite ground handling" in options[0]["text"]
    assert "recovering about 8 business days" in options[0]["text"]
    assert "recovering about 6 business days" in options[0]["text"]
    assert "I recommend Reroute through Amsterdam" in options[0]["text"]

    recommend = msg(port, "chat", "kenji", "Which one do you recommend?", "m4")
    assert "Reroute through Amsterdam" in recommend[0]["text"]
    assert "8 business days" in recommend[0]["text"]
    assert "6 business days" in recommend[0]["text"]

    prepare = msg(port, "chat", "kenji", "Prepare the proposal.", "m5")
    assert "p-reroute" in prepare[0]["caption"]
    assert "2026-12-04" in prepare[0]["text"] or "Dec 4" in prepare[0]["text"]
    assert port.convos["chat"]["status"] == pc.STATUS_AWAITING_APPROVAL
    assert port.convos["chat"]["selected_proposal_id"] == "p-reroute"
    assert port.decisions == []  # never auto-approved


def test_prepare_is_idempotent_on_replay():
    port = FakePort()
    msg(port, "chat", "kenji", "What's the status of the Germany shipment?", "m1")
    first = msg(port, "chat", "kenji", "Prepare the proposal.", "m2")
    second = msg(port, "chat", "kenji", "Prepare the proposal.", "m3")  # e.g. a duplicate/retry
    assert port.convos["chat"]["selected_proposal_id"] == "p-reroute"
    assert port.decisions == []
    # Second call hits the already-AWAITING_APPROVAL branch, delegating straight to
    # handle_reply instead of re-running the fresh-preview short circuit.
    assert "p-reroute" in second[0].get("caption", "") or "p-reroute" in second[0]["text"]


def test_unauthorized_approve_is_refused_and_plan_untouched():
    port = FakePort(authorized_actor="maya")
    msg(port, "chat", "kenji", "What's the status of the Germany shipment?", "m1")
    msg(port, "chat", "kenji", "Prepare the proposal.", "m2")
    refusal = msg(port, "chat", "kenji", "APPROVE", "m3")
    assert "authorized" in refusal[0]["text"].lower()
    assert port.decisions == []
    assert port.convos["chat"]["status"] == pc.STATUS_AWAITING_APPROVAL  # unchanged


def test_authorized_approve_still_goes_through_real_governance():
    port = FakePort(authorized_actor="maya")
    msg(port, "chat", "maya", "What's the status of the Germany shipment?", "m1")
    msg(port, "chat", "maya", "Prepare the proposal.", "m2")
    approved = msg(port, "chat", "maya", "APPROVE", "m3")
    assert "version 2" in approved[0]["text"]
    assert port.decisions == [("approve", "p-reroute", {
        "actor_id": "maya", "actor_role": "supply_lead",
        "rationale": "Approved option 1 for de-route-delay via photon",
        "channel": "photon", "idempotency_key": "photon:m3:approve",
    })]
    assert port.convos["chat"]["status"] == pc.STATUS_APPROVED


def test_repeating_status_after_started_does_not_reset_conversation():
    port = FakePort()
    msg(port, "chat", "kenji", "What's the status of the Germany shipment?", "m1")
    msg(port, "chat", "kenji", "Prepare the proposal.", "m2")
    assert port.convos["chat"]["status"] == pc.STATUS_AWAITING_APPROVAL
    # Asking "what's the status" again must not silently roll the conversation
    # back to AWAITING_OPTION and lose the prepared proposal.
    status_again = msg(port, "chat", "kenji", "What's the status of the Germany shipment?", "m3")
    assert port.convos["chat"]["status"] == pc.STATUS_AWAITING_APPROVAL
    assert port.convos["chat"]["selected_proposal_id"] == "p-reroute"
    assert "Reroute through Amsterdam" in status_again[0]["text"]


def test_demo_labeled_scenario_only_once():
    port = FakePort()
    first = msg(port, "chat", "kenji", "What's the status of the Germany shipment?", "m1")
    assert "Demo scenario" in first[0]["text"]
    why = msg(port, "chat", "kenji", "Why is it delayed?", "m2")
    assert "Demo scenario" not in why[0]["text"]
    options = msg(port, "chat", "kenji", "What are my options?", "m3")
    assert "Demo scenario" not in options[0]["text"]
