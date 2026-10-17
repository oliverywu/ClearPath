"""Proposals, the current-plan pointer and the only approval path that can move it.

Vocabulary used across the integrated application:
  * plan / scenario  - an immutable planner result (SQLite `scenarios`, never updated).
  * current plan     - the scenario named by settings.approved_scenario_id.
  * proposal         - a scenario generated from the current plan for one disruption
                       event and one remediation option (`proposal_options` row).

Lifecycles are kept separate on purpose:
  * Plan status:     proposed | approved | rejected | superseded
  * Warning status:  open | in_review | resolved            (see frontend.py)
  * Evidence status: needs_review | verified | retired | synthetic
"""
import json
from pathlib import Path

from packages.planner.engine import compare_plans
from .repository import identifier, encode, now

ROOT = Path(__file__).resolve().parents[2]
ROLES_PATH = ROOT / 'data/demo/authorized_roles.json'
ACCEPT_OPTION = {'id': 'accept', 'action': 'accept_delay', 'title': 'Accept the delay (no mitigation)',
                 'description': 'Keep the current routes and labels and absorb the disruption.',
                 'tradeoffs': 'No added cost; the schedule impact shown is taken as-is.'}


class DecisionRefused(Exception):
    """A governed decision was refused. Carries an HTTP status and a stable code."""

    def __init__(self, message, status, code, details=None):
        super().__init__(message)
        self.status, self.code, self.details = status, code, details or {}


def load_roles(path=None):
    path = Path(path or ROLES_PATH)
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def event_options(event):
    """Remediation options in the order they are numbered for people (1, 2, 3...)."""
    return [*event.get('repair_options', []), ACCEPT_OPTION]


def evidence_status(record):
    """Map planner/regulatory review states onto the four evidence lifecycle values."""
    status = record.get('review_status')
    if record.get('synthetic') or status == 'synthetic' or record.get('source_tier') in ('modeled', 'synthetic'):
        return 'synthetic'
    if status in ('verified', 'confirmed'):
        return 'verified'
    if status == 'retired':
        return 'retired'
    return 'needs_review'


