"""Pure functions shared by local and deployed Chalk resolvers."""
from datetime import date, timedelta
import json
def effective_transit(baseline_transit_days, disruption_delay_days, customs_buffer_days):
    return max(0, baseline_transit_days) + max(0, disruption_delay_days) + max(0, customs_buffer_days)


def risk_score(slack_days, constraint_blocked, synthetic_count, model):
    model = json.loads(model) if isinstance(model,str) else model
    blocked = constraint_blocked or slack_days < 0
    base = model['blocked_base'] + min(model['delay_cap'],max(0,-slack_days)*model['delay_weight']) if blocked else max(model['minimum'],model['base']-slack_days*model['slack_weight'])
    return min(model['maximum'],base + (model['synthetic_penalty'] if synthetic_count else 0))


def risk_band(slack_days, constraint_blocked, low_slack_days):
    if constraint_blocked or slack_days < 0:
        return 'blocked'
    return 'at_risk' if slack_days <= low_slack_days else 'on_track'


def projected_delivery(start_date, durations_json, holidays_json):
    current = date.fromisoformat(start_date[:10])
    holidays = set(json.loads(holidays_json))
    for duration in json.loads(durations_json):
        days = int(duration)
        while days:
            current += timedelta(days=1)
            if current.weekday()<5 and current.isoformat() not in holidays:
                days -= 1
    return current.isoformat()


def delivery_slack(projected, target, holidays_json):
    holidays = set(json.loads(holidays_json))
    start, end = sorted((projected,target))
    current, finish, days = date.fromisoformat(start[:10]),date.fromisoformat(end[:10]),0
    while current<finish:
        current += timedelta(days=1)
        if current.weekday()<5 and current.isoformat() not in holidays:
            days += 1
    return days if projected<=target else -days
