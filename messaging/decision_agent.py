"""Conversation state machine for Cleared for Takeoff's Photon decision agent.

Turns a disruption alert into a short back-and-forth: the agent proposes
1-3 numbered remediation options, previews the shipment-level consequence of
whichever one the user picks using the existing shipment math, and only
changes anything once a verified, authorized actor explicitly replies
APPROVE. Selecting an option is never treated as approval (requirement 4),
and nothing here ever auto-approves a regulatory or operational change
(requirement 6).

Conversation state is scoped per (space_id, event_id) -- one Photon space is
one 1:1 iMessage thread with one person, so this keys state per
conversation/user AND per event, never globally. State lives in a small
JSON file, matching the persistence style already used by photon_bridge.py
and notification_manager.py.

Reuses existing, already-tested building blocks rather than re-implementing
them:
  - shipment_planner.load_shipments() / calculate_shipment()
  - impact_analyzer.SIMULATED_DISRUPTION_EVENT
  - audit_log.append_entry() / load_entries()

Every message this module produces is plain text (no Markdown) and marked
SIMULATED, per the hackathon scenario.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import audit_log
from impact_analyzer import SIMULATED_DISRUPTION_EVENT
from shipment_planner import calculate_shipment, load_shipments

CONVERSATION_STATE_PATH = Path(__file__).resolve().parent / ".conversation_state.json"
AUDIT_LOG_PATH = Path(__file__).resolve().parent / ".audit_log.jsonl"
AUTHORIZED_ROLES_PATH = Path(__file__).resolve().parent / "data" / "authorized_roles.json"

STATUS_AWAITING_OPTION = "AWAITING_OPTION"
STATUS_AWAITING_APPROVAL = "AWAITING_APPROVAL"
STATUS_APPROVED = "APPROVED"
STATUS_CANCELLED = "CANCELLED"

PENDING_STATUSES = (STATUS_AWAITING_OPTION, STATUS_AWAITING_APPROVAL)

# --- SIMULATED remediation options for the SHIP-001 customs-hold event ------
#
# Each option's `delay_reduction_days` is applied against the disruption's
# own `additional_delay_days` and previewed through the existing
# shipment_planner.calculate_shipment() -- the ETA numbers shown to the user
# are always real outputs of that function, never invented. `cost_known`
# marks options where no cost/feasibility data exists in this dataset; the
# agent must say so rather than invent a dollar figure (requirement 3).
CUSTOMS_HOLD_OPTIONS = [
    {
        "option_id": 1,
        "label": "Reroute via Rotterdam (alternate port)",
        "delay_reduction_days": 4,
        "cost_known": False,
    },
    {
        "option_id": 2,
        "label": "Expedite customs clearance (priority lane)",
        "delay_reduction_days": 2,
        "cost_known": False,
    },
    {
        "option_id": 3,
        "label": "Keep current plan (no change)",
        "delay_reduction_days": 0,
        "cost_known": True,
    },
]

EVENT_REGISTRY: dict[str, dict] = {
    SIMULATED_DISRUPTION_EVENT["event_id"]: SIMULATED_DISRUPTION_EVENT,
}
EVENT_OPTIONS: dict[str, list[dict]] = {
    SIMULATED_DISRUPTION_EVENT["event_id"]: CUSTOMS_HOLD_OPTIONS,
}


# --- state persistence --------------------------------------------------------


def conversation_key(space_id: str, event_id: str) -> str:
    return f"{space_id}:{event_id}"


def load_conversations(path: Path = CONVERSATION_STATE_PATH) -> dict:
    path = Path(path)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save_conversations(conversations: dict, path: Path = CONVERSATION_STATE_PATH) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(conversations), encoding="utf-8")


def find_active_conversation_for_space(
    space_id: str,
    conversations: Optional[dict] = None,
    state_path: Path = CONVERSATION_STATE_PATH,
) -> Optional[tuple[str, dict]]:
    """Return (event_id, convo) for the most recently updated PENDING
    conversation in this space, or None if there isn't one. A space with no
    pending decision falls through to regular Q&A handling.
    """
    conversations = conversations if conversations is not None else load_conversations(state_path)
    candidates = [
        convo
        for convo in conversations.values()
        if convo.get("space_id") == space_id and convo.get("status") in PENDING_STATUSES
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda c: c.get("updated_at", ""), reverse=True)
    latest = candidates[0]
    return latest["event_id"], latest


def find_conversation_for_space(
    space_id: str,
    conversations: Optional[dict] = None,
    state_path: Path = CONVERSATION_STATE_PATH,
) -> Optional[tuple[str, dict]]:
    """Return (event_id, convo) for the most recently updated conversation
    in this space, REGARDLESS of status. Unlike
    find_active_conversation_for_space (pending only), this is used to
    decide whether an inbound decision-shaped reply (1/2/3, DETAILS,
    SOURCE, CANCEL, APPROVE) belongs to a conversation that has already
    been resolved -- e.g. a duplicate APPROVE or a DETAILS follow-up after
    approval must still reach handle_reply's idempotent/approved-state
    handling, not silently fall through to unrelated Q&A handling.
    """
    conversations = conversations if conversations is not None else load_conversations(state_path)
    candidates = [c for c in conversations.values() if c.get("space_id") == space_id]
    if not candidates:
        return None
    candidates.sort(key=lambda c: c.get("updated_at", ""), reverse=True)
    latest = candidates[0]
    return latest["event_id"], latest


def is_decision_reply(text: str) -> bool:
    """True if `text` parses as decision-flow grammar (1/2/3, DETAILS,
    SOURCE, CANCEL, APPROVE) -- used to gate routing a reply to
    handle_reply only when it actually looks like a decision-flow command,
    so a space with a resolved conversation can still ask ordinary
    regulatory questions afterward.
    """
    return _parse_reply(text)[0] != "UNKNOWN"


def get_conversation(
    space_id: str,
    event_id: str,
    conversations: Optional[dict] = None,
    state_path: Path = CONVERSATION_STATE_PATH,
) -> Optional[dict]:
    conversations = conversations if conversations is not None else load_conversations(state_path)
    return conversations.get(conversation_key(space_id, event_id))


def get_approved_plan(
    space_id: str,
    event_id: str,
    conversations: Optional[dict] = None,
    state_path: Path = CONVERSATION_STATE_PATH,
) -> Optional[dict]:
    """The committed, approved plan for this conversation -- distinct from
    any proposed option, which never appears here until APPROVE succeeds
    (requirement 6).
    """
    convo = get_conversation(space_id, event_id, conversations, state_path)
    if convo is None or convo.get("status") != STATUS_APPROVED:
        return None
    return convo.get("approved_plan")


def find_approved_decision(
    shipment_id: str,
    event_id: Optional[str] = None,
    conversations: Optional[dict] = None,
    state_path: Path = CONVERSATION_STATE_PATH,
) -> Optional[dict]:
    """The most recently approved decision for this shipment, optionally
    scoped to one event_id, across every conversation/space. This is the
    ONLY bridge from decision-agent state into the rest of the app: callers
    (the dashboard API) overlay this on top of the simulated baseline/
    disruption numbers at read time. It never mutates shipments.json or any
    simulated baseline data -- approved-plan state lives entirely in the
    conversation store, kept separate on purpose (requirement 6: proposed
    options and unverified updates never leak into committed plan state,
    and nothing here is auto-approved).

    If more than one space approved a decision for the same shipment/event
    (e.g. two people independently approved), the most recently approved
    one wins -- deterministic, not a silent merge of conflicting plans.
    """
    conversations = conversations if conversations is not None else load_conversations(state_path)
    candidates = [
        c
        for c in conversations.values()
        if c.get("status") == STATUS_APPROVED
        and c.get("shipment_id") == shipment_id
        and (event_id is None or c.get("event_id") == event_id)
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda c: c.get("approved_at") or "", reverse=True)
    return candidates[0]


# --- authorization -------------------------------------------------------------


def load_authorized_roles(path: Path = AUTHORIZED_ROLES_PATH) -> dict:
    path = Path(path)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def is_authorized_to_approve(actor_id: Optional[str], roles: Optional[dict] = None) -> Optional[dict]:
    """Return the role record if `actor_id` is a verified, authorized
    approver, else None. A missing/unknown actor is never authorized --
    the safe default is to require verification, not assume it.
    """
    if not actor_id:
        return None
    roles = roles if roles is not None else load_authorized_roles()
    role = roles.get(actor_id)
    if role and role.get("can_approve"):
        return role
    return None


# --- shipment math reuse ---------------------------------------------------


def _find_shipment(shipment_id: str, shipments: Optional[list] = None) -> dict:
    pool = shipments if shipments is not None else load_shipments()
    shipment = next((s for s in pool if s.get("shipment_id") == shipment_id), None)
    if shipment is None:
        raise ValueError(f"Shipment {shipment_id!r} not found")
    return shipment


def compute_option_preview(shipment: dict, disruption_event: dict, option: dict) -> dict:
    """Preview a remediation option's effect using the existing shipment
    calculation -- never invented numbers. Returns parsed dates (callers
    needing JSON use `_plan_snapshot` instead).
    """
    base_delay = disruption_event.get("additional_delay_days", 0)
    effective_delay = max(0, base_delay - option.get("delay_reduction_days", 0))
    calc = calculate_shipment(shipment, delay_days=effective_delay)
    return {
        "option_id": option["option_id"],
        "label": option["label"],
        "effective_delay_days": effective_delay,
        "estimated_arrival_date": calc["estimated_arrival_date"],
        "required_delivery_date": calc["required_delivery_date"],
        "buffer_days": calc["buffer_days"],
        "at_risk": calc["at_risk"],
        "cost_known": option.get("cost_known", False),
    }


def _plan_snapshot(shipment: dict, delay_days: int) -> dict:
    """A JSON-safe plan snapshot for the audit log / API."""
    calc = calculate_shipment(shipment, delay_days=delay_days)
    return {
        "estimated_arrival_date": calc["estimated_arrival_date"].isoformat(),
        "required_delivery_date": calc["required_delivery_date"].isoformat(),
        "buffer_days": calc["buffer_days"],
        "at_risk": calc["at_risk"],
        "delay_days": delay_days,
    }


# --- message building (requirement 1: mobile-first plain text) -------------


def _days_late(preview_or_calc: dict) -> int:
    delta = (preview_or_calc["estimated_arrival_date"] - preview_or_calc["required_delivery_date"]).days
    return max(0, delta)


def build_initial_alert(shipment: dict, disruption_event: dict, options: list[dict]) -> str:
    original = calculate_shipment(shipment, delay_days=0)
    revised = calculate_shipment(shipment, delay_days=disruption_event.get("additional_delay_days", 0))
    late = _days_late(revised)

    lines = [
        f"SIMULATED {disruption_event['event_id']}: {disruption_event['description']}",
        f"Shipment: {shipment['shipment_id']} ({shipment.get('drug_name', 'unknown drug')})",
        f"Revised ETA: {revised['estimated_arrival_date'].isoformat()} (was {original['estimated_arrival_date'].isoformat()})",
        f"Deadline: {revised['required_delivery_date'].isoformat()}"
        + (f" -- {late} day(s) late" if late else ""),
        "",
        "Pick a fix (reply 1, 2, or 3):",
    ]
    for option in options:
        preview = compute_option_preview(shipment, disruption_event, option)
        cost_note = "" if preview["cost_known"] else " -- cost not available, needs verification"
        risk_note = "" if not preview["at_risk"] else f" -- still {_days_late(preview)} day(s) late"
        lines.append(
            f"{option['option_id']}. {option['label']} -- ETA {preview['estimated_arrival_date'].isoformat()}"
            f"{risk_note}{cost_note}"
        )
    lines.append("")
    lines.append("Reply DETAILS for the full event, or CANCEL to stop.")
    return "\n".join(lines)


def _build_preview_message(shipment: dict, disruption_event: dict, option: dict) -> str:
    preview = compute_option_preview(shipment, disruption_event, option)
    lines = [f"Option {option['option_id']} selected: {option['label']}."]
    if preview["at_risk"]:
        lines.append(
            f"Preview: {shipment['shipment_id']} revised ETA {preview['estimated_arrival_date'].isoformat()}, "
            f"required by {preview['required_delivery_date'].isoformat()} -- "
            f"still AT RISK, {_days_late(preview)} day(s) late."
        )
    else:
        lines.append(
            f"Preview: {shipment['shipment_id']} revised ETA {preview['estimated_arrival_date'].isoformat()}, "
            f"required by {preview['required_delivery_date'].isoformat()} -- "
            f"ON TRACK, {preview['buffer_days']} day(s) buffer."
        )
    if not preview["cost_known"]:
        lines.append("Cost: not available in this dataset -- requires verification before committing.")
    lines.append("")
    lines.append("Reply APPROVE to make this the current plan, or CANCEL.")
    return "\n".join(lines)


def build_details_message(shipment: dict, disruption_event: dict, options: list[dict]) -> str:
    original = calculate_shipment(shipment, delay_days=0)
    lines = [
        f"SIMULATED {disruption_event['event_id']} -- full detail",
        f"Event: {disruption_event['description']}",
        f"Shipment: {shipment['shipment_id']} ({shipment.get('drug_name', 'unknown drug')})",
        f"Origin: {shipment.get('origin', 'unknown')}",
        f"Destination: {shipment.get('destination', 'unknown')}",
        f"Original ETA: {original['estimated_arrival_date'].isoformat()}",
        f"Required delivery: {original['required_delivery_date'].isoformat()}",
        "",
        "Options:",
    ]
    for option in options:
        preview = compute_option_preview(shipment, disruption_event, option)
        cost_note = "cost not available" if not preview["cost_known"] else "no additional cost"
        lines.append(
            f"{option['option_id']}. {option['label']} -- ETA {preview['estimated_arrival_date'].isoformat()}, {cost_note}"
        )
    lines.append("")
    lines.append("Source: SIMULATED demo event for HackHarvard -- not a real customs record.")
    return "\n".join(lines)


# --- reply parsing -----------------------------------------------------------


def _parse_reply(text: str) -> tuple[str, Optional[int]]:
    normalized = (text or "").strip().upper()
    if normalized in ("DETAILS", "DETAIL"):
        return "DETAILS", None
    if normalized == "SOURCE":
        return "SOURCE", None
    if normalized == "CANCEL":
        return "CANCEL", None
    if normalized == "APPROVE":
        return "APPROVE", None
    if normalized.lstrip("-").isdigit():
        return "OPTION", int(normalized)
    return "UNKNOWN", None


# --- main state machine entry points ----------------------------------------


def start_conversation(
    space_id: str,
    event_id: str,
    shipment_id: str,
    *,
    shipment: Optional[dict] = None,
    disruption_event: Optional[dict] = None,
    options: Optional[list[dict]] = None,
    shipments: Optional[list] = None,
    conversations: Optional[dict] = None,
    state_path: Path = CONVERSATION_STATE_PATH,
    now: Optional[datetime] = None,
) -> str:
    """Open a new decision conversation for (space_id, event_id) and return
    the initial plain-text alert to send. Persists the conversation as
    AWAITING_OPTION -- nothing is approved or changed yet.
    """
    event = disruption_event or EVENT_REGISTRY.get(event_id)
    if event is None:
        raise ValueError(f"Unknown event_id {event_id!r} and no disruption_event provided")
    opts = options or EVENT_OPTIONS.get(event_id)
    if not opts:
        raise ValueError(f"No remediation options registered for event_id {event_id!r}")
    if shipment is None:
        shipment = _find_shipment(shipment_id, shipments)

    now = now or datetime.now(timezone.utc)
    conversations = conversations if conversations is not None else load_conversations(state_path)

    message = build_initial_alert(shipment, event, opts)

    conversations[conversation_key(space_id, event_id)] = {
        "space_id": space_id,
        "event_id": event_id,
        "shipment_id": shipment_id,
        "status": STATUS_AWAITING_OPTION,
        "selected_option": None,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "approved_by": None,
        "approved_at": None,
        "approved_plan": None,
    }
    save_conversations(conversations, state_path)
    return message


def handle_reply(
    space_id: str,
    event_id: str,
    actor_id: Optional[str],
    text: str,
    *,
    shipments: Optional[list] = None,
    disruption_event: Optional[dict] = None,
    options: Optional[list[dict]] = None,
    conversations: Optional[dict] = None,
    state_path: Path = CONVERSATION_STATE_PATH,
    audit_path: Path = AUDIT_LOG_PATH,
    roles: Optional[dict] = None,
    now: Optional[datetime] = None,
) -> str:
    """Advance the (space_id, event_id) conversation given an inbound reply
    and return the plain-text response to send back. Never mutates
    shipment/regulatory data; only ever writes the audit log, and only on a
    successful, authorized APPROVE.
    """
    now = now or datetime.now(timezone.utc)
    owns_store = conversations is None
    conversations = conversations if conversations is not None else load_conversations(state_path)

    key = conversation_key(space_id, event_id)
    convo = conversations.get(key)
    if convo is None:
        return (
            "No pending decision for this conversation. If you're expecting an alert, "
            "it may have already been resolved or hasn't been sent yet."
        )

    event = disruption_event or EVENT_REGISTRY.get(convo["event_id"])
    opts = options or EVENT_OPTIONS.get(convo["event_id"])
    shipment = _find_shipment(convo["shipment_id"], shipments)

    kind, value = _parse_reply(text)
    status = convo["status"]

    def _save_if_owner() -> None:
        if owns_store:
            save_conversations(conversations, state_path)

    if status == STATUS_CANCELLED:
        return "This decision was cancelled. No pending action for this event."

    if status == STATUS_APPROVED:
        if kind == "APPROVE":
            option_label = convo.get("selected_option", {}).get("label", "the selected option")
            actor_name = (convo.get("approved_by") or {}).get("name", "someone")
            return (
                f'Already recorded: {actor_name} approved "{option_label}" for '
                f"{shipment['shipment_id']} via iMessage. No change made."
            )
        if kind in ("DETAILS", "SOURCE"):
            return build_details_message(shipment, event, opts)
        return (
            f"This decision is already approved and recorded. Reply DETAILS to review it, "
            f"or contact the supply lead to propose a new change."
        )

    if kind == "CANCEL":
        convo["status"] = STATUS_CANCELLED
        convo["updated_at"] = now.isoformat()
        _save_if_owner()
        return f"Cancelled. No change made to {shipment['shipment_id']}'s current plan."

    if kind == "DETAILS":
        return build_details_message(shipment, event, opts)

    if kind == "SOURCE":
        return (
            "This is a simulated logistics event, not a regulatory citation -- "
            "there's no source document to verify. Reply DETAILS for the full event."
        )

    if kind == "OPTION":
        option = next((o for o in opts if o["option_id"] == value), None)
        if option is None:
            valid = ", ".join(str(o["option_id"]) for o in opts)
            return f"Please reply with a valid option ({valid}), DETAILS, or CANCEL."
        convo["selected_option"] = {"option_id": option["option_id"], "label": option["label"]}
        convo["status"] = STATUS_AWAITING_APPROVAL
        convo["updated_at"] = now.isoformat()
        _save_if_owner()
        return _build_preview_message(shipment, event, option)

    if kind == "APPROVE":
        if status != STATUS_AWAITING_APPROVAL or not convo.get("selected_option"):
            return "Pick an option first (reply 1, 2, or 3) before approving."

        role = is_authorized_to_approve(actor_id, roles)
        if role is None:
            return (
                "I can't approve plans; only an authorized supply lead can. "
                "I've noted your reply, but no change was made."
            )

        option_id = convo["selected_option"]["option_id"]
        option = next(o for o in opts if o["option_id"] == option_id)
        base_delay = event.get("additional_delay_days", 0)
        effective_delay = max(0, base_delay - option.get("delay_reduction_days", 0))

        before_plan = _plan_snapshot(shipment, base_delay)
        after_plan = _plan_snapshot(shipment, effective_delay)

        entry = {
            "label": "SIMULATED",
            "event_id": convo["event_id"],
            "shipment_id": convo["shipment_id"],
            "selected_option": convo["selected_option"],
            "authorized_actor": {"id": actor_id, "name": role.get("name"), "role": role.get("role")},
            "timestamp": now.isoformat(),
            "before_plan": before_plan,
            "after_plan": after_plan,
            "channel": "iMessage",
        }
        audit_log.append_entry(entry, path=audit_path)

        convo["status"] = STATUS_APPROVED
        convo["approved_by"] = {"id": actor_id, "name": role.get("name"), "role": role.get("role")}
        convo["approved_at"] = now.isoformat()
        convo["approved_plan"] = after_plan
        convo["updated_at"] = now.isoformat()
        _save_if_owner()

        time_str = now.strftime("%H:%M UTC")
        lines = [
            f'Recorded: {role.get("name")} approved "{option["label"]}" for '
            f"{shipment['shipment_id']} via iMessage at {time_str}.",
            f"Revised ETA: {after_plan['estimated_arrival_date']} (required {after_plan['required_delivery_date']}).",
        ]
        return "\n".join(lines)

    return "Sorry, I didn't understand that reply. Reply 1, 2, 3, DETAILS, or CANCEL."


def conversation_view(convo: dict) -> dict:
    """Sanitized, JSON-safe view of a conversation record for the dashboard
    API. Nothing here is secret -- it's the same identifiers already
    exchanged over Photon.
    """
    return dict(convo)
