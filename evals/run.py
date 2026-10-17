"""Run the checked-in gold set; AI cases run only when its provider is configured."""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from apps.api.service import APIError, Service


def score_text(answer, case):
    low = answer.lower()
    return all(term.lower() in low for term in case.get('must_include', []))


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
