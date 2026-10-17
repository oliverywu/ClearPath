"""Curated primary-law facts used to replace synthetic regulatory assumptions."""

PRIORITY_EVIDENCE = {
    ("US", "documents.required"): {
        "value": ["ind_application", "protocol", "investigator_brochure", "chemistry_manufacturing_controls", "pharmacology_toxicology_information"],
        "source_url": "https://www.ecfr.gov/current/title-21/chapter-I/subchapter-D/part-312/subpart-B/section-312.23",
        "source_title": "21 CFR 312.23 — IND content and format",
        "source_excerpt": "An IND includes required introductory information, protocols, investigator information, CMC information, and pharmacology/toxicology information.",
    },
    ("DE", "documents.required"): {
        "value": ["clinical_trial_application_dossier", "protocol", "investigator_brochure", "investigational_medicinal_product_dossier", "informed_consent_materials"],
        "source_url": "https://eur-lex.europa.eu/eli/reg/2014/536/oj",
        "source_title": "Regulation (EU) No 536/2014, Annex I — Application dossier",
        "source_excerpt": "Annex I specifies the application dossier and supporting documents for a clinical trial application in the Union.",
    },
    ("CA", "label.mandatory_fields"): {
        "value": ["qualified_investigators_only", "drug_name_or_code", "expiry_date", "storage_conditions", "lot_number", "sponsor_name_and_address", "protocol_code"],
        "source_url": "https://laws-lois.justice.gc.ca/eng/regulations/c.r.c.,_c._870/section-C.05.011.html",
        "source_title": "Canada Food and Drug Regulations C.05.011 — Labelling",
        "source_excerpt": "The inner and outer labels must carry the prescribed investigator-use statement and product, expiry, storage, lot, sponsor, and protocol particulars.",
    },
    ("CA", "documents.required"): {
        "value": ["clinical_trial_application", "protocol", "informed_consent_form", "investigator_brochure", "attestation"],
        "source_url": "https://laws-lois.justice.gc.ca/eng/regulations/c.r.c.,_c._870/section-C.05.005.html",
        "source_title": "Canada Food and Drug Regulations C.05.005 — Application",
        "source_excerpt": "A sponsor must submit the prescribed clinical-trial application information and documents to the Minister.",
    },
    ("BR", "documents.required"): {
        "value": ["clinical_development_dossier", "clinical_trial_protocol", "investigators_brochure", "informed_consent_form", "ethics_approval", "import_authorization_if_applicable"],
        "source_url": "https://www.gov.br/anvisa/pt-br/assuntos/medicamentos/ensaios-clinicos",
        "source_title": "ANVISA — Clinical trials and clinical drug development",
        "source_excerpt": "ANVISA's official clinical-trial framework requires the applicable development dossier, protocol, supporting trial documents, and authorization before regulated use or import.",
    },
    ("IN", "documents.required"): {
        "value": ["clinical_trial_permission", "protocol", "investigator_brochure", "informed_consent_documents", "ethics_committee_approval", "import_licence_if_applicable"],
        "source_url": "https://cdsco.gov.in/opencms/export/sites/CDSCO_WEB/Pdf-documents/NewDrugs_CTRules_2019.pdf",
        "source_title": "India New Drugs and Clinical Trials Rules, 2019",
        "source_excerpt": "The Rules prescribe applications, permissions, ethics review, and supporting material for clinical trials and investigational new drugs.",
    },
    ("IN", "label.mandatory_fields"): {
        "value": ["clinical_trial_use_only", "product_name_or_code", "batch_number", "expiry_date", "storage_conditions", "sponsor_name_and_address", "protocol_reference"],
        "source_url": "https://cdsco.gov.in/opencms/export/sites/CDSCO_WEB/Pdf-documents/NewDrugs_CTRules_2019.pdf",
        "source_title": "India New Drugs and Clinical Trials Rules, 2019 — investigational product controls",
        "source_excerpt": "The investigational product must be controlled and identified for clinical-trial use with the applicable product, batch, expiry, storage, sponsor, and trial particulars.",
    },
}

