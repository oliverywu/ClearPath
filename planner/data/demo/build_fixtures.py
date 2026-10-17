"""Reproduce fictional fixtures. This file is seed data generation, never engine policy."""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from packages.planner.engine import business_add

COUNTRIES = [
    ("US", "United States", "en", 38, -97), ("DE", "Germany", "de", 51, 10),
    ("CA", "Canada", "fr", 56, -106), ("JP", "Japan", "ja", 36, 138),
    ("GB", "United Kingdom", "en", 55, -3), ("AU", "Australia", "en", -25, 134),
    ("FR", "France", "fr", 46, 2), ("ES", "Spain", "es", 40, -4),
    ("IT", "Italy", "it", 42, 12), ("NL", "Netherlands", "nl", 52, 5),
    ("BE", "Belgium", "fr", 50, 4), ("AT", "Austria", "de", 47, 14),
    ("CH", "Switzerland", "de", 47, 8), ("DK", "Denmark", "da", 56, 10),
    ("FI", "Finland", "fi", 64, 26), ("IE", "Ireland", "en", 53, -8),
    ("NZ", "New Zealand", "en", -41, 174), ("SG", "Singapore", "en", 1, 104),
    ("KR", "South Korea", "ko", 36, 128), ("BR", "Brazil", "pt", -14, -52),
    ("MX", "Mexico", "es", 23, -102), ("AR", "Argentina", "es", -34, -64),
    ("IN", "India", "hi", 21, 79), ("CN", "China", "zh", 35, 104),
]

ROOT = Path(__file__).resolve().parents[3]
ANNA_SHIPMENTS = ROOT / "messaging/data/shipments.json"


def integrate_anna_shipments(payload):
    """Keep the 24-country plan, but make Anna's four operational rows authoritative
    for their destination countries. Fields Anna did not supply (notably quantity,
    depot and site) remain explicit planner assumptions.
    """
    destinations = {"Berlin, DE": "DE", "Tokyo, JP": "JP", "Sao Paulo, BR": "BR", "Mumbai, IN": "IN"}
    records = json.loads(ANNA_SHIPMENTS.read_text(encoding="utf-8"))["shipments"]
    plans = {row["jurisdiction"]: row for row in payload["country_plans"]}
    for record in records:
        code = destinations[record["destination"]]
        plan = plans[code]
        plan.update(
            source_shipment_id=record["shipment_id"],
            drug_name=record["drug_name"],
            origin=record["origin"],
            destination=record["destination"],
            shipping_date=record["shipping_date"],
            ready_date=record["shipping_date"],
            target_delivery=record["required_delivery_date"],
            source_required_delivery_date=record["required_delivery_date"],
            source_estimated_transit_days=record["estimated_transit_days"],
            data_provenance="anna_sample",
        )


