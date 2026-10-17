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

try:  # POSIX advisory lock; Windows falls back to an in-process lock (see poll_once).
    import fcntl
except ImportError:  # pragma: no cover - exercised on Windows only
    fcntl = None

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # python-dotenv is optional for the integrated app
    pass

# The Photon and Anthropic SDKs are optional in the integrated application: the
# unified planner API imports this module only for the inbound bridge, and only when
# Photon credentials are configured. The standalone bridge still requires both.
try:
    import anthropic
except ImportError:  # pragma: no cover
    anthropic = None
try:
    from photon_api import Photon
    from photon_api.rpc_generated import ListMessagesInput, MarkMessageReadInput, SendMessageInput
except ImportError:  # pragma: no cover
    Photon = ListMessagesInput = MarkMessageReadInput = SendMessageInput = None

import decision_agent

try:
    from agent import answer_question
except ImportError:  # pragma: no cover - agent.py needs the anthropic SDK
    answer_question = None
from retrieval import load_regulations
import threading

_THREAD_LOCK = threading.Lock()

STATE_PATH = Path(__file__).parent / ".photon_bridge_state.json"
QA_STATE_PATH = Path(__file__).parent / ".qa_context_state.json"
LOCK_PATH = Path(__file__).parent / ".photon_bridge.lock"
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


def _actor_id(message: Any) -> Optional[str]:
    """The Photon user id of the human who SENT this inbound message --
    used only for decision-approval authorization (decision_agent). This is
    distinct from `_reply_identity`, which is the identity our *own* reply
    should be sent as.
    """
    sent_by = _unwrap(getattr(message, "sentBy", None))
    return getattr(sent_by, "id", None) if sent_by is not None else None


def _load_qa_context(path: Path = QA_STATE_PATH) -> dict:
    """Per-space cache of the last free-text regulatory question asked, so a
    later DETAILS/SOURCE reply can return the fuller cited answer without
    the user having to repeat their question.
    """
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _save_qa_context(context: dict, path: Path = QA_STATE_PATH) -> None:
    path.write_text(json.dumps(context), encoding="utf-8")


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


def send_text_message(
    client: Photon,
    project_id: str,
    space_id: str,
    sender_id: str,
    text: str,
    idempotency_key: Optional[str] = None,
) -> Any:
    """Send a plain-text message into an existing Photon space.

    Thin wrapper around the exact SendMessageInput construction poll_once
    already used for replies, pulled out so other modules (e.g.
    notification_manager) can send outbound Photon messages without
    duplicating it.
    """
    headers = {"idempotency-key": idempotency_key} if idempotency_key else {}
    return client.projects.send_message(
        SendMessageInput.model_validate(
            {
                "path": {"id": project_id},
                "headers": headers,
                "body": {
                    "spaceId": space_id,
                    "senderId": sender_id,
                    "content": {"type": "text", "format": "plain", "text": text},
                },
            }
        )
    )


def poll_once(
    client: Photon,
    project_id: str,
    regulations: list,
    anthropic_client: anthropic.Anthropic,
    state: dict,
    *,
    conversation_state_path: Path = decision_agent.CONVERSATION_STATE_PATH,
    audit_log_path: Path = decision_agent.AUDIT_LOG_PATH,
    qa_state_path: Path = QA_STATE_PATH,
    roles: Optional[dict] = None,
    lock_path: Path = LOCK_PATH,
    handler: Optional[Any] = None,
) -> dict:
    """Acquire an exclusive, non-blocking lock around one poll cycle.

    Two overlapping poll_once calls (e.g. the standalone bridge process and
    a second one started by mistake, both against the same Photon project)
    would otherwise each load the same on-disk `processed_ids` before
    either had replied, and both answer the same inbound message -- this
    previously produced duplicate outbound replies to a single text
    (observed live: one inbound message answered 4 times within ~1.2s,
    far faster than POLL_INTERVAL_SECONDS allows from a single process).
    If the lock is already held, this poll is skipped entirely and `state`
    is returned unchanged -- safe, since the message is simply retried by
    whichever instance currently holds the lock.
    """
    if fcntl is None:  # Windows: serialize polls within this process
        if not _THREAD_LOCK.acquire(blocking=False):
            return state
        try:
            return _poll_once_locked(client, project_id, regulations, anthropic_client, state,
                                     conversation_state_path=conversation_state_path, audit_log_path=audit_log_path,
                                     qa_state_path=qa_state_path, roles=roles, handler=handler)
        finally:
            _THREAD_LOCK.release()
    lock_file = open(lock_path, "a+")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print(
            "[photon_bridge] poll skipped: another poll_once is already in "
            "progress (lock held) -- avoids double-answering the same inbound message.",
            file=sys.stderr,
        )
        lock_file.close()
        return state
    try:
        return _poll_once_locked(
            client,
            project_id,
            regulations,
            anthropic_client,
            state,
            conversation_state_path=conversation_state_path,
            audit_log_path=audit_log_path,
            qa_state_path=qa_state_path,
            roles=roles,
            handler=handler,
        )
    finally:
        fcntl.flock(lock_file, fcntl.LOCK_UN)
        lock_file.close()


