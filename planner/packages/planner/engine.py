"""Pure deterministic planning. Every jurisdiction, duration and change is input data."""
from copy import deepcopy
from datetime import date, timedelta
from hashlib import sha256
import json
import math

CALCULATION_VERSION = "cleared-1.0.0"


def stable_id(prefix, value):
    return prefix + "-" + sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:12]


def business_add(value, days, holidays=()):
    current = date.fromisoformat(value) if isinstance(value, str) else value
    direction = 1 if days >= 0 else -1
    remaining = abs(int(days))
    holidays = set(holidays)
    while remaining:
        current += timedelta(days=direction)
        if current.weekday() < 5 and current.isoformat() not in holidays:
            remaining -= 1
    return current.isoformat()


def business_diff(start, end, holidays=()):
    if start == end:
        return 0
    if start > end:
        return -business_diff(end, start, holidays)
    current, result = date.fromisoformat(start), 0
    finish = date.fromisoformat(end)
    while current < finish:
        current += timedelta(days=1)
        if current.weekday() < 5 and current.isoformat() not in holidays:
            result += 1
    return result


def leg_range(route, field):
    """Best / likely / worst business days for one route leg. A route without a range is exact."""
    likely = route.get(field, 0)
    given = route.get(field + "_range") or {}
    best, worst = given.get("best", likely), given.get("worst", likely)
    return {"best": min(best, likely), "likely": likely, "worst": max(worst, likely)}


def delivery_range(route, transit_delay, dispatch_date, target, holidays=()):
    """Delivery dates and ship-by dates when transit and customs vary within their ranges.

    The likely case matches the main schedule. The safe ship-by date is the latest dispatch
    that still meets the target if every post-dispatch leg takes its worst-case duration.
    """
    legs = [leg_range(route, f) for f in ("transit_days", "customs_days", "depot_days", "last_mile_days")]
    totals = {case: sum(leg[case] for leg in legs) + transit_delay for case in ("best", "likely", "worst")}
    delivery = {case: business_add(dispatch_date, days, holidays) for case, days in totals.items()}
    ship_by = {"likely": business_add(target, -totals["likely"], holidays), "safe": business_add(target, -totals["worst"], holidays)}
    return {"delivery": delivery, "ship_by": ship_by, "post_dispatch_days": totals,
            "worst_case_slack_days": business_diff(delivery["worst"], target, holidays)}


def select_rules(dataset, as_of=None):
    """Select approved evidence or explicitly simulated evidence; never unreviewed rules."""
    when = as_of or dataset["as_of"]
    grouped = {}
    for rule in dataset["rules"]:
        if rule.get("review_status") not in {"verified", "synthetic"}:
            continue
        if rule["effective_from"] > when or (rule.get("effective_to") and when >= rule["effective_to"]):
            continue
        key = (rule["jurisdiction"], rule["requirement_key"])
        priority = (rule["review_status"] == "verified", rule["effective_from"], rule.get("id", ""))
        if key not in grouped or priority > grouped[key][0]:
            grouped[key] = (priority, deepcopy(rule))
    return [grouped[key][1] for key in sorted(grouped)]


def signature(rules):
    values = {rule["requirement_key"]: rule["value"] for rule in rules}
    return {"languages": sorted(set(values.get("label.languages", []))),
            "mandatory_fields": sorted(set(values.get("label.mandatory_fields", []))),
            "prohibited_fields": sorted(set(values.get("label.prohibited_fields", []))),
            "expiry_format": values.get("label.expiry_format", "unspecified"),
            "exclusive_template": values.get("label.exclusive_template"),
            "sponsor_constraint": values.get("label.sponsor_constraint", "common"),
            "blinding_constraint": values.get("label.blinding_constraint", "blinded")}


def compatibility(signatures, config):
    languages = set().union(*(set(s["languages"]) for s in signatures))
    required = set().union(*(set(s["mandatory_fields"]) for s in signatures))
    prohibited = set().union(*(set(s["prohibited_fields"]) for s in signatures))
    reasons = []
    conflicts = required & prohibited
    if conflicts:
        reasons.append({"code": "field_conflict", "detail": "Required and prohibited fields conflict: " + ", ".join(sorted(conflicts))})
    for key in ("expiry_format", "sponsor_constraint", "blinding_constraint"):
        if len({s[key] for s in signatures}) > 1:
            reasons.append({"code": key + "_conflict", "detail": key.replace("_", " ") + " differs"})
    if len(signatures) > 1 and any(s["exclusive_template"] for s in signatures):
        reasons.append({"code": "exclusive_template", "detail": "A national template requires a separate artwork"})
    if any(not s["languages"] for s in signatures):
        reasons.append({"code": "missing_languages", "detail": "Mandatory language requirements are missing"})
    pages = config.get("base_label_pages", 2) + math.ceil(len(languages) / config.get("languages_per_page", 2))
    if pages > config.get("booklet_capacity_pages", 8):
        reasons.append({"code": "booklet_capacity", "detail": f"{pages} pages exceed booklet capacity"})
    return reasons, pages


