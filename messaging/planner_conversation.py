"""Decision conversations backed by the canonical planner (integrated application).

This is Anna's decision-agent state machine (decision_agent.py) bound to the
planner instead of to local JSON files:

  * Same reply grammar (1/2/3, DETAILS, SOURCE, CANCEL, APPROVE; plus REJECT) and
    the same status names (AWAITING_OPTION -> AWAITING_APPROVAL -> APPROVED /
    CANCELLED), reused from decision_agent.
  * Options are the planner's immutable proposals for the event (one per
    remediation option); selecting one only previews it.
  * APPROVE / REJECT call the planner's governed decision service with the
    proposal id, actor id, actor role, rationale, channel, an idempotency key
    derived from the inbound message id, and the plan id the person previewed.
    The planner decides; this module never stores an operational plan.
  * Anna's arrival/buffer math (shipment_planner.calculate_shipment) and her
    risk-transition rule (notification_manager.find_newly_at_risk) are applied to
    planner shipments as a cross-check and shown in previews.

The `port` object is supplied by the planner (apps/api/messaging_link.py). It is
the only way this module reads or changes planning state.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

import decision_agent
from shipment_planner import calculate_shipment

STATUS_AWAITING_OPTION = decision_agent.STATUS_AWAITING_OPTION
STATUS_AWAITING_APPROVAL = decision_agent.STATUS_AWAITING_APPROVAL
STATUS_APPROVED = decision_agent.STATUS_APPROVED
STATUS_CANCELLED = decision_agent.STATUS_CANCELLED
STATUS_REJECTED = "REJECTED"
PENDING_STATUSES = decision_agent.PENDING_STATUSES
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def parse_reply(text: str) -> tuple[str, Optional[int]]:
    kind, value = decision_agent._parse_reply(text)
    if kind == "UNKNOWN" and (text or "").strip().upper() == "REJECT":
        return "REJECT", None
    return kind, value


def is_decision_reply(text: str) -> bool:
    return parse_reply(text)[0] != "UNKNOWN"


def short(iso: Optional[str]) -> str:
    if not iso:
        return "none"
    value = date.fromisoformat(iso[:10])
    return f"{_MONTHS[value.month - 1]} {value.day}"


# --- Anna's shipment math applied to planner shipments -------------------------


def anna_record(shipment: dict) -> dict:
    """Express a planner shipment in shipment_planner's record shape.

    shipping_date is the planner's dispatch milestone; transit is the calendar-day
    span to the planner's projected site delivery. calculate_shipment therefore
    reproduces the planner's arrival date and adds Anna's calendar-day buffer and
    at-risk flag, which must agree with the planner's business-day slack sign.
    """
    dispatch = next(m["projected_date"] for m in shipment["milestones"] if m["type"] == "dispatch")
    transit = (date.fromisoformat(shipment["projected_delivery"]) - date.fromisoformat(dispatch)).days
    return {"shipment_id": shipment["id"], "drug_name": shipment.get("product", "investigational product"),
            "origin": shipment.get("origin"), "destination": shipment.get("country_name"),
            "shipping_date": dispatch, "estimated_transit_days": transit,
            "required_delivery_date": shipment["target_delivery"]}


def anna_projection(shipment: dict) -> dict:
    result = calculate_shipment(anna_record(shipment))
    return {"estimated_arrival_date": result["estimated_arrival_date"].isoformat(),
            "buffer_days": result["buffer_days"], "at_risk": result["at_risk"]}


def risk_transitions(before: list[dict], after: list[dict], event_id: str) -> list[dict]:
    """Shipments that flip ON TRACK -> AT RISK, using Anna's notification rule."""
    from notification_manager import find_newly_at_risk  # imported lazily: optional Photon SDK

    previous = {s["id"]: s for s in before}
    rows = []
    for shipment in after:
        old = previous.get(shipment["id"])
        if not old:
            continue
        a, b = calculate_shipment(anna_record(old)), calculate_shipment(anna_record(shipment))
        rows.append({"shipment_id": shipment["id"], "affected": old.get("projected_delivery") != shipment.get("projected_delivery"),
                     "original_at_risk": a["at_risk"], "new_at_risk": b["at_risk"], "event_id": event_id})
    return find_newly_at_risk(rows)