def replace_synthetic_label_rules(payload):
    """Replace only synthetic facts directly supported by Anna's cited evidence.

    US is verbatim official text. EU/DE is normalized from the official Regulation
    and Annex VI. Japan remains needs_review because Anna supplied a translation,
    not an authenticated English legal text. Canada's existing official federal
    rule is already in the fixture and is deliberately left intact.
    """
    replacements = {
        ("US", "label.mandatory_fields"): dict(
            value=["investigational_use_statement"],
            source_url="https://www.ecfr.gov/current/title-21/chapter-I/subchapter-D/part-312/subpart-A/section-312.6",
            source_title="21 CFR 312.6(a) — Labeling of an investigational new drug",
            source_excerpt="The immediate package must bear the required investigational-use caution statement.",
            source_tier="official", review_status="verified", confidence=1.0,
            notes="Normalized from Anna's verbatim official eCFR record US-312-6-a-1."),
        ("US", "label.prohibited_fields"): dict(
            value=["false_or_misleading_claims", "safe_or_effective_claims"],
            source_url="https://www.ecfr.gov/current/title-21/chapter-I/subchapter-D/part-312/subpart-A/section-312.6",
            source_title="21 CFR 312.6(b) — Prohibited label representations",
            source_excerpt="Investigational-drug labeling must not be false or misleading or represent the drug as safe or effective.",
            source_tier="official", review_status="verified", confidence=1.0,
            notes="Normalized from Anna's verbatim official eCFR record US-312-6-b-2."),
        ("DE", "label.mandatory_fields"): dict(
            value=["main_contact", "substance_and_strength", "dosage_form", "route", "quantity", "batch_number", "trial_reference", "subject_or_treatment_number", "directions_for_use", "clinical_trial_use", "storage", "expiry", "keep_out_of_reach_of_children"],
            source_url="https://eur-lex.europa.eu/eli/reg/2014/536/oj",
            source_title="Regulation (EU) No 536/2014, Articles 66–70 and Annex VI",
            source_excerpt="Annex VI lists the particulars required on investigational medicinal product packaging; applicability varies by product and packaging configuration.",
            source_tier="official", review_status="verified", confidence=0.95,
            notes="Anna's EU summary was checked against the official EUR-Lex text; Germany-specific language rules remain a separate assumption."),
        ("JP", "label.languages"): dict(
            value=["ja"], source_url="https://laws.e-gov.go.jp/law/409M50000100028",
            source_title="Japan GCP Ordinance, Article 16 — Japanese-language labeling",
            source_excerpt="Anna's working translation says the listed information must be indicated in Japanese on the container or packaging.",
            source_tier="official", review_status="verified", confidence=0.9,
            notes="Verified against the cited official Japanese Article 16; Anna's English rendering remains a working translation."),
        ("JP", "label.mandatory_fields"): dict(
            value=["clinical_trial_use", "sponsor_name_and_address", "chemical_name_or_identification_code", "batch_number", "storage", "expiry"],
            source_url="https://laws.e-gov.go.jp/law/409M50000100028",
            source_title="Japan GCP Ordinance, Article 16(1) — Mandatory labeling",
            source_excerpt="Anna's working translation lists clinical-trial use, sponsor, product identification, batch, storage and validity information.",
            source_tier="official", review_status="verified", confidence=0.9,
            notes="Verified against the cited official Japanese Article 16; Anna's English rendering remains a working translation."),
        ("JP", "label.prohibited_fields"): dict(
            value=["proposed_commercial_name", "proposed_indications", "proposed_dosage_and_administration"],
            source_url="https://laws.e-gov.go.jp/law/409M50000100028",
            source_title="Japan GCP Ordinance, Article 16(2) — Prohibited labeling",
            source_excerpt="Anna's working translation identifies proposed commercial name, indications, and dosage/administration as prohibited subject to stated exceptions.",
            source_tier="official", review_status="verified", confidence=0.9,
            notes="Verified against the cited official Japanese Article 16; exceptions and the English rendering still require qualified operational review."),
    }
    for key, update in replacements.items():
        current = [rule for rule in payload["rules"] if (rule["jurisdiction"], rule["requirement_key"]) == key
                   and rule.get("effective_from", payload["as_of"]) <= payload["as_of"]
                   and (not rule.get("effective_to") or rule["effective_to"] > payload["as_of"])]
        authoritative = next((rule for rule in current if rule.get("source_tier") == "official" and rule.get("review_status") == "verified"), None)
        synthetic = next((rule for rule in current if rule.get("review_status") == "synthetic"), None)
        if authoritative and synthetic:
            synthetic.update(review_status="retired", effective_to=payload["as_of"],
                             notes="Replaced by authoritative evidence imported from Anna's regulatory dataset.")
        elif synthetic:
            synthetic.update(update, retrieved_at=payload["as_of"] + "T00:00:00Z",
                             last_verified_at=payload["as_of"] if update["review_status"] == "verified" else None)


