import json

import label_grouping
from models import Regulation
from retrieval import load_regulations


def make_requirement(jurisdiction, languages=None, mandatory=None, prohibited=None, source_url=None, member_state=None):
    return label_grouping.NormalizedRequirement(
        jurisdiction=jurisdiction,
        member_state=member_state,
        mandatory_label_content=mandatory or [],
        prohibited_label_content=prohibited or [],
        languages=languages or [],
        investigational_product_details=[],
        source_url=[source_url] if source_url else [],
        source_date=[],
        verification_status="sourced_verbatim",
        review_reasons=[],
        source_ids=[f"{jurisdiction}-test"],
        source="regulations.json",
    )


def make_shipment(shipment_id, drug_name, destination):
    return {
        "shipment_id": shipment_id,
        "drug_name": drug_name,
        "origin": "Indianapolis, US",
        "destination": destination,
        "shipping_date": "2026-10-01",
        "estimated_transit_days": 5,
        "required_delivery_date": "2026-10-10",
    }


# --- classify_destination / exclusion scope ----------------------------------


def test_classify_destination_resolves_us_eu_japan_and_canada():
    assert label_grouping.classify_destination("Indianapolis, US")[0] == "US"
    assert label_grouping.classify_destination("Berlin, DE")[0] == "EU"
    assert label_grouping.classify_destination("Berlin, DE")[1] == "DE"
    assert label_grouping.classify_destination("Tokyo, JP")[0] == "Japan"
    assert label_grouping.classify_destination("Toronto, CA")[0] == "Canada"
    assert label_grouping.classify_destination("Sao Paulo, BR")[0] is None


def test_canada_excluded_from_grouping_and_not_mutated():
    shipments = [
        make_shipment("SHIP-A", "Drug X", "Berlin, DE"),
        make_shipment("SHIP-B", "Drug X", "Toronto, CA"),
    ]
    original_copy = [dict(s) for s in shipments]

    eligible = label_grouping.label_eligible_shipments(shipments)

    eligible_ids = {s["shipment_id"] for s in eligible}
    assert "SHIP-B" not in eligible_ids  # Canada excluded
    assert "SHIP-A" in eligible_ids
    assert shipments == original_copy  # input never mutated


def test_canada_shipment_never_forms_or_joins_a_group():
    shipments = [
        make_shipment("SHIP-A", "Drug X", "Berlin, DE"),
        make_shipment("SHIP-B", "Drug X", "Toronto, CA"),
        make_shipment("SHIP-C", "Drug X", "Toronto, CA"),
    ]
    normalized = {"EU": make_requirement("EU", languages=["German"])}

    groups = label_grouping.build_candidate_groups(shipments, normalized)

    all_shipment_ids = {sid for g in groups for sid in g["shipment_ids"]}
    assert "SHIP-B" not in all_shipment_ids
    assert "SHIP-C" not in all_shipment_ids


# --- grouping / product separation -------------------------------------------


def test_grouping_combines_same_product_across_jurisdictions_when_clean():
    shipments = [
        make_shipment("SHIP-001", "Investigational Drug A", "Berlin, DE"),
        make_shipment("SHIP-002", "Investigational Drug A", "Tokyo, JP"),
    ]
    normalized = {
        "EU": make_requirement("EU", languages=["German"], mandatory=["[EU-1] storage conditions"], source_url="https://eu.example/reg"),
        ("EU", "DE"): make_requirement(
            "EU", member_state="DE", languages=["German"],
            mandatory=["[EU-1] storage conditions"], source_url="https://eu.example/reg",
        ),
        "Japan": make_requirement("Japan", languages=["Japanese"], mandatory=["[JP-1] sponsor name"], source_url="https://jp.example/reg"),
    }

    groups = label_grouping.build_candidate_groups(shipments, normalized)

    assert len(groups) == 1
    group = groups[0]
    assert group["drug_name"] == "Investigational Drug A"
    assert set(group["shipment_ids"]) == {"SHIP-001", "SHIP-002"}
    assert set(group["jurisdictions"]) == {"EU-DE", "Japan"}
    assert group["status"] == "CANDIDATE_GROUP"  # no gaps/conflicts in this clean fixture
    assert group["reasons"] == []
    assert "https://eu.example/reg" in group["sources"]
    assert "https://jp.example/reg" in group["sources"]
    assert "German" in group["combined_languages"]
    assert "Japanese" in group["combined_languages"]


def test_product_separation_different_drugs_are_not_grouped_together():
    shipments = [
        make_shipment("SHIP-001", "Drug A", "Berlin, DE"),
        make_shipment("SHIP-002", "Drug A", "Tokyo, JP"),
        make_shipment("SHIP-003", "Drug B", "Berlin, DE"),
        make_shipment("SHIP-004", "Drug B", "Tokyo, JP"),
    ]
    normalized = {
        "EU": make_requirement("EU", languages=["German"]),
        "Japan": make_requirement("Japan", languages=["Japanese"]),
    }

    groups = label_grouping.build_candidate_groups(shipments, normalized)

    assert len(groups) == 2
    drug_to_shipments = {g["drug_name"]: set(g["shipment_ids"]) for g in groups}
    assert drug_to_shipments["Drug A"] == {"SHIP-001", "SHIP-002"}
    assert drug_to_shipments["Drug B"] == {"SHIP-003", "SHIP-004"}


def test_single_shipment_product_does_not_form_a_group():
    shipments = [make_shipment("SHIP-001", "Lonely Drug", "Berlin, DE")]
    normalized = {"EU": make_requirement("EU", languages=["German"])}

    groups = label_grouping.build_candidate_groups(shipments, normalized)

    assert groups == []


# --- missing / ambiguous requirements -> NEEDS_REVIEW ------------------------