# --- message building ----------------------------------------------------------------


def _row_text(row: dict) -> str:
    after = row["after"]
    return f"delivery {short(after['projected_delivery'])}, slack {after['slack_days']} business days ({after['risk_band'].replace('_', ' ')})"


def _marker(event: dict) -> str:
    return "[SIMULATED] " if event.get("evidence_status") == "synthetic" else ""


def _primary(option: dict) -> Optional[dict]:
    return option["preview"][0] if option.get("preview") else None


def build_alert(event: dict, options: list[dict], baseline: Optional[dict]) -> list[dict]:
    accept = next((o for o in options if o["key"] == "accept"), options[-1])
    primary = _primary(accept)
    lines = [f"{_marker(event)}{event['title']}", event.get("description", "")]
    if event.get("source_url"):
        # Source + effective date, when the event carries cited evidence (e.g. a
        # regulatory labeling change) -- never stated as confirmed beyond what
        # _caption's evidence_status already says (synthetic/needs_review/verified).
        when = f", effective {short(event['effective_from'])}" if event.get("effective_from") else ""
        lines.append(f"Source: {event.get('source_title', event['title'])} ({event['source_url']}){when}.")
    if primary:
        before = primary["before"]
        route = primary["after"].get("route_name")
        lines += [f"Current plan for {primary['country_name']}: delivery {short(before.get('projected_delivery'))}, "
                  f"slack {before.get('slack_days')} business days ({str(before.get('risk_band', '')).replace('_', ' ')})."
                  + (f" Route: {route}." if route else ""),
                  f"Without mitigation: {_row_text(primary)}."]
    extra = max(0, len(accept.get("preview", [])) - 1)
    if extra:
        lines.append(f"{extra} more shipment(s) in the same label group or lane are affected.")
    numbers = ", ".join(str(o["number"]) for o in options)
    if not any(o.get("feasible") for o in options):
        lines.append("No option keeps every affected shipment on its target date; the options below differ in how late they are.")
    lines += ["", f"Pick a fix (reply {numbers}):"]
    for option in options:
        row = _primary(option)
        lines.append(f"{option['number']}. {option['title']}" + (f" -- {_row_text(row)}" if row else ""))
    lines += ["", "Reply DETAILS for the evidence, or CANCEL to stop. Picking an option only previews it."]
    rows = []
    if primary:
        rows = [["Projected delivery", short(primary["before"].get("projected_delivery"))],
                ["Slack", f"{primary['before'].get('slack_days')} business days"],
                ["Safe ship-by", short((baseline or {}).get("ship_by", {}).get("safe"))],
                ["Shipments affected", str(len(accept.get("preview", [])))]]
    return [
        {"text": "\n".join(l for l in lines if l is not None), "caption": _caption(event)},
        {"card": {"type": "plan", "title": f"{event.get('country_name', event.get('jurisdiction'))}, current plan", "rows": rows, "tone": "warn"},
         "links": [{"label": "Details", "href": f"#/warnings/{event['warning_id']}"}]},
        {"card": {"type": "options", "title": f"Pick a fix (reply {numbers})",
                  "options": [o["title"] + (f" · {short(_primary(o)['after']['projected_delivery'])}" if _primary(o) else "") for o in options]},
         "quickReplies": [str(o["number"]) for o in options] + ["DETAILS"]},
    ]


def _caption(event: dict) -> str:
    status = event.get("evidence_status")
    return {"synthetic": "Synthetic demo event", "needs_review": "Evidence needs review",
            "verified": "Verified evidence", "retired": "Retired evidence"}.get(status, "Evidence status unknown")


