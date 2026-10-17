"""Browser-facing /api endpoints and the one adapter layer for Garima's frontend.

Canonical planner records stay snake_case and unchanged; this module is the only
place they are translated into the frontend's camelCase shapes (slack_days ->
slackDays, target_delivery -> targetDelivery, label_group_id -> labelGroup, ...).
No calculation happens here: every date, slack value and risk band is read from an
immutable planner scenario. Every response is validated against apps.api.schemas.
"""
import json
import re
from datetime import date, timedelta

from . import schemas
from .governance import evidence_status, event_options

MILESTONE_LABELS = {'permit_approval': 'Permit approval', 'label_approval': 'Label approval', 'packaging_complete': 'Packaging complete',
                    'dispatch': 'Dispatch', 'customs_release': 'Customs release', 'site_delivery': 'Projected delivery'}
SCHEDULE_TYPES = {'permit_approval': 'deadline', 'label_review': 'deadline', 'label_approval': 'deadline', 'packaging_complete': 'packed',
                  'dispatch': 'in_transit', 'customs_arrival': 'customs', 'customs_release': 'customs', 'depot_arrival': 'in_transit',
                  'site_delivery': 'delivered'}
TRACKING_STAGES = [('packed', 'packaging_complete', 'Packed · {origin}'), ('departed', 'dispatch', 'Departed {origin}'),
                   ('customs', 'customs_release', 'Customs · {gateway}'), ('out_for_delivery', 'depot_arrival', 'Depot · {country}'),
                   ('delivered', 'site_delivery', 'Delivered · {site}')]
RISK_RANK = {'low': 0, 'medium': 1, 'high': 2, 'critical': 3}


def camel(key):
    return re.sub(r'_([a-z0-9])', lambda m: m.group(1).upper(), key)


