"""The integrated application service behind the single /api surface.

Composes the canonical planner (Service), the governed decision service
(Governance), Anna's planner-backed messaging (MessagingLink) and the frontend
adapter layer (Frontend). The browser never learns which subsystem answered.
"""
import os

from .service import Service, APIError, now
from .governance import Governance, DecisionRefused, load_roles
from .messaging_link import MessagingLink
from .frontend import Frontend
from .schemas import check, ContractError

LEGACY_DECISION_MESSAGE = ('Direct scenario approval is disabled in the integrated application. '
                           'Use POST /api/proposals/{id}/approve or reply APPROVE to Max, which apply authorization, '
                           'stale-plan and idempotency checks.')


class IntegratedService(Service):
    def __init__(self, db_path, fixture=None, roles_path=None):
        # Collaborators must exist before Service.__init__, which may call reset().
        self._roles_path = roles_path
        self._ready = False
        super().__init__(db_path, fixture)
        self._wire()
        self.messaging.seed()
        self.governance.analyze_open_events(actor='startup impact analysis')
        for event in self.repo.events():
            self.messaging.open_conversations(event['id'])
        self._ready = True

    def _wire(self):
        if getattr(self, 'governance', None) is None:
            self.governance = Governance(self, load_roles(self._roles_path))
            self.messaging = MessagingLink(self)
            self.frontend = Frontend(self)

    def reset(self, dataset):
        self._wire()
        result = super().reset(dataset)
        # A reset starts a fresh synthetic baseline. Conversations and chat history refer to
        # the old events, so they are cleared; audit history and old scenarios are kept.
        with self.repo.transaction():
            for table in ('conversations', 'chat_messages', 'inbound_messages'):
                self.repo.db.execute(f'DELETE FROM {table}')
            self.repo.audit('integration.reset', dataset.get('id'), payload={'cleared': ['conversations', 'chat_messages', 'inbound_messages']})
        if getattr(self, '_ready', False):
            self.messaging.seed()
            self.governance.analyze_open_events(actor='reset impact analysis')
            for event in self.repo.events():
                self.messaging.open_conversations(event['id'])
        return result

    def ingest_event(self, body):
        """Introduce a regulatory or logistics disruption: store it, calculate its impact as
        immutable proposals (the current plan is unchanged) and alert every chat."""
        body = dict(body)
        body.setdefault('detected_at', now())
        event = super().dispatch('POST', '/api/change-events', {}, body)
        proposals = self.governance.analyze_event(event['id'], actor='impact analyzer')
        self.messaging.open_conversations(event['id'])
        warning = self.frontend.warning(self.repo.event(event['id']))
        return {**warning, 'proposalIds': [p['proposal_id'] for p in proposals]}

    def dispatch(self, method, path, query, body):
        parts = path.strip('/').split('/')
        if method == 'POST' and len(parts) == 4 and parts[1] == 'scenarios' and parts[3] in ('approve', 'reject'):
            raise APIError(LEGACY_DECISION_MESSAGE, 410)
        if method == 'POST' and path == '/api/change-events':
            return self.ingest_event(body)
        if method == 'GET' and path == '/api/health':
            return {**super().dispatch(method, path, query, body), 'integrated': True,
                    'current_plan_id': self.governance.current_plan_id(), 'schema_version': self.repo.schema_version()}
        try:
            routed = self.frontend.handle(method, path, query, body)
        except DecisionRefused as exc:
            raise APIError(str(exc), exc.status, {'code': exc.code, **exc.details}) from exc
        if routed is not None:
            schema, payload = routed
            try:
                return check(f'{method} {path}', payload, schema)
            except ContractError as exc:
                raise APIError(str(exc), 500, {'code': 'contract_violation', 'errors': exc.errors[:20]}) from exc
        return super().dispatch(method, path, query, body)

    def start_background(self, state_dir):
        return self.messaging.start_photon_bridge(os.path.join(state_dir, 'photon_bridge_state.json'))

    def stop_background(self):
        self.messaging.stop()
