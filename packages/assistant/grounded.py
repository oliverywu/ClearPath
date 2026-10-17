"""Read-only, deterministic assistant tools over stored plans and cited evidence."""
import re


def answer_question(question, scenario, dataset, comparison=None):
    question = str(question).strip()[:4000]
    low = question.lower()
    if re.search(r'\b(approve|reject|delete|commit|send|modify|overwrite)\b', low):
        return {'answer':'I can explain stored requirements, features, and comparisons. I cannot approve, reject, or modify plans. Use the scenario review controls for a human decision.','citations':[],'suggested_questions':['Why are shipments at risk?','What repair options are available?']}
    selected = [s for s in scenario['shipments'] if s['country_name'].lower() in low or re.search(r'\b' + re.escape(s['country_code'].lower()) + r'\b', low)]
    if not selected:
        selected = sorted(scenario['shipments'],key=lambda s:(-s.get('risk_score',0),s['country_code']))[:5]
    codes = {s['country_code'] for s in selected}
    active_ids = set(scenario.get('input_ids',{}).get('rules',[])) if isinstance(scenario.get('input_ids'),dict) else set()
    rules = [r for r in scenario.get('rules',dataset.get('rules',[])) if r['jurisdiction'] in codes and (not active_ids or r.get('id') in active_ids)]
    citations = [{'title':r.get('source_title',r['requirement_key']),'url':r['source_url'],'excerpt':r['source_excerpt'],'status':r['review_status'],'requirement_key':r['requirement_key'],'effective_from':r['effective_from']} for r in rules if r.get('source_url') and r.get('source_excerpt')]
    unique = {(r['url'],r['excerpt']):r for r in citations}
    lines = [f"Stored scenario {scenario['name']} ({scenario.get('status','proposed')}), calculated as of {scenario['as_of']}."]
    for shipment in selected:
        reasons = shipment.get('reasons',[])
        reasons_text = '; '.join(str(r.get('explanation',r.get('message',r))) if isinstance(r,dict) else str(r) for r in reasons)
        lines.append(f"{shipment['country_name']}: {shipment['risk_band'].replace('_',' ')}, {shipment['slack_days']} business days of slack; projected delivery {shipment['projected_delivery']} against target {shipment['target_delivery']}. Route: {shipment.get('route_name','unassigned')}. {reasons_text}")
    if any(word in low for word in ('split','repair','what if','alternative','expedite')):
        options = scenario.get('repair_options',[])
        lines.extend(f"Proposed option: {o['title']}. {o.get('description','')} Trade-off: {o.get('tradeoffs','Review the scenario comparison.')}" for o in options)
        if not options:
            lines.append('No event repair is stored for this scenario. Analyze an event to calculate a separate proposal before assessing a split or route change.')
    if comparison and ('change' in low or 'why' in low):
        lines.append('Stored causal chain: ' + '; '.join(' → '.join(v.get('steps',[])) if isinstance(v,dict) else str(v) for v in comparison.get('causal_chain',[]) if not isinstance(v,dict) or v.get('country_code') in codes))
    if not citations:
        lines.append('No cited rule supports a legal conclusion for this selection. Import and review source evidence before relying on a requirement.')
    elif any(r.get('review_status') != 'verified' for r in rules):
        lines.append('Some or all selected requirements are synthetic or awaiting review. These are planning assumptions, not verified legal requirements.')
    lines.append('Decision support only; this answer does not approve changes or provide regulatory or legal advice.')
    return {'answer':'\n\n'.join(lines),'citations':list(unique.values())[:20],'suggested_questions':['Why are shipments at risk?','What repair options are available?','Which evidence supports these requirements?'],'scenario_id':scenario['id'],'calculation_version':scenario['calculation_version'],'tools_used':['read_scenario','read_shipment_features','read_source_evidence']}