def camelize(value):
    """Generic key conversion for nested read-only payloads (comparisons, audit payloads)."""
    if isinstance(value, dict):
        return {camel(k) if isinstance(k, str) else k: camelize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [camelize(v) for v in value]
    return value


def study_code(trial):
    return trial.get('code') or str(trial.get('name', trial.get('id', 'Study'))).split(' · ')[0].strip()


def kit_label(trial):
    product = trial.get('product', {})
    return ' · '.join(x for x in (product.get('name'), product.get('dosage_form')) if x) or 'Investigational product'


class Frontend:
    def __init__(self, service):
        self.service, self.repo, self.gov = service, service.repo, service.governance

    # --- shared reads ------------------------------------------------------------------
    def dataset(self):
        return self.repo.dataset()

    def current(self):
        current_id = self.gov.current_plan_id()
        if not current_id:
            raise KeyError('No current plan')
        return self.repo.plan(current_id)

    def today(self):
        return self.dataset()['as_of']

    def countries(self):
        return {j['iso_code']: j for j in self.dataset()['jurisdictions']}

    def pending_by_shipment(self):
        result = {}
        current = self.gov.current_plan_id()
        for event in self.repo.events():
            for view in self.gov.option_views(event['id']) if self.gov.proposal_rows(event['id'], current) else []:
                if view['status'] != 'proposed':
                    continue
                for row in view['preview']:
                    result.setdefault(row['shipment_id'], []).append(view['proposal_id'])
        return result

    # --- adapters (canonical -> frontend) ------------------------------------------------
    def shipment(self, s, plan, trial, pending=None):
        route = next((r for r in s.get('route_options', []) if r['id'] == s['route_id']), {})
        synthetic = s.get('verification_status') == 'synthetic' or route.get('synthetic')
        operational_provenance = 'sample' if s.get('data_provenance') == 'anna_sample' else 'synthetic'
        features = s.get('features', {})
        return {
            'id': s['id'], 'country': s['country_code'], 'countryName': s['country_name'], 'study': study_code(trial),
            'kit': s.get('drug_name') or kit_label(trial), 'origin': s.get('origin') or trial.get('manufacturing_origin', {}).get('city', 'Origin'),
            'destination': s.get('destination') or s['country_name'], 'site': s.get('site'), 'depot': s.get('depot'),
            'status': s['risk_band'], 'slackDays': int(s['slack_days']), 'targetDelivery': s['target_delivery'],
            'projectedDelivery': s['projected_delivery'], 'labelGroup': s['label_group_id'],
            'route': {'id': s['route_id'], 'name': s['route_name'], 'gatewayAirport': s.get('gateway_airport')},
            'deliveryRange': s['delivery_range'], 'shipBy': s['ship_by'], 'worstCaseSlackDays': int(s['worst_case_slack_days']),
            'riskScore': s['risk_score'], 'quantity': s.get('quantity'), 'reasons': [str(r) for r in s.get('reasons', [])],
            'verificationStatus': s.get('verification_status'),
            'sourceShipmentId': s.get('source_shipment_id'), 'sourceRequiredDelivery': s.get('source_required_delivery_date'),
            'sourceShippingDate': s.get('shipping_date'), 'dataProvenance': s.get('data_provenance', 'planner_demo'),
            'outlook': {'agentAnswer': features.get('agent_answer'), 'source': features.get('outlook_source', 'local')},
            'currentPlanId': plan['id'], 'proposalIds': (pending or {}).get(s['id'], []),
            'provenance': operational_provenance,
            'planningProvenance': 'modeled' if route.get('data_provenance') == 'modeled' else (
                'synthetic' if synthetic else ('needs_review' if s.get('verification_status') == 'needs_review' else 'modeled')),
        }

    def evidence_from_event(self, event):
        return {'id': event['id'], 'status': evidence_status(event), 'title': event.get('source_title') or event.get('title'),
                'url': event.get('source_url'), 'excerpt': event.get('source_excerpt'),
                'sourceTier': event.get('source_tier') or ('synthetic' if event.get('synthetic') else None),
                'jurisdiction': event.get('jurisdiction'), 'requirementKey': None, 'kind': 'event'}

    @staticmethod
    def evidence_from_rule(rule):
        return {'id': rule['id'], 'status': evidence_status(rule), 'title': rule.get('source_title') or rule['requirement_key'],
                'url': rule.get('source_url'), 'excerpt': rule.get('source_excerpt'), 'sourceTier': rule.get('source_tier'),
                'jurisdiction': rule.get('jurisdiction'), 'requirementKey': rule.get('requirement_key'), 'kind': 'rule',
                'effectiveFrom': rule.get('effective_from'), 'value': rule.get('value')}

    def option(self, view):
        def side(s):
            return {'projectedDelivery': s['projected_delivery'], 'slackDays': s['slack_days'], 'status': s['risk_band'],
                    'routeName': s['route_name'], 'labelGroup': s['label_group_id'], 'shipBy': s['ship_by'],
                    'deliveryRange': s['delivery_range']}
        return {'number': view['number'], 'key': view['key'], 'title': view['title'], 'description': view.get('description'),
                'tradeoffs': view.get('tradeoffs'), 'proposalId': view['proposal_id'], 'parentPlanId': view['parent_id'],
                'status': view['status'], 'stale': view['stale'], 'recommended': view['recommended'], 'feasible': view['feasible'],
                'costDelta': view['cost_delta'],
                'preview': [{'shipmentId': p['shipment_id'], 'countryName': p['country_name'], 'before': side(p['before']), 'after': side(p['after'])}
                            for p in view['preview']]}

    def warning(self, event, detail=False):
        countries = self.countries()
        views = self.gov.option_views(event['id'])
        accept = next((v for v in views if v['key'] == 'accept'), None)
        affected = [p['shipment_id'] for p in (accept or {}).get('preview', [])]
        if not affected:
            affected = [s['id'] for s in self.current()['shipments'] if s['country_code'] == event.get('jurisdiction')]
        severity = 'low'
        for row in (accept or {}).get('preview', []):
            after, before = row['after'], row['before']
            if after['risk_band'] == 'blocked':
                level = 'critical'
            elif after['risk_band'] == 'at_risk':
                level = 'high'
            elif after['slack_days'] < before['slack_days']:
                level = 'medium'
            else:
                level = 'low'
            severity = max(severity, level, key=RISK_RANK.get)
        evid = evidence_status(event)
        if self.gov.event_resolved(event['id']) or evid == 'retired':
            status = 'resolved'
        elif any(v['status'] == 'proposed' for v in views):
            status = 'in_review'
        else:
            status = 'open'
        recommended = next((v for v in views if v.get('recommended')), None)
        if status == 'resolved':
            approved = next((v for v in views if v['status'] in ('approved', 'superseded') and not v['stale']), None)
            action = f"Resolved: {approved['title']}" if approved else 'Resolved'
        elif recommended and not recommended['feasible']:
            action = f"No option meets every target date; least impact: {recommended['title']}"
        elif recommended:
            action = recommended['title']
        elif not self.gov.analyzable(event):
            action = 'Review the changed source and import normalized requirement changes'
        else:
            action = 'Analyze impact'
        title = event.get('title', 'Planning event')
        requirement = event.get('requirement') or (title.split(' · ', 1)[1] if ' · ' in title else title)
        kind = event.get('event_type', 'event')
        provenance = ('sample' if event.get('operational_provenance') == 'anna_sample' else
                      'synthetic' if evid == 'synthetic' else ('needs_review' if evid == 'needs_review' else 'live'))
        source = event.get('source_title') or event.get('source_url') or 'Planner event'
        source_label = {'synthetic': f'Synthetic demo event · {kind}', 'needs_review': f'{source} (needs review)'}.get(evid, source)
        jurisdiction = event.get('jurisdiction') or ''
        result = {
            'id': 'wrn-' + event['id'], 'eventId': event['id'], 'kind': kind, 'country': jurisdiction,
            'countryName': countries.get(jurisdiction, {}).get('name', jurisdiction or 'Multiple'),
            'requirement': requirement, 'summary': event.get('description', ''), 'study': study_code(self.dataset()['trial']),
            'shipmentsAffected': len(affected), 'severity': severity, 'createdAt': event.get('detected_at') or self.today() + 'T00:00:00Z',
            'status': status, 'recommendedAction': action, 'source': source_label, 'shipmentIds': affected,
            'proposalId': recommended['proposal_id'] if recommended and status != 'resolved' else None,
            'evidenceStatus': evid, 'provenance': provenance, 'sourceUrl': event.get('source_url'),
            'feasible': any(v['feasible'] for v in views) if views else None,
        }
        if detail:
            ids = [event['id']] + [v['proposal_id'] for v in views]
            current = self.current()
            result.update(evidence=self.evidence_for_event(event), options=[self.option(v) for v in views],
                          currentPlan=self.current_plan(), audit=self.audit(entity_ids=ids, limit=40),
                          chatLinks=[c['id'] for c in self.service.messaging.store.chats()],
                          appliedToCurrentPlan=event['id'] in current.get('applied_event_ids', []))
        return result

    def evidence_for_event(self, event):
        items = [self.evidence_from_event(event)]
        keys = {c.get('requirement_key') for c in event.get('changes', [])}
        rows = self.gov.proposal_set(event['id'])
        if rows:
            plan = self.repo.plan(rows[-1]['proposal_id'])
            items += [self.evidence_from_rule(r) for r in plan.get('rules', [])
                      if r.get('jurisdiction') == event.get('jurisdiction') and (r.get('requirement_key') in keys or r.get('source_event_id') == event['id'])]
        return items

    def current_plan(self):
        plan = self.current()
        approval = plan.get('approval') or {}
        return {'planId': plan['id'], 'version': self.gov.current_plan_version(), 'approvedAt': approval.get('created_at'),
                'approvedBy': approval.get('approver'), 'status': 'approved', 'name': plan.get('name'),
                'appliedEventIds': plan.get('applied_event_ids', []), 'selectedRepairs': plan.get('selected_repairs', {}),
                'calculationVersion': plan.get('calculation_version'), 'provider': plan.get('provider')}

    def audit(self, entity_ids=None, limit=200):
        sql, args = 'SELECT * FROM audit', []
        if entity_ids:
            sql += ' WHERE entity_id IN (%s)' % ','.join('?' * len(entity_ids))
            args = list(entity_ids)
        rows = self.repo.db.execute(sql + ' ORDER BY rowid DESC LIMIT ?', args + [int(limit)])
        return [{'id': r['id'], 'action': r['action'], 'entityId': r['entity_id'], 'actor': r['actor'], 'createdAt': r['created_at'],
                 'payload': camelize(json.loads(r['payload']))} for r in rows]

    def proposal(self, proposal_id):
        plan = self.repo.plan(proposal_id)
        meta = self.gov.proposal_meta(proposal_id)
        if meta is None:
            raise KeyError('Proposal not found')
        event = self.repo.event(meta['event_id'])
        option = next((o for o in event_options(event) if o['id'] == meta['option_key']), {})
        comparison = self.gov.comparison(proposal_id) or {}
        return {'id': plan['id'], 'status': self.gov.plan_status(plan), 'parentPlanId': plan.get('parent_scenario_id'),
                'eventId': meta['event_id'], 'warningId': 'wrn-' + meta['event_id'],
                'option': {'number': meta['option_number'], 'key': meta['option_key'], 'title': option.get('title'),
                           'description': option.get('description'), 'tradeoffs': option.get('tradeoffs')},
                'createdAt': meta['created_at'], 'stale': self.gov.is_stale(plan), 'contentHash': plan['content_hash'],
                'decision': camelize(plan.get('approval')) if plan.get('approval') else None,
                'metrics': camelize(plan.get('metrics', {})), 'comparison': camelize(comparison)}

    def tracking(self, s, plan, trial, pending):
        base = self.shipment(s, plan, trial, pending)
        today = self.today()
        milestones = {m['type']: m['projected_date'] for m in s['milestones']}
        origin = trial.get('manufacturing_origin', {})
        country = self.countries().get(s['country_code'], {})
        o = {'lat': float(origin.get('latitude', 0)), 'lng': float(origin.get('longitude', 0))}
        d = {'lat': float(country.get('latitude', o['lat'])), 'lng': float(country.get('longitude', o['lng']))}
        dispatch, delivery = milestones['dispatch'], milestones['site_delivery']
        if today <= dispatch:
            progress = 0.0
        elif today >= delivery:
            progress = 1.0
        else:
            span = (date.fromisoformat(delivery) - date.fromisoformat(dispatch)).days or 1
            progress = round((date.fromisoformat(today) - date.fromisoformat(dispatch)).days / span, 3)
        names = {'origin': base['origin'], 'gateway': s.get('gateway_airport') or 'gateway', 'country': s['country_name'], 'site': s.get('site') or s['country_name']}
        stages, current_key = [], None
        started = milestones[TRACKING_STAGES[0][1]] < today
        for key, mtype, label in TRACKING_STAGES:
            when = milestones[mtype]
            # A stage is "current" only once the shipment has started moving through the stages.
            state = 'completed' if when < today else ('current' if started and current_key is None else 'upcoming')
            if state == 'current':
                current_key = key
            stages.append({'key': key, 'label': label.format(**names), 'at': when + 'T12:00:00Z', 'state': state, 'plannedDate': when})
        next_stage = next((st for st in stages if st['state'] != 'completed'), stages[-1])
        short = lambda iso: date.fromisoformat(iso).strftime('%b %d').replace(' 0', ' ')
        if progress == 0:
            status_label = f"Planned · dispatch {short(dispatch)}"
        elif progress >= 1:
            status_label = f"Planned · delivered {short(delivery)}"
        else:
            status_label = f"Planned · {next_stage['label'].split(' · ')[0].lower()} {short(next_stage['plannedDate'])}"
        location = f"{base['origin']} (not yet dispatched)" if progress == 0 else (s['country_name'] if progress >= 1 else f"En route to {s['country_name']} (modeled)")
        return {**base, 'synthetic': True, 'telemetry': 'none', 'progress': progress, 'stage': next_stage['key'],
                'statusLabel': status_label,
                'currentLocation': location,
                'coords': {'origin': o, 'destination': d, 'current': {'lat': o['lat'] + (d['lat'] - o['lat']) * progress, 'lng': o['lng'] + (d['lng'] - o['lng']) * progress}},
                'eta': s['projected_delivery'], 'temperatureC': None,
                'tempRange': f"{trial['product']['storage_min_c']}–{trial['product']['storage_max_c']} °C (product storage limit)",
                'updatedAt': plan.get('generated_at') or today + 'T00:00:00Z',
                'note': 'Modeled from the current plan; no carrier telemetry is connected.' + (f" {'; '.join(str(r) for r in s['reasons'][:2])}" if s.get('reasons') else ''),
                'milestones': stages}

    def calendar(self, month):
        if not re.fullmatch(r'\d{4}-\d{2}', month or ''):
            raise ValueError('month must be YYYY-MM')
        plan, by_date = self.current(), {}

        def add(day, phrase, major):
            if day and day.startswith(month):
                entry = by_date.setdefault(day, {'phrases': {}, 'major': False})
                entry['phrases'].setdefault(phrase, 0)
                entry['phrases'][phrase] += 1
                entry['major'] = entry['major'] or major
        for s in plan['shipments']:
            risky = s['risk_band'] != 'on_track'
            for m in s['milestones']:
                if m['type'] in MILESTONE_LABELS:
                    add(m['projected_date'], MILESTONE_LABELS[m['type']], risky and m['type'] in ('dispatch', 'site_delivery'))
            add(s['ship_by']['safe'], 'Safe ship-by', True)
            add(s['target_delivery'], 'Target delivery', True)
        for event in self.repo.events():
            add((event.get('detected_at') or '')[:10], 'Warning: ' + event.get('title', 'event'), True)
        events = []
        for day in sorted(by_date):
            entry = by_date[day]
            label = '; '.join(f"{p} ({n})" if n > 1 and not p.startswith('Warning') else p for p, n in entry['phrases'].items())
            events.append({'date': day, 'level': 'major' if entry['major'] else 'minor', 'label': label})
        return {'month': month, 'events': events}

    def schedule(self, day):
        date.fromisoformat(day)
        plan, today, items = self.current(), self.today(), []
        for event in self.repo.events():
            if (event.get('detected_at') or '')[:10] == day:
                warning = self.warning(event)
                items.append({'time': event['detected_at'][11:16] or '—', 'type': 'alert', 'title': event.get('title', 'Warning'),
                              'shipmentId': (warning['shipmentIds'] or ['—'])[0], 'party': warning['source'], 'status': warning['status']})
        for s in plan['shipments']:
            for m in s['milestones']:
                if m['projected_date'] == day and m['type'] in SCHEDULE_TYPES:
                    party = {'permit_approval': f"Regulator · {s['country_name']}", 'label_review': 'Regulatory affairs', 'label_approval': 'Regulatory affairs',
                             'packaging_complete': 'Packaging · origin', 'dispatch': f"Carrier · {s['route_name']}", 'customs_arrival': f"Customs · {s.get('gateway_airport') or s['country_name']}",
                             'customs_release': f"Customs · {s.get('gateway_airport') or s['country_name']}", 'depot_arrival': s.get('depot') or 'Depot',
                             'site_delivery': s.get('site') or 'Site'}[m['type']]
                    items.append({'time': '—', 'type': SCHEDULE_TYPES[m['type']], 'title': f"{s['country_name']}: {m['label']}",
                                  'shipmentId': s['id'], 'party': party, 'status': 'done' if day < today else 'scheduled'})
            if s['ship_by']['safe'] == day:
                items.append({'time': '—', 'type': 'deadline', 'title': f"{s['country_name']}: safe ship-by date", 'shipmentId': s['id'],
                              'party': 'Supply lead', 'status': 'done' if day < today else 'open'})
        for row in self.gov.proposal_rows():
            if row['created_at'][:10] == day and row['parent_id'] == self.gov.current_plan_id() and row['option_number'] == 1:
                items.append({'time': row['created_at'][11:16], 'type': 'review', 'title': f"Proposals awaiting review · {row['event_id']}",
                              'shipmentId': '—', 'party': 'Supply lead', 'status': 'open'})
        return {'date': day, 'items': items}

    def insight(self, day):
        """Chalk insight for a day. Values are the outlook features stored in the current
        plan (Chalk online query when configured and parity-checked, otherwise the local
        deterministic fallback); the summary and recommendations are explanations of them."""
        date.fromisoformat(day)
        plan = self.current()
        provider = plan.get('provider') or {}
        relevant = [s for s in plan['shipments'] if any(m['projected_date'] == day for m in s['milestones'])
                    or s['ship_by']['safe'] == day or s['ship_by']['likely'] == day or s['target_delivery'] == day]
        risk = 'low'
        for s in relevant:
            if s['risk_band'] == 'blocked':
                level = 'critical' if s['slack_days'] < 0 else 'high'
            elif s['risk_band'] == 'at_risk':
                level = 'high'
            elif s['worst_case_slack_days'] < 0:
                level = 'medium'
            else:
                level = 'low'
            risk = max(risk, level, key=RISK_RANK.get)
        used_chalk = provider.get('active') == 'chalk'
        label = ('Chalk online query · values parity-checked against the local formula' if used_chalk else
                 f"Local deterministic fallback · {provider.get('reason') or 'Chalk is not configured'}")
        source = {'provider': 'chalk' if used_chalk else 'local', 'kind': 'deterministic derived feature', 'label': label,
                  'requested': provider.get('requested', 'local'), 'fallback': bool(provider.get('fallback')),
                  'planId': plan['id'], 'valueKinds': {'risk': 'deterministic derived feature', 'shipBy': 'deterministic derived feature',
                                                       'summary': 'explanation', 'recommendations': 'recommendation'}}
        if not relevant:
            return {'date': day, 'risk': 'low', 'summary': 'No shipment milestones on this day.', 'recommendations': [], 'source': source, 'available': True}
        at_risk = [s for s in relevant if s['risk_band'] != 'on_track']
        ship_by = [s for s in relevant if s['ship_by']['safe'] == day]
        summary = (f"{len(relevant)} shipment(s) have milestones or deadlines on this day"
                   + (f"; {len(at_risk)} at risk or blocked in the current plan" if at_risk else '; all on track in the current plan')
                   + (f"; {len(ship_by)} reach their safe ship-by date." if ship_by else '.'))
        recs = [s['features']['agent_answer'] for s in sorted(relevant, key=lambda s: (s['risk_band'] == 'on_track', s['slack_days']))
                if s.get('features', {}).get('agent_answer')][:4]
        for event in self.repo.events():
            if not self.gov.event_resolved(event['id']) and any(s['country_code'] == event.get('jurisdiction') for s in relevant):
                recs.insert(0, f"Decide on warning wrn-{event['id']} ({event.get('title')}) before acting on the affected shipments.")
        return {'date': day, 'risk': risk, 'summary': summary, 'recommendations': recs[:6], 'source': source, 'available': True}

    def evidence(self, warning_id=None, country=None):
        if warning_id:
            return self.evidence_for_event(self.repo.event(warning_id.removeprefix('wrn-')))
        plan = self.current()
        rules = [r for r in plan.get('rules', []) if not country or r['jurisdiction'] == country.upper()]
        return [self.evidence_from_rule(r) for r in rules]

    def chats(self):
        store = self.service.messaging.store
        result = []
        for chat in store.chats():
            messages = store.messages(chat['id'])
            last = messages[-1] if messages else {}
            role = self.gov.roles.get(chat['actor_id'], {})
            links = []
            for m in messages[-6:]:
                for link in m.get('links', []):
                    target = link.get('href', '').rsplit('/', 1)[-1]
                    if target and target not in links:
                        links.append(target)
            result.append({'id': chat['id'], 'name': chat['name'], 'role': chat['role'], 'initial': chat['initial'],
                           'unread': store.unread(chat['id']), 'updatedAt': last.get('sentAt', chat['created_at']),
                           'lastMessage': (last.get('text') or (last.get('card') or {}).get('title') or 'No messages yet').split('\n')[0][:120],
                           'links': links, 'canApprove': bool(role.get('can_approve')), 'actorId': chat['actor_id'],
                           'channel': 'photon' if chat.get('photon_space_id') else 'web'})
        return sorted(result, key=lambda c: c['updatedAt'], reverse=True)

    # --- routing ----------------------------------------------------------------------------
    def handle(self, method, path, query, body):
        """Return (schema, payload) for a frontend endpoint, or None if not ours."""
        parts = path.strip('/').split('/')
        q = lambda k, d=None: query.get(k, [d])[0]
        S = schemas
        if method == 'GET':
            if path == '/api/context':
                ds = self.dataset()
                return S.CONTEXT, {'today': self.today(), 'trial': {'id': ds['trial']['id'], 'study': study_code(ds['trial']), 'name': ds['trial']['name'],
                                                                  'kit': kit_label(ds['trial'])},
                                   'currentPlan': self.current_plan(),
                                   'providers': {'features': self.service.provider.name, 'notifications': self.service.notifications.name,
                                                 'assistant': self.service.assistant.name},
                                   'schemaVersion': self.repo.schema_version()}
            if path == '/api/shipments':
                plan, trial, pending = self.current(), self.dataset()['trial'], self.pending_by_shipment()
                return S.list_of(S.SHIPMENT), [self.shipment(s, plan, trial, pending) for s in plan['shipments']]
            if path == '/api/warnings':
                rows = [self.warning(e) for e in self.repo.events()]
                return S.list_of(S.WARNING), sorted(rows, key=lambda w: w['createdAt'], reverse=True)
            if len(parts) == 3 and parts[1] == 'warnings':
                return S.WARNING_DETAIL, self.warning(self.repo.event(parts[2].removeprefix('wrn-')), detail=True)
            if len(parts) == 4 and parts[1] == 'warnings' and parts[3] == 'options':
                return S.list_of(S.OPTION), [self.option(v) for v in self.gov.option_views(parts[2].removeprefix('wrn-'))]
            if path == '/api/inventory':
                items = self.dataset().get('inventory', [])
                if items:
                    return S.INVENTORY, {'configured': True, 'items': items,
                                         'live': self.dataset().get('inventory_provenance') == 'live',
                                         'provenance': self.dataset().get('inventory_provenance', 'sample'),
                                         'sourceSystem': self.dataset().get('inventory_source_system'),
                                         'message': 'Sample recurring inventory supplied with the integrated dataset; no live inventory system is connected.'}
                return S.INVENTORY, {'configured': False, 'live': False, 'items': [], 'provenance': 'not_configured', 'sourceSystem': None,
                                     'message': 'Inventory data is not configured. No inventory system is connected, and shipment schedules are not shown as stock.'}
            if path == '/api/photon/chats':
                return S.list_of(S.CHAT), self.chats()
            if len(parts) == 5 and parts[1] == 'photon' and parts[2] == 'chats' and parts[4] == 'messages':
                store = self.service.messaging.store
                store.chat(parts[3])
                messages = store.messages(parts[3])
                store.mark_read(parts[3])
                return S.list_of(S.MESSAGE), messages
            if path == '/api/calendar':
                return S.CALENDAR, self.calendar(q('month', self.today()[:7]))
            if len(parts) == 3 and parts[1] == 'schedule':
                return S.SCHEDULE, self.schedule(parts[2])
            if path == '/api/chalk/insights':
                return S.INSIGHT, self.insight(q('date', self.today()))
            if path == '/api/tracking' or (len(parts) == 3 and parts[1] == 'tracking'):
                plan, trial, pending = self.current(), self.dataset()['trial'], self.pending_by_shipment()
                rows = [self.tracking(s, plan, trial, pending) for s in plan['shipments']]
                if len(parts) == 3:
                    row = next((r for r in rows if r['id'] == parts[2]), None)
                    if row is None:
                        raise KeyError('Shipment not found')
                    return S.TRACKING, row
                return S.list_of(S.TRACKING), rows
            if path == '/api/proposals':
                event_id = (q('warningId') or '').removeprefix('wrn-') or None
                rows = self.gov.proposal_rows(event_id)
                return S.list_of(S.PROPOSAL), [self.proposal(r['proposal_id']) for r in rows]
            if len(parts) == 3 and parts[1] == 'proposals':
                return S.PROPOSAL, self.proposal(parts[2])
            if len(parts) == 4 and parts[1] == 'proposals' and parts[3] == 'comparison':
                self.proposal(parts[2])
                return {'type': 'object', 'required': ['beforeId', 'afterId', 'changes']}, camelize(self.gov.comparison(parts[2]))
            if path == '/api/current-plan':
                return S.CURRENT_PLAN, self.current_plan()
            if path == '/api/audit-history':
                ids = [x for x in (q('entityId') or '').split(',') if x] or None
                return S.list_of(S.AUDIT_ENTRY), self.audit(ids, min(int(q('limit', '200')), 1000))
            if path == '/api/evidence':
                return S.list_of(S.EVIDENCE), self.evidence(q('warningId'), q('country'))
        if method == 'POST':
            if len(parts) == 5 and parts[1] == 'photon' and parts[2] == 'chats' and parts[4] == 'messages':
                client_id = body.get('clientMessageId')
                if client_id is not None and (not isinstance(client_id, str) or len(client_id) > 100):
                    raise ValueError('clientMessageId must be a short string')
                return S.SEND_RESULT, self.service.messaging.receive(parts[3], body.get('text'), external_id=client_id, channel='web')
            if len(parts) == 4 and parts[1] == 'proposals' and parts[3] in ('approve', 'reject'):
                action = 'approve' if parts[3] == 'approve' else 'reject'
                kwargs = dict(actor_id=body.get('actorId'), actor_role=body.get('actorRole'), rationale=body.get('rationale'),
                              channel=body.get('channel', 'web'), idempotency_key=body.get('idempotencyKey'),
                              expected_current_plan_id=body.get('expectedCurrentPlanId'))
                result = self.gov.decide(action, parts[2], **kwargs)
                if action == 'approve' and not result['replayed']:
                    self.service.messaging.broadcast_approval(result)
                return S.DECISION_RESULT, result
            if len(parts) == 5 and parts[1] == 'warnings' and parts[3] == 'evidence' and parts[4] == 'review':
                event = self.gov.review_evidence(parts[2].removeprefix('wrn-'), actor_id=body.get('actorId'), status=body.get('status'), note=body.get('note'))
                return S.WARNING, self.warning(event)
        return None