def group_labels(country_rules, config, separate=()):
    """Stable greedy clique cover with group-wide capacity and field checks."""
    groups = []
    for country in sorted(country_rules):
        sig = signature(country_rules[country])
        rejected = []
        target = None
        for group in groups:
            if country in separate or set(group["country_codes"]) & set(separate):
                rejected.append({"code": "operational_split", "detail": "Separate artwork requested"})
                continue
            failures, _ = compatibility(group["signatures"] + [sig], config)
            if failures:
                rejected.extend(failures)
            else:
                target = group
                break
        if target is None:
            target = {"country_codes": [], "signatures": [], "reasons": rejected}
            groups.append(target)
        target["country_codes"].append(country)
        target["signatures"].append(sig)
    for group in groups:
        signatures = group.pop("signatures")
        failures, pages = compatibility(signatures, config)
        if not group["reasons"]:
            group["reasons"] = [{"code": "shared_compatible" if len(group["country_codes"]) > 1 else "single_country", "detail": "All members share compatible fields, expiry format, sponsor and blinding constraints; combined mandatory languages fit booklet capacity."}]
        group.update(id=stable_id("label", group["country_codes"]),
                     languages=sorted(set().union(*(set(s["languages"]) for s in signatures))),
                     mandatory_fields=sorted(set().union(*(set(s["mandatory_fields"]) for s in signatures))),
                     estimated_pages=pages, compatible=not failures, rework_days=0,
                     incompatibilities=failures,
                     compatibility_decision="compatible" if not failures else "blocked")
    return groups


def _event_active(event, as_of):
    return event and event.get("effective_from", as_of) <= as_of and (not event.get("effective_to") or event["effective_to"] > as_of)


