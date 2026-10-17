"""Identical allowlisted feature contract for offline and authenticated Chalk queries."""
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Protocol
from urllib.request import Request, urlopen
from .formulas import effective_transit


class FeatureProvider(Protocol):
    def shipment(self, shipment, as_of=None): ...
    def enrich(self, plan): ...


class LocalFeatureProvider:
    name = 'local'
    def shipment(self, shipment, as_of=None):
        features = dict(shipment.get('features',{}))
        features.update({k:shipment[k] for k in ('slack_days','risk_score','risk_band','projected_delivery') if k in shipment})
        features['projected_delivery_at'] = shipment['projected_delivery']
        features['effective_transit_days'] = effective_transit(features.get('baseline_transit_days',0),features.get('disruption_delay_days',0),features.get('customs_buffer_days',0))
        return {'features':features,'provider':'local','as_of':as_of,'calculation_version':'cft-features-1','fallback_reason':None}

    def enrich(self, plan):
        results = [self.shipment(shipment,plan['as_of']) for shipment in plan['shipments']]
        for shipment,result in zip(plan['shipments'],results):
            shipment['features'] = result['features']
            shipment['feature_query'] = {k:v for k,v in result.items() if k != 'features'}
        plan['provider'] = {'active':self.name,'requested':self.name,'fallback':False,'query_count':len(results)}
        plan['feature_snapshot'] = self.namespace_snapshot(plan)
        return plan

    def namespace_snapshot(self, plan):
        return {'scenario':{**dict(plan['metrics']),'countries_blocked':plan['metrics']['blocked_shipments']},
                'country_plan':{s['country_code']:{key:s['features'].get(key) for key in ('permit_lead_days','required_language_count','verification_coverage','unresolved_requirement_count','readiness_score')} for s in plan['shipments']},
                'label_group':{g['id']:{'country_count':len(g['country_codes']),'language_count':len(g['languages']),'estimated_pages':g['estimated_pages'],'compatible':g.get('compatible',True),'rework_days':g.get('rework_days',0),'affected_by_change':g.get('rework_days',0)>0} for g in plan['label_groups']},
                'route':{s['route_id']:{'effective_transit_days':s['features']['effective_transit_days'],'disruption_delay_days':s['features'].get('disruption_delay_days',0)} for s in plan['shipments']},
                'as_of':plan['as_of'],'calculation_version':'cft-features-1'}

    def replay(self, scenario):
        # Stored feature snapshots are point-in-time values, never recomputed with today's data.
        return {'as_of':scenario['as_of'],'scenario_id':scenario['id'],'features':[dict(s['features']) for s in scenario['shipments']],'source':'immutable scenario snapshot'}