def build_preview(event: dict, option: dict, transitions: list[dict]) -> list[dict]:
    row = _primary(option)
    lines = [f"Option {option['number']} selected: {option['title']}."]
    card_rows = []
    if row:
        before, after = row["before"], row["after"]
        lines.append(f"Preview for {row['country_name']}: delivery {short(before.get('projected_delivery'))} -> {short(after['projected_delivery'])}, "
                     f"slack {before.get('slack_days')} -> {after['slack_days']} business days ({after['risk_band'].replace('_', ' ')}).")
        anna = row.get("calendar_check") or {}
        if anna:
            lines.append(f"Calendar-day check: arrives {abs(anna['buffer_days'])} calendar day(s) "
                         f"{'after' if anna['at_risk'] else 'before'} the target ({'late' if anna['at_risk'] else 'not late'}).")
        card_rows = [["Projected delivery", f"{short(before.get('projected_delivery'))} → {short(after['projected_delivery'])}"],
                     ["Slack", f"{before.get('slack_days')} → {after['slack_days']} business days"],
                     ["Safe ship-by", short(after.get("ship_by", {}).get("safe"))],
                     ["Cost delta", f"{option.get('cost_delta', 0):+g} (cost proxy)"],
                     ["Status", "Needs approval"]]
    for item in transitions:
        lines.append(f"Risk transition: {item['shipment_id']} goes ON TRACK -> AT RISK under this option.")
    if option.get("tradeoffs"):
        lines.append(f"Trade-off: {option['tradeoffs']}")
    lines += ["", "Nothing has changed yet. Reply APPROVE to make this the current plan, REJECT to reject it, or CANCEL."]
    ok = bool(row) and row["after"]["risk_band"] == "on_track"
    return [{"text": "\n".join(lines), "caption": f"Preview only · proposal {option['proposal_id']}"},
            {"card": {"type": "plan", "title": f"{event.get('country_name', event.get('jurisdiction'))}, option {option['number']} preview",
                      "rows": card_rows, "tone": "ok" if ok else "warn"},
             "links": [{"label": "Compare plans", "href": f"#/warnings/{event['warning_id']}"}],
             "quickReplies": ["APPROVE", "REJECT", "CANCEL"]}]


def build_details(event: dict, options: list[dict]) -> list[dict]:
    lines = [f"{_marker(event)}{event['title']} -- evidence",
             f"Evidence status: {event.get('evidence_status')}",
             f"Source: {event.get('source_title') or event.get('title')}",
             f"Link: {event.get('source_url') or 'none recorded'}",
             f"Excerpt: {event.get('source_excerpt') or 'none recorded'}", "", "Options:"]
    for option in options:
        row = _primary(option)
        lines.append(f"{option['number']}. {option['title']}" + (f" -- {_row_text(row)}" if row else "") + f" [{option['proposal_id']}]")
    return [{"text": "\n".join(lines), "caption": _caption(event),
             "links": [{"label": "Evidence", "href": f"#/warnings/{event['warning_id']}"}]}]


# --- state machine -------------------------------------------------------------------


def start_conversation(port: Any, chat_id: str, event_id: str) -> list[dict]:
    """Open (or re-open) the decision conversation for this chat and event."""
    event = port.event(event_id)
    options = port.options(event_id)
    if not options:
        return []
    port.save_conversation({"chat_id": chat_id, "event_id": event_id, "status": STATUS_AWAITING_OPTION,
                            "selected_option": None, "selected_proposal_id": None, "approved_proposal_id": None})
    return build_alert(event, options, port.primary_shipment(event_id))


def handle_message(port: Any, chat_id: str, actor_id: Optional[str], text: str, *, channel: str, message_id: str) -> list[dict]:
    """Route one inbound message: a scoped demo intent first (if enabled), then decision
    grammar to the conversation, then everything else to Q&A."""
    convo = port.latest_conversation(chat_id)
    import demo_dialogue  # imported lazily: avoids a circular import (demo_dialogue imports this module)
    demo_reply = demo_dialogue.handle(port, convo, chat_id, actor_id, text, channel=channel, message_id=message_id)
    if demo_reply is not None:
        return demo_reply
    if convo is None or not is_decision_reply(text):
        return [port.answer_question(chat_id, text)]
    return handle_reply(port, convo, actor_id, text, channel=channel, message_id=message_id)