def _poll_once_locked(
    client: Photon,
    project_id: str,
    regulations: list,
    anthropic_client: anthropic.Anthropic,
    state: dict,
    *,
    conversation_state_path: Path = decision_agent.CONVERSATION_STATE_PATH,
    audit_log_path: Path = decision_agent.AUDIT_LOG_PATH,
    qa_state_path: Path = QA_STATE_PATH,
    roles: Optional[dict] = None,
    handler: Optional[Any] = None,
) -> dict:
    """Fetch new inbound messages, answer each, reply, and return updated state.

    When `handler` is given (the integrated application), every human text message
    is passed to `handler(space_id, actor_id, text, message_id)` instead of the local
    decision_agent / Q&A routing below; the handler returns the reply text. The
    planner-backed handler dedupes on the Photon message id itself, so a replayed
    message never repeats a decision.

    Each human text message is routed one of two ways:
      - If its space has an active (pending) decision conversation, the
        reply is handled by decision_agent.handle_reply -- 1/2/3, DETAILS,
        SOURCE, CANCEL, APPROVE.
      - Otherwise it's treated as a free-text regulatory question and
        answered concisely via agent.answer_question(concise=True), with
        DETAILS/SOURCE replaying the fuller cited answer for the last
        question asked in that space.

    A failure handling any single message (API error, missing fields, a
    failed Claude call) is logged and that message is simply left out of
    `processed_ids` -- it is retried on the next call rather than lost.

    Called only from poll_once, which holds the cross-process lock for the
    duration of this call.
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
    print(f"[photon_bridge] list_messages returned {len(messages)} message(s)", file=sys.stderr)

    processed_ids = set(state.get("processed_ids", []))
    latest_created_at = state.get("cursor")

    for message in messages:
        if message.id in processed_ids:
            print(f"[photon_bridge] {message.id}: skip (already processed)", file=sys.stderr)
            continue  # already answered -- guards overlapping poll windows

        if is_from_agent(message):
            print(f"[photon_bridge] {message.id}: skip (sent by agent)", file=sys.stderr)
            processed_ids.add(message.id)
            continue

        text = extract_text(message)
        if text is None:
            # Not a text question (attachment/reaction/etc.) -- nothing to
            # answer, but mark seen so we don't keep re-evaluating it.
            print(f"[photon_bridge] {message.id}: skip (no answerable text content)", file=sys.stderr)
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

        space_id = _unwrap(message.space).id
        actor_id = _actor_id(message)

        try:
            if handler is not None:
                answer = handler(space_id, actor_id, text, message.id)
            # Route to decision_agent only when BOTH a conversation exists
            # for this space (any status -- including already resolved, so
            # a duplicate APPROVE or a DETAILS follow-up still reaches
            # handle_reply's idempotent handling instead of silently
            # falling through to Q&A) AND the reply text actually looks
            # like decision-flow grammar, so an ordinary regulatory
            # question asked later in the same space still falls through.
            active = None if handler is not None else decision_agent.find_conversation_for_space(space_id, state_path=conversation_state_path)
            if handler is not None:
                pass
            elif active is not None and decision_agent.is_decision_reply(text):
                active_event_id, _convo = active
                print(f"[photon_bridge] {message.id}: routed to decision_agent (event={active_event_id})", file=sys.stderr)
                answer = decision_agent.handle_reply(
                    space_id,
                    active_event_id,
                    actor_id,
                    text,
                    state_path=conversation_state_path,
                    audit_path=audit_log_path,
                    roles=roles,
                )
            else:
                print(f"[photon_bridge] {message.id}: routed to Q&A", file=sys.stderr)
                normalized = text.strip().upper()
                qa_context = _load_qa_context(qa_state_path)
                prior = qa_context.get(space_id)
                if normalized in ("DETAILS", "SOURCE") and prior:
                    answer = answer_question(
                        anthropic_client,
                        prior["question"],
                        regulations,
                        jurisdiction=prior.get("jurisdiction"),
                        concise=False,
                    )
                else:
                    answer = answer_question(anthropic_client, text, regulations, concise=True)
                    qa_context[space_id] = {"question": text, "jurisdiction": None}
                    _save_qa_context(qa_context, qa_state_path)
        except Exception as exc:
            print(f"[photon_bridge] reply handling failed for {message.id}: {exc}", file=sys.stderr)
            continue  # leave unprocessed -- retried on next poll

        try:
            # Not all space kinds support threaded replies (iMessage's
            # shared-line "direct" space rejects parentMessageId with
            # "Replies are not supported for this Space" -- confirmed live).
            # It's optional in the schema, so omit it.
            send_text_message(
                client,
                project_id,
                space_id=space_id,
                sender_id=sender_id,
                text=answer,
                idempotency_key=f"reply:{message.id}",
            )
            print(f"[photon_bridge] {message.id}: reply sent", file=sys.stderr)
        except Exception as exc:
            print(f"[photon_bridge] send_message failed for {message.id}: {exc}", file=sys.stderr)
            # Deliberately NOT marked processed. The idempotency key above
            # means a retried send for this same message id is safe even if
            # this attempt actually succeeded upstream before raising here.
            continue

        try:
            # headers.idempotency-key is required by the installed SDK
            # (MarkMessageReadHeader), same as SendMessageHeader above --
            # derived from the message id so a retried mark-read for the
            # same message is always safe to repeat.
            client.projects.mark_message_read(
                MarkMessageReadInput.model_validate(
                    {
                        "path": {"id": project_id, "messageId": message.id},
                        "headers": {"idempotency-key": f"mark-read:{message.id}"},
                    }
                )
            )
            print(f"[photon_bridge] {message.id}: marked read", file=sys.stderr)
        except Exception as exc:
            # Non-critical -- the reply already went out successfully.
            print(f"[photon_bridge] mark_message_read failed for {message.id}: {exc}", file=sys.stderr)

        processed_ids.add(message.id)
        if latest_created_at is None or message.createdAt > latest_created_at:
            latest_created_at = message.createdAt

    state["processed_ids"] = list(processed_ids)
    if latest_created_at:
        state["cursor"] = latest_created_at
    print(
        f"[photon_bridge] poll complete: cursor={state.get('cursor')!r} "
        f"tracked_ids={len(state['processed_ids'])}",
        file=sys.stderr,
    )
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
