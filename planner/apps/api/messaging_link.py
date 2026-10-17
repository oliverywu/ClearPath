"""In-process link between the planner and Anna's messaging/decision-agent modules.

The planner database stores chats, messages, inbound-message dedupe records and
conversation state (only proposal ids, never plan copies). Anna's
planner_conversation module drives the dialogue through `PlannerPort`, which is the
only way it can read or change planning state.
"""
import json
import os
import sys
import threading
from pathlib import Path

from .repository import identifier, encode, now
from .governance import DecisionRefused, evidence_status

ROOT = Path(__file__).resolve().parents[2]
MESSAGING_DIR = Path(os.getenv('MESSAGING_DIR', ROOT.parent / 'messaging')).resolve()
if str(MESSAGING_DIR) not in sys.path:
    sys.path.append(str(MESSAGING_DIR))

import planner_conversation  # noqa: E402  (Anna's module, planner-backed)


class ChatStore:
    def __init__(self, repo):
        self.repo = repo

    def seed(self, roles):
        with self.repo.transaction():
            for actor_id, role in roles.items():
                chat_id = role.get('chat_id')
                if not chat_id:
                    continue
                initial = role.get('initial') or role.get('name', '?')[:2].upper()
                self.repo.db.execute('INSERT OR IGNORE INTO chats(id,actor_id,name,role,initial,photon_space_id,created_at) VALUES(?,?,?,?,?,NULL,?)',
                                     (chat_id, actor_id, role.get('name', actor_id), role.get('display_role', role.get('role', '')), initial, now()))

    def chat(self, chat_id):
        row = self.repo.db.execute('SELECT * FROM chats WHERE id=?', (chat_id,)).fetchone()
        if not row:
            raise KeyError('Chat not found')
        return dict(row)

    def chats(self):
        return [dict(r) for r in self.repo.db.execute('SELECT * FROM chats ORDER BY rowid')]

    def chat_for_space(self, space_id, actor_id, roles):
        row = self.repo.db.execute('SELECT * FROM chats WHERE photon_space_id=?', (space_id,)).fetchone()
        if row:
            return dict(row)
        role = roles.get(actor_id or '', {})
        chat_id = role.get('chat_id')
        if chat_id and self.repo.db.execute('SELECT 1 FROM chats WHERE id=? AND photon_space_id IS NULL', (chat_id,)).fetchone():
            self.repo.db.execute('UPDATE chats SET photon_space_id=? WHERE id=?', (space_id, chat_id))
            return self.chat(chat_id)
        chat_id = 'photon-' + space_id
        self.repo.db.execute('INSERT OR IGNORE INTO chats VALUES(?,?,?,?,?,?,?)',
                             (chat_id, actor_id or 'unknown', role.get('name', 'Photon contact'), role.get('display_role', 'unverified'),
                              'PH', space_id, now()))
        return self.chat(chat_id)

    def add(self, chat_id, sender, payload):
        message = {'id': identifier('msg'), 'from': sender, 'sentAt': now(), **{k: v for k, v in payload.items() if v not in (None, [], '')}}
        self.repo.db.execute('INSERT INTO chat_messages VALUES(?,?,?,?,?,?)',
                             (message['id'], chat_id, sender, encode(message), 1 if sender == 'me' else 0, message['sentAt']))
        return message

    def messages(self, chat_id):
        return [json.loads(r[0]) for r in self.repo.db.execute('SELECT payload FROM chat_messages WHERE chat_id=? ORDER BY rowid', (chat_id,))]

    def mark_read(self, chat_id):
        self.repo.db.execute('UPDATE chat_messages SET read=1 WHERE chat_id=?', (chat_id,))

    def unread(self, chat_id):
        return self.repo.db.execute('SELECT COUNT(*) FROM chat_messages WHERE chat_id=? AND read=0', (chat_id,)).fetchone()[0]

    def inbound(self, external_id):
        row = self.repo.db.execute('SELECT * FROM inbound_messages WHERE external_id=?', (external_id,)).fetchone()
        return dict(row) if row else None

    def message(self, message_id):
        row = self.repo.db.execute('SELECT payload FROM chat_messages WHERE id=?', (message_id,)).fetchone()
        return json.loads(row[0]) if row else None

    # conversation state: proposal ids and delivery state only
    def save_conversation(self, convo):
        key = f"{convo['chat_id']}:{convo['event_id']}"
        stamp = now()
        prior = self.repo.db.execute('SELECT created_at FROM conversations WHERE key=?', (key,)).fetchone()
        self.repo.db.execute('INSERT OR REPLACE INTO conversations VALUES(?,?,?,?,?,?,?,?,?)',
                             (key, convo['chat_id'], convo['event_id'], convo['status'], convo.get('selected_option'),
                              convo.get('selected_proposal_id'), convo.get('approved_proposal_id'),
                              prior[0] if prior else stamp, stamp))

    def conversation(self, chat_id, event_id):
        row = self.repo.db.execute('SELECT * FROM conversations WHERE key=?', (f'{chat_id}:{event_id}',)).fetchone()
        return dict(row) if row else None

    def latest_conversation(self, chat_id):
        row = self.repo.db.execute('SELECT * FROM conversations WHERE chat_id=? ORDER BY updated_at DESC, rowid DESC LIMIT 1', (chat_id,)).fetchone()
        return dict(row) if row else None


