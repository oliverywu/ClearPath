"""Natural-language demo conversation for the seeded Germany shipment event.

Scoped narrowly on purpose: this module only ever answers questions about
`DEMO_EVENT_ID` (the real, already-seeded `de-route-delay` change-event), and
only when `PHOTON_DEMO_MODE=true`. Every number it states -- delay days,
recovered days, dates, proposal ids -- comes from `port` (the same
PlannerPort interface planner_conversation.py uses), never a hardcoded
value, so it can never drift from what the governed planner actually
computed. Approval/rejection still goes through the existing decision
grammar (APPROVE/REJECT) and `handle_reply` -> `governance.decide()`
unchanged; this module never calls `decide()` directly and never approves
anything itself.

`handle()` returns None when the message isn't a demo intent for this
event, so callers fall through to the existing generic path untouched.
"""
from __future__ import annotations

import os
import re
from typing import Any, Optional

import planner_conversation

DEMO_EVENT_ID = "de-route-delay"

_STATUS_RE = re.compile(r"\bgerman(y)?\b.*\b(status|shipment|ship|delay)\b|\b(status|shipment|ship|delay)\b.*\bgerman(y)?\b", re.I)
_WHY_RE = re.compile(r"\bwhy\b", re.I)
_OPTIONS_RE = re.compile(r"\b(option|options|show me|what can|what are my)\b|^\s*yes\b", re.I)
_RECOMMEND_RE = re.compile(r"\brecommend\b|\bwhich (one|option)\b|\bwhy .*\b(option|recommend)", re.I)
_PREPARE_RE = re.compile(r"\bprepare\b.*\bproposal\b|\bprepare it\b", re.I)


def demo_mode_enabled() -> bool:
    return os.getenv("PHOTON_DEMO_MODE", "false").strip().lower() == "true"


def _is_demo_convo(convo: Optional[dict]) -> bool:
    return bool(convo) and convo.get("event_id") == DEMO_EVENT_ID


def _accept_option(options: list[dict]) -> Optional[dict]:
    return next((o for o in options if o.get("key") == "accept"), None)


def _recommended_option(options: list[dict]) -> Optional[dict]:
    return next((o for o in options if o.get("recommended")), None)


def _recovered_days(option: dict, accept: Optional[dict]) -> Optional[int]:
    """Business days recovered vs. doing nothing, from the planner's own preview rows."""
    if not accept or not option.get("preview") or not accept.get("preview"):
        return None
    try:
        option_slack = option["preview"][0]["after"]["slack_days"]
        accept_slack = accept["preview"][0]["after"]["slack_days"]
        return option_slack - accept_slack
    except (KeyError, IndexError, TypeError):
        return None


def _short(iso: Optional[str]) -> str:
    return planner_conversation.short(iso)


def _status_text(event: dict, delay_days: int, label: bool) -> str:
    prefix = "Demo scenario: " if label else ""
    return (f"{prefix}The {event.get('country_name', 'Germany')} shipment is currently delayed "
            f"{delay_days} business days by {event.get('title', 'a logistics event').split(chr(183))[-1].strip()}. "
            f"I found a couple of ways to reduce the delay. Want to see them?")


def _why_text(event: dict, delay_days: int) -> str:
    cause = event.get("description") or event.get("title") or "a logistics disruption"
    return f"{cause} That adds {delay_days} business days versus the original schedule."


def _options_text(real_options: list[dict], accept: Optional[dict]) -> str:
    lines = []
    for i, option in enumerate(real_options, start=1):
        recovered = _recovered_days(option, accept)
        tail = f", recovering about {recovered} business day{'s' if recovered != 1 else ''}" if recovered is not None else ""
        lines.append(f"Option {i}: {option['title']}{tail}.")
    recommended = _recommended_option(real_options)
    if recommended:
        lines.append(f"I recommend {recommended['title']} because it recovers more schedule. Want me to prepare the proposal?")
    return " ".join(lines)


