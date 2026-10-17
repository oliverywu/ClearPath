"""Run the checked-in gold set; AI cases run only when its provider is configured."""
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from apps.api.service import APIError, Service


def score_text(answer, case):
    low = answer.lower()
    return all(term.lower() in low for term in case.get('must_include', []))


MONTHS = ('Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec')


def short(iso):
    return f"{MONTHS[int(iso[5:7]) - 1]} {int(iso[8:10])}"


def ship_by_accuracy(service, case):
    """Ask the agent about every country; each answer must state the planner's own dates."""
    scenario = service.bootstrap()['approved_scenario']
    failures = []
    for shipment in scenario['shipments']:
        answer = service.handle('POST','/api/assistant/query',body={'question':f"When does {shipment['country_name']} need to ship?",'scenario_id':scenario['id']})['answer']
        features = shipment['features']
        expected = [features['ship_by_safe'],features['ship_by_likely'],features['delivery_likely_at'],features['delivery_worst_at'],shipment['target_delivery']]
        missing = [day for day in expected if not re.search(r'\b' + re.escape(short(day)) + r'\b', answer)]
        if missing or 'dispatch by' not in answer:
            failures.append(shipment['country_code'])
    return not failures, {'countries':len(scenario['shipments']),'mismatched':failures}


def run():
    cases = json.loads((ROOT / 'evals/gold.json').read_text(encoding='utf-8'))['cases']
    results = []
    with tempfile.TemporaryDirectory() as folder:
        service = Service(Path(folder) / 'eval.sqlite3')
        baseline = service.bootstrap()['approved_scenario']
        germany = next(e for e in service.repo.events() if e.get('jurisdiction') == 'DE')
        germany_plan = service.handle('POST', f"/api/change-events/{germany['id']}/analyze", body={'parent_scenario_id': baseline['id']})
        scenarios = {'baseline': baseline['id'], 'germany_event': germany_plan['id']}
        for case in cases:
            kind = case['kind']
            if kind in ('research_extraction', 'source_change'):
                results.append({'id':case['id'],'kind':kind,'status':'ready_for_live_run','passed':None,
                                'reason':'Requires configured AI_RESEARCH_PROVIDER and credentials.'})
                continue
            try:
                if kind == 'ship_by_accuracy':
                    target = service
                    if case.get('fixture'):
                        target = Service(Path(folder) / (case['id'] + '.sqlite3'), ROOT / 'data/demo' / (case['fixture'] + '.json'))
                    passed, detail = ship_by_accuracy(target, case)
                    if target is not service:
                        target.repo.close()
                    results.append({'id':case['id'],'kind':kind,'status':'passed' if passed else 'failed','passed':passed,**detail})
                    continue
                if kind == 'planner_question':
                    output = service.handle('POST','/api/assistant/query',body={'question':case['question'],'scenario_id':scenarios[case['scenario']]})
                    passed = score_text(output['answer'],case) and (not case.get('must_cite') or bool(output.get('citations')))
                elif kind == 'what_if':
                    before = len(service.repo.plans(baseline['trial_id']))
                    output = service.handle('POST','/api/assistant/query',body={'question':case['question'],'scenario_id':baseline['id']})
                    passed = score_text(output['answer'],case) and bool(output['comparison']['changes']) == case['must_change'] and len(service.repo.plans(baseline['trial_id'])) == before
                else:
                    try:
                        service.handle('POST','/api/assistant/query',body={'question':case['question'],'scenario_id':baseline['id']})
                        passed = False
                    except APIError as exc:
                        passed = exc.status == case['expected_status']
                results.append({'id':case['id'],'kind':kind,'status':'passed' if passed else 'failed','passed':passed})
            except Exception as exc:
                results.append({'id':case['id'],'kind':kind,'status':'failed','passed':False,'reason':type(exc).__name__})
        service.repo.close()
    scored = [r for r in results if r['passed'] is not None]
    report = {'gold_cases':len(cases),'executed':len(scored),'passed':sum(r['passed'] for r in scored),
              'pass_rate':round(sum(r['passed'] for r in scored)/len(scored),3) if scored else None,
              'ready_for_live_run':sum(r['status']=='ready_for_live_run' for r in results),'results':results}
    print(json.dumps(report,indent=2))
    return 0 if all(r['passed'] for r in scored) else 1


if __name__ == '__main__':
    raise SystemExit(run())
