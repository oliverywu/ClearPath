"""Merge Anna's committed evidence and shipment metadata into planner fixtures.

This is intentionally repeatable. It preserves the planner's forward-looking schedule
while replacing matching synthetic regulatory facts and attaching Anna's four source
shipment records to DE, JP, BR and IN.
"""
import json
from copy import deepcopy
from pathlib import Path

from build_fixtures import integrate_anna_shipments, integrate_regulators, replace_synthetic_label_rules
from regulatory_catalog import apply_eu_rules, apply_evidence, apply_global_rules, consolidate_japan_rules


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
INVENTORY = ROOT / "cleared-for-takeoff/cleared-for-takeoff-app/src/mock/inventory.json"


def merge(path, evidence_rules=()):
    payload = json.loads(path.read_text(encoding="utf-8"))
    evidence_by_id = {rule["id"]: rule for rule in evidence_rules}
    payload["rules"] = [deepcopy(evidence_by_id.get(rule["id"], rule)) for rule in payload["rules"]]
    known_rule_ids = {rule["id"] for rule in payload["rules"]}
    payload["rules"].extend(deepcopy(rule) for rule in evidence_rules if rule["id"] not in known_rule_ids)
    integrate_anna_shipments(payload)
    integrate_regulators(payload)
    replace_synthetic_label_rules(payload)
    apply_evidence(payload)
    apply_eu_rules(payload)
    apply_global_rules(payload)
    consolidate_japan_rules(payload)
    # The frontend inventory seed is now canonical API data. It is still sample
    # operational data and must not be presented as live inventory telemetry.
    payload["inventory"] = [dict(row, dataProvenance="sample") for row in json.loads(INVENTORY.read_text(encoding="utf-8"))]
    payload["inventory_provenance"] = "sample"
    for event in payload.get("events", []):
        if event.get("id") == "jp-label-field":
            event.update(
                title="Japan GCP Ordinance, Article 16",
                description="Anna's sample operational review found that the Japan kit artwork needs the applicable in-country sponsor/representative information before departure.",
                synthetic=False,
                operational_provenance="anna_sample",
                review_status="verified",
                source_tier="official",
                source_url="https://laws.e-gov.go.jp/law/409M50000100028",
                source_title="Japan GCP Ordinance, Article 16",
                source_excerpt="Article 16 requires specified investigational-drug information in Japanese, including sponsor information and an in-country representative when applicable.",
            )
    for rule in payload["rules"]:
        if rule.get("id") == "demo-JP-label.mandatory_fields-v2":
            rule.update(source_url="https://example.org/cleared-synthetic/demo/jp", source_title="Japan simulated label assumptions",
                        source_tier="synthetic", review_status="synthetic", confidence=0.5, last_verified_at=None,
                        notes="Synthetic future rule for scenario testing; not a statement of Japanese law.")
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    logistics = json.loads((HERE / "trial_logistics.json").read_text(encoding="utf-8"))
    # Preserve reviewed/official research records when regenerating the simpler
    # base fixture. Logistics enrichment must never be the only copy of law data.
    evidence_rules = [rule for rule in logistics["rules"] if rule.get("source_tier") == "official"]
    for name in ("trial.json", "trial_logistics.json"):
        payload = merge(HERE / name, evidence_rules)
        anna = [row for row in payload["country_plans"] if row.get("data_provenance") == "anna_sample"]
        print(f"Merged {name}: {len(anna)} Anna shipment records, {len(payload['inventory'])} sample inventory rows")