EU_COUNTRIES = ("AT", "BE", "DE", "DK", "ES", "FI", "FR", "IE", "IT", "NL")
EU_MANDATORY_FIELDS = ["main_contact", "substance_and_strength", "dosage_form", "route", "quantity", "batch_number", "trial_reference", "subject_or_treatment_number", "directions_for_use", "clinical_trial_use", "storage", "expiry", "keep_out_of_reach_of_children"]
EU_APPLICATION_DOCUMENTS = ["clinical_trial_application_dossier", "protocol", "investigator_brochure", "investigational_medicinal_product_dossier", "informed_consent_materials"]
EU_EVIDENCE = {}
for _country in EU_COUNTRIES:
    EU_EVIDENCE[(_country, "label.mandatory_fields")] = {
        "value": EU_MANDATORY_FIELDS,
        "source_url": "https://eur-lex.europa.eu/eli/reg/2014/536/oj",
        "source_title": "Regulation (EU) No 536/2014, Articles 66–70 and Annex VI",
        "source_excerpt": "Annex VI specifies particulars for investigational medicinal product and auxiliary medicinal product labelling.",
    }
    EU_EVIDENCE[(_country, "documents.required")] = {
        "value": EU_APPLICATION_DOCUMENTS,
        "source_url": "https://eur-lex.europa.eu/eli/reg/2014/536/oj",
        "source_title": "Regulation (EU) No 536/2014, Annex I — Application dossier",
        "source_excerpt": "Annex I specifies the application dossier and supporting documents for a clinical trial application in the Union.",
    }
    EU_EVIDENCE[(_country, "label.language_determination")] = {
        "value": "member_state_determined_or_broadly_understood_language",
        "source_url": "https://eur-lex.europa.eu/eli/reg/2014/536/oj",
        "source_title": "Regulation (EU) No 536/2014, Article 69 — Language",
        "source_excerpt": "The Member State concerned determines the label language and may permit a language broadly understood by the medical profession.",
    }

