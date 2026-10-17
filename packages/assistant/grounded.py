"""Read-only, deterministic assistant tools over stored plans and cited evidence."""
import re


def _select_shipments(question, shipments):
    """Prefer country names; accept codes only when clearly expressed as codes."""
    low = question.lower()
    named = [s for s in shipments if re.search(r'(?<!\w)' + re.escape(s['country_name'].lower()) + r'(?!\w)', low)]
    if named:
        return named
    explicit_codes = set(re.findall(r'\b[A-Z]{2}\b', question))
    explicit_codes.update(code.upper() for code in re.findall(r'\bcountry\s*:\s*([a-z]{2})\b', low))
    return [s for s in shipments if s['country_code'].upper() in explicit_codes]


def _days(value):
    return f"{value} business {'day' if value == 1 else 'days'}"


def _reason_text(reasons):
    values = [str(r.get('explanation',r.get('message',''))) if isinstance(r,dict) else str(r) for r in reasons]
    cleaned = [re.sub(r'\b1 business days\b','1 business day',value.strip().rstrip('.')) for value in values if value.strip()]
    return '; '.join(dict.fromkeys(cleaned))


def answer_question(question, scenario, dataset, comparison=None):
    question = str(question).strip()[:4000]
    low = question.lower()
    if re.search(r'\b(approve|reject|delete|commit|send|modify|overwrite)\b', low):
        return {'answer':'I can explain stored requirements, features, and comparisons. I cannot approve, reject, or modify plans. Use the scenario review controls for a human decision.','citations':[],'suggested_questions':['Why are shipments at risk?','What repair options are available?']}
    selected = _select_shipments(question,scenario['shipments'])
    if not selected:
        selected = sorted(scenario['shipments'],key=lambda s:(-s.get('risk_score',0),s['country_code']))[:5]
    codes = {s['country_code'] for s in selected}
    active_ids = set(scenario.get('input_ids',{}).get('rules',[])) if isinstance(scenario.get('input_ids'),dict) else set()
    rules = [r for r in scenario.get('rules',dataset.get('rules',[])) if r['jurisdiction'] in codes and (not active_ids or r.get('id') in active_ids)]
    citations = [{'title':r.get('source_title',r['requirement_key']),'url':r['source_url'],'excerpt':r['source_excerpt'],'status':r['review_status'],'requirement_key':r['requirement_key'],'effective_from':r['effective_from']} for r in rules if r.get('source_url') and r.get('source_excerpt')]
    unique = {(r['url'],r['excerpt']):r for r in citations}
    lines = []
    if re.search(r'\b(ship|ship-by|dispatch|deadline|when)\b', low):
        # Timing questions are answered only with the outlook features (Chalk query or
        # local fallback), so every date the agent states matches the planner.
        facts = [s for s in selected if s.get('features',{}).get('agent_answer')]
        for shipment in facts:
            source = 'Chalk feature query' if shipment['features'].get('outlook_source') == 'chalk' else 'local planner calculation'
            lines.append(f"{shipment['features']['agent_answer']} (Source: {source}.)")
        if facts:
            selected = [s for s in selected if s not in facts]
    for shipment in selected:
        risk = shipment['risk_band'].replace('_',' ')
        slack_days = shipment['slack_days']
        reason = _reason_text(shipment.get('reasons',[]))
        if slack_days < 0:
            timing = f"it is projected to arrive {_days(abs(slack_days))} late"
        elif slack_days == 0:
            timing = "it has no delivery slack"
        else:
            timing = f"it has {_days(slack_days)} of delivery slack"
        lead = f"{shipment['country_name']} is {risk} because {timing}."
        schedule = f"Projected delivery is {shipment['projected_delivery']}, against a target of {shipment['target_delivery']}, via {shipment.get('route_name','an unassigned route')}."
        reason_parts = [part for part in reason.split('; ') if not (slack_days < 0 and ('misses target' in part.lower() or 'delivery slack' in part.lower()))]
        cause = f"Primary scenario drivers: {'; '.join(reason_parts)}." if reason_parts else ''
        lines.append(' '.join(part for part in (lead,schedule,cause) if part))
    lines.append(f"Scenario: {scenario['name']} ({scenario.get('status','proposed')}), calculated as of {scenario['as_of']}.")
    if any(word in low for word in ('split','repair','what if','alternative','expedite')):
        options = scenario.get('repair_options',[])
        lines.extend(f"Proposed option: {o['title']}. {o.get('description','')} Trade-off: {o.get('tradeoffs','Review the scenario comparison.')}" for o in options)
        if not options:
            lines.append('No event repair is stored for this scenario. Analyze an event to calculate a separate proposal before assessing a split or route change.')
    if comparison and 'change' in low:
        chains = [' → '.join(v.get('steps',[])) if isinstance(v,dict) else str(v) for v in comparison.get('causal_chain',[]) if not isinstance(v,dict) or v.get('country_code') in codes]
        chains = list(dict.fromkeys(chain for chain in chains if chain))
        if chains:
            lines.append('Change path: ' + '; '.join(chains))
    if not citations:
        lines.append('No cited rule supports a legal conclusion for this selection. Import and review source evidence before relying on a requirement.')
    elif any(r.get('review_status') != 'verified' for r in rules):
        lines.append('Evidence note: this explanation includes synthetic or unreviewed planning assumptions.')
    lines.append('Decision support only; no plan changes are approved by this answer.')
    return {'answer':'\n\n'.join(lines),'citations':list(unique.values())[:20],'suggested_questions':['Why are shipments at risk?','What repair options are available?','Which evidence supports these requirements?'],'scenario_id':scenario['id'],'calculation_version':scenario['calculation_version'],'tools_used':['read_scenario','read_shipment_features','read_source_evidence']}
