"""Unit tests for the planner-backed decision conversation (fake planner port)."""

import planner_conversation as pc


class Refused(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def row(slack_after, band="on_track"):
    shipment = {"projected_delivery": "2026-12-03", "slack_days": slack_after, "risk_band": band, "ship_by": {"safe": "2026-11-10"}}
    return {"shipment_id": "shipment-demo-jp", "country_name": "Japan",
            "before": {"projected_delivery": "2026-12-01", "slack_days": 3, "risk_band": "on_track"}, "after": shipment}


class FakePort:
    def __init__(self, approve_error=None):
        self.convos, self.decisions, self.approve_error = {}, [], approve_error
        self.roles = {"maya": {"name": "Maya", "role": "supply_lead", "can_approve": True}, "kenji": {"name": "Kenji", "role": "affiliate"}}

    def event(self, event_id):
        return {"id": event_id, "title": "Japan · closure", "description": "d", "warning_id": "wrn-" + event_id,
                "evidence_status": "synthetic", "country_name": "Japan", "jurisdiction": "JP"}

    def options(self, event_id):
        return [{"number": 1, "key": "express", "title": "Express", "proposal_id": "p1", "status": "proposed", "feasible": True,
                 "cost_delta": 700, "tradeoffs": "Cost", "preview": [row(1)]},
                {"number": 2, "key": "accept", "title": "Accept", "proposal_id": "p2", "status": "proposed", "feasible": False,
                 "cost_delta": 0, "preview": [row(-2, "blocked")]}]

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
            raise Refused(self.approve_error)
        if kwargs["actor_id"] != "maya":
            raise Refused("unauthorized")
        self.decisions.append((action, proposal_id, kwargs))
        return {"proposalId": proposal_id, "currentPlanVersion": 2, "actor": {"name": "Maya"}}

    def answer_question(self, chat_id, text):
        return {"text": "answer: " + text}


def start(port):
    return pc.start_conversation(port, "chat", "ev")


def test_alert_lists_numbered_options_and_previews_only():
    port = FakePort()
    messages = start(port)
    assert "Pick a fix (reply 1, 2)" in messages[0]["text"]
    assert messages[2]["quickReplies"] == ["1", "2", "DETAILS"]
    reply = pc.handle_message(port, "chat", "maya", "1", channel="web", message_id="m1")
    assert "Nothing has changed yet" in reply[0]["text"]
    assert port.decisions == []
    assert port.convos["chat"]["status"] == pc.STATUS_AWAITING_APPROVAL
    assert port.convos["chat"]["selected_proposal_id"] == "p1"


def test_approve_requires_selection_and_passes_governed_fields():
    port = FakePort()
    start(port)
    assert "Pick an option first" in pc.handle_message(port, "chat", "maya", "APPROVE", channel="web", message_id="m0")[0]["text"]
    pc.handle_message(port, "chat", "maya", "1", channel="web", message_id="m1")
    reply = pc.handle_message(port, "chat", "maya", "APPROVE", channel="photon", message_id="m2")
    assert "version 2" in reply[0]["text"]
    action, proposal, kwargs = port.decisions[0]
    assert (action, proposal) == ("approve", "p1")
    assert kwargs["actor_role"] == "supply_lead" and kwargs["channel"] == "photon"
    assert kwargs["idempotency_key"] == "photon:m2:approve"
    assert port.convos["chat"] == {**port.convos["chat"], "status": pc.STATUS_APPROVED, "approved_proposal_id": "p1"}
    assert "approved_plan" not in port.convos["chat"]


def test_unauthorized_and_stale_refusals():
    port = FakePort()
    start(port)
    pc.handle_message(port, "chat", "kenji", "1", channel="web", message_id="k1")
    assert "only an authorized supply lead" in pc.handle_message(port, "chat", "kenji", "APPROVE", channel="web", message_id="k2")[0]["text"]
    stale = FakePort(approve_error="stale_proposal")
    start(stale)
    pc.handle_message(stale, "chat", "maya", "1", channel="web", message_id="m1")
    reply = pc.handle_message(stale, "chat", "maya", "APPROVE", channel="web", message_id="m2")
    assert "superseded" in reply[0]["text"]
    assert stale.convos["chat"]["status"] == pc.STATUS_AWAITING_OPTION


def test_cancel_reject_details_and_free_text():
    port = FakePort()
    start(port)
    assert "evidence" in pc.handle_message(port, "chat", "maya", "DETAILS", channel="web", message_id="d")[0]["text"]
    pc.handle_message(port, "chat", "maya", "1", channel="web", message_id="m1")
    assert "Rejected option 1" in pc.handle_message(port, "chat", "maya", "REJECT", channel="web", message_id="r")[0]["text"]
    assert port.decisions[-1][0] == "reject"
    assert "Cancelled" in pc.handle_message(port, "chat", "maya", "CANCEL", channel="web", message_id="c")[0]["text"]
    assert pc.handle_message(port, "chat", "maya", "What about Japan?", channel="web", message_id="q")[0]["text"] == "answer: What about Japan?"


def test_grammar_extends_annas_parser():
    assert pc.parse_reply("reject") == ("REJECT", None)
    assert pc.parse_reply("2") == ("OPTION", 2)
    assert pc.is_decision_reply("approve") and not pc.is_decision_reply("why is Japan late?")
