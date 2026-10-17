"""Photon messaging bridge for Cleared for Takeoff.

Polls the Photon Platform (Beta) for new inbound iMessage text messages,
answers each one using the existing regulatory agent logic unchanged
(agent.answer_question), and replies in the same conversation.

This file never touches extraction/retrieval/comparison logic -- it is a
thin adapter between Photon's messaging API and the agent that already
exists and is already tested.

Run:
    python photon_bridge.py

Stop:
    Ctrl+C. The poll cursor and the set of already-answered message ids are
    persisted to .photon_bridge_state.json, so restarting does not re-answer
    messages that were already handled.

Requires in .env: PHOTON_PROJECT_ID, PHOTON_API_KEY, and (for live use)
ANTHROPIC_API_KEY.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

load_dotenv()

import anthropic
from photon_api import Photon
from photon_api.rpc_generated import ListMessagesInput, MarkMessageReadInput, SendMessageInput

from agent import answer_question
from retrieval import load_regulations

STATE_PATH = Path(__file__).parent / ".photon_bridge_state.json"
POLL_INTERVAL_SECONDS = 3
# Bounds how many processed message ids are retained, so the dedupe set
# does not grow without limit over a long-running process.
MAX_TRACKED_IDS = 2000


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not set. Add it to .env before running the bridge.")
    return value


def build_photon_client() -> Photon:
    api_key = _required_env("PHOTON_API_KEY")
    return Photon(headers={"Authorization": f"Bearer {api_key}"})


def load_state(path: Path = STATE_PATH) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"cursor": None, "processed_ids": []}


def save_state(state: dict, path: Path = STATE_PATH) -> None:
    trimmed = dict(state)
    trimmed["processed_ids"] = list(state.get("processed_ids", []))[-MAX_TRACKED_IDS:]
    path.write_text(json.dumps(trimmed), encoding="utf-8")


def _unwrap(obj: Any) -> Any:
    """Unwrap a Pydantic RootModel (possibly nested) to the underlying value.

    The generated Photon client wraps list_messages items in nested
    RootModels (e.g. PlatformMessage -> Message -> the actual typed message),
    and some nested snapshot fields (space, sentBy, receivedBy) are wrapped
    one level deep too. This is a no-op for plain objects (including the
    SimpleNamespace fixtures used in tests), so it is safe to apply
    unconditionally.
    """
    while hasattr(obj, "root"):
        obj = obj.root
    return obj


def is_from_agent(message: Any) -> bool:
    """True if this message was sent by our own agent identity.

    `direction="received"` on the list query already excludes our own sent
    messages, but this is a second, explicit check against the message
    itself (sentBy.kind == "agent", per Photon's own example payloads) so
    the bridge never replies to itself even if the query filter is ever
    loosened.
    """
    sent_by = _unwrap(getattr(message, "sentBy", None))
    return bool(sent_by) and getattr(sent_by, "kind", None) == "agent"


def extract_text(message: Any) -> Optional[str]:
    """Return the plain text of an inbound message, or None if it carries no
    answerable text (attachment, reaction, read receipt, etc.).
    """
    content = getattr(message, "content", None)
    if content is None or getattr(content, "type", None) != "text":
        return None
    text = getattr(content, "text", None)
    return text.strip() if text else None


def _reply_identity(message: Any) -> Optional[str]:
    """The user id the reply should be sent *as* -- the project's own
    identity in this conversation. `receivedBy` is the documented field for
    this; `addressedTo` is used as a fallback since `receivedBy` is not
    guaranteed present on every message shape.
    """
    received_by = _unwrap(getattr(message, "receivedBy", None))
    if received_by is not None:
        return received_by.id
    addressed_to = _unwrap(getattr(message, "addressedTo", None))
    if addressed_to is not None:
        return addressed_to.id
    return None


def poll_once(
    client: Photon,
    project_id: str,
    regulations: list,
    anthropic_client: anthropic.Anthropic,
    state: dict,
) -> dict:
    """Fetch new inbound messages, answer each, reply, and return updated state.

    A failure handling any single message (API error, missing fields, a
    failed Claude call) is logged and that message is simply left out of
    `processed_ids` -- it is retried on the next call rather than lost.
    """
    query: dict[str, Any] = {"direction": "received", "platform": "imessage"}
    if state.get("cursor"):
        query["createdSince"] = state["cursor"]

    try:
        page = client.projects.list_messages(
            ListMessagesInput.model_validate({"path": {"id": project_id}, "query": query})
        )
    except Exception as exc:  # network/API failure -- retry next tick, nothing lost
        print(f"[photon_bridge] list_messages failed: {exc}", file=sys.stderr)
        return state

    messages = sorted((_unwrap(m) for m in page.items), key=lambda m: m.createdAt)

    processed_ids = set(state.get("processed_ids", []))
    latest_created_at = state.get("cursor")

    for message in messages:
        if message.id in processed_ids:
            continue  # already answered -- guards overlapping poll windows

        if is_from_agent(message):
            processed_ids.add(message.id)
            continue

        text = extract_text(message)
        if text is None:
            # Not a text question (attachment/reaction/etc.) -- nothing to
            # answer, but mark seen so we don't keep re-evaluating it.
            processed_ids.add(message.id)
            continue

        sender_id = _reply_identity(message)
        if sender_id is None:
            print(
                f"[photon_bridge] message {message.id} has neither receivedBy nor "
                "addressedTo -- cannot determine reply identity; leaving for retry.",
                file=sys.stderr,
            )
            continue

        try:
            answer = answer_question(anthropic_client, text, regulations)
        except Exception as exc:
            print(f"[photon_bridge] answer_question failed for {message.id}: {exc}", file=sys.stderr)
            continue  # leave unprocessed -- retried on next poll

        try:
            client.projects.send_message(
                SendMessageInput.model_validate(
                    {
                        "path": {"id": project_id},
                        "headers": {"idempotency-key": f"reply:{message.id}"},
                        "body": {
                            # Not all space kinds support threaded replies
                            # (iMessage's shared-line "direct" space rejects
                            # parentMessageId with "Replies are not
                            # supported for this Space" -- confirmed live).
                            # It's optional in the schema, so omit it.
                            "spaceId": _unwrap(message.space).id,
                            "senderId": sender_id,
                            "content": {"type": "text", "format": "plain", "text": answer},
                        },
                    }
                )
            )
        except Exception as exc:
            print(f"[photon_bridge] send_message failed for {message.id}: {exc}", file=sys.stderr)
            # Deliberately NOT marked processed. The idempotency key above
            # means a retried send for this same message id is safe even if
            # this attempt actually succeeded upstream before raising here.
            continue

        try:
            client.projects.mark_message_read(
                MarkMessageReadInput.model_validate(
                    {"path": {"id": project_id, "messageId": message.id}, "headers": {}}
                )
            )
        except Exception as exc:
            # Non-critical -- the reply already went out successfully.
            print(f"[photon_bridge] mark_message_read failed for {message.id}: {exc}", file=sys.stderr)

        processed_ids.add(message.id)
        if latest_created_at is None or message.createdAt > latest_created_at:
            latest_created_at = message.createdAt

    state["processed_ids"] = list(processed_ids)
    if latest_created_at:
        state["cursor"] = latest_created_at
    return state


def run() -> None:
    project_id = _required_env("PHOTON_PROJECT_ID")
    client = build_photon_client()
    anthropic_client = anthropic.Anthropic()
    regulations = load_regulations()

    state = load_state()
    print("Cleared for Takeoff -- Photon bridge running. Press Ctrl+C to stop.")

    running = True

    def _stop(*_args: Any) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    while running:
        try:
            state = poll_once(client, project_id, regulations, anthropic_client, state)
            save_state(state)
        except Exception as exc:
            # Catch-all so one unexpected error doesn't kill a long-running
            # process; already-sent replies are safe (idempotency key), and
            # anything not yet answered is simply retried on the next tick.
            print(f"[photon_bridge] unexpected error in poll loop: {exc}", file=sys.stderr)
        for _ in range(POLL_INTERVAL_SECONDS):
            if not running:
                break
            time.sleep(1)

    print("\n[photon_bridge] stopped; state saved.")


if __name__ == "__main__":
    run()