GLOBAL_EVIDENCE = {
    ("AR", "label.languages"): (["es"], "https://www.argentina.gob.ar/normativa/nacional/disposici%C3%B3n-6677-2010-174557/texto", "ANMAT Disposición 6677/2010, C.8.1"),
    ("AR", "label.mandatory_fields"): (["study_identifier", "sponsor", "investigator", "product_name_or_code", "dosage", "route_of_administration", "strength_or_potency", "batch_or_packaging_code", "participant_code", "storage_conditions", "expiry_date", "clinical_trial_use_only"], "https://www.argentina.gob.ar/normativa/nacional/disposici%C3%B3n-6677-2010-174557/texto", "ANMAT Disposición 6677/2010, C.8.1"),
    ("AR", "label.expiry_format"): ("MM/YYYY", "https://www.argentina.gob.ar/normativa/nacional/disposici%C3%B3n-6677-2010-174557/texto", "ANMAT Disposición 6677/2010, C.8.1"),
    ("AR", "documents.required"): (["clinical_trial_authorization", "investigators_brochure", "protocol", "informed_consent", "ethics_committee_approval"], "https://www.argentina.gob.ar/normativa/nacional/disposici%C3%B3n-6677-2010-174557/texto", "ANMAT Disposición 6677/2010"),
    ("AU", "label.mandatory_fields"): (["australian_main_contact", "product_name_or_identifier", "strength_or_potency", "dosage_form", "route_of_administration", "quantity", "batch_or_code", "trial_reference", "participant_or_treatment_number", "directions_for_use", "clinical_trial_use_only", "storage_conditions", "expiry_or_retest_date"], "https://www.tga.gov.au/sites/default/files/pe009-pics-guide-gmp-medicinal-products.pdf", "TGA-adopted PIC/S GMP Annex 13"),
    ("AU", "label.expiry_format"): ("MM/YYYY", "https://www.tga.gov.au/sites/default/files/pe009-pics-guide-gmp-medicinal-products.pdf", "TGA-adopted PIC/S GMP Annex 13"),
    ("AU", "documents.required"): (["hrec_approval", "ctn_or_cta", "gmp_evidence"], "https://www.tga.gov.au/resources/guidance/australian-clinical-trial-handbook", "TGA Australian Clinical Trial Handbook"),
    ("CH", "documents.required"): (["clinical_trial_authorization", "protocol", "investigator_brochure", "informed_consent_documents", "ethics_committee_authorization"], "https://www.fedlex.admin.ch/eli/cc/2013/643/en", "Swiss Ordinance on Clinical Trials in Human Research (ClinO)"),
    ("CN", "label.mandatory_fields"): (["clinical_trial_use_only", "product_identification_or_code"], "https://www.gov.cn/gbgl/c3b91a472a6141c397dabebc7984a5a1/files/c1136cecc15b43b5aaae09ebcbf8a3d7.pdf", "China Good Clinical Practice for Drug Trials (2020)"),
    ("CN", "documents.required"): (["clinical_trial_approval_or_notification", "protocol", "investigators_brochure"], "https://zwfw.nmpa.gov.cn/web/taskview/11100000MB0341032Y100017210200001", "NMPA clinical-trial approval service"),
    ("GB", "label.mandatory_fields"): (["main_contact", "product_name_or_identifier", "strength_or_potency", "dosage_form", "route", "quantity", "batch_or_code", "trial_reference", "participant_or_treatment_number", "directions_for_use", "clinical_trial_use_only", "storage_conditions", "expiry_or_retest_date"], "https://www.legislation.gov.uk/uksi/2004/1031/contents", "UK Medicines for Human Use (Clinical Trials) Regulations 2004"),
    ("GB", "documents.required"): (["clinical_trial_authorisation_application", "protocol", "investigator_brochure", "investigational_medicinal_product_dossier", "informed_consent_materials"], "https://www.legislation.gov.uk/uksi/2004/1031/contents", "UK Medicines for Human Use (Clinical Trials) Regulations 2004"),
    ("KR", "label.mandatory_fields"): (["clinical_trial_use_only", "product_name_or_identifier", "dosage_form", "route_of_administration", "quantity", "strength_or_potency", "batch_or_code", "sponsor_name_address_phone", "expiry_date", "storage_conditions", "trial_reference", "participant_or_treatment_number", "visit_number"], "https://www.law.go.kr/flDownload.do?bylClsCd=200201&flSeq=136112033", "Korea GMP Annex 11 for investigational medicines"),
    ("KR", "label.expiry_format"): ("YYYY/MM", "https://www.law.go.kr/flDownload.do?bylClsCd=200201&flSeq=136112033", "Korea GMP Annex 11 for investigational medicines"),
    ("MX", "documents.required"): (["clinical_trial_authorization", "cofepris_import_permit_01_010_a"], "https://www.gob.mx/cofepris/acciones-y-programas/ensayos-clinicos-protocolos-de-investigacion-en-seres-humanos-397098", "COFEPRIS clinical-trial requirements"),
    ("NZ", "label.mandatory_fields"): (["qualified_investigators_only", "sponsor_or_cro_or_investigator_contact", "dosage_form", "route", "quantity", "product_name_or_identifier", "strength_or_potency", "batch_or_code", "trial_reference", "participant_or_treatment_number", "directions_for_use", "storage_conditions", "expiry_or_retest_date"], "https://www.medsafe.govt.nz/regulatory/Guideline/PE_009-14_GMP_Guide%20_Annexes.pdf", "New Zealand PIC/S GMP Annex 13"),
    ("NZ", "label.expiry_format"): ("MM/YYYY", "https://www.medsafe.govt.nz/regulatory/Guideline/PE_009-14_GMP_Guide%20_Annexes.pdf", "New Zealand PIC/S GMP Annex 13"),
    ("NZ", "documents.required"): (["clinical_trial_approval", "product_specification_file", "gmp_evidence", "certificate_of_analysis"], "https://www.medsafe.govt.nz/regulatory/Guideline/GRTPNZ/Clinical-Trials-Regulatory-Approval-and-GCP-Requirements.pdf", "Medsafe Clinical Trials Regulatory Approval and GCP Requirements"),
    ("SG", "label.mandatory_fields"): (["clinical_trial_use_only", "trial_reference", "participant_or_treatment_number", "visit_number", "main_contact_name_address_phone", "substance_name", "strength_or_potency", "dosage_form", "route", "quantity", "directions_for_use", "batch_or_code", "expiry_or_retest_period", "storage_conditions"], "https://sso.agc.gov.sg/SL/HPA2007-S331-2016?DocDate=20160715&ProvIds=Sc2-.", "Singapore Health Products (Clinical Trials) Regulations 2016, Second Schedule"),
    ("SG", "label.expiry_format"): ("MM/YYYY", "https://sso.agc.gov.sg/SL/HPA2007-S331-2016?DocDate=20160715&ProvIds=Sc2-.", "Singapore Health Products (Clinical Trials) Regulations 2016, Second Schedule"),
    ("SG", "documents.required"): (["protocol", "informed_consent_english", "investigators_brochure_or_local_approved_label", "principal_investigator_cv", "gmp_certificate", "certificate_of_analysis"], "https://www.hsa.gov.sg/other-regulations/clinical-trials/application/apply-cta-ctn/", "HSA CTA/CTN application requirements"),
}
GLOBAL_EVIDENCE = {key: {"value": value, "source_url": url, "source_title": title,
                         "source_excerpt": f"Normalized investigational-product requirement from {title}."}
                   for key, (value, url, title) in GLOBAL_EVIDENCE.items()}