def _recommend_text(real_options: list[dict], accept: Optional[dict]) -> str:
    recommended = _recommended_option(real_options)
    if not recommended:
        return "None of the options fully resolve this one -- ask me for details to see the trade-offs."
    others = [o for o in real_options if o is not recommended]
    recovered = _recovered_days(recommended, accept)
    if others:
        other_recovered = _recovered_days(others[0], accept)
        if recovered is not None and other_recovered is not None:
            return (f"{recommended['title']} recovers about {recovered} business days, versus "
                    f"{other_recovered} business days for {others[0]['title']} -- more schedule recovery, so it "
                    f"gives the shipment a better chance of reaching the trial site on schedule.")
    return f"{recommended['title']} is the strongest option here -- it recovers the most schedule of what's available."


def handle(
    port: Any,
    convo: Optional[dict],
    chat_id: str,
    actor_id: Optional[str],
    text: str,
    *,
    channel: str,
    message_id: str,
) -> Optional[list[dict]]:
    if not demo_mode_enabled():
        return None

    text = str(text or "").strip()
    is_demo = _is_demo_convo(convo)

    if _STATUS_RE.search(text):
        event = port.event(DEMO_EVENT_ID)
        options = port.options(DEMO_EVENT_ID)
        if not options:
            return None
        delay = event.get("transit_delay_days", 0)
        if not is_demo:
            # Fresh start: reuse the real state machine's save_conversation side effect,
            # but render our own short text instead of the default long alert.
            planner_conversation.start_conversation(port, chat_id, DEMO_EVENT_ID)
            return [{"text": _status_text(event, delay, label=True), "caption": "Demo scenario · synthetic seeded event"}]
        # Already an active demo conversation for this chat -- read-only status, no re-save.
        status = convo["status"]
        if status == planner_conversation.STATUS_AWAITING_OPTION:
            return [{"text": _status_text(event, delay, label=False)}]
        if status == planner_conversation.STATUS_AWAITING_APPROVAL:
            option = next((o for o in port.options(DEMO_EVENT_ID) if o["number"] == convo.get("selected_option")), None)
            title = option["title"] if option else "the selected option"
            return [{"text": f"Still waiting on your decision for {title}. Reply APPROVE, REJECT, or ask me more."}]
        if status in (planner_conversation.STATUS_APPROVED, "REJECTED", planner_conversation.STATUS_CANCELLED):
            return None  # let the existing grammar/already-decided handling answer this
        return [{"text": _status_text(event, delay, label=False)}]

    if not is_demo:
        return None  # no active demo conversation and not a status trigger -- not our concern

    event = port.event(DEMO_EVENT_ID)
    options = port.options(DEMO_EVENT_ID)
    if not options:
        return None
    accept = _accept_option(options)
    real_options = [o for o in options if o is not accept]
    delay = event.get("transit_delay_days", 0)

    if _WHY_RE.search(text) and not _RECOMMEND_RE.search(text):
        return [{"text": _why_text(event, delay)}]

    if _RECOMMEND_RE.search(text):
        return [{"text": _recommend_text(real_options, accept)}]

    if _OPTIONS_RE.search(text):
        return [{"text": _options_text(real_options, accept)}]

    if _PREPARE_RE.search(text):
        recommended = _recommended_option(real_options)
        if not recommended:
            return None
        if convo["status"] != planner_conversation.STATUS_AWAITING_OPTION:
            # Already prepared/decided/cancelled -- the existing grammar handles this
            # state correctly (idempotent replay, already-decided, etc.); don't shortcut it.
            return planner_conversation.handle_reply(
                port, convo, actor_id, str(recommended["number"]), channel=channel, message_id=message_id,
            )
        before = recommended["preview"][0]["before"]
        after = recommended["preview"][0]["after"]
        # Side effect only (selects the option, computes the real proposal via governance);
        # we render our own short confirmation below instead of its default long preview.
        planner_conversation.handle_reply(
            port, convo, actor_id, str(recommended["number"]), channel=channel, message_id=message_id,
        )
        return [{
            "text": (f"Proposal ready: {recommended['title']}. Delivery moves from {_short(before.get('projected_delivery'))} "
                     f"to {_short(after.get('projected_delivery'))}. Nothing has changed yet -- reply APPROVE to make this "
                     f"the current plan, or REJECT."),
            "caption": f"Awaiting authorized approval · proposal {recommended['proposal_id']}",
        }]

    return None  # not a recognized demo intent -- fall through to the existing path
