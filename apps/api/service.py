"""Application operations, transaction boundaries and auditable human governance."""
import copy
import difflib
import hashlib
import json
from datetime import date
from pathlib import Path

from packages.domain.validation import validate_dataset, validate_rule
from packages.planner.engine import generate_plan, compare_plans, select_rules, CALCULATION_VERSION
from packages.feature_provider import configured_provider
from packages.feature_provider.providers import LocalFeatureProvider
from packages.ingestion.adapters import GenericPageAdapter, ECFRAdapter, EURLexAdapter, parse_records, field_diff, CachedGeographyProvider
from packages.assistant import configured_assistant
from packages.research import configured_research, ResearchUnavailable
from packages.calendar import ICSCalendarProvider
from packages.notifications import configured_notifications
from .repository import Repository, identifier, encode, now

ROOT = Path(__file__).resolve().parents[2]


class APIError(Exception):
    def __init__(self, message, status=400, details=None):
        super().__init__(message)
        self.status, self.details = status, details


class Service:
    def __init__(self, db_path, fixture=None):
        self.repo = Repository(db_path)
        self.provider = configured_provider()
        self.notifications = configured_notifications()
        self.assistant = configured_assistant()
        self.research = configured_research()
        if self.repo.dataset() is None:
            path = Path(fixture) if fixture else ROOT / 'data/demo/trial.json'
            self.reset(json.loads(path.read_text(encoding='utf-8')))

    def validate(self, dataset):
        errors = validate_dataset(dataset)
        if errors:
            raise APIError('Dataset validation failed',422,errors)

    def reset(self, dataset):
        self.validate(dataset)
        with self.repo.transaction():
            self.repo.save_dataset(dataset)
            self.sync_sources(dataset)
            self.repo.set_setting('approved_scenario_id',None)
            # Reset activates a fresh fixture but does not erase historical plans or audit.
            self.repo.db.execute('DELETE FROM events')
            self.repo.db.execute('DELETE FROM acknowledgements')
            for event in dataset.get('events',[]):
                self.repo.save_event(event)
            self.repo.audit('dataset.reset',dataset['id'],payload={'synthetic_demo':True})
            plan = self.generate(dataset)
            self.repo.decide(plan['id'],'approved','demo seed','Explicit synthetic demo baseline initialization; not a human regulatory approval.')
        return self.bootstrap()

    def sync_sources(self, dataset):
        for source in dataset.get('source_documents',[]):
            url = source.get('canonical_url') or source.get('url')
            if url:
                self.repo.save_source({'id':source['id'],'title':source.get('title',source['id']),'url':url,'adapter':source.get('adapter','generic'),'jurisdiction':source.get('jurisdiction'),'enabled':source.get('enabled',True)})

    def generate(self, dataset, parent=None, event=None, repair=None):
        dataset = copy.deepcopy(dataset)
        dataset['events'] = self.repo.events()
        plan = generate_plan(dataset,parent=parent,event=event,repair=repair)
        plan['id'] = identifier('scenario')
        plan['scenario_id'] = plan['id']
        plan['generated_at'] = now()
        plan['parent_scenario_id'] = parent['id'] if parent else None
        plan['trigger_event_id'] = event['id'] if event else None
        plan['input_dataset_id'] = self.repo.setting('dataset_id')
        countries = {cp['jurisdiction']:cp for cp in dataset['country_plans']}
        for shipment in plan['shipments']:
            shipment['features']['calendar_holidays'] = countries[shipment['country_code']].get('holidays',[])
            shipment['features']['low_slack_days'] = dataset['config'].get('low_slack_days',3)
        self.provider.enrich(plan)
        self.repo.save_plan(plan,dataset)
        return self.repo.plan(plan['id'])

    def summaries(self):
        dataset = self.repo.dataset()
        fields = ('id','trial_id','name','generated_at','as_of','status','parent_scenario_id','trigger_event_id','metrics','approval','calculation_version')
        return [{k:p.get(k) for k in fields} for p in self.repo.plans(dataset['trial']['id'])]

    def alerts(self):
        approved = self.repo.setting('approved_scenario_id')
        if not approved:
            return []
        plan = self.repo.plan(approved)
        acknowledged = {r[0] for r in self.repo.db.execute('SELECT alert_id FROM acknowledgements')}
        alerts = []
        for shipment in sorted(plan['shipments'],key=lambda s:-s['risk_score']):
            if shipment['risk_band'] != 'on_track':
                key = plan['id'] + ':' + shipment['id']
                alerts.append({'id':key,'title':shipment['country_name'] + ' shipment ' + shipment['risk_band'].replace('_',' '),'severity':shipment['risk_band'],'cause':'; '.join(str(v) for v in shipment.get('reasons',[])),'country_code':shipment['country_code'],'affected_shipment_count':1,'recommended_action':'Review evidence and analyze a repair scenario','scenario_id':plan['id'],'acknowledged':key in acknowledged,'deep_link':'/#scenarios'})
        for scenario in self.repo.plans(plan['trial_id']):
            if scenario['status'] == 'proposed':
                key = 'review:' + scenario['id']
                alerts.append({'id':key,'title':'Scenario awaiting human review','severity':'at_risk','cause':scenario['name'],'affected_shipment_count':len(scenario.get('impacts',[])),'recommended_action':'Compare and approve or reject','scenario_id':scenario['id'],'acknowledged':key in acknowledged,'deep_link':'/#scenarios'})
        return alerts

    def what_if(self, body):
        question = str(body.get('question','')).strip()[:4000]
        if not question:
            raise APIError('Question is required')
        scenario_id = body.get('scenario_id') or self.repo.setting('approved_scenario_id')
        parent = self.repo.plan(scenario_id)
        dataset = self.repo.plan_dataset(scenario_id)
        low = question.lower()
        jurisdictions = {j['iso_code']:j['name'] for j in dataset['jurisdictions']}
        codes = [code for code,name in jurisdictions.items() if name.lower() in low or code.lower() in low.split()]
        actions = []
        if any(term in low for term in ('separate label','split label','separate-label')): actions.append('split_label')
        if any(term in low for term in ('alternative route','reroute','amsterdam')): actions.append('alternative_route')
        if 'expedite' in low and any(term in low for term in ('label','review')): actions.append('expedite_review')
        if 'expedite' in low and 'permit' in low: actions.append('expedite_permit')
        if len(codes)!=1 or len(set(actions))!=1:
            raise APIError('Supported what-if questions must name one country and one action: separate label, alternative route, expedite label review, or expedite permit.',422)
        action = actions[0]
        matches = []
        for event in self.repo.events():
            if event.get('jurisdiction') != codes[0]:
                continue
            for option in event.get('repair_options',[]):
                if option.get('action') == action:
                    matches.append((event,option))
        if len(matches)!=1:
            raise APIError(f'No allowlisted {action.replace("_"," ")} simulation is configured for {jurisdictions[codes[0]]}.',422)
        event,option = matches[0]
        temporary = generate_plan(dataset,parent=parent,event=event,repair=option['id'])
        temporary['id'] = 'temporary_' + temporary['id'].split('_',1)[-1]
        temporary['scenario_id'] = temporary['id']
        temporary['status'] = 'temporary'
        temporary['ephemeral'] = True
        temporary['persisted'] = False
        temporary['generated_at'] = now()
        temporary['parent_scenario_id'] = parent['id']
        temporary['input_dataset_id'] = parent.get('input_dataset_id')
        LocalFeatureProvider().enrich(temporary)
        comparison = compare_plans(parent,temporary)
        affected = comparison.get('changes',[])
        before_cost = parent.get('metrics',{}).get('cost_proxy',0)
        after_cost = temporary.get('metrics',{}).get('cost_proxy',0)
        lines = [f"Temporary simulation: {option['title']}. {option.get('description','')}"]
        if affected:
            for change in affected:
                before,after = change['before'],change['after']
                lines.append(f"{change['country_name']}: delivery {before.get('projected_delivery')} → {after.get('projected_delivery')}; slack {before.get('slack_days')} → {after.get('slack_days')} business days; risk {before.get('risk_band')} → {after.get('risk_band')}.")
        else:
            lines.append('The deterministic planner found no material schedule or route change from this option.')
        lines.append(f"Cost proxy: {before_cost} → {after_cost}. Trade-off: {option.get('tradeoffs','Review the comparison.')}")
        lines.append('This result is temporary: it was not saved, approved, or applied.')
        rules = [r for r in temporary.get('rules',[]) if r.get('jurisdiction')==codes[0]]
        citations = [{'title':r.get('source_title',r['requirement_key']),'url':r.get('source_url'),
                      'excerpt':r.get('source_excerpt'),'status':r.get('review_status')} for r in rules if r.get('source_url')]
        self.repo.audit('assistant.what_if.simulated',parent['id'],payload={'question':question,'event_id':event['id'],'repair':option['id'],'persisted':False})
        return {'answer':'\n\n'.join(lines),'provider':'deterministic','temporary_scenario':temporary,
                'comparison':comparison,'citations':citations[:20],
                'suggested_questions':['Why is this shipment at risk?','What evidence supports this requirement?']}

    def bootstrap(self):
        dataset = self.repo.dataset()
        approved = self.repo.setting('approved_scenario_id')
        plan = self.repo.plan(approved) if approved else None
        return {'trial':dataset['trial'],'dataset_summary':{'id':dataset['id'],'as_of':dataset['as_of'],'countries':len(dataset['jurisdictions']),'rules':len(dataset['rules']),'routes':len(dataset['routes']),'synthetic_rules':sum(r['review_status']=='synthetic' for r in dataset['rules'])},'approved_scenario':plan,'scenarios':self.summaries(),'events':self.repo.events(),'alerts':self.alerts(),'provider':plan.get('provider') if plan else {'active':self.provider.name},'assistant_provider':self.assistant.name,'research_provider':self.research.name,'notification_provider':self.notifications.name,'jurisdictions':dataset['jurisdictions']}

    def preview(self, body, kind):
        dataset = self.repo.dataset()
        if kind == 'dataset':
            candidate = body.get('dataset')
            if not isinstance(candidate,dict):
                raise APIError('dataset object required')
            errors = validate_dataset(candidate)
            diff = [{'collection':key,'before':len(dataset.get(key,[])),'after':len(candidate.get(key,[]))} for key in ('jurisdictions','rules','routes','country_plans','events')]
            data = {'dataset':candidate,'diff':diff,'errors':errors,'valid':not errors}
        else:
            records = parse_records(body)
            if not records:
                raise APIError('At least one rule is required')
            if any(not isinstance(record,dict) for record in records):
                raise APIError('Each rule record must be an object',422)
            records = copy.deepcopy(records)
            for record in records:
                record.setdefault('id',identifier('rule'))
            candidate, diff = self.merge_rules(dataset,records)
            errors = validate_dataset(candidate)
            keys = [(r.get('jurisdiction'),r.get('requirement_key'),r.get('effective_from')) for r in records]
            conflicts = sorted({str(key) for key in keys if keys.count(key)>1})
            summary = {'records':len(records),'jurisdictions':len({r.get('jurisdiction') for r in records}),'adds':sum(d['operation']=='add' for d in diff),'supersedes':sum(d['operation']=='supersede' for d in diff),'needs_review':sum(r.get('review_status')=='needs_review' for r in records),'conflicts':conflicts}
            data = {'records':records,'diff':diff,'summary':summary,'errors':errors + ([{'path':'records','message':'Duplicate jurisdiction, requirement key, and effective date','conflicts':conflicts}] if conflicts else []),'valid':not errors and not conflicts}
        key = identifier('preview')
        self.repo.db.execute('INSERT INTO previews VALUES(?,?,?,?,0,?)',(key,kind,encode(data),self.repo.setting('dataset_id'),now()))
        self.repo.audit('import.preview',key,payload={'kind':kind,'valid':data['valid']})
        return {'preview_id':key,**data}

    def merge_rules(self, dataset, records):
        candidate = copy.deepcopy(dataset)
        existing = {r['id']:r for r in candidate['rules']}
        diff = []
        for record in records:
            old = existing.get(record.get('supersedes_id'))
            if record['id'] in existing:
                if record != existing[record['id']]:
                    # Immutable rule versions require a new id, not in-place edits.
                    raise APIError('Rule ids are immutable; use a new id and supersedes_id',422)
                continue
            if old:
                # The imported version closes the prior effective interval in a new dataset snapshot.
                if record['effective_from'] <= old['effective_from']:
                    raise APIError('Superseding rule must start after its predecessor',422)
                old['effective_to'] = record['effective_from']
            existing[record['id']] = record
            diff.append({'id':record['id'],'jurisdiction':record.get('jurisdiction'),'requirement_key':record.get('requirement_key'),'operation':'supersede' if old else 'add','changes':field_diff(old or {},record)})
        candidate['rules'] = list(existing.values())
        return candidate,diff

    def commit(self, body, kind):
        key = body.get('preview_id')
        reviewer = str(body.get('reviewer','')).strip()
        if not reviewer:
            raise APIError('A named reviewer is required')
        row = self.repo.db.execute('SELECT * FROM previews WHERE id=?',(key,)).fetchone()
        if not row or row['kind'] != kind:
            raise APIError('Import preview not found',404)
        data = json.loads(row['payload'])
        if row['consumed']:
            raise APIError('Import preview has already been committed',409)
        if row['dataset_id'] != self.repo.setting('dataset_id'):
            raise APIError('Dataset changed since preview; create a fresh preview',409)
        if not data['valid']:
            raise APIError('Invalid preview cannot be committed',422,data['errors'])
        dataset = data['dataset'] if kind == 'dataset' else self.merge_rules(self.repo.dataset(),data['records'])[0]
        self.validate(dataset)
        self.repo.save_dataset(dataset)
        self.sync_sources(dataset)
        self.repo.db.execute('UPDATE previews SET consumed=1 WHERE id=?',(key,))
        self.repo.audit('import.committed',key,reviewer,{'kind':kind,'records':len(data.get('records',dataset['rules']))})
        if kind == 'dataset':
            self.repo.db.execute('DELETE FROM events')
            for event in dataset.get('events',[]):
                self.repo.save_event(event)
            self.repo.set_setting('approved_scenario_id',None)
        parent_id = self.repo.setting('approved_scenario_id')
        parent = self.repo.plan(parent_id) if parent_id else None
        plan = self.generate(dataset,parent=parent)
        return {'imported':len(data.get('records',dataset['rules'])),'scenario_id':plan['id'],'status':'proposed','message':'Imported data is active for new proposals; human approval is required to apply the new plan.'}

    def requirements(self, iso, as_of, scenario_id=None):
        dataset = self.repo.dataset()
        date.fromisoformat(as_of)
        plan = self.repo.plan(scenario_id) if scenario_id else None
        if plan:
            dataset = self.repo.plan_dataset(scenario_id)
        elif self.repo.setting('approved_scenario_id'):
            approved = self.repo.plan(self.repo.setting('approved_scenario_id'))
            if approved.get('input_dataset_id') == self.repo.setting('dataset_id'):
                plan = approved
        country = next((j for j in dataset['jurisdictions'] if j['iso_code']==iso),None)
        if not country:
            raise KeyError('Jurisdiction not found')
        active = {r['id'] for r in select_rules(dataset,as_of)}
        records = [{**r,'active':r['id'] in active,'future_effective':r['effective_from']>as_of} for r in dataset['rules'] if r['jurisdiction']==iso]
        if plan and plan['as_of']==as_of:
            # Event-derived rules live in the immutable scenario, not in the research registry.
            # Expose their exact evidence without changing or hiding prior source versions.
            known = {r['id'] for r in records}
            derived = [r for r in plan.get('rules',[]) if r['jurisdiction']==iso and r['id'] not in known]
            changed_keys = {r['requirement_key'] for r in derived}
            for record in records:
                if record['requirement_key'] in changed_keys:
                    record['active'] = False
                    record['superseded_in_scenario'] = plan['id']
            records.extend({**r,'active':True,'future_effective':False,'scenario_assumption':True,'scenario_id':plan['id']} for r in derived)
        return {'country':country,'as_of':as_of,'requirements':records,'scenario_id':plan['id'] if plan else None}

    def snapshot(self, body):
        source_id = str(body.get('source_id','')).strip()
        if not source_id:
            raise APIError('source_id required')
        content = body.get('content')
        adapter_name = body.get('adapter','generic')
        adapters = {'generic':GenericPageAdapter,'ecfr':ECFRAdapter,'eurlex':EURLexAdapter}
        if adapter_name not in adapters:
            raise APIError('Unknown regulatory adapter')
        adapter = adapters[adapter_name]()
        if content is None:
            content = adapter.fetch(body.get('url',''))
        if not isinstance(content,str) or len(content.encode()) > 2_000_000:
            raise APIError('Source content must be text under 2 MB')
        old = self.repo.db.execute('SELECT * FROM snapshots WHERE source_id=? ORDER BY rowid DESC LIMIT 1',(source_id,)).fetchone()
        snapshot = adapter.snapshot(content)
        key = identifier('snapshot')
        self.repo.db.execute('INSERT INTO snapshots VALUES(?,?,?,?,?)',(key,source_id,snapshot['content_hash'],content,now()))
        changed = bool(old and old['content_hash'] != snapshot['content_hash'])
        result = {'id':key,'source_id':source_id,'old_hash':old['content_hash'] if old else None,'content_hash':snapshot['content_hash'],'changed':changed,'diff':list(difflib.unified_diff((old['content'] if old else '').splitlines(),content.splitlines(),lineterm=''))[:500],'review_status':'needs_review','metadata':adapter.extract_metadata(content,body.get('url',source_id)),'candidate_rules':adapter.normalize_candidate_rules(body.get('records',[]))}
        if changed:
            event = {'id':identifier('event'),'title':'Source snapshot changed','description':'Evidence changed; review normalized candidate rules before planning.','event_type':'source_snapshot','jurisdiction':body.get('jurisdiction'),'synthetic':False,'source_id':source_id,'old_hash':old['content_hash'],'new_hash':snapshot['content_hash'],'review_status':'needs_review','changes':[]}
            self.repo.save_event(event)
            result['event_id'] = event['id']
        self.repo.audit('source.snapshot',source_id,payload={k:v for k,v in result.items() if k != 'diff'})
        return result

    def check_source(self, source):
        return self.snapshot({'source_id':source['id'],'url':source['url'],'adapter':source.get('adapter','generic'),'jurisdiction':source.get('jurisdiction')})

    def research_extract(self, body):
        dataset = self.repo.dataset()
        source_id = str(body.get('source_id','')).strip()
        source = next((s for s in self.repo.sources() if s['id']==source_id),None)
        content = body.get('content')
        if source:
            if content is None:
                row = self.repo.db.execute('SELECT * FROM snapshots WHERE source_id=? ORDER BY rowid DESC LIMIT 1',(source_id,)).fetchone()
                if not row:
                    raise APIError('Collect or paste a source snapshot before AI extraction',409)
                content, retrieved_at = row['content'], row['created_at']
            else:
                result = self.snapshot({'source_id':source_id,'content':content,'url':source['url'],'adapter':source.get('adapter','generic'),'jurisdiction':source.get('jurisdiction')})
                retrieved_at = now()
        else:
            title = str(body.get('source_title','')).strip()
            url = str(body.get('source_url','')).strip()
            if not title or not url.startswith(('https://','http://')):
                raise APIError('A registered source or pasted source title and HTTP(S) URL is required')
            if not isinstance(content,str) or not content.strip():
                raise APIError('Pasted source text is required')
            source = {'id':source_id or identifier('source'),'title':title,'url':url,'adapter':'generic',
                      'jurisdiction':body.get('jurisdiction'),'enabled':True,'source_tier':body.get('source_tier','authoritative_secondary')}
            self.repo.save_source(source)
            source_id = source['id']
            result = self.snapshot({'source_id':source_id,'content':content,'url':url,'adapter':'generic','jurisdiction':source.get('jurisdiction')})
            retrieved_at = now()
        jurisdiction = str(body.get('jurisdiction') or source.get('jurisdiction') or '').upper()
        if jurisdiction not in {j['iso_code'] for j in dataset['jurisdictions']}:
            raise APIError('Choose a jurisdiction in the active trial')
        if not isinstance(content,str) or not content.strip():
            raise APIError('Source content is required')
        tier = source.get('source_tier') or ('official' if source.get('adapter') in ('ecfr','eurlex') else 'authoritative_secondary')
        try:
            output = self.research.extract(content=content,jurisdiction=jurisdiction,source=source,
                                           requirement_keys={r['requirement_key'] for r in dataset['rules']})
        except ResearchUnavailable as exc:
            raise APIError(str(exc),503)
        candidates, errors = [], []
        for index, item in enumerate(output.get('candidates',[])):
            candidate = {**item,'id':identifier('rule'),'jurisdiction':jurisdiction,
                         'source_url':source['url'],'source_title':source['title'],
                         'retrieved_at':retrieved_at,'source_tier':tier,
                         'review_status':'needs_review','last_verified_at':None,
                         'source_document_id':source_id}
            if candidate.get('source_excerpt') not in content:
                errors.append({'candidate':index,'message':'Supporting quotation was not found verbatim in the source snapshot'})
                continue
            candidate_errors = validate_rule(candidate)
            if candidate_errors:
                errors.extend({'candidate':index,'message':message} for message in candidate_errors)
                continue
            candidates.append(candidate)
        result = {'source_id':source_id,'provider':self.research.name,'model':getattr(self.research,'model',None),
                  'review_status':'needs_review','candidates':candidates,'errors':errors,
                  'document_note':output.get('document_note',''),'valid':bool(candidates) and not errors}
        self.repo.audit('ai.research.extracted',source_id,payload={'candidates':len(candidates),'errors':errors,'provider':self.research.name})
        return result

    def analyze_source_change(self, source_id):
        dataset = self.repo.dataset()
        source = next((s for s in self.repo.sources() if s['id']==source_id),None)
        if not source:
            raise KeyError('Source not found')
        rows = self.repo.db.execute('SELECT * FROM snapshots WHERE source_id=? ORDER BY rowid DESC LIMIT 2',(source_id,)).fetchall()
        if len(rows)<2:
            raise APIError('Two source snapshots are required for change analysis',409)
        new, old = rows[0], rows[1]
        if new['content_hash']==old['content_hash']:
            raise APIError('The latest source snapshot has not changed',409)
        jurisdiction = str(source.get('jurisdiction') or '').upper()
        if jurisdiction not in {j['iso_code'] for j in dataset['jurisdictions']}:
            raise APIError('The registered source needs a jurisdiction from the active trial',422)
        try:
            output = self.research.compare(old_content=old['content'],new_content=new['content'],jurisdiction=jurisdiction,
                                           source=source,requirement_keys={r['requirement_key'] for r in dataset['rules']})
        except ResearchUnavailable as exc:
            raise APIError(str(exc),503)
        quote_errors = []
        if output.get('old_excerpt') not in old['content']:
            quote_errors.append('Previous-version quotation was not found verbatim')
        if output.get('new_excerpt') not in new['content']:
            quote_errors.append('New-version quotation was not found verbatim')
        affected = [code for code in output.get('affected_jurisdictions',[]) if code in {j['iso_code'] for j in dataset['jurisdictions']}]
        event_data = output.get('event',{})
        event = {**event_data,'id':identifier('event'),'event_type':'regulatory','jurisdiction':jurisdiction,
                 'synthetic':False,'source_id':source_id,'source_url':source['url'],'source_excerpt':output.get('new_excerpt',''),
                 'source_tier':source.get('source_tier') or ('official' if source.get('adapter') in ('ecfr','eurlex') else 'authoritative_secondary'),
                 'review_status':'needs_review','materiality':output.get('materiality'),'ambiguity_note':output.get('ambiguity_note',''),
                 'likely_requirement_keys':output.get('likely_requirement_keys',[]),'affected_jurisdictions':affected,
                 'old_snapshot_id':old['id'],'new_snapshot_id':new['id']}
        raw_diff = list(difflib.unified_diff(old['content'].splitlines(),new['content'].splitlines(),fromfile=old['id'],tofile=new['id'],lineterm=''))[:500]
        data = {'source_id':source_id,'provider':self.research.name,'model':getattr(self.research,'model',None),
                'summary':output.get('summary',''),'materiality':output.get('materiality'),'ambiguity_note':output.get('ambiguity_note',''),
                'likely_requirement_keys':output.get('likely_requirement_keys',[]),'affected_jurisdictions':affected,
                'citations':[{'snapshot_id':old['id'],'label':'previous','excerpt':output.get('old_excerpt','')},
                             {'snapshot_id':new['id'],'label':'new','excerpt':output.get('new_excerpt','')}],
                'raw_diff':raw_diff,'event':event,'errors':quote_errors,'valid':not quote_errors}
        key = identifier('analysis')
        self.repo.db.execute('INSERT INTO previews VALUES(?,?,?,?,0,?)',(key,'change_event',encode(data),self.repo.setting('dataset_id'),now()))
        self.repo.audit('ai.change.analyzed',key,payload={'source_id':source_id,'materiality':data['materiality'],'valid':data['valid'],'provider':self.research.name})
        return {'analysis_id':key,**data}

    def confirm_source_change(self, analysis_id, body):
        reviewer, note = str(body.get('reviewer','')).strip(),str(body.get('note','')).strip()
        if not reviewer or not note:
            raise APIError('A named reviewer and confirmation note are required')
        row = self.repo.db.execute('SELECT * FROM previews WHERE id=?',(analysis_id,)).fetchone()
        if not row or row['kind']!='change_event':
            raise APIError('Change analysis not found',404)
        if row['consumed']:
            raise APIError('Change analysis has already been confirmed',409)
        if row['dataset_id'] != self.repo.setting('dataset_id'):
            raise APIError('Dataset changed since analysis; create a fresh analysis',409)
        data = json.loads(row['payload'])
        if not data.get('valid'):
            raise APIError('An analysis with invalid citations cannot be confirmed',422,data.get('errors'))
        event = copy.deepcopy(data['event'])
        edits = body.get('event')
        if edits is not None:
            if not isinstance(edits,dict):
                raise APIError('Normalized event edits must be an object')
            for key in ('title','description','effective_from','changes'):
                if key in edits:
                    event[key] = edits[key]
        event.update(review_status='confirmed',confirmed_by=reviewer,confirmation_note=note,
                     source_analysis_id=analysis_id,raw_diff=data['raw_diff'],citations=data['citations'])
        dataset = self.repo.dataset()
        candidate = copy.deepcopy(dataset)
        candidate['events'] = [e for e in self.repo.events() if e.get('event_type')!='source_snapshot'] + [event]
        self.validate(candidate)
        self.repo.save_event(event)
        self.repo.db.execute('UPDATE previews SET consumed=1 WHERE id=?',(analysis_id,))
        self.repo.audit('ai.change.confirmed',event['id'],reviewer,{'analysis_id':analysis_id,'note':note})
        return event

    def dispatch(self, method, path, query, body):
        parts = path.strip('/').split('/')
        dataset = self.repo.dataset()
        if method == 'GET':
            if path == '/api/health':
                return {'status':'ok','provider':self.provider.name,'research_provider':self.research.name,'calculation_version':CALCULATION_VERSION}
            if path == '/api/bootstrap':
                return self.bootstrap()
            if path == '/api/dataset':
                return dataset
            if path == '/api/scenarios':
                return {'scenarios':self.summaries()}
            if path == '/api/alerts':
                return {'alerts':self.alerts()}
            if path == '/api/audit':
                return {'events':[{**dict(r),'payload':json.loads(r['payload'])} for r in self.repo.db.execute('SELECT * FROM audit ORDER BY rowid DESC')]}
            if path == '/api/geography':
                return {'countries':CachedGeographyProvider(dataset).countries()}
            if path == '/api/sources':
                return {'sources':self.repo.sources()}
            if path.startswith('/api/templates/'):
                name = path.rsplit('/',1)[-1]
                allowed = {'research.csv':'research-template.csv','research-rule.schema.json':'research-rule.schema.json','dataset.schema.json':'dataset.schema.json'}
                if name not in allowed:
                    raise KeyError('Template not found')
                target = ROOT / 'data/schemas' / allowed[name]
                return (('text/csv' if name.endswith('.csv') else 'application/schema+json') + '; charset=utf-8',target.read_text(encoding='utf-8'))
            if len(parts)==3 and parts[1]=='change-events':
                return self.repo.event(parts[2])
            if len(parts)==3 and parts[1]=='trials':
                if parts[2] != dataset['trial']['id']:
                    raise KeyError('Trial not found')
                return dataset['trial']
            if len(parts)==4 and parts[1]=='jurisdictions' and parts[3]=='requirements':
                return self.requirements(parts[2].upper(),query.get('as_of',[dataset['as_of']])[0],query.get('scenario_id',[None])[0])
            if len(parts)>=3 and parts[1]=='scenarios':
                plan = self.repo.plan(parts[2])
                if len(parts)==3:
                    return plan
                if parts[3]=='timeline':
                    return {k:plan[k] for k in ('shipments','label_groups','calculation_version','id','scenario_id','input_ids','assumptions','evidence_refs')}
                if parts[3]=='features':
                    return self.provider.replay(plan)
                if parts[3]=='compare' and len(parts)==5:
                    other = self.repo.plan(parts[4])
                    if plan['trial_id'] != other['trial_id']:
                        raise APIError('Cannot compare scenarios from different trials')
                    return {**compare_plans(plan,other),'before_scenario_id':plan['id'],'after_scenario_id':other['id'],'scenario_id':other['id'],'calculation_version':other['calculation_version'],'assumptions':other['assumptions'],'evidence_refs':other['evidence_refs']}
                if parts[3]=='calendar.ics':
                    return ('text/calendar; charset=utf-8',ICSCalendarProvider().export(plan))
        if method == 'POST':
            if path == '/api/demo/reset':
                if 'dataset' in body:
                    return self.reset(body['dataset'])
                fixture = body.get('fixture','demo')
                if fixture not in ('demo','replacement'):
                    raise APIError('Unknown fixture')
                return self.reset(json.loads((ROOT / 'data/demo' / ('trial.json' if fixture=='demo' else 'replacement.json')).read_text(encoding='utf-8')))
            if path == '/api/trials':
                candidate = body.get('dataset')
                if not isinstance(candidate,dict):
                    candidate = copy.deepcopy(dataset)
                    candidate['trial'] = body.get('trial',body)
                    candidate['trial'].setdefault('id',identifier('trial'))
                    candidate['id'] = identifier('dataset')
                self.validate(candidate)
                self.repo.save_dataset(candidate)
                self.repo.set_setting('approved_scenario_id',None)
                self.repo.audit('trial.created',candidate['trial']['id'])
                return candidate['trial']
            if path in ('/api/rules/import/preview','/api/datasets/import/preview'):
                return self.preview(body,'rules' if parts[1]=='rules' else 'dataset')
            if path in ('/api/rules/import/commit','/api/datasets/import/commit'):
                return self.commit(body,'rules' if parts[1]=='rules' else 'dataset')
            if path == '/api/sources/snapshot':
                return self.snapshot(body)
            if path == '/api/research/extract':
                return self.research_extract(body)
            if path == '/api/sources':
                source = {k:body.get(k) for k in ('id','title','url','adapter','jurisdiction','enabled')}
                source['id'], source['title'], source['url'] = str(source.get('id') or identifier('source')).strip(),str(source.get('title') or '').strip(),str(source.get('url') or '').strip()
                source['adapter'] = source.get('adapter') or 'generic'; source['enabled'] = source.get('enabled') is not False
                if not source['title'] or not source['url'].startswith('https://') or source['adapter'] not in ('generic','ecfr','eurlex'):
                    raise APIError('Source title, HTTPS URL, and supported adapter required')
                self.repo.save_source(source); self.repo.audit('source.registered',source['id'],payload=source)
                return source
            if len(parts)==4 and parts[1]=='sources' and parts[3]=='check':
                source = next((s for s in self.repo.sources() if s['id']==parts[2]),None)
                if not source: raise KeyError('Source not found')
                return self.check_source(source)
            if len(parts)==4 and parts[1]=='sources' and parts[3]=='analyze-change':
                return self.analyze_source_change(parts[2])
            if len(parts)==4 and parts[1]=='change-analyses' and parts[3]=='confirm':
                return self.confirm_source_change(parts[2],body)
            if len(parts)==4 and parts[1]=='rules' and parts[3]=='review':
                reviewer, note = str(body.get('reviewer','')).strip(),str(body.get('note','')).strip()
                status = body.get('status')
                if not reviewer or not note or status not in ('verified','needs_review','retired'):
                    raise APIError('Named reviewer, review note, and valid status required')
                source = next((r for r in dataset['rules'] if r['id']==parts[2]),None)
                if not source:
                    raise KeyError('Rule not found')
                if status=='verified' and source['source_tier']=='synthetic':
                    raise APIError('Synthetic evidence cannot be verified; import a cited official or authoritative record',422)
                candidate = copy.deepcopy(dataset)
                previous = next(r for r in candidate['rules'] if r['id']==parts[2])
                new = {**previous,'id':identifier('rule'),'review_status':status,'reviewer':reviewer,'review_note':note,'last_verified_at':now() if status=='verified' else None,'supersedes_id':previous['id']}
                previous['review_status'] = 'retired'
                candidate['rules'].append(new)
                self.validate(candidate)
                self.repo.save_dataset(candidate)
                self.repo.audit('rule.reviewed',new['id'],reviewer,{'supersedes_id':parts[2],'status':status,'note':note})
                parent_id = self.repo.setting('approved_scenario_id')
                plan = self.generate(candidate,parent=self.repo.plan(parent_id) if parent_id else None)
                return {**new,'scenario_id':plan['id'],'scenario_status':'proposed'}
            if path == '/api/change-events':
                event = copy.deepcopy(body)
                if not event.get('title') or not event.get('event_type'):
                    raise APIError('Event title and event_type required')
                if not isinstance(event.get('jurisdiction'),str) or event.get('jurisdiction') not in {j['iso_code'] for j in dataset['jurisdictions']}:
                    raise APIError('Event jurisdiction must be in the trial')
                for key in ('transit_delay_days','permit_delay_days','rework_days'):
                    if not isinstance(event.get(key,0),(int,float)) or event.get(key,0)<0:
                        raise APIError('Event duration must be nonnegative')
                event.setdefault('id',identifier('event'))
                event.setdefault('synthetic',True)
                event.setdefault('description','User supplied planning event')
                event.setdefault('changes',[])
                event.setdefault('effective_from',dataset['as_of'])
                if not isinstance(event['id'],str) or not isinstance(event['synthetic'],bool):
                    raise APIError('Event id must be text and synthetic must be boolean',422)
                if event['synthetic']:
                    event.setdefault('source_url','https://example.invalid/cleared/synthetic-events/' + event['id'])
                    event.setdefault('source_excerpt',event['description'])
                candidate = copy.deepcopy(dataset)
                candidate['events'] = [e for e in self.repo.events() if e.get('event_type')!='source_snapshot'] + [event]
                self.validate(candidate)
                self.repo.save_event(event)
                return event
            if len(parts)==5 and parts[1]=='trials' and parts[3:] == ['scenarios','generate']:
                if parts[2] != dataset['trial']['id']:
                    raise KeyError('Trial not found')
                parent_id = self.repo.setting('approved_scenario_id')
                return self.generate(dataset,parent=self.repo.plan(parent_id) if parent_id else None)
            if len(parts)==4 and parts[1]=='change-events' and parts[3]=='analyze':
                event = self.repo.event(parts[2])
                if event['event_type']=='source_snapshot' and not event.get('changes'):
                    raise APIError('Review and import normalized source changes before analyzing impact',409)
                parent_id = body.get('parent_scenario_id') or self.repo.setting('approved_scenario_id')
                if not parent_id:
                    raise APIError('Generate a baseline before analyzing events',409)
                parent = self.repo.plan(parent_id)
                if parent['status']=='rejected':
                    raise APIError('A rejected scenario cannot be a planning baseline',409)
                if parent['trial_id'] != dataset['trial']['id']:
                    raise APIError('Baseline belongs to a different trial',409)
                repair = body.get('repair')
                if repair and repair not in {o['id'] for o in event.get('repair_options',[])}:
                    raise APIError('Unknown repair option')
                plan = self.generate(dataset,parent=parent,event=event,repair=repair)
                self.repo.audit('change_event.analyzed',event['id'],payload={'scenario_id':plan['id'],'parent_scenario_id':parent_id,'repair':repair})
                changed = [s for s in plan.get('shipments',[]) if s.get('country_code')==event.get('jurisdiction')]
                consequence = '; '.join(f"{s['country_name']} delivery {s['projected_delivery']} ({s['slack_days']} business days slack)" for s in changed) or 'Review the deterministic scenario comparison.'
                notification = self.notifications.send({'id':'review:'+plan['id'],'title':plan['name'],'scenario_id':plan['id'],
                    'cause':event.get('description','Planning change detected'),'consequence':consequence,
                    'review_status':'proposed','deep_link':'/#scenarios?scenario='+plan['id']})
                self.repo.audit('notification.result',plan['id'],payload=notification)
                return plan
            if len(parts)==4 and parts[1]=='scenarios' and parts[3] in ('approve','reject'):
                actor, note = str(body.get('approver','')).strip(), str(body.get('note','')).strip()
                if not actor or not note:
                    raise APIError('A human approver name and decision note are required')
                plan = self.repo.plan(parts[2])
                if plan['trial_id'] != dataset['trial']['id']:
                    raise APIError('Scenario belongs to a different active trial',409)
                if parts[3]=='approve' and plan.get('input_dataset_id') != self.repo.setting('dataset_id'):
                    raise APIError('Dataset changed after this proposal; generate a fresh scenario',409)
                return self.repo.decide(parts[2],'approved' if parts[3]=='approve' else 'rejected',actor,note)
            if len(parts)==4 and parts[1]=='alerts' and parts[3]=='acknowledge':
                alert = next((a for a in self.alerts() if a['id']==parts[2]),None)
                if not alert:
                    raise KeyError('Alert not found')
                actor = str(body.get('actor','local planner'))
                self.repo.db.execute('INSERT OR REPLACE INTO acknowledgements VALUES(?,?,?)',(parts[2],actor,now()))
                self.repo.audit('alert.acknowledged',parts[2],actor)
                return {**alert,'acknowledged':True}
            if path == '/api/assistant/query':
                if not body.get('question'):
                    raise APIError('Question is required')
                if 'what if' in str(body.get('question','')).lower():
                    return self.what_if(body)
                key = body.get('scenario_id') or self.repo.setting('approved_scenario_id')
                plan = self.repo.plan(key)
                if body.get('trial_id') and body['trial_id'] != plan['trial_id']:
                    raise APIError('Trial and scenario do not match')
                comparison = compare_plans(self.repo.plan(plan['parent_scenario_id']),plan) if plan.get('parent_scenario_id') else None
                return self.assistant.answer(body['question'],plan,self.repo.plan_dataset(key),comparison)
            if path == '/api/photon/follow-up':
                question = str(body.get('question','')).strip()
                space_id = str(body.get('space_id','')).strip()
                if not question or not space_id:
                    raise APIError('Photon space_id and question are required')
                key = body.get('scenario_id') or self.repo.setting('approved_scenario_id')
                plan = self.repo.plan(key)
                dataset = self.repo.plan_dataset(key)
                comparison = compare_plans(self.repo.plan(plan['parent_scenario_id']),plan) if plan.get('parent_scenario_id') else None
                answer = self.what_if({'question':question,'scenario_id':key}) if 'what if' in question.lower() else self.assistant.answer(question,plan,dataset,comparison)
                delivery = self.notifications.reply(space_id=space_id,text=answer['answer'],reply_id=identifier('photon_reply')) if hasattr(self.notifications,'reply') else {'delivered':False,'reason':'Photon provider is not active'}
                self.repo.audit('photon.follow_up',key,payload={'space_id':space_id,'delivery':delivery,'question_length':len(question)})
                return {'answer':answer,'delivery':delivery}
            if len(parts)==4 and parts[1]=='scenarios' and parts[3]=='calendar-sync':
                plan = self.repo.plan(parts[2])
                ICSCalendarProvider().export(plan)
                return ICSCalendarProvider().sync(plan)
        raise APIError('Endpoint not found',404)

    def handle(self, method, path, query=None, body=None):
        with self.repo.transaction():
            try:
                return self.dispatch(method,path,query or {},body or {})
            except KeyError as exc:
                raise APIError(str(exc).strip("'"),404) from exc
            except ValueError as exc:
                raise APIError(str(exc),422) from exc