def apply_evidence(payload, evidence=PRIORITY_EVIDENCE):
    """Replace active synthetic atoms with normalized facts from primary sources."""
    for (country, key), source in evidence.items():
        candidates = [rule for rule in payload["rules"] if rule["jurisdiction"] == country and rule["requirement_key"] == key
                      and rule.get("effective_from", payload["as_of"]) <= payload["as_of"]
                      and (not rule.get("effective_to") or rule["effective_to"] > payload["as_of"])]
        target = next((rule for rule in candidates if rule.get("source_tier") == "official"), None)
        target = target or next((rule for rule in candidates if rule.get("review_status") == "synthetic"), None)
        if not target:
            target = {
                "id": f"official-{country}-{key}-v1", "jurisdiction": country,
                "rule_type": "label" if key.startswith("label.") else "required_document",
                "requirement_key": key, "operator": "contains_all" if isinstance(source["value"], list) else "equals",
                "effective_from": "2026-01-01", "effective_to": None, "supersedes_id": None,
            }
            payload["rules"].append(target)
        target.update(source, source_tier="official", review_status="verified", confidence=0.95,
                      retrieved_at=payload["as_of"] + "T00:00:00Z", last_verified_at=payload["as_of"],
                      source_document_id=f"official-{country.lower()}-primary",
                      notes="Normalized from the cited primary source for planning support; applicability remains subject to protocol-specific human review.")

    existing = {source["id"] for source in payload.get("sources", [])}
    for country in sorted({country for country, _ in evidence}):
        source_id = f"official-{country.lower()}-primary"
        rule = next(value for (code, _), value in evidence.items() if code == country)
        if source_id not in existing:
            payload.setdefault("sources", []).append({
                "id": source_id, "jurisdiction_id": country, "title": rule["source_title"],
                "canonical_url": rule["source_url"], "publisher": payload["jurisdictions"][next(i for i, j in enumerate(payload["jurisdictions"]) if j["iso_code"] == country)]["regulator_name"],
                "retrieved_at": payload["as_of"] + "T00:00:00Z", "content_hash": f"curated-{country.lower()}-primary",
                "snapshot_path": None, "source_tier": "official", "enabled": True,
                "content": "Curated primary-source record; see the atomic rule excerpts and canonical URL.",
            })
    unique = {}
    for rule in payload["rules"]:
        unique[rule["id"]] = rule
    rules = list(unique.values())
    for country, key in evidence:
        matching = [rule for rule in rules if rule["jurisdiction"] == country and rule["requirement_key"] == key
                    and rule.get("source_tier") == "official" and rule.get("review_status") == "verified"
                    and rule.get("effective_from", payload["as_of"]) <= payload["as_of"]
                    and (not rule.get("effective_to") or rule["effective_to"] > payload["as_of"])]
        if len(matching) > 1:
            keep = next((rule for rule in matching if not rule["id"].startswith("official-")), matching[0])
            rules = [rule for rule in rules if rule is keep or rule not in matching]
    payload["rules"] = rules


def apply_eu_rules(payload):
    """Apply common EU CTR facts without inventing national label-language policy."""
    apply_evidence(payload, EU_EVIDENCE)
    planning_languages = {"AT": ["de"], "BE": ["nl", "fr", "de"], "DE": ["de"], "DK": ["da"],
                          "ES": ["es"], "FI": ["fi", "sv"], "FR": ["fr"], "IE": ["en", "ga"],
                          "IT": ["it"], "NL": ["nl"]}
    for jurisdiction in payload.get("jurisdictions", []):
        code = jurisdiction["iso_code"]
        if code in planning_languages:
            jurisdiction["planning_language_assumption"] = planning_languages[code]
            jurisdiction["planning_language_status"] = "needs_member_state_confirmation"


def apply_global_rules(payload):
    apply_evidence(payload, GLOBAL_EVIDENCE)
    for rule in payload["rules"]:
        if rule.get("source_tier") == "synthetic":
            rule.update(source_tier="modeled", review_status="synthetic", confidence=0.5,
                        source_title=f"{rule['jurisdiction']} modeled planning assumption",
                        notes="Operational or product-specific placeholder; not represented as law and must be replaced by sponsor/carrier data.")
    for source in payload.get("sources", []):
        if source.get("source_tier") == "synthetic":
            source["source_tier"] = "modeled"


def consolidate_japan_rules(payload):
    """Accept the Article 16 translations and remove overlapping active atoms."""
    cutoff = "2026-10-17"
    candidates = {rule["requirement_key"]: rule for rule in payload["rules"]
                  if rule.get("id", "").startswith("candidate-JP-")}
    for rule in candidates.values():
        rule.update(review_status="verified", confidence=1.0, last_verified_at=payload["as_of"],
                    notes="Working English translation accepted as correct for this prototype by project direction.")
    if "label.mandatory_fields" in candidates:
        candidates["label.mandatory_fields"]["effective_to"] = "2027-01-15"
    for rule in payload["rules"]:
        if rule["jurisdiction"] != "JP" or rule.get("id", "").startswith("candidate-JP-"):
            continue
        if rule["requirement_key"] in candidates and rule.get("effective_from", cutoff) < cutoff and (
                not rule.get("effective_to") or rule["effective_to"] > cutoff):
            rule.update(effective_to=cutoff, review_status="retired",
                        notes=f"Superseded by {candidates[rule['requirement_key']]['id']} after the Article 16 translation was accepted.")
