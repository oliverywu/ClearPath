"""Shipment outlook formulas shared by the local app and the deployed Chalk resolvers.

chalk/logistics_formulas.py must stay a byte-identical copy of this file (a unit test
enforces it), so the numbers the Photon agent states are the same whether they come
from a Chalk online query or from the local fallback.

Standard library only: the Chalk deployment and the app both import it unchanged.
"""
from datetime import date, timedelta
import json

CASES = ("best", "likely", "worst")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _business_add(value, days, holidays):
    current = date.fromisoformat(value[:10])
    step = 1 if days >= 0 else -1
    remaining = abs(int(days))
    while remaining:
        current += timedelta(days=step)
        if current.weekday() < 5 and current.isoformat() not in holidays:
            remaining -= 1
    return current.isoformat()


def _business_diff(start, end, holidays):
    if start == end:
        return 0
    if start > end:
        return -_business_diff(end, start, holidays)
    current, finish, days = date.fromisoformat(start[:10]), date.fromisoformat(end[:10]), 0
    while current < finish:
        current += timedelta(days=1)
        if current.weekday() < 5 and current.isoformat() not in holidays:
            days += 1
    return days


def _short(iso):
    value = date.fromisoformat(iso[:10])
    return f"{_MONTHS[value.month - 1]} {value.day}"


def outlook(dispatch_date, target, legs_json, delay_days, holidays_json):
    """Best / likely / worst delivery, ship-by dates and worst-case slack.

    legs_json: JSON list of {"best","likely","worst"} business-day ranges for the
    post-dispatch legs (transit, customs, depot, last mile). delay_days is an active
    disruption on the route and applies to every case.
    """
    holidays = set(json.loads(holidays_json))
    legs = json.loads(legs_json)
    totals = {case: sum(int(leg[case]) for leg in legs) + int(delay_days) for case in CASES}
    delivery = {case: _business_add(dispatch_date, totals[case], holidays) for case in CASES}
    return {
        "delivery_best_at": delivery["best"],
        "delivery_likely_at": delivery["likely"],
        "delivery_worst_at": delivery["worst"],
        "ship_by_likely": _business_add(target, -totals["likely"], holidays),
        "ship_by_safe": _business_add(target, -totals["worst"], holidays),
        "worst_case_slack_days": float(_business_diff(delivery["worst"], target, holidays)),
    }


def agent_answer(country_name, planning_date, dispatch_date, target, gateway_airport,
                 customs_source, legs_json, delay_days, holidays_json):
    """The one sentence the messaging agent may say about a shipment's timing.

    Every number in it is computed here from the same inputs, so the agent never
    states a date the planner did not produce.
    """
    values = outlook(dispatch_date, target, legs_json, delay_days, holidays_json)
    customs = json.loads(legs_json)[1] if len(json.loads(legs_json)) > 1 else {"best": 0, "worst": 0}
    if int(customs["worst"]) == 0:
        customs_text = "no import clearance (domestic shipment)"
    else:
        customs_text = (f"{customs['best']}-{customs['worst']} business days at {gateway_airport} "
                        f"({customs_source})")
    window = sorted(day for day in json.loads(holidays_json) if planning_date[:10] <= day <= target[:10])
    late_note = ", after the safe date" if dispatch_date[:10] > values["ship_by_safe"] else ""
    return (
        f"{country_name}: dispatch by {_short(values['ship_by_safe'])} to be safe "
        f"(by {_short(values['ship_by_likely'])} if transit and customs run as expected). "
        f"The current plan dispatches {_short(dispatch_date)}{late_note}. "
        f"Delivery {_short(values['delivery_best_at'])} to {_short(values['delivery_worst_at'])}, "
        f"likely {_short(values['delivery_likely_at'])}; target {_short(target)}. "
        f"Customs: {customs_text}. "
        f"Non-working days in the window: {', '.join(_short(day) for day in window) if window else 'none'}."
    )