class PlannerPort:
    """The narrow interface planner_conversation uses. Bound to one chat at a time."""

    def __init__(self, link):
        self.link, self.service, self.gov, self.store = link, link.service, link.service.governance, link.store

    def event(self, event_id):
        event = self.service.repo.event(event_id)
        countries = {j['iso_code']: j['name'] for j in self.service.repo.dataset()['jurisdictions']}
        return {**event, 'warning_id': 'wrn-' + event_id, 'evidence_status': evidence_status(event),
                'country_name': countries.get(event.get('jurisdiction'), event.get('jurisdiction'))}

    def options(self, event_id):
        views = [v for v in self.gov.option_views(event_id) if not v['stale']]
        for view in views:
            for row in view['preview']:
                try:
                    row['calendar_check'] = planner_conversation.anna_projection(row['after'])
                except Exception:
                    row['calendar_check'] = None
        return views

    def primary_shipment(self, event_id):
        current = self.gov.current_plan_id()
        event = self.service.repo.event(event_id)
        plan = self.service.repo.plan(current)
        return next((s for s in plan['shipments'] if s['country_code'] == event.get('jurisdiction')), None)

    def transitions(self, proposal_id):
        plan = self.service.repo.plan(proposal_id)
        parent = self.service.repo.plan(plan['parent_scenario_id'])
        try:
            return planner_conversation.risk_transitions(parent['shipments'], plan['shipments'], plan.get('trigger_event_id'))
        except ImportError:
            return []

    def role(self, actor_id):
        return self.gov.roles.get(actor_id or '')

    def decision(self, proposal_id):
        plan = self.service.repo.plan(proposal_id)
        return plan.get('approval')

    def save_conversation(self, convo):
        self.store.save_conversation(convo)

    def latest_conversation(self, chat_id):
        return self.store.latest_conversation(chat_id)

    def decide(self, action, proposal_id, **kwargs):
        plan = self.service.repo.plan(proposal_id)
        # The plan the person previewed is the proposal's parent: that is the version they expect.
        result = self.gov.decide(action, proposal_id, expected_current_plan_id=plan.get('parent_scenario_id'), **kwargs)
        if action == 'approve' and not result.get('replayed'):
            self.link.broadcast_approval(result)
        return result

    def answer_question(self, chat_id, text):
        return self.link.answer_question(text)