def generate_plan(dataset, *, parent=None, event=None, repair=None):
    data = deepcopy(dataset)
    config, as_of = data["config"], data["as_of"]
    active_rules = select_rules(data)
    # Rebuild previous event assumptions so sequential scenarios retain their causes.
    event_map = {e["id"]: e for e in data.get("events", [])}
    ids = list(parent.get("applied_event_ids", [])) if parent else []
    if isinstance(event, str):
        event = event_map[event]
    if event and event["id"] not in ids and _event_active(event, as_of):
        ids.append(event["id"])
    if event:
        event_map[event["id"]] = event
    applied = [event_map[i] for i in ids if i in event_map and _event_active(event_map[i], as_of)]
    selected_repairs = dict(parent.get("selected_repairs", {})) if parent else {}
    if repair and event:
        selected_repairs[event["id"]] = repair
    repairs = {}
    for change in applied:
        for option in change.get("repair_options", []):
            if option["id"] == selected_repairs.get(change["id"]):
                repairs[change["id"]] = option
        for diff in change.get("changes", []):
            matches = [r for r in active_rules if r["jurisdiction"] == change["jurisdiction"] and r["requirement_key"] == diff["requirement_key"]]
            predecessor_id = matches[0]["id"] if matches else None
            if not matches:
                added = {"id": stable_id("event-rule", [change["id"], diff["requirement_key"]]), "jurisdiction": change["jurisdiction"],
                         "rule_type": diff["requirement_key"].split(".")[0], "requirement_key": diff["requirement_key"], "operator": diff.get("operator", "equals"),
                         "value": [] if isinstance(diff["value"], list) else diff["value"], "effective_from": change.get("effective_from", as_of), "effective_to": change.get("effective_to"),
                         "source_title": change["title"], "source_url": change["source_url"], "source_excerpt": change["source_excerpt"],
                         "source_tier": "synthetic" if change.get("synthetic") else change.get("source_tier", "authoritative_secondary"), "review_status": "synthetic" if change.get("synthetic") else "needs_review",
                         "retrieved_at": change.get("detected_at", as_of + "T00:00:00Z"), "confidence": 0.5}
                active_rules.append(added)
                matches = [added]
            if matches:
                rule = matches[0]
                value = diff["value"]
                if diff.get("operator") in {"contains", "contains_all"}:
                    value = sorted(set(rule["value"]) | set(value))
                elif diff.get("operator") == "excludes":
                    value = sorted(set(rule["value"]) - set(value))
                elif diff.get("operator") == ">=":
                    value = max(rule["value"], value)
                elif diff.get("operator") == "<=":
                    value = min(rule["value"], value)
                synthetic = change.get("synthetic") or change.get("source_tier") == "synthetic"
                interval_ends = [end for end in (rule.get("effective_to"), change.get("effective_to")) if end]
                rule.update(value=value, id=stable_id("event-rule", [change["id"], diff["requirement_key"]]),
                            source_title=change.get("source_title", change["title"]),
                            source_url=change["source_url"], source_excerpt=change["source_excerpt"],
                            source_tier="synthetic" if synthetic else change.get("source_tier", "authoritative_secondary"),
                            source_document_id=change.get("source_document_id"), source_event_id=change["id"],
                            retrieved_at=change.get("retrieved_at", change.get("detected_at", as_of + "T00:00:00Z")),
                            detected_at=change.get("detected_at"), last_verified_at=None,
                            effective_from=max(rule.get("effective_from", as_of), change.get("effective_from", as_of)),
                            effective_to=min(interval_ends) if interval_ends else None,
                            event_effective_from=change.get("effective_from", as_of), event_effective_to=change.get("effective_to"),
                            supersedes_id=predecessor_id, confidence=change.get("confidence", 0.5),
                            notes="Scenario requirement derived from change evidence; human review required before operational use.",
                            review_status="synthetic" if synthetic else "needs_review")
    countries = {j["iso_code"]: j for j in data["jurisdictions"]}
    country_rules = {cp["jurisdiction"]: [r for r in active_rules if r["jurisdiction"] == cp["jurisdiction"]] for cp in data["country_plans"]}
    separate = [e["jurisdiction"] for e in applied if repairs.get(e["id"], {}).get("action") == "split_label"]
    baseline_labels = group_labels({c: [r for r in select_rules(data) if r["jurisdiction"] == c] for c in country_rules}, config)
    # Keep unaffected approved group memberships stable; repair only each affected subgraph.
    labels = []
    for baseline_group in baseline_labels:
        labels.extend(group_labels({c: country_rules[c] for c in baseline_group["country_codes"]}, config, separate))
    label_map = {c: g for g in labels for c in g["country_codes"]}
    baseline_map = {c: g for g in baseline_labels for c in g["country_codes"]}
    shipments, impacts = [], []
    for cp in sorted(data["country_plans"], key=lambda x: x["jurisdiction"]):
        code = cp["jurisdiction"]
        rules = country_rules[code]
        values = {r["requirement_key"]: r["value"] for r in rules}
        evidence = [r["id"] for r in rules]
        routes = sorted([r for r in data["routes"] if r["jurisdiction"] == code], key=lambda r: (not r.get("preferred", False), r["cost_proxy"], r["id"]))
        route = deepcopy(routes[0]) if routes else {"id": "missing", "name": "Route missing", "transit_days": 0, "customs_days": 0, "depot_days": 0, "last_mile_days": 0, "cost_proxy": 0, "storage_min_c": 0, "storage_max_c": 0, "source": "Missing"}
        rework, permit_delay, transit_delay = 0, 0, 0
        causes = []
        for change in applied:
            option = repairs.get(change["id"], {})
            affected = code == change["jurisdiction"]
            old_members = baseline_map.get(change["jurisdiction"], {}).get("country_codes", [])
            label_affected = change.get("rework_days", 0) and (affected or (code in old_members and option.get("action") != "split_label"))
            if label_affected:
                rework += option.get("rework_days", change.get("rework_days", 0))
                causes.append(change)
            if affected:
                permit_delay += option.get("permit_delay_days", change.get("permit_delay_days", 0))
                transit_delay += change.get("transit_delay_days", 0)
                if change not in causes:
                    causes.append(change)
                if option.get("action") == "alternative_route":
                    alternative = next((r for r in routes if r["id"] == option.get("route_id")), None)
                    if alternative:
                        route = deepcopy(alternative)
                        transit_delay -= change.get("transit_delay_days", 0)
        group = label_map[code]
        group["rework_days"] = max(group["rework_days"], rework)
        holidays = cp.get("holidays", [])
        def duration_source(key):
            return next((r["id"] for r in rules if r["requirement_key"] == key), "missing_requirement")
        stages = [
            ("permit_application", "Permit application", 0, duration_source("permit.lead_time_business_days")),
            ("permit_approval", "Permit approval", values.get("permit.lead_time_business_days", 0) + permit_delay, duration_source("permit.lead_time_business_days")),
            ("artwork_freeze", "Artwork freeze", 0, duration_source("label.languages")),
            ("label_review", "Label review deadline", values.get("label.review_days", 0) + rework, duration_source("label.review_days")),
            ("label_approval", "Label approval", 0, duration_source("label.review_days")),
            ("packaging_start", "Packaging start", 0, duration_source("packaging.duration_days")),
            ("packaging_complete", "Packaging complete", values.get("packaging.duration_days", 0), duration_source("packaging.duration_days")),
            ("dispatch", "Dispatch", 0, route["id"]),
            ("customs_arrival", "Customs arrival", route["transit_days"] + transit_delay, route["id"]),
            ("customs_release", "Customs release", route["customs_days"], route["id"]),
            ("depot_arrival", "Depot arrival", route["depot_days"], route["id"]),
            ("site_delivery", "Site delivery", route["last_mile_days"], route["id"]),
        ]
        planned = cp["target_delivery"]
        backward = {}
        for index in range(len(stages) - 1, -1, -1):
            backward[stages[index][0]] = planned
            planned = business_add(planned, -stages[index][2], holidays)
        projected = max(cp["ready_date"], as_of)
        if date.fromisoformat(projected).weekday() >= 5 or projected in holidays:
            projected = business_add(projected, 1, holidays)
        milestones = []
        for kind, title, days, source in stages:
            projected = business_add(projected, days, holidays)
            mid = f"{cp['id']}:{kind}"
            change_sources = [cause["id"] for cause in causes if (kind == "label_review" and cause.get("rework_days")) or (kind == "permit_approval" and cause.get("permit_delay_days")) or (kind == "customs_arrival" and cause.get("transit_delay_days"))]
            milestones.append({"id": mid, "type": kind, "label": title, "planned_date": backward[kind], "projected_date": projected,
                               "actual_date": None, "duration_days": days, "duration_unit": "business_days", "duration_source": source,
                               "duration_sources": [source] + change_sources,
                               "dependencies": [milestones[-1]["id"]] if milestones else []})
        slack = business_diff(projected, cp["target_delivery"], holidays)
        dispatch_date = next(m["projected_date"] for m in milestones if m["type"] == "dispatch")
        uncertainty = delivery_range(route, transit_delay, dispatch_date, cp["target_delivery"], holidays)
        missing = [key for key in ("label.languages", "label.mandatory_fields", "label.review_days", "permit.lead_time_business_days", "packaging.duration_days") if key not in values]
        product = data["trial"]["product"]
        temperature_ok = route["storage_min_c"] >= max(product["storage_min_c"], values.get("storage.minimum_c", product["storage_min_c"])) and route["storage_max_c"] <= min(product["storage_max_c"], values.get("storage.maximum_c", product["storage_max_c"]))
        reasons = []
        if missing:
            reasons.append("Missing accepted requirements: " + ", ".join(missing))
        if not routes:
            reasons.append("No route available")
        if not temperature_ok:
            reasons.append("Route temperature band exceeds product storage limits")
        if not group["compatible"]:
            reasons.extend(x["detail"] for x in group["incompatibilities"])
        if slack < 0:
            reasons.append(f"Projected delivery misses target by {-slack} business days")
        elif slack <= config.get("low_slack_days", 3):
            reasons.append(f"Only {slack} business days of delivery slack")
        for cause in causes:
            reasons.append(cause["description"])
        if slack >= 0 and uncertainty["worst_case_slack_days"] < 0:
            reasons.append(f"Worst case (transit and customs at upper estimates) misses target by {-uncertainty['worst_case_slack_days']} business days; "
                           f"dispatch by {uncertainty['ship_by']['safe']} to absorb it")
        synthetic_count = sum(r.get("review_status") == "synthetic" for r in rules)
        coverage = sum(r.get("review_status") == "verified" for r in rules) / len(rules) if rules else 0
        hard_block = bool(missing or not routes or not temperature_ok or not group["compatible"] or slack < 0)
        risk_band = "blocked" if hard_block else "at_risk" if slack <= config.get("low_slack_days", 3) else "on_track"
        model = config["risk_model"]
        risk_score = min(model["maximum"], (model["blocked_base"] + min(model["delay_cap"], max(0, -slack) * model["delay_weight"]) if hard_block else max(model["minimum"], model["base"] - slack * model["slack_weight"])) + (model["synthetic_penalty"] if synthetic_count else 0))
        features = {"baseline_transit_days": route["transit_days"], "disruption_delay_days": transit_delay,
                    "customs_buffer_days": route["customs_days"], "permit_lead_days": values.get("permit.lead_time_business_days", 0) + permit_delay,
                    "permit_ready": "permit.lead_time_business_days" in values, "label_ready": group["compatible"] and not missing,
                    "projected_delivery_at": projected, "slack_days": slack, "risk_score": risk_score, "risk_band": risk_band,
                    "verification_coverage": round(coverage, 3), "unresolved_requirement_count": len(missing),
                    "readiness_score": max(0, model["readiness_maximum"] - len(missing) * model["missing_requirement_penalty"] - (model["synthetic_readiness_penalty"] if synthetic_count else 0)),
                    "required_language_count": len(values.get("label.languages", [])), "rework_days": rework,
                    "temperature_compatible": temperature_ok, "demand_quantity": cp["quantity"], "hard_block": hard_block,
                    "synthetic_count": synthetic_count, "risk_model": model, "low_slack_days": config["low_slack_days"],
                    "calendar_holidays": holidays, "source": "local_deterministic"}
        shipment = {"id": "shipment-" + cp["id"], "country_code": code, "country_name": countries[code]["name"],
                    "target_delivery": cp["target_delivery"], "projected_delivery": projected, "slack_days": slack,
                    "risk_band": risk_band, "risk_score": risk_score, "route_id": route["id"], "route_name": route["name"],
                    "route_options": routes, "cost_proxy": route["cost_proxy"], "label_group_id": group["id"], "quantity": cp["quantity"],
                    "milestones": milestones, "reasons": reasons, "evidence_refs": evidence, "features": features,
                    "verification_status": "synthetic" if synthetic_count else "verified" if coverage == 1 else "needs_review",
                    "site": cp.get("site"), "depot": cp.get("depot"),
                    "delivery_range": uncertainty["delivery"], "ship_by": uncertainty["ship_by"],
                    "worst_case_slack_days": uncertainty["worst_case_slack_days"], "gateway_airport": route.get("gateway_airport")}
        shipments.append(shipment)
        for cause in causes:
            starts = set()
            if cause.get("rework_days"):
                starts.add("label_review")
            if cause.get("transit_delay_days"):
                starts.add("customs_arrival")
            if cause.get("permit_delay_days"):
                starts.add("permit_approval")
            for diff in cause.get("changes", []):
                starts.add("label_review" if diff["requirement_key"].startswith("label.") else "permit_approval" if diff["requirement_key"].startswith("permit.") else "packaging_start")
            impacted_ids = set()
            for milestone in milestones:
                if milestone["type"] in starts or impacted_ids.intersection(milestone["dependencies"]):
                    impacted_ids.add(milestone["id"])
            previous_shipment = next((s for s in (parent or {}).get("shipments", []) if s["id"] == shipment["id"]), {})
            impact_values = ("projected_delivery", "slack_days", "risk_band", "route_id", "label_group_id")
            impacts.append({"event_id": cause["id"], "country_code": code, "shipment_id": shipment["id"],
                            "label_group_id": group["id"], "milestone_ids": [m["id"] for m in milestones if m["id"] in impacted_ids],
                            "old_value": {key: previous_shipment.get(key) for key in impact_values}, "new_value": {key: shipment[key] for key in impact_values},
                            "severity": risk_band, "explanation": cause["description"], "affected_keys": [d["requirement_key"] for d in cause.get("changes", [])],
                            "evidence_refs": evidence, "recommended_actions": [o["title"] for o in cause.get("repair_options", [])]})
    deadline_end = (date.fromisoformat(as_of) + timedelta(days=14)).isoformat()
    metrics = {"countries": len(shipments), "shipments_at_risk": sum(s["risk_band"] != "on_track" for s in shipments),
               "blocked_shipments": sum(s["risk_band"] == "blocked" for s in shipments),
               "deadlines_14_days": sum(as_of <= m["planned_date"] <= deadline_end for s in shipments for m in s["milestones"]),
               "label_groups": len(labels), "cost_proxy": sum(s["cost_proxy"] for s in shipments) + len(labels) * config["artwork_cost_proxy"],
               "transport_cost_proxy": sum(s["cost_proxy"] for s in shipments), "artwork_cost_proxy": len(labels) * config["artwork_cost_proxy"],
               "max_delay_days": max([0] + [-s["slack_days"] for s in shipments]), "labels_requiring_rework": sum(g["rework_days"] > 0 for g in labels)}
    options = [dict(o, event_id=e["id"]) for e in applied for o in e.get("repair_options", [])]
    identity = {"dataset": data, "events": applied, "repairs": selected_repairs, "parent": parent.get("id") if parent else None}
    return {"id": stable_id("scenario", identity), "trial_id": data["trial"]["id"], "name": event["title"] if event else "Baseline supply plan",
            "generated_at": as_of + "T09:00:00Z", "as_of": as_of, "calculation_version": CALCULATION_VERSION,
            "parent_scenario_id": parent.get("id") if parent else None,
            "assumptions": ["Decision support; human approval is required before applying any scenario.", "Synthetic records are simulated assumptions, not verified regulatory facts.", "All durations use business days; configured jurisdiction holidays are excluded."],
            "input_ids": {"dataset": data["id"], "trial": data["trial"]["id"], "rules": [r["id"] for r in active_rules]},
            "evidence_refs": [r["id"] for r in active_rules], "rules": active_rules, "label_groups": labels, "shipments": shipments,
            "metrics": metrics, "impacts": impacts, "repair_options": options, "applied_event_ids": [e["id"] for e in applied],
            "selected_repairs": selected_repairs}