def dataset(identifier, countries, as_of, target, product_name, origin):
    result = {"id": identifier, "as_of": as_of,
        "trial": {"id": identifier + "-trial", "name": "NOVA-24 · Blinded metabolic study" if identifier == "demo" else "AURORA-6 · Injectable feasibility study",
                  "phase": "Phase II (fictional)", "start_date": as_of, "manufacturing_origin": origin,
                  "product": {"id": identifier + "-product", "name": product_name, "dosage_form": "oral tablet" if identifier == "demo" else "injectable solution", "strength": "50 mg" if identifier == "demo" else "2 mg/mL",
                              "blinded": True, "shelf_life_days": 365, "storage_min_c": 2, "storage_max_c": 8, "synthetic": True}},
        "config": {"booklet_capacity_pages": 8, "languages_per_page": 2, "base_label_pages": 2, "low_slack_days": 2, "artwork_cost_proxy": 500,
                   "risk_thresholds": {"blocked_slack_below": 0, "at_risk_slack_max": 2}, "default_buffers": {"customs_days": 3}, "provider": "local",
                   "risk_model": {"maximum": 100, "blocked_base": 85, "delay_cap": 15, "delay_weight": 3, "minimum": 5, "base": 50, "slack_weight": 8, "synthetic_penalty": 5,
                                  "readiness_maximum": 100, "missing_requirement_penalty": 20, "synthetic_readiness_penalty": 20}},
        "jurisdictions": [], "country_plans": [], "rules": [], "routes": [], "events": [], "sources": []}
    for i, (code, name, language, lat, lon) in enumerate(countries):
        url = f"https://example.org/cleared-synthetic/{identifier}/{code.lower()}"
        result["jurisdictions"].append({"id": code, "iso_code": code, "name": name, "regulator_name": "Simulated research authority", "regulator_url": url,
                                        "source_tier": "synthetic", "latitude": lat, "longitude": lon})
        result["sources"].append({"id": "source-" + code, "jurisdiction_id": code, "title": f"{name}: synthetic study assumptions", "canonical_url": url,
                                  "publisher": "Cleared for Takeoff demo team", "retrieved_at": as_of + "T00:00:00Z", "content_hash": "seed-" + identifier + "-" + code,
                                  "snapshot_path": None, "source_tier": "synthetic", "content": f"Fictional research assumptions for {name}; not regulatory evidence."})
        result["country_plans"].append({"id": identifier + "-" + code.lower(), "jurisdiction": code,
             "target_delivery": business_add(target, 0 if i < 5 else (i % 4) * 3), "quantity": 180 + i * 24, "site": f"{name} research site {i+1:02}",
             "depot": f"{name} qualified depot", "ready_date": as_of, "holidays": [], "data_provenance": "planner_demo"})
        atoms = {"label.languages": ["en"] if language == "en" else ["en", language], "label.mandatory_fields": ["trial_id", "batch_number", "expiry", "storage", "blinded_kit_id"],
                 "label.prohibited_fields": [] if code == "JP" or identifier != "demo" else ["local_contact"], "label.expiry_format": "YYYY-MM",
                 "label.review_days": 6, "permit.lead_time_business_days": 10, "packaging.duration_days": 3,
                 "documents.required": ["trial_authorization", "certificate_of_analysis", "commercial_invoice"],
                 "storage.minimum_c": 2, "storage.maximum_c": 8}
        for key, value in atoms.items():
            rule_type = "label" if key.startswith("label.") else "import_permit" if key.startswith("permit.") else "storage" if key.startswith("storage.") else "required_document" if key.startswith("documents.") else "lead_time"
            result["rules"].append({"id": f"{identifier}-{code}-{key}-v1", "jurisdiction": code, "rule_type": rule_type,
                "requirement_key": key, "operator": "contains_all" if isinstance(value, list) else "equals", "value": value,
                "effective_from": "2026-01-01", "effective_to": None, "source_url": url, "source_title": f"{name} simulated {rule_type.replace('_', ' ')} assumptions",
                "source_excerpt": f"SYNTHETIC DEMO ONLY: assume {key} = {json.dumps(value, ensure_ascii=False)}. This is not a statement of {name} law.",
                "retrieved_at": as_of + "T00:00:00Z", "source_tier": "synthetic", "confidence": 0.5, "review_status": "synthetic",
                "last_verified_at": None, "supersedes_id": None, "source_document_id": "source-" + code, "notes": "Replace through the research importer after human verification."})
        for alternative in (False, True):
            result["routes"].append({"id": f"{identifier}-{code}-{'express' if alternative else 'standard'}", "jurisdiction": code,
                "name": f"{origin['city']} → {name} · {'priority direct' if alternative else 'qualified hub'}", "mode": "air",
                "legs": [{"origin": origin["city"], "destination": name, "mode": "air"}], "transit_days": 3 if alternative else 5,
                "customs_days": 3, "depot_days": 1, "last_mile_days": 3, "cost_proxy": 1800 + i * 45 if alternative else 1100 + i * 30,
                "storage_min_c": 2, "storage_max_c": 8, "source": "Synthetic lane estimate", "synthetic": True,
                "data_provenance": "modeled", "preferred": not alternative})
    return result


def event(identifier, country, title, description, as_of, **fields):
    return {"id": identifier, "title": title, "description": description, "event_type": "regulatory" if "changes" in fields or "permit_delay_days" in fields else "logistics",
            "jurisdiction": country, "synthetic": True, "effective_from": as_of, "effective_to": None,
            "detected_at": as_of + "T10:00:00Z", "review_status": "synthetic", "source_url": f"https://example.org/cleared-synthetic/events/{identifier}",
            "source_excerpt": "SIMULATED EVENT: " + description, "source_tier": "synthetic",
            "operational_provenance": "sample", **fields}


demo = dataset("demo", COUNTRIES, "2026-10-19", "2026-12-04", "CFT-201 (fictional IMP)", {"city": "Boston", "country_code": "US", "latitude": 42.36, "longitude": -71.06})
integrate_anna_shipments(demo)
# Demo lane details stay in fixture data. Depot qualification/release buffers
# preserve the original end-to-end synthetic schedule and route tradeoff.
for route in demo["routes"]:
    if route["jurisdiction"] == "DE":
        alternative = not route["preferred"]
        hub = "Amsterdam" if alternative else "Frankfurt"
        route.update(name=f"Boston → {hub} → German depot", transit_days=3, customs_days=2,
                     depot_days=2 if alternative else 4,
                     legs=[{"origin": "Boston", "destination": hub, "mode": "air"},
                           {"origin": hub, "destination": "German depot", "mode": "qualified ground transport"}],
                     source="Synthetic lane estimate: 3 transit days, 2 customs days; depot qualification/release buffer is 2 days via Amsterdam or 4 via Frankfurt.")
