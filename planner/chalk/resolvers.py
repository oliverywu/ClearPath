from chalk.features import Features, online
from features import Shipment, CountryPlan, Route
from datetime import date, timedelta
import json

import logistics_formulas


@online
def shipment_transit(baseline: Shipment.baseline_transit_days, disruption: Shipment.disruption_delay_days, customs: Shipment.customs_buffer_days) -> Shipment.effective_transit_days:
    return max(0,baseline) + max(0,disruption) + max(0,customs)


@online
def route_transit(baseline: Route.baseline_transit_days, disruption: Route.disruption_delay_days) -> Route.effective_transit_days:
    return max(0,baseline) + max(0,disruption)


@online
def country_readiness(coverage: CountryPlan.verification_coverage, unresolved: CountryPlan.unresolved_requirement_count) -> CountryPlan.readiness_score:
    return max(0, min(100,coverage * 100 - unresolved * 10))


@online
def projected_delivery(start: Shipment.ready_date, durations: Shipment.duration_days_json, holidays: Shipment.holidays_json) -> Shipment.projected_delivery_at:
    current, excluded = date.fromisoformat(start[:10]), set(json.loads(holidays))
    for duration in json.loads(durations):
        remaining = int(duration)
        while remaining:
            current += timedelta(days=1)
            if current.weekday() < 5 and current.isoformat() not in excluded:
                remaining -= 1
    return current.isoformat()


@online
def slack(projected: Shipment.projected_delivery_at, target: Shipment.target_delivery, holidays: Shipment.holidays_json) -> Shipment.slack_days:
    start, end = sorted((projected,target))
    current, finish = date.fromisoformat(start[:10]),date.fromisoformat(end[:10])
    excluded, days = set(json.loads(holidays)),0
    while current < finish:
        current += timedelta(days=1)
        if current.weekday()<5 and current.isoformat() not in excluded:
            days += 1
    return days if projected<=target else -days


@online
def score(slack: Shipment.slack_days, blocked: Shipment.constraint_blocked, synthetic: Shipment.synthetic_count, model_json: Shipment.risk_model_json) -> Shipment.risk_score:
    model = json.loads(model_json)
    base = model['blocked_base'] + min(model['delay_cap'],max(0,-slack)*model['delay_weight']) if blocked or slack<0 else max(model['minimum'],model['base']-slack*model['slack_weight'])
    return min(model['maximum'],base + (model['synthetic_penalty'] if synthetic else 0))


@online
def band(slack: Shipment.slack_days, blocked: Shipment.constraint_blocked, threshold: Shipment.low_slack_days) -> Shipment.risk_band:
    return 'blocked' if blocked or slack<0 else 'at_risk' if slack<=threshold else 'on_track'


# --- Shipment outlook (Chalk idea 1) -------------------------------------
# The same formulas as packages/feature_provider/logistics.py (byte-identical copy in
# logistics_formulas.py), so the app can check every value Chalk returns.
@online
def shipment_outlook(
    dispatch: Shipment.dispatch_date,
    target: Shipment.target_delivery,
    legs: Shipment.leg_ranges_json,
    delay: Shipment.disruption_delay_days,
    holidays: Shipment.holidays_json,
) -> Features[
    Shipment.delivery_best_at,
    Shipment.delivery_likely_at,
    Shipment.delivery_worst_at,
    Shipment.ship_by_likely,
    Shipment.ship_by_safe,
    Shipment.worst_case_slack_days,
]:
    return Shipment(**logistics_formulas.outlook(dispatch, target, legs, delay, holidays))


@online
def shipment_agent_answer(
    country: Shipment.country_name,
    planning: Shipment.planning_date,
    dispatch: Shipment.dispatch_date,
    target: Shipment.target_delivery,
    gateway: Shipment.gateway_airport,
    source: Shipment.customs_source,
    legs: Shipment.leg_ranges_json,
    delay: Shipment.disruption_delay_days,
    holidays: Shipment.holidays_json,
) -> Shipment.agent_answer:
    return logistics_formulas.agent_answer(country, planning, dispatch, target, gateway, source, legs, delay, holidays)
