"""Dependency-free validation for atomic research records and complete datasets."""
from datetime import date
from urllib.parse import urlparse
import math

OPERATORS = {"equals", "contains_all", "contains", "excludes", "=", ">=", "<=", "in"}
STATUSES = {"verified", "needs_review", "synthetic", "retired"}
SOURCE_TIERS = {"official", "authoritative_secondary", "modeled", "synthetic"}


def valid_date(value):
    try:
        date.fromisoformat(value)
        return True
    except (TypeError, ValueError):
        return False


def validate_rule(record):
    if not isinstance(record, dict):
        return ["Rule must be an object"]
    errors = []
    required = ("jurisdiction", "rule_type", "requirement_key", "operator", "value", "effective_from", "source_url", "source_title", "source_excerpt", "retrieved_at", "source_tier", "confidence", "review_status")
    for key in required:
        if key not in record or record[key] is None or (isinstance(record[key], str) and not record[key].strip()):
            errors.append(f"Missing {key}")
    for key in ("jurisdiction", "rule_type", "requirement_key", "operator", "source_url", "source_title", "source_excerpt", "retrieved_at", "source_tier", "review_status"):
        if key in record and not isinstance(record[key], str):
            errors.append(f"{key} must be text")
    if not isinstance(record.get("operator"), str) or record.get("operator") not in OPERATORS:
        errors.append("Unsupported operator")
    if not isinstance(record.get("review_status"), str) or record.get("review_status") not in STATUSES:
        errors.append("Unknown review_status")
    if not isinstance(record.get("source_tier"), str) or record.get("source_tier") not in SOURCE_TIERS:
        errors.append("Unknown source_tier")
    if record.get("review_status") == "verified" and record.get("source_tier") in {"modeled", "synthetic"}:
        errors.append("Verified records cannot use modeled or synthetic sources")
    if not valid_date(record.get("effective_from")):
        errors.append("effective_from must be an ISO date")
    if record.get("effective_to"):
        if not valid_date(record["effective_to"]) or (valid_date(record.get("effective_from")) and record["effective_to"] <= record["effective_from"]):
            errors.append("Invalid effective interval; effective_to is exclusive")
    if not valid_date(str(record.get("retrieved_at", ""))[:10]):
        errors.append("retrieved_at must include an ISO date")
    try:
        parsed = urlparse(str(record.get("source_url", "")))
        url_valid = parsed.scheme in {"https", "http"} and bool(parsed.netloc)
    except ValueError:
        url_valid = False
    if not url_valid:
        errors.append("source_url must be an HTTP(S) citation")
    confidence = record.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        errors.append("confidence must be between 0 and 1")
    key, value = record.get("requirement_key", ""), record.get("value")
    if not isinstance(key, str):
        return errors + ["requirement_key must be text"]
    if not isinstance(record.get("jurisdiction"), str):
        errors.append("jurisdiction must be text")
    if key in {"label.languages", "label.mandatory_fields", "label.prohibited_fields", "documents.required"} and (not isinstance(value, list) or not all(isinstance(x, str) and x for x in value)):
        errors.append(f"{key} must be an array of nonempty strings")
    if key.endswith(("_days", "_business_days")) and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
        errors.append(f"{key} must be a nonnegative integer")
    if key in {"label.expiry_format", "label.sponsor_constraint", "label.blinding_constraint", "label.exclusive_template"} and not isinstance(value, str):
        errors.append(f"{key} must be text")
    if key in {"storage.minimum_c", "storage.maximum_c"} and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < -273.15):
        errors.append(f"{key} must be a valid temperature")
    return errors