class Governance:
    def __init__(self, service, roles=None):
        self.service = service
        self.repo = service.repo
        self.roles = roles if roles is not None else load_roles()

    # --- pointer & lifecycle -------------------------------------------------
    def current_plan_id(self):
        return self.repo.setting('approved_scenario_id')

    def current_plan_version(self):
        return self.repo.db.execute("SELECT COUNT(*) FROM decisions WHERE status='approved'").fetchone()[0]

    def plan_status(self, plan, current_id=None):
        current_id = current_id or self.current_plan_id()
        if plan['status'] == 'approved':
            return 'approved' if plan['id'] == current_id else 'superseded'
        if plan['status'] == 'proposed' and plan.get('parent_scenario_id') != current_id:
            return 'superseded'
        return plan['status']

    def is_stale(self, plan, current_id=None):
        return plan['status'] == 'proposed' and plan.get('parent_scenario_id') != (current_id or self.current_plan_id())

    # --- proposals -------------------------------------------------------------
    def proposal_rows(self, event_id=None, parent_id=None):
        sql, args = 'SELECT * FROM proposal_options', []
        clauses = []
        if event_id:
            clauses.append('event_id=?'); args.append(event_id)
        if parent_id:
            clauses.append('parent_id=?'); args.append(parent_id)
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        return [dict(r) for r in self.repo.db.execute(sql + ' ORDER BY rowid', args)]

    def proposal_meta(self, proposal_id):
        row = self.repo.db.execute('SELECT * FROM proposal_options WHERE proposal_id=?', (proposal_id,)).fetchone()
        return dict(row) if row else None

    def current_proposals(self, event_id):
        """Proposals for this event calculated from the current plan, by option number."""
        rows = self.proposal_rows(event_id, self.current_plan_id())
        return sorted(rows, key=lambda r: r['option_number'])

    def event_resolved(self, event_id):
        current = self.current_plan_id()
        return bool(current) and event_id in self.repo.plan(current).get('applied_event_ids', [])

    def analyzable(self, event):
        return not (event.get('event_type') == 'source_snapshot' and not event.get('changes'))

    def analyze_event(self, event_id, actor='impact analyzer'):
        """Create one immutable proposal per remediation option from the current plan.

        Idempotent: if proposals already exist for this event and this parent plan, they
        are returned unchanged. The current plan itself is never modified here.
        """
        event = self.repo.event(event_id)
        current_id = self.current_plan_id()
        if not current_id or not self.analyzable(event) or self.event_resolved(event_id):
            return []
        existing = self.current_proposals(event_id)
        if existing:
            return existing
        parent = self.repo.plan(current_id)
        dataset = self.repo.dataset()
        rows = []
        with self.repo.transaction():
            for number, option in enumerate(event_options(event), 1):
                repair = option['id'] if option is not ACCEPT_OPTION else None
                plan = self.service.generate(dataset, parent=parent, event=event, repair=repair)
                row = {'proposal_id': plan['id'], 'event_id': event_id, 'option_key': option['id'],
                       'option_number': number, 'parent_id': current_id, 'created_at': now()}
                self.repo.db.execute('INSERT INTO proposal_options VALUES(:proposal_id,:event_id,:option_key,:option_number,:parent_id,:created_at)', row)
                rows.append(row)
            self.repo.audit('proposal.created', event_id, actor, {
                'parent_plan_id': current_id, 'proposal_ids': [r['proposal_id'] for r in rows],
                'options': [r['option_key'] for r in rows], 'current_plan_unchanged': True})
        return rows

    def analyze_open_events(self, actor='impact analyzer'):
        created = []
        for event in self.repo.events():
            created.extend(self.analyze_event(event['id'], actor))
        return created

    def proposal_set(self, event_id):
        """The option set to show for an event: current-plan proposals if any, else the
        set that produced the approved plan, else the most recent set."""
        rows = self.proposal_rows(event_id)
        if not rows:
            return []
        groups = {}
        for row in rows:
            groups.setdefault(row['parent_id'], []).append(row)
        current = self.current_plan_id()
        if current in groups:
            chosen = groups[current]
        else:
            approved = [g for g in groups.values() if any(self.repo.plan(r['proposal_id'])['status'] == 'approved' for r in g)]
            chosen = approved[-1] if approved else list(groups.values())[-1]
        return sorted(chosen, key=lambda r: r['option_number'])

    @staticmethod
    def _shipment_view(shipment):
        keys = ('id', 'country_code', 'country_name', 'projected_delivery', 'target_delivery', 'slack_days', 'risk_band',
                'route_id', 'route_name', 'label_group_id', 'ship_by', 'delivery_range', 'worst_case_slack_days', 'milestones')
        return {k: shipment.get(k) for k in keys}

    def option_views(self, event_id):
        """Canonical (snake_case) option views with before/after rows for affected shipments."""
        event = self.repo.event(event_id)
        rows = self.proposal_set(event_id)
        if not rows:
            return []
        options = {o['id']: o for o in event_options(event)}
        current = self.current_plan_id()
        plans = {r['proposal_id']: self.repo.plan(r['proposal_id']) for r in rows}
        parent = self.repo.plan(rows[0]['parent_id'])
        before = {s['id']: s for s in parent['shipments']}
        accept = next((plans[r['proposal_id']] for r in rows if r['option_key'] == 'accept'), plans[rows[-1]['proposal_id']])
        affected = [s['id'] for s in accept['shipments'] if before.get(s['id'], {}).get('projected_delivery') != s['projected_delivery']
                    or before.get(s['id'], {}).get('risk_band') != s['risk_band']]
        primary = next((s['id'] for s in parent['shipments'] if s['country_code'] == event.get('jurisdiction')), None)
        if primary:
            affected = [primary] + [a for a in affected if a != primary]
        views = []
        for row in rows:
            plan = plans[row['proposal_id']]
            after = {s['id']: s for s in plan['shipments']}
            option = options.get(row['option_key'], ACCEPT_OPTION)
            preview = [{'shipment_id': sid, 'country_name': after[sid]['country_name'],
                        'before': self._shipment_view(before[sid]), 'after': self._shipment_view(after[sid])}
                       for sid in affected if sid in after and sid in before]
            views.append({'number': row['option_number'], 'key': row['option_key'], 'title': option['title'],
                          'description': option.get('description'), 'tradeoffs': option.get('tradeoffs'),
                          'proposal_id': plan['id'], 'parent_id': row['parent_id'], 'status': self.plan_status(plan, current),
                          'stale': self.is_stale(plan, current), 'created_at': row['created_at'],
                          'cost_delta': plan['metrics']['cost_proxy'] - parent['metrics']['cost_proxy'], 'preview': preview})
        # Recommendation: maximize the worst affected slack, then minimize added cost.
        def score(view):
            slacks = [p['after']['slack_days'] for p in view['preview']] or [0]
            return (min(slacks), -view['cost_delta'], -view['number'])
        best = max(views, key=score)
        for view in views:
            view['recommended'] = view is best
            # Feasible: every affected shipment still meets its target and is not blocked.
            view['feasible'] = all(p['after']['slack_days'] >= 0 and p['after']['risk_band'] != 'blocked' for p in view['preview'])
        return views

    def comparison(self, proposal_id):
        plan = self.repo.plan(proposal_id)
        parent_id = plan.get('parent_scenario_id')
        if not parent_id:
            return None
        return compare_plans(self.repo.plan(parent_id), plan)

    # --- decisions -------------------------------------------------------------
    def authorize(self, actor_id, actor_role):
        role = self.roles.get(actor_id or '')
        if not role or not role.get('can_approve'):
            return None, 'Only an authorized supply lead can approve or reject plan changes.'
        if actor_role and actor_role != role.get('role'):
            return None, 'The stated actor role does not match the registered role for this actor.'
        return role, None

    def _refuse(self, proposal_id, action, actor_id, channel, refusal):
        # Refusals are audited in their own committed transaction before raising.
        with self.repo.transaction():
            self.repo.audit(f'proposal.{action}_refused', proposal_id, actor_id or 'unknown actor',
                            {'code': refusal.code, 'reason': str(refusal), 'channel': channel, **refusal.details})
        raise refusal

    def decide(self, action, proposal_id, *, actor_id, actor_role, rationale, channel, idempotency_key,
               expected_current_plan_id=None):
        """Atomically approve or reject a proposal. The only code path that moves the pointer.

        Steps, all under the repository lock and in one transaction:
          1. idempotency replay  2. proposal exists and is pending  3. calculated from the
          expected current plan  4. actor authorized  5. evidence reviewed  6. record the
          decision  7. move the current-plan pointer exactly once (approve only)
          8. write audit with before/after plan ids  9. store the idempotent result.
        """
        if action not in ('approve', 'reject'):
            raise ValueError('Unknown decision action')
        missing = [name for name, value in (('proposalId', proposal_id), ('actorId', actor_id), ('channel', channel),
                                            ('idempotencyKey', idempotency_key), ('rationale', rationale)) if not str(value or '').strip()]
        if action == 'approve' and not expected_current_plan_id:
            missing.append('expectedCurrentPlanId')
        if missing:
            raise DecisionRefused('Missing required decision fields: ' + ', '.join(missing), 400, 'missing_fields')
        status_word = 'approved' if action == 'approve' else 'rejected'
        refusal = None
        with self.repo.transaction():
            prior = self.repo.db.execute('SELECT * FROM decision_requests WHERE idempotency_key=?', (idempotency_key,)).fetchone()
            if prior:
                if prior['proposal_id'] != proposal_id or prior['action'] != action or prior['actor_id'] != actor_id:
                    raise DecisionRefused('Idempotency key was already used for a different decision.', 409, 'idempotency_conflict')
                return {**json.loads(prior['result']), 'replayed': True}
            meta = self.proposal_meta(proposal_id)
            try:
                plan = self.repo.plan(proposal_id)
            except KeyError:
                raise DecisionRefused('Proposal not found.', 404, 'not_found')
            current_id = self.current_plan_id()
            if meta is None:
                refusal = DecisionRefused('Only planner proposals can be decided through this service.', 409, 'not_a_proposal')
            elif plan['status'] != 'proposed':
                refusal = DecisionRefused(f'This proposal was already {plan["status"]}; nothing changed.', 409, 'already_decided',
                                          {'decision': plan.get('approval')})
            elif action == 'approve' and expected_current_plan_id != current_id:
                refusal = DecisionRefused('The current plan changed since this decision was prepared. Refresh and review again.', 409,
                                          'stale_expected_plan', {'expected_current_plan_id': expected_current_plan_id, 'current_plan_id': current_id})
            elif action == 'approve' and plan.get('parent_scenario_id') != current_id:
                refusal = DecisionRefused('This proposal was calculated from an older plan and is superseded.', 409, 'stale_proposal',
                                          {'parent_plan_id': plan.get('parent_scenario_id'), 'current_plan_id': current_id})
            elif action == 'approve' and plan.get('input_dataset_id') != self.repo.setting('dataset_id'):
                refusal = DecisionRefused('Planning inputs changed after this proposal; a fresh proposal is required.', 409, 'stale_dataset')
            if refusal is None:
                role, reason = self.authorize(actor_id, actor_role)
                if role is None:
                    refusal = DecisionRefused(reason, 403, 'unauthorized', {'actor_role': actor_role})
            if refusal is None and action == 'approve':
                event = self.repo.event(meta['event_id'])
                if evidence_status(event) in ('needs_review', 'retired'):
                    refusal = DecisionRefused('The evidence behind this disruption has not been verified; verify or retire it before approving.',
                                              422, 'unverified_evidence', {'event_id': event['id'], 'evidence_status': evidence_status(event)})
            if refusal is None:
                before = current_id
                note = f'{rationale} [channel={channel}; role={role["role"]}; actor_id={actor_id}]'
                self.repo.decide(proposal_id, status_word, role.get('name', actor_id), note)
                after = proposal_id if action == 'approve' else current_id
                if action == 'approve' and self.current_plan_id() != proposal_id:
                    raise RuntimeError('Current-plan pointer did not move to the approved proposal')
                version = self.current_plan_version()
                result = {'proposalId': proposal_id, 'status': status_word, 'beforePlanId': before, 'afterPlanId': after,
                          'currentPlanId': self.current_plan_id(), 'currentPlanVersion': version, 'eventId': meta['event_id'],
                          'optionKey': meta['option_key'], 'optionNumber': meta['option_number'],
                          'actor': {'id': actor_id, 'name': role.get('name'), 'role': role.get('role')},
                          'channel': channel, 'decidedAt': now(), 'replayed': False}
                self.repo.audit('current_plan.changed' if action == 'approve' else 'proposal.rejected', proposal_id, role.get('name', actor_id), {
                    'before_plan_id': before, 'after_plan_id': after, 'version': version, 'event_id': meta['event_id'],
                    'option': meta['option_key'], 'actor_id': actor_id, 'actor_role': role.get('role'), 'channel': channel,
                    'rationale': rationale, 'idempotency_key': idempotency_key})
                self.repo.db.execute('INSERT INTO decision_requests VALUES(?,?,?,?,?,?)',
                                     (idempotency_key, proposal_id, action, actor_id, encode(result), now()))
        if refusal is not None:
            self._refuse(proposal_id, action, actor_id, channel, refusal)
        if action == 'approve':
            self.after_approval(result)
        return result

    def after_approval(self, result):
        """Rebase unresolved disruptions on the new current plan and send one notification."""
        self.analyze_open_events(actor='rebase after approval')
        self.notify_once('approved:' + result['proposalId'], {
            'id': 'approved:' + result['proposalId'], 'title': 'Plan change approved',
            'scenario_id': result['proposalId'], 'cause': f"{result['actor']['name']} approved option {result['optionNumber']} for {result['eventId']}",
            'consequence': f"Current plan is now version {result['currentPlanVersion']} ({result['currentPlanId']}).",
            'review_status': 'approved', 'deep_link': '/#/warnings/wrn-' + result['eventId']})

    def notify_once(self, key, alert):
        with self.repo.transaction():
            if self.repo.db.execute('SELECT 1 FROM notifications WHERE key=?', (key,)).fetchone():
                return None
            delivery = self.service.notifications.send(alert)
            self.repo.db.execute('INSERT INTO notifications VALUES(?,?,?,?)', (key, encode(alert), encode(delivery), now()))
            self.repo.audit('notification.result', alert.get('scenario_id'), payload={'key': key, **delivery})
        return delivery

    def review_evidence(self, event_id, *, actor_id, status, note):
        if status not in ('verified', 'retired'):
            raise DecisionRefused('Evidence review status must be verified or retired.', 400, 'bad_status')
        if not str(note or '').strip():
            raise DecisionRefused('A review note is required.', 400, 'missing_fields')
        role, reason = self.authorize(actor_id, None)
        if role is None:
            raise DecisionRefused(reason, 403, 'unauthorized')
        event = self.repo.event(event_id)
        if evidence_status(event) == 'synthetic' and status == 'verified':
            raise DecisionRefused('Synthetic events cannot be verified as real evidence.', 422, 'synthetic_evidence')
        with self.repo.transaction():
            event = {**event, 'review_status': status, 'reviewed_by': role.get('name'), 'review_note': note, 'reviewed_at': now()}
            self.repo.db.execute('UPDATE events SET payload=? WHERE id=?', (encode(event), event_id))
            self.repo.audit('evidence.reviewed', event_id, role.get('name'), {'status': status, 'note': note, 'actor_id': actor_id})
        return event