def test_missing_normalized_requirement_returns_needs_review():
    shipments = [
        make_shipment("SHIP-001", "Drug A", "Berlin, DE"),
        make_shipment("SHIP-002", "Drug A", "Tokyo, JP"),
    ]
    normalized = {"EU": make_requirement("EU", languages=["German"])}  # Japan missing entirely

    groups = label_grouping.build_candidate_groups(shipments, normalized)

    assert len(groups) == 1
    assert groups[0]["status"] == "NEEDS_REVIEW"
    assert any("Japan" in reason for reason in groups[0]["reasons"])


def test_eu_member_state_without_override_adds_review_reason():
    normalized = {"EU": make_requirement("EU", languages=[])}
    req = label_grouping.get_effective_requirement("EU", "FR", normalized)
    assert req is not None
    assert any("FR" in reason for reason in req.review_reasons)


def test_conflict_detection_flags_potential_conflict():
    req_a = make_requirement("Japan", prohibited=["[JP-X] proposed commercial name of the drug"])
    req_b = make_requirement("EU", mandatory=["[EU-X] Commercial Name: Foo 10mg"])

    conflicts = label_grouping._detect_conflicts([req_a, req_b])

    assert len(conflicts) == 1
    assert "commercial name" in conflicts[0].lower()


# --- simulated regulatory change ---------------------------------------------


def test_simulated_change_adds_language_and_marks_source():
    normalized = {"EU": make_requirement("EU", languages=[])}

    updated = label_grouping.apply_simulated_regulatory_change(normalized, label_grouping.SIMULATED_REGULATORY_CHANGE)

    key = ("EU", "DE")
    assert key in updated
    assert "German" in updated[key].languages
    assert "SIMULATED" in updated[key].source
    assert any("SIM-REG-CHANGE-001" in r for r in updated[key].review_reasons)
    # original dict/object untouched
    assert normalized["EU"].languages == []


def test_simulated_change_before_after_diff_on_real_regulations_json():
    regulations = load_regulations()
    shipments = [
        make_shipment("SHIP-001", "Investigational Insulin Glargine", "Berlin, DE"),
        make_shipment("SHIP-002", "Investigational Insulin Glargine", "Tokyo, JP"),
    ]

    normalized_before = label_grouping.normalize_requirements(regulations)
    groups_before = label_grouping.build_candidate_groups(shipments, normalized_before)

    normalized_after = label_grouping.apply_simulated_regulatory_change(
        normalized_before, label_grouping.SIMULATED_REGULATORY_CHANGE
    )
    groups_after = label_grouping.build_candidate_groups(shipments, normalized_after)

    diff = label_grouping.diff_group_reasons(groups_before, groups_after)
    glargine_diff = next(d for d in diff if d["drug_name"] == "Investigational Insulin Glargine")

    # the simulated change sources a Germany-specific requirement, so the
    # generic "no DE-specific requirement sourced" caveat disappears...
    assert any(
        "No country-specific requirement sourced for EU member state 'DE'" in r
        for r in glargine_diff["reasons_removed"]
    )
    # ...replaced by an explicit SIMULATED provenance reason
    assert any("SIMULATED" in r for r in glargine_diff["reasons_added"])
    # the EU-wide missing-language warning is about the EU jurisdiction as a
    # whole (not Germany specifically) and is correctly NOT resolved by a
    # simulated, Germany-only change -- it must still be present after.
    assert any(
        "No documented language requirement" in r and "EU" in r
        for r in glargine_diff["reasons_removed"] + glargine_diff["reasons_added"]
    ) is False
    before_group = next(g for g in groups_before if g["drug_name"] == "Investigational Insulin Glargine")
    after_group = next(g for g in groups_after if g["drug_name"] == "Investigational Insulin Glargine")
    assert any("No documented language requirement" in r and "EU" in r for r in before_group["reasons"])
    assert any("No documented language requirement" in r and "EU" in r for r in after_group["reasons"])
    # real data (secondary-source EU, unverified Japan translation) still needs review either way
    assert glargine_diff["status_before"] == "NEEDS_REVIEW"
    assert glargine_diff["status_after"] == "NEEDS_REVIEW"


# --- real-data sanity checks (US verbatim, EU/Japan flagged) -----------------


def test_real_regulations_json_normalizes_expected_jurisdictions():
    regulations = load_regulations()
    normalized = label_grouping.normalize_requirements(regulations)

    assert set(normalized) == {"US", "EU", "Japan"}  # no Canada bucket, even if present upstream
    assert normalized["Japan"].verification_status == "needs_review"  # translation, unverified
    assert normalized["EU"].verification_status == "needs_review"  # secondary-source, unverified
    assert "Japanese" in normalized["Japan"].languages


def test_real_regulations_json_excludes_non_scope_jurisdictions_without_deleting_source():
    regulations = load_regulations()
    before_count = len(regulations)

    label_grouping.normalize_requirements(regulations)

    assert len(regulations) == before_count  # normalize_requirements never mutates its input


# --- report / JSON serializability -------------------------------------------


def test_build_report_is_json_serializable_and_has_expected_shape():
    shipments = [
        make_shipment("SHIP-001", "Investigational Insulin Glargine", "Berlin, DE"),
        make_shipment("SHIP-002", "Investigational Insulin Glargine", "Tokyo, JP"),
    ]
    regulations = load_regulations()

    report = label_grouping.build_report(shipments=shipments, regulations=regulations)
    dumped = json.dumps(report)  # must not raise

    assert json.loads(dumped)["scope"] == ["EU", "Japan", "US"]
    assert "Canada" in report["excluded_jurisdictions"]
    assert report["groups_before_simulated_change"]
    assert report["groups_after_simulated_change"]
    assert "disclaimer" in report
