"""Candidate shared-label grouping for Cleared for Takeoff.

Scope is United States, European Union, and Japan ONLY. Canada (and any
destination outside these three) is recognized and excluded from label
grouping and regulatory analysis -- never deleted or mutated. This reuses
existing building blocks rather than re-implementing them:
  - shipment_planner.load_shipments() for shipment records
  - retrieval.load_regulations() / models.Regulation for the sourced
    regulatory dataset

This module never claims a candidate group is legally approved. Every
result carries a disclaimer: human regulatory review is required before
any shared label is used. "CANDIDATE_GROUP" means "worth a human review",
never "compliant".
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field, replace
from typing import Optional

from models import Regulation
from retrieval import load_regulations
from shipment_planner import ShipmentDataError, load_shipments

# --- Scope -------------------------------------------------------------------

IN_SCOPE_JURISDICTIONS = {"US", "EU", "Japan"}
EXCLUDED_JURISDICTIONS = {"Canada"}  # recognized, explicitly excluded, never deleted

EU_MEMBER_STATE_CODES = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR",
    "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK",
    "SI", "ES", "SE",
}

COUNTRY_CODE_TO_JURISDICTION = {"US": "US", "JP": "Japan", "CA": "Canada"}

_DEST_CODE_RE = re.compile(r",\s*([A-Za-z]{2})\s*$")

# Heuristic keyword filters over free-text regulation passages. These are
# intentionally simple substring checks -- good enough to drive grouping
# caution and traceability, not a substitute for a human reading the actual
# source text cited in `source_url`.
PRODUCT_DETAIL_KEYWORDS = (
    "name", "strength", "potency", "batch", "code", "identification",
    "chemical", "manufacturing",
)
CONFLICT_PHRASES = ("commercial name", "indications", "dosage and administration")


def classify_destination(destination: str):
    """Return (jurisdiction, member_state, country_code) for a shipment's
    `destination` string such as "Berlin, DE". `jurisdiction` is one of
    "US", "EU", "Japan", "Canada", or None if the trailing country code is
    unparseable or outside all of the above.
    """
    if not destination:
        return None, None, None
    match = _DEST_CODE_RE.search(destination)
    if not match:
        return None, None, None
    code = match.group(1).upper()
    if code in EU_MEMBER_STATE_CODES:
        return "EU", code, code
    return COUNTRY_CODE_TO_JURISDICTION.get(code), None, code


def label_eligible_shipments(shipments: list) -> list:
    """Shipments whose destination resolves to US, EU, or Japan.

    Canada and any other out-of-scope destination are excluded from the
    returned list but the input `shipments` (and each shipment dict) is
    never mutated -- new dicts are returned.
    """
    eligible = []
    for shipment in shipments:
        jurisdiction, member_state, country_code = classify_destination(shipment.get("destination", ""))
        if jurisdiction in IN_SCOPE_JURISDICTIONS:
            eligible.append(
                {
                    **shipment,
                    "_jurisdiction": jurisdiction,
                    "_member_state": member_state,
                    "_country_code": country_code,
                }
            )
    return eligible


# --- Normalized regulatory requirements -------------------------------------


@dataclass
class NormalizedRequirement:
    jurisdiction: str
    member_state: Optional[str]
    mandatory_label_content: list = field(default_factory=list)
    prohibited_label_content: list = field(default_factory=list)
    languages: list = field(default_factory=list)
    investigational_product_details: list = field(default_factory=list)
    source_url: list = field(default_factory=list)
    source_date: list = field(default_factory=list)
    verification_status: str = "needs_review"
    review_reasons: list = field(default_factory=list)
    source_ids: list = field(default_factory=list)
    source: str = "regulations.json"

    def to_dict(self) -> dict:
        return asdict(self)


def _is_verbatim_and_clean(reg: Regulation) -> bool:
    return reg.source_type == "verbatim_regulation" and not reg.notes


def normalize_requirements(regulations: list) -> dict:
    """Aggregate regulations.json entries into one NormalizedRequirement per
    in-scope jurisdiction (US, EU, Japan). Canada and any other jurisdiction
    present in the dataset are skipped, not deleted from the source list.

    Fields: jurisdiction, mandatory_label_content, languages,
    investigational_product_details, source_url, source_date, and
    verification_status, per the required normalized schema.
    """
    by_jurisdiction = defaultdict(list)
    for reg in regulations:
        if reg.jurisdiction not in IN_SCOPE_JURISDICTIONS:
            continue
        by_jurisdiction[reg.jurisdiction].append(reg)

    normalized = {}
    for jurisdiction, regs in by_jurisdiction.items():
        mandatory, prohibited = [], []
        languages = set()
        source_urls, source_dates, source_ids, review_reasons = [], [], [], []
        all_clean = True

        for reg in regs:
            topic = (reg.topic or "").lower()
            text = reg.text or ""

            if "mandatory label content" in topic:
                mandatory.append(f"[{reg.id}] {text.strip()}")
            if "prohibited label content" in topic:
                prohibited.append(f"[{reg.id}] {text.strip()}")
            if "japanese" in text.lower():
                languages.add("Japanese")

            if reg.source_url:
                source_urls.append(reg.source_url)
            if reg.effective_date:
                source_dates.append(reg.effective_date)
            source_ids.append(reg.id)

            if not _is_verbatim_and_clean(reg):
                all_clean = False
                note = reg.notes or f"source_type '{reg.source_type}' requires verification"
                review_reasons.append(f"{reg.id}: {note}")

        if not languages:
            review_reasons.append(
                f"No documented language requirement found in regulations.json for {jurisdiction}."
            )

        product_details = sorted(
            {item for item in mandatory if any(k in item.lower() for k in PRODUCT_DETAIL_KEYWORDS)}
        )

        verification_status = "sourced_verbatim" if (all_clean and languages) else "needs_review"

        normalized[jurisdiction] = NormalizedRequirement(
            jurisdiction=jurisdiction,
            member_state=None,
            mandatory_label_content=sorted(set(mandatory)),
            prohibited_label_content=sorted(set(prohibited)),
            languages=sorted(languages),
            investigational_product_details=product_details,
            source_url=sorted(set(source_urls)),
            source_date=sorted({d for d in source_dates if d}),
            verification_status=verification_status,
            review_reasons=review_reasons,
            source_ids=sorted(source_ids),
            source="regulations.json",
        )
    return normalized


def get_effective_requirement(jurisdiction: str, member_state: Optional[str], normalized: dict):
    """Resolve the requirement that actually applies to one shipment.

    For EU, this looks for a member-state-specific override first (only
    present if a simulated or future sourced country-specific requirement
    was applied via apply_simulated_regulatory_change). Absent an override,
    the EU-wide requirement is used but an explicit review reason is added
    noting that country-specific requirements for that member state are
    NOT sourced -- the EU is never silently treated as one uniform
    jurisdiction.
    """
    if member_state:
        override = normalized.get((jurisdiction, member_state))
        if override is not None:
            return override

    base = normalized.get(jurisdiction)
    if base is None:
        return None

    if jurisdiction == "EU" and member_state:
        reason = (
            f"No country-specific requirement sourced for EU member state '{member_state}'; "
            "eu.txt lists country-specific language/content requirements as unverified."
        )
        return replace(base, member_state=member_state, review_reasons=base.review_reasons + [reason])

    return base


# --- Simulated regulatory change (requirement 6) -----------------------------

SIMULATED_REGULATORY_CHANGE = {
    "change_id": "SIM-REG-CHANGE-001",
    "label": "SIMULATED",
    "jurisdiction": "EU",
    "member_state": "DE",
    "description": (
        "Simulated new rule: Germany requires investigational product labels "
        "to additionally bear the mandatory label content in German."
    ),
    "added_languages": ["German"],
}


def apply_simulated_regulatory_change(normalized: dict, change: dict) -> dict:
    """Return a NEW normalized dict with `change` applied as a member-state
    (or jurisdiction-level) override. Does not mutate `normalized` or any
    underlying regulations.json data -- this is a proposed, clearly
    SIMULATED change for comparison purposes only.
    """
    updated = dict(normalized)
    base = normalized.get(change["jurisdiction"])
    if base is None:
        raise ValueError(f"No base normalized requirement for jurisdiction {change['jurisdiction']!r}")

    merged_languages = sorted(set(base.languages) | set(change.get("added_languages", [])))
    merged_reasons = list(base.review_reasons) + [
        f"[{change['label']}] {change['change_id']}: {change['description']}"
    ]

    member_state = change.get("member_state")
    key = (change["jurisdiction"], member_state) if member_state else change["jurisdiction"]
    updated[key] = replace(
        base,
        member_state=member_state,
        languages=merged_languages,
        review_reasons=merged_reasons,
        source=f"{base.source}+SIMULATED",
    )
    return updated


# --- Conflict detection -------------------------------------------------------


def _detect_conflicts(reqs: list) -> list:
    """Flag a potential conflict when one jurisdiction's prohibited content
    textually overlaps another's mandatory content. A conservative,
    phrase-based heuristic -- not a legal determination.
    """
    conflicts = []
    for req_a in reqs:
        for phrase in CONFLICT_PHRASES:
            if not any(phrase in item.lower() for item in req_a.prohibited_label_content):
                continue
            for req_b in reqs:
                if req_b is req_a:
                    continue
                if any(phrase in item.lower() for item in req_b.mandatory_label_content):
                    conflicts.append(
                        f"Potential conflict: {_jurisdiction_label(req_a)} prohibits content matching "
                        f"'{phrase}', but {_jurisdiction_label(req_b)} mandatory content includes a "
                        "related item -- requires human review."
                    )
    return list(dict.fromkeys(conflicts))


def _jurisdiction_label(req: NormalizedRequirement) -> str:
    return f"{req.jurisdiction}-{req.member_state}" if req.member_state else req.jurisdiction


# --- Candidate group evaluation (requirements 2, 4, 5) -----------------------


def build_candidate_groups(shipments: list, normalized: dict) -> list:
    """Group in-scope shipments by investigational product (drug_name) and
    evaluate whether their documented requirements can be jointly
    satisfied by one shared label.

    Returns a list of group dicts, each JSON-serializable, with status
    "CANDIDATE_GROUP" (no gaps/conflicts found -- worth a human review) or
    "NEEDS_REVIEW" (missing, ambiguous, or conflicting information), never
    an assertion of compliance.
    """
    eligible = label_eligible_shipments(shipments)
    by_product = defaultdict(list)
    for shipment in eligible:
        by_product[shipment["drug_name"]].append(shipment)

    groups = []
    for drug_name, members in by_product.items():
        if len(members) < 2:
            continue  # a "shared" label group needs at least two shipments
        groups.append(_evaluate_group(drug_name, members, normalized))
    return groups


def _evaluate_group(drug_name: str, members: list, normalized: dict) -> dict:
    resolved = []
    reasons = []
    jurisdiction_labels = []

    for shipment in members:
        jurisdiction, member_state = shipment["_jurisdiction"], shipment["_member_state"]
        req = get_effective_requirement(jurisdiction, member_state, normalized)
        if req is None:
            reasons.append(f"No normalized regulatory requirement available for jurisdiction '{jurisdiction}'.")
            continue
        resolved.append(req)
        label = _jurisdiction_label(req)
        if label not in jurisdiction_labels:
            jurisdiction_labels.append(label)

    for req in resolved:
        reasons.extend(req.review_reasons)
    reasons.extend(_detect_conflicts(resolved))
    reasons = list(dict.fromkeys(reasons))  # de-dup, preserve order

    combined_mandatory = sorted({item for req in resolved for item in req.mandatory_label_content})
    combined_languages = sorted({lang for req in resolved for lang in req.languages})
    sources = sorted({url for req in resolved for url in req.source_url})

    status = "NEEDS_REVIEW" if reasons else "CANDIDATE_GROUP"

    return {
        "drug_name": drug_name,
        "shipment_ids": [m["shipment_id"] for m in members],
        "jurisdictions": jurisdiction_labels,
        "status": status,
        "reasons": reasons,
        "combined_mandatory_label_content": combined_mandatory,
        "combined_languages": combined_languages,
        "sources": sources,
        "disclaimer": (
            "Candidate grouping only -- not a legal compliance determination. "
            "Human regulatory review is required before this label is used."
        ),
    }


def diff_group_reasons(before_groups: list, after_groups: list) -> list:
    """Per drug_name, show how a group's status/reasons changed between two
    runs (e.g. before vs. after a simulated regulatory change).
    """
    before_by_drug = {g["drug_name"]: g for g in before_groups}
    after_by_drug = {g["drug_name"]: g for g in after_groups}

    diffs = []
    for drug_name in sorted(set(before_by_drug) | set(after_by_drug)):
        before = before_by_drug.get(drug_name)
        after = after_by_drug.get(drug_name)
        before_reasons = set(before["reasons"]) if before else set()
        after_reasons = set(after["reasons"]) if after else set()
        diffs.append(
            {
                "drug_name": drug_name,
                "status_before": before["status"] if before else None,
                "status_after": after["status"] if after else None,
                "reasons_removed": sorted(before_reasons - after_reasons),
                "reasons_added": sorted(after_reasons - before_reasons),
            }
        )
    return diffs


# --- Report assembly (requirement 7) -----------------------------------------


def _json_safe_normalized(normalized: dict) -> dict:
    out = {}
    for key, req in normalized.items():
        safe_key = f"{key[0]}:{key[1]}" if isinstance(key, tuple) else key
        out[safe_key] = req.to_dict()
    return out


def build_report(shipments: Optional[list] = None, regulations: Optional[list] = None) -> dict:
    """Build the full, JSON-serializable grouping report: scope, normalized
    requirements, candidate groups, and a before/after comparison under the
    one simulated regulatory change. Intended for a future dashboard; safe
    to json.dumps() directly.
    """
    if shipments is None:
        shipments = load_shipments()
    if regulations is None:
        regulations = load_regulations()

    normalized_before = normalize_requirements(regulations)
    groups_before = build_candidate_groups(shipments, normalized_before)

    normalized_after = apply_simulated_regulatory_change(normalized_before, SIMULATED_REGULATORY_CHANGE)
    groups_after = build_candidate_groups(shipments, normalized_after)

    return {
        "scope": sorted(IN_SCOPE_JURISDICTIONS),
        "excluded_jurisdictions": sorted(EXCLUDED_JURISDICTIONS),
        "normalized_requirements": _json_safe_normalized(normalized_before),
        "groups_before_simulated_change": groups_before,
        "simulated_change": SIMULATED_REGULATORY_CHANGE,
        "normalized_requirements_after_change": _json_safe_normalized(normalized_after),
        "groups_after_simulated_change": groups_after,
        "diff": diff_group_reasons(groups_before, groups_after),
        "disclaimer": (
            "All candidate groups are proposals for human regulatory review only. "
            "Nothing in this report is a legal compliance or approval determination."
        ),
    }


# --- Terminal output ----------------------------------------------------------


def _print_group(group: dict) -> None:
    print(f"{group['drug_name']} -- shipments: {', '.join(group['shipment_ids'])}")
    print(f"    Jurisdictions: {', '.join(group['jurisdictions'])}")
    print(f"    Status:        {group['status']}")
    if group["reasons"]:
        print("    Reasons:")
        for reason in group["reasons"]:
            print(f"      - {reason}")
    else:
        print("    Reasons:        none found")
    if group["sources"]:
        print("    Sources:")
        for url in group["sources"]:
            print(f"      - {url}")
    print(f"    Disclaimer:     {group['disclaimer']}")


def main() -> None:
    try:
        report = build_report()
    except ShipmentDataError as exc:
        print(f"Error loading shipment data: {exc}")
        return

    print(f"Scope: {', '.join(report['scope'])} (excluded: {', '.join(report['excluded_jurisdictions'])})\n")

    print("=== Candidate label groups (before simulated change) ===\n")
    if not report["groups_before_simulated_change"]:
        print("No candidate groups found (need >=2 in-scope shipments of the same product).\n")
    for group in report["groups_before_simulated_change"]:
        _print_group(group)
        print()

    change = report["simulated_change"]
    print(f"=== [{change['label']}] {change['change_id']} ===")
    print(f"Jurisdiction/member state: {change['jurisdiction']}/{change.get('member_state')}")
    print(f"{change['description']}\n")

    print("=== Candidate label groups (after simulated change) ===\n")
    for group in report["groups_after_simulated_change"]:
        _print_group(group)
        print()

    print("=== Before vs. after comparison ===\n")
    for d in report["diff"]:
        print(f"{d['drug_name']}: {d['status_before']} -> {d['status_after']}")
        if d["reasons_removed"]:
            print("    Reasons resolved by the simulated change:")
            for r in d["reasons_removed"]:
                print(f"      - {r}")
        if d["reasons_added"]:
            print("    New reasons introduced by the simulated change:")
            for r in d["reasons_added"]:
                print(f"      - {r}")
        print()

    serialized = json.dumps(report)
    print(f"Full report is JSON-serializable ({len(serialized)} bytes) for dashboard consumption.")
    print(report["disclaimer"])


if __name__ == "__main__":
    main()