class MessagingLink:
    def __init__(self, service):
        self.service = service
        self.store = ChatStore(service.repo)
        self.port = PlannerPort(self)
        self._poller = None

    def seed(self):
        self.store.seed(self.service.governance.roles)

    def open_conversations(self, event_id):
        """Send the alert for this event to every chat that has not seen it yet."""
        if not self.service.governance.current_proposals(event_id):
            return 0
        sent = 0
        with self.service.repo.transaction():
            for chat in self.store.chats():
                if self.store.conversation(chat['id'], event_id):
                    continue
                for payload in planner_conversation.start_conversation(self.port, chat['id'], event_id):
                    self.store.add(chat['id'], 'max', payload)
                sent += 1
        return sent

    def receive(self, chat_id, text, *, actor_id=None, external_id=None, channel='web'):
        """Handle one inbound message exactly once per external id."""
        text = str(text or '').strip()
        if not text:
            raise ValueError('Message text is required')
        if len(text) > 2000:
            raise ValueError('Message text must be 2000 characters or fewer')
        chat = self.store.chat(chat_id)
        actor_id = actor_id or chat['actor_id']
        external_id = external_id or identifier(channel)
        key = f'{channel}:{external_id}'
        with self.service.repo.transaction():
            prior = self.store.inbound(key)
            if prior:
                return {'message': self.store.message(prior['message_id']),
                        'replies': [self.store.message(m) for m in json.loads(prior['reply_ids'])], 'replayed': True}
            message = self.store.add(chat_id, 'me', {'text': text})
            payloads = planner_conversation.handle_message(self.port, chat_id, actor_id, text, channel=channel, message_id=external_id)
            replies = [self.store.add(chat_id, 'max', payload) for payload in payloads]
            self.store.mark_read(chat_id)
            self.service.repo.db.execute('INSERT INTO inbound_messages VALUES(?,?,?,?,?)',
                                         (key, chat_id, message['id'], encode([r['id'] for r in replies]), now()))
        return {'message': message, 'replies': replies, 'replayed': False}

    def broadcast_approval(self, result):
        """Post-approval notification to every other chat (once per approval)."""
        event = self.port.event(result['eventId'])
        text = (f"Plan update: {result['actor']['name']} approved option {result['optionNumber']} for {event['title']}. "
                f"Current plan is now version {result['currentPlanVersion']}.")
        for chat in self.store.chats():
            if chat['actor_id'] == result['actor']['id']:
                continue
            convo = self.store.conversation(chat['id'], result['eventId'])
            if convo and convo['status'] in planner_conversation.PENDING_STATUSES:
                self.store.save_conversation({**convo, 'status': planner_conversation.STATUS_APPROVED,
                                              'approved_proposal_id': result['proposalId']})
            self.store.add(chat['id'], 'max', {'text': text, 'caption': 'Post-approval notification',
                                               'links': [{'label': 'View the plan', 'href': f"#/warnings/{event['warning_id']}"}]})

    def answer_question(self, text):
        """Free-text questions: Anna's cited regulation agent when configured, else the
        planner's deterministic grounded assistant over the current plan."""
        anna = self._anna_answer(text)
        if anna:
            return {'text': anna, 'caption': 'Answered from cited regulation passages'}
        current = self.service.governance.current_plan_id()
        plan = self.service.repo.plan(current)
        answer = self.service.assistant.answer(text, plan, self.service.repo.plan_dataset(current), None)
        return {'text': answer['answer'], 'caption': f"Grounded planner answer · {answer.get('provider', 'local')}"}

    @staticmethod
    def _anna_answer(text):
        if not os.getenv('ANTHROPIC_API_KEY'):
            return None
        try:
            import anthropic
            from agent import answer_question
            from retrieval import load_regulations
            return answer_question(anthropic.Anthropic(), text, load_regulations(), concise=True)
        except Exception:
            return None

    # --- optional inbound Photon bridge (Anna's photon_bridge polling loop) ---------------
    def photon_handler(self, space_id, actor_id, text, message_id):
        with self.service.repo.transaction():
            chat = self.store.chat_for_space(space_id, actor_id, self.service.governance.roles)
        result = self.receive(chat['id'], text, actor_id=actor_id, external_id=message_id, channel='photon')
        return '\n\n'.join(r.get('text') or r.get('card', {}).get('title', '') for r in result['replies'] if r.get('text') or r.get('card'))

    def start_photon_bridge(self, state_path):
        if os.getenv('PHOTON_BRIDGE_ENABLED', 'false').lower() != 'true':
            return False
        import photon_bridge
        if photon_bridge.Photon is None:
            raise RuntimeError('PHOTON_BRIDGE_ENABLED=true but the photonhq-api package is not installed (pip install -r messaging/requirements.txt)')
        client, project_id = photon_bridge.build_photon_client(), photon_bridge._required_env('PHOTON_PROJECT_ID')
        stop = threading.Event()

        def loop():
            state = photon_bridge.load_state(Path(state_path))
            while not stop.is_set():
                state = photon_bridge.poll_once(client, project_id, [], None, state, handler=self.photon_handler,
                                                lock_path=Path(state_path).with_suffix('.lock'))
                photon_bridge.save_state(state, Path(state_path))
                stop.wait(photon_bridge.POLL_INTERVAL_SECONDS)
        self._poller = (threading.Thread(target=loop, name='photon-bridge', daemon=True), stop)
        self._poller[0].start()
        return True

    def stop(self):
        if self._poller:
            self._poller[1].set()