class ChalkFeatureProvider(LocalFeatureProvider):
    name = 'chalk'
    outputs = ['shipment.effective_transit_days','shipment.risk_score','shipment.risk_band','shipment.projected_delivery_at','shipment.slack_days']

    def __init__(self):
        self.api = os.getenv('CHALK_API_SERVER','https://api.chalk.ai').rstrip('/')
        self.query_server = os.getenv('CHALK_QUERY_SERVER',self.api).rstrip('/')
        self.environment = os.getenv('CHALK_ENVIRONMENT','')
        self.token = os.getenv('CHALK_ACCESS_TOKEN','')
        self.token_expiry = float('inf') if self.token else 0
        self.timeout = float(os.getenv('CHALK_TIMEOUT_SECONDS','5'))

    def _post(self, url, payload, token=None):
        if not url.startswith('https://'):
            raise ValueError('Chalk endpoint must use HTTPS')
        headers = {'Content-Type':'application/json'}
        if token:
            headers.update({'Authorization':'Bearer ' + token,'x-chalk-env-id':self.environment,'x-chalk-deployment-type':'engine'})
        request = Request(url,data=json.dumps(payload).encode(),headers=headers,method='POST')
        with urlopen(request,timeout=self.timeout) as response:
            return json.load(response)

    def authenticate(self):
        if self.token and time.time() < self.token_expiry:
            return
        response = self._post(self.api + '/v1/oauth/token',{'client_id':os.getenv('CHALK_CLIENT_ID',''),'client_secret':os.getenv('CHALK_CLIENT_SECRET',''),'grant_type':'client_credentials'})
        self.token = response['access_token']
        self.token_expiry = time.time() + response.get('expires_in',3600) - 30

    def shipment(self, shipment, as_of=None):
        local = super().shipment(shipment,as_of)
        try:
            self.authenticate()
            f = local['features']
            inputs = {'shipment.id':shipment['id'],'shipment.baseline_transit_days':f.get('baseline_transit_days',0),'shipment.disruption_delay_days':f.get('disruption_delay_days',0),'shipment.customs_buffer_days':f.get('customs_buffer_days',0),
                      'shipment.ready_date':shipment['milestones'][0]['projected_date'],'shipment.duration_days_json':json.dumps([m['duration_days'] for m in shipment['milestones']]),'shipment.holidays_json':json.dumps(f.get('calendar_holidays',[])),
                      'shipment.target_delivery':shipment['target_delivery'],'shipment.constraint_blocked':bool(f.get('unresolved_requirement_count') or not f.get('temperature_compatible',True) or not f.get('label_ready',True) or shipment.get('route_id')=='missing'),
                      'shipment.synthetic_count':f.get('synthetic_count',0),'shipment.risk_model_json':json.dumps(f['risk_model']),'shipment.low_slack_days':f.get('low_slack_days',3)}
            response = self._post(self.query_server + '/v1/query/online',{'inputs':inputs,'outputs':self.outputs},self.token)
            if response.get('errors'):
                raise ValueError('Chalk query returned feature errors')
            data = response.get('data',[])
            values = {item['field']:item.get('value') for item in data} if isinstance(data,list) else data
            if any(key not in values or values[key] is None for key in self.outputs):
                raise ValueError('Incomplete Chalk feature response')
            # Parity is a safety invariant: different deployed resolver versions cannot change approval inputs.
            expected = {'shipment.'+key:f[key] for key in ('effective_transit_days','risk_score','risk_band','projected_delivery_at','slack_days')}
            if any(values[key] != expected[key] for key in self.outputs):
                raise ValueError('Chalk/local feature parity mismatch')
            local['features'].update({key.split('.',1)[1]:values[key] for key in self.outputs})
            return {**local,'provider':'chalk','query_id':response.get('meta',{}).get('query_id')}
        except Exception as exc:
            # Never leak service response bodies, credentials, or request headers into diagnostics.
            return {**local,'fallback_reason':type(exc).__name__ + ': remote query unavailable or parity check failed'}

    def enrich(self, plan):
        # Authenticate once; bounded pool avoids 25 serial network timeout waits.
        try:
            self.authenticate()
        except Exception:
            local = LocalFeatureProvider().enrich(plan)
            local['provider'] = {'active':'local','requested':'chalk','fallback':True,'reason':'Chalk authentication unavailable','query_count':0}
            return local
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda s:self.shipment(s,plan['as_of']),plan['shipments']))
        for shipment,result in zip(plan['shipments'],results):
            shipment['features'] = result['features']
            shipment['feature_query'] = {k:v for k,v in result.items() if k != 'features'}
        fallback = any(r['provider'] != 'chalk' for r in results)
        plan['provider'] = {'active':'local' if fallback else 'chalk','requested':'chalk','fallback':fallback,'query_count':len(results),'reason':next((r['fallback_reason'] for r in results if r.get('fallback_reason')),None)}
        plan['feature_snapshot'] = self.namespace_snapshot(plan)
        return plan


def configured_provider():
    configured = os.getenv('CHALK_ACCESS_TOKEN') or (os.getenv('CHALK_CLIENT_ID') and os.getenv('CHALK_CLIENT_SECRET'))
    return ChalkFeatureProvider() if configured and os.getenv('FEATURE_PROVIDER','auto') != 'local' else LocalFeatureProvider()