def compare_plans(before, after):
    previous = {s["country_code"]: s for s in before["shipments"]}
    changes = []
    for shipment in after["shipments"]:
        old = previous.get(shipment["country_code"])
        keys = ("projected_delivery", "slack_days", "risk_band", "risk_score", "route_id", "route_name", "label_group_id", "cost_proxy")
        old_values = {k: old.get(k) for k in keys} if old else {}
        new_values = {k: shipment.get(k) for k in keys}
        old_milestones = {m["type"]: m for m in old["milestones"]} if old else {}
        milestone_changes = [{"type": m["type"], "label": m["label"], "before": old_milestones.get(m["type"], {}).get("projected_date"), "after": m["projected_date"],
                              "planned_before": old_milestones.get(m["type"], {}).get("planned_date"), "planned_after": m["planned_date"]}
                             for m in shipment["milestones"] if old_milestones.get(m["type"], {}).get("projected_date") != m["projected_date"] or old_milestones.get(m["type"], {}).get("planned_date") != m["planned_date"]]
        if old_values != new_values or milestone_changes:
            changes.append({"country_code": shipment["country_code"], "country_name": shipment["country_name"], "before": old_values, "after": new_values,
                            "changed_milestones": milestone_changes, "reasons": shipment["reasons"]})
    causal = []
    changed_countries = {change["country_code"] for change in changes}
    previous_events = set(before.get("applied_event_ids", []))
    previous_repairs = before.get("selected_repairs", {})
    current_repairs = after.get("selected_repairs", {})
    previous_impacts = {(impact["country_code"], impact["event_id"]) for impact in before.get("impacts", [])}
    seen = set()
    for impact in after.get("impacts", []):
        key = (impact["country_code"], impact["event_id"])
        if impact["country_code"] not in changed_countries or key in seen:
            continue
        # Cumulative scenarios retain their historical impacts, but unchanged
        # previously applied events are not causes of this comparison's delta.
        if key in previous_impacts and impact["event_id"] in previous_events and previous_repairs.get(impact["event_id"]) == current_repairs.get(impact["event_id"]):
            continue
        seen.add(key)
        s = next(s for s in after["shipments"] if s["country_code"] == impact["country_code"])
        causal.append({"country_code": s["country_code"], "event_id": impact["event_id"], "steps": [impact["explanation"],
                       f"Label rework {s['features']['rework_days']} business days; route delay {s['features']['disruption_delay_days']} business days",
                       f"Projected delivery {s['projected_delivery']}", f"Delivery slack {s['slack_days']} business days ({s['risk_band']})"], "evidence_refs": impact["evidence_refs"]})
    return {"before_id": before["id"], "after_id": after["id"], "calculation_version": CALCULATION_VERSION, "changes": changes, "causal_chain": causal,
            "summary": {"changed_countries": len(changes), "before": before["metrics"], "after": after["metrics"],
                        "cost_delta": after["metrics"]["cost_proxy"] - before["metrics"]["cost_proxy"],
                        "risk_delta": after["metrics"]["shipments_at_risk"] - before["metrics"]["shipments_at_risk"]}}