def handle_reply(port: Any, convo: dict, actor_id: Optional[str], text: str, *, channel: str, message_id: str) -> list[dict]:
    kind, value = parse_reply(text)
    event = port.event(convo["event_id"])
    options = port.options(convo["event_id"])
    status = convo["status"]

    if status == STATUS_CANCELLED:
        return [{"text": "This decision was cancelled. No pending action for this event."}]
    if status in (STATUS_APPROVED, STATUS_REJECTED):
        if kind in ("DETAILS", "SOURCE"):
            return build_details(event, options)
        if kind == "APPROVE" and status == STATUS_APPROVED:
            decision = port.decision(convo["approved_proposal_id"]) or {}
            return [{"text": f"Already recorded: {decision.get('approver', 'someone')} approved this plan. No change made.",
                     "links": [{"label": "View the plan", "href": f"#/warnings/{event['warning_id']}"}]}]
        return [{"text": f"This decision is already {status.lower()} and recorded. Reply DETAILS to review it."}]

    if kind == "CANCEL":
        port.save_conversation({**convo, "status": STATUS_CANCELLED})
        return [{"text": "Cancelled. The current plan is unchanged and the proposals stay available for review."}]
    if kind in ("DETAILS", "SOURCE"):
        return build_details(event, options)

    if kind == "OPTION":
        option = next((o for o in options if o["number"] == value), None)
        if option is None:
            valid = ", ".join(str(o["number"]) for o in options) or "none (this event is resolved)"
            return [{"text": f"Please reply with a valid option ({valid}), DETAILS, or CANCEL."}]
        port.save_conversation({**convo, "status": STATUS_AWAITING_APPROVAL, "selected_option": option["number"],
                                "selected_proposal_id": option["proposal_id"]})
        return build_preview(event, option, port.transitions(option["proposal_id"]))

    if kind in ("APPROVE", "REJECT"):
        if status != STATUS_AWAITING_APPROVAL or not convo.get("selected_proposal_id"):
            return [{"text": "Pick an option first (reply with its number) before approving or rejecting."}]
        role = port.role(actor_id)
        action = "approve" if kind == "APPROVE" else "reject"
        label = f"option {convo['selected_option']}"
        try:
            result = port.decide(action, convo["selected_proposal_id"], actor_id=actor_id,
                                 actor_role=(role or {}).get("role"),
                                 rationale=f"{action.title()}d {label} for {event['id']} via {channel}",
                                 channel=channel, idempotency_key=f"{channel}:{message_id}:{action}")
        except Exception as exc:  # DecisionRefused from the planner
            code = getattr(exc, "code", "error")
            if code == "unauthorized":
                return [{"text": "I can't record that: only an authorized supply lead can approve or reject plans. "
                                 "I've noted your reply, but no change was made.", "caption": "Refused by planner · unauthorized"}]
            if code in ("stale_proposal", "stale_expected_plan", "stale_dataset"):
                port.save_conversation({**convo, "status": STATUS_AWAITING_OPTION, "selected_option": None, "selected_proposal_id": None})
                return [{"text": "The current plan changed since this option was calculated, so it is superseded. "
                                 "Nothing changed. Reply with an option number to preview it against the current plan.",
                         "caption": "Refused by planner · stale proposal", "quickReplies": [str(o["number"]) for o in options]}]
            if code == "already_decided":
                return [{"text": f"That proposal was already decided; nothing changed. ({exc})"}]
            return [{"text": f"The planner refused this decision: {exc}", "caption": f"Refused by planner · {code}"}]
        if action == "approve":
            port.save_conversation({**convo, "status": STATUS_APPROVED, "approved_proposal_id": result["proposalId"]})
            return [{"text": f"Recorded: {result['actor']['name']} approved {label} for {event['title']} via {channel}. "
                             f"The planner moved the current plan to version {result['currentPlanVersion']}.",
                     "caption": f"Approved · {result['proposalId']}",
                     "links": [{"label": "View the plan", "href": f"#/warnings/{event['warning_id']}"}]}]
        # A rejection closes that one proposal; the person can still pick another option.
        port.save_conversation({**convo, "status": STATUS_AWAITING_OPTION, "selected_option": None, "selected_proposal_id": None})
        remaining = [str(o["number"]) for o in port.options(event["id"]) if o["status"] == "proposed"]
        return [{"text": f"Rejected {label}. The current plan is unchanged; reply with another option number to preview it.",
                 "caption": f"Rejected · {result['proposalId']}", "quickReplies": remaining}]

    return [{"text": "Sorry, I didn't understand that reply. Reply with an option number, DETAILS, or CANCEL."}]