def validate_dataset(data):
    if not isinstance(data, dict):
        return ["Dataset must be an object"]
    errors = []
    for key in ("id", "as_of", "trial", "config", "jurisdictions", "country_plans", "rules", "routes", "events"):
        if key not in data:
            errors.append(f"Missing dataset field: {key}")
    if errors:
        return errors
    if not valid_date(data["as_of"]):
        errors.append("Invalid dataset as_of")
    for key in ("trial", "config"):
        if not isinstance(data[key], dict):
            errors.append(f"{key} must be an object")
    for key in ("jurisdictions", "country_plans", "rules", "routes", "events"):
        if not isinstance(data[key], list):
            errors.append(f"{key} must be an array")
        elif any(not isinstance(row, dict) for row in data[key]):
            errors.append(f"{key} entries must be objects")
    if errors:
        return errors
    def text_fields(row, fields, label):
        for field in fields:
            if not isinstance(row.get(field), str) or not row[field].strip():
                errors.append(f"{label}: {field} must be nonempty text")
    def numeric(row, field, label, minimum=0, integer=False):
        value = row.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < minimum or (integer and not isinstance(value, int)):
            errors.append(f"{label}: invalid {field}")
    text_fields(data, ("id",), "dataset")
    for row in data["jurisdictions"]:
        text_fields(row, ("id", "iso_code", "name", "regulator_name", "regulator_url"), "jurisdiction")
    if errors:
        return errors
    codes = {j.get("iso_code") for j in data["jurisdictions"]}
    if len(codes) != len(data["jurisdictions"]):
        errors.append("Duplicate jurisdictions")
    if not data["country_plans"]:
        errors.append("At least one country plan is required")
    text_fields(data["trial"], ("id", "name", "start_date"), "trial")
    if not valid_date(data["trial"].get("start_date")):
        errors.append("Invalid trial start_date")
    origin = data["trial"].get("manufacturing_origin")
    if not isinstance(origin, dict):
        errors.append("manufacturing_origin must be an object")
    else:
        text_fields(origin, ("city", "country_code"), "manufacturing_origin")
    product = data["trial"].get("product")
    if not isinstance(product, dict):
        errors.append("product must be an object")
    else:
        text_fields(product, ("name", "dosage_form", "strength"), "product")
        for field in ("storage_min_c", "storage_max_c"):
            numeric(product, field, "product", minimum=-273.15)
        numeric(product, "shelf_life_days", "product", minimum=1, integer=True)
        if all(isinstance(product.get(f), (int, float)) for f in ("storage_min_c", "storage_max_c")) and product["storage_min_c"] > product["storage_max_c"]:
            errors.append("Invalid product storage range")
        for field in ("blinded", "synthetic"):
            if not isinstance(product.get(field), bool):
                errors.append(f"product: {field} must be boolean")
    config = data["config"]
    for field in ("booklet_capacity_pages", "languages_per_page", "base_label_pages"):
        numeric(config, field, "config", minimum=1, integer=True)
    numeric(config, "low_slack_days", "config", integer=True)
    numeric(config, "artwork_cost_proxy", "config")
    model = config.get("risk_model")
    if not isinstance(model, dict):
        errors.append("config.risk_model must be an object")
    else:
        for field in ("maximum", "blocked_base", "delay_cap", "delay_weight", "minimum", "base", "slack_weight", "synthetic_penalty", "readiness_maximum", "missing_requirement_penalty", "synthetic_readiness_penalty"):
            numeric(model, field, "risk_model")
    if errors:
        return errors
    for kind in ("rules", "routes", "country_plans", "events"):
        ids = set()
        for row in data[kind]:
            if not isinstance(row, dict):
                errors.append(f"{kind} entries must be objects")
                continue
            identifier = row.get("id")
            if not isinstance(identifier, str) or not isinstance(row.get("jurisdiction"), str):
                errors.append(f"{kind}: id and jurisdiction must be text")
                continue
            if not identifier or identifier in ids:
                errors.append(f"{kind}: missing or duplicate id {identifier}")
            ids.add(identifier)
            if row.get("jurisdiction") not in codes:
                errors.append(f"{kind}: unknown jurisdiction {row.get('jurisdiction')}")
            if kind == "rules":
                errors.extend(f"{identifier}: {error}" for error in validate_rule(row))
            elif kind == "country_plans":
                if not valid_date(row.get("target_delivery")) or not valid_date(row.get("ready_date")):
                    errors.append(f"{identifier}: invalid planning date")
                if isinstance(row.get("quantity"), bool) or not isinstance(row.get("quantity"), int) or row["quantity"] <= 0:
                    errors.append(f"{identifier}: quantity must be a positive integer")
                holidays = row.get("holidays", [])
                if not isinstance(holidays, list) or not all(valid_date(day) for day in holidays):
                    errors.append(f"{identifier}: holidays must be ISO dates")
            elif kind == "routes":
                text_fields(row, ("name", "mode", "source"), identifier)
                for field in ("transit_days", "customs_days", "depot_days", "last_mile_days", "cost_proxy"):
                    numeric(row, field, identifier, integer=field != "cost_proxy")
                for field in ("storage_min_c", "storage_max_c"):
                    numeric(row, field, identifier, minimum=-273.15)
                if all(isinstance(row.get(f), (int, float)) for f in ("storage_min_c", "storage_max_c")) and row["storage_min_c"] > row["storage_max_c"]:
                    errors.append(f"{identifier}: invalid storage range")
            elif kind == "events":
                text_fields(row, ("title", "description", "event_type", "source_url", "source_excerpt"), identifier)
                if not valid_date(row.get("effective_from")) or (row.get("effective_to") and (not valid_date(row["effective_to"]) or (valid_date(row.get("effective_from")) and row["effective_to"] <= row["effective_from"]))):
                    errors.append(f"{identifier}: invalid event interval")
                for field in ("rework_days", "permit_delay_days", "transit_delay_days"):
                    if field in row:
                        numeric(row, field, identifier, integer=True)
                diffs = row.get("changes", [])
                if not isinstance(diffs, list) or any(not isinstance(diff, dict) for diff in diffs):
                    errors.append(f"{identifier}: changes must be objects")
                else:
                    for diff in diffs:
                        if not isinstance(diff.get("requirement_key"), str) or not isinstance(diff.get("operator"), str) or diff.get("operator") not in OPERATORS or "value" not in diff:
                            errors.append(f"{identifier}: invalid requirement change")
                        elif isinstance(diff["requirement_key"], str):
                            candidate = {"jurisdiction": row["jurisdiction"], "rule_type": "label", "requirement_key": diff["requirement_key"], "operator": diff["operator"], "value": diff["value"],
                                         "effective_from": row.get("effective_from"), "source_url": row.get("source_url"), "source_title": row.get("title"), "source_excerpt": row.get("source_excerpt"),
                                         "retrieved_at": str(row.get("effective_from")) + "T00:00:00Z", "source_tier": "synthetic", "review_status": "synthetic", "confidence": 0.5}
                            errors.extend(f"{identifier}: {error}" for error in validate_rule(candidate))
                options = row.get("repair_options", [])
                if not isinstance(options, list) or any(not isinstance(option, dict) for option in options):
                    errors.append(f"{identifier}: repair_options must be objects")
                else:
                    for option in options:
                        text_fields(option, ("id", "title", "description", "tradeoffs", "action"), identifier)
                        if option.get("action") not in {"split_label", "expedite_review", "alternative_route", "expedite_permit"}:
                            errors.append(f"{identifier}: unsupported repair action")
                        for field in ("rework_days", "permit_delay_days"):
                            if field in option:
                                numeric(option, field, identifier, integer=True)
                        if option.get("action") == "alternative_route" and not any(route.get("id") == option.get("route_id") and route.get("jurisdiction") == row["jurisdiction"] for route in data["routes"]):
                            errors.append(f"{identifier}: alternative route is missing or belongs to another jurisdiction")
    if errors:
        return errors
    # Concurrent accepted records for the same atomic requirement are ambiguous.
    groups = {}
    for row in data["rules"]:
        if not isinstance(row, dict) or row.get("review_status") not in {"verified", "synthetic"}:
            continue
        key = (row.get("jurisdiction"), row.get("requirement_key"))
        groups.setdefault(key, []).append(row)
    for key, rows in groups.items():
        rows.sort(key=lambda x: x.get("effective_from", ""))
        for earlier, later in zip(rows, rows[1:]):
            if earlier.get("effective_to", "9999-12-31") is None or earlier.get("effective_to", "9999-12-31") > later.get("effective_from", ""):
                errors.append(f"Overlapping active intervals: {key[0]} {key[1]}")
    return errors