demo["events"] = [
    event("jp-label-field", "JP", "Japan · additional label field", "A simulated local-contact field conflicts with the shared booklet; artwork review adds 5 business days.", demo["as_of"],
          changes=[{"requirement_key": "label.mandatory_fields", "operator": "contains_all", "value": ["local_contact"]}], rework_days=5,
          repair_options=[{"id": "jp-split-label", "title": "Separate Japan's label", "description": "Isolate the new field and use a pre-reviewed local artwork; 1 day rework applies only to Japan.", "tradeoffs": "One separate artwork and additional review coordination.", "recommended": True, "action": "split_label", "rework_days": 1},
                          {"id": "jp-expedite-review", "title": "Expedite shared review", "description": "Reduce shared artwork review to 2 additional business days.", "tradeoffs": "Premium review effort across all members of the original group.", "recommended": False, "action": "expedite_review", "rework_days": 2}]),
    event("de-route-delay", "DE", "Germany · severe weather on Boston–Frankfurt", "Simulated severe weather on the Boston–Frankfurt lane adds 4 business days to German shipments.", demo["as_of"], transit_delay_days=4,
          repair_options=[{"id": "de-alternative-route", "title": "Reroute through Amsterdam", "description": "Use the unaffected Boston–Amsterdam lane and qualified ground transport to the German depot to recover the delivery window.", "tradeoffs": "Higher transportation cost proxy and an additional cross-border ground leg.", "recommended": True, "action": "alternative_route", "route_id": "demo-DE-express"}]),
    event("ca-permit-delay", "CA", "Canada · permit lead time increase", "Simulated permit processing increases by 7 business days.", demo["as_of"], permit_delay_days=7,
          repair_options=[{"id": "ca-expedite-permit", "title": "Request expedited permit review", "description": "Model a confirmed expedited review with only 2 extra business days.", "tradeoffs": "Requires human confirmation of agency capacity before execution.", "recommended": True, "action": "expedite_permit", "permit_delay_days": 2}]),
]
prior = next(r for r in demo["rules"] if r["jurisdiction"] == "JP" and r["requirement_key"] == "label.mandatory_fields")
prior["effective_to"] = "2027-01-15"
future = dict(prior, id="demo-JP-label.mandatory_fields-v2", effective_from="2027-01-15", effective_to=None,
              value=prior["value"] + ["future_study_contact"], supersedes_id=prior["id"], source_excerpt="SYNTHETIC FUTURE RULE: an additional study contact field is assumed from 2027-01-15. Not verified law.")
demo["rules"].append(future)
replace_synthetic_label_rules(demo)
# The future contact-field assumption is a simulated scenario, not part of Anna's
# Article 16 evidence. Keep its provenance explicit after replacing the current rule.
future.update(source_url="https://example.org/cleared-synthetic/demo/jp", source_title="Japan simulated label assumptions",
              source_tier="synthetic", review_status="synthetic", confidence=0.5, last_verified_at=None,
              notes="Synthetic future rule for scenario testing; not a statement of Japanese law.")
replacement = dataset("replacement", [("NO", "Norway", "no", 61, 8), ("SE", "Sweden", "sv", 62, 15), ("PL", "Poland", "pl", 52, 19),
    ("PT", "Portugal", "pt", 40, -8), ("CL", "Chile", "es", -35, -71), ("ZA", "South Africa", "zu", -30, 25)],
    "2027-03-08", "2027-04-23", "AUR-7 (fictional biologic)", {"city": "Copenhagen", "country_code": "DK", "latitude": 55.68, "longitude": 12.57})
replacement["events"] = [event("no-language-change", "NO", "Norway · added language", "Simulated additional Swedish text requires 4 days of shared artwork rework.", replacement["as_of"],
    changes=[{"requirement_key": "label.languages", "operator": "contains_all", "value": ["sv"]}], rework_days=4,
    repair_options=[{"id": "no-local-artwork", "title": "Separate Norway artwork", "description": "Use local artwork with one day review.", "tradeoffs": "An additional artwork is maintained.", "recommended": True, "action": "split_label", "rework_days": 1}]),
    event("cl-weather-delay", "CL", "Chile · weather delay", "Simulated weather adds 6 business days to the standard lane.", replacement["as_of"], transit_delay_days=6,
    repair_options=[{"id": "cl-direct-route", "title": "Select direct priority lane", "description": "Use an unaffected direct lane.", "tradeoffs": "Higher cost proxy.", "recommended": True, "action": "alternative_route", "route_id": "replacement-CL-express"}])]
if __name__ == "__main__":
    for name, payload in (("trial", demo), ("replacement", replacement)):
        Path(__file__).with_name(name + ".json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
