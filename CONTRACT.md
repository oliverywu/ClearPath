# Internal integration contract

Python 3.11+ standard library backend and planner; buildless ES module browser frontend. No runtime package download is required. Recommended stack in plan is advisory; portability and complete offline operation govern this choice.

## Ownership
- Planner agent: packages/domain, packages/planner, data/demo, data/schemas, tests/unit.
- API agent: apps/api, packages/ingestion, packages/feature_provider, packages/assistant, packages/calendar, packages/notifications, chalk, tests/integration.
- Web agent: apps/web only.
- Parent: startup, documentation, E2E, integration fixes, Git.

## Planner contract
`packages.domain.validation.validate_dataset(data) -> list[str]` (empty means valid).
`packages.planner.engine.generate_plan(dataset, *, parent=None, event=None, repair=None) -> dict`.
`packages.planner.engine.compare_plans(before, after) -> dict`.
`data/demo/trial.json` and `data/demo/replacement.json` are complete datasets. Planner agent owns schema; communicate details promptly.
Plan shape: id, trial_id, name, generated_at, as_of, calculation_version, assumptions, evidence_refs, label_groups, shipments, metrics, impacts, repair_options, applied_event_ids. Scenario governance stored separately by API.
shipment: id, country_code, country_name, target_delivery, projected_delivery, slack_days, risk_band (on_track/at_risk/blocked), risk_score, route_id, route_name, label_group_id, quantity, milestones, reasons, evidence_refs, features.
milestone: id, type, label, planned_date, projected_date, duration_days, dependencies.
label_group: id, country_codes, languages, mandatory_fields, estimated_pages, reasons.
metrics: countries, shipments_at_risk, blocked_shipments, deadlines_14_days, label_groups.
repair_option: id, title, description, tradeoffs, recommended, event_id. `repair` is option id string.
comparison: changes (country_code, country_name, before, after, changed_milestones), summary, causal_chain.

## HTTP contract
All errors `{error: string, details?: any}`. JSON bodies. All non-API static files served on web :3000. API :8000 (web requests relative `/api`, static server proxies to API).
- GET /api/bootstrap => {trial, dataset_summary, approved_scenario, scenarios, events, alerts, provider, jurisdictions}. approved_scenario includes plan fields plus status/approval metadata. jurisdictions list id/iso_code/name.
- GET /api/scenarios => {scenarios:[summary]}
- GET /api/scenarios/{id} => full plan with status
- POST /api/trials/{id}/scenarios/generate => full baseline plan; first baseline approved with explicit seed audit.
- GET /api/jurisdictions/{iso}/requirements?as_of=YYYY-MM-DD => {country, as_of, requirements:[atomic rules including source_url/source_excerpt/review_status/source_tier/effective_from]}
- GET /api/scenarios/{id}/timeline => {shipments,label_groups}
- GET /api/scenarios/{id}/compare/{other_id} => comparison before=id after=other_id
- POST /api/change-events/{id}/analyze body {repair?: option-id, parent_scenario_id?: id} => full proposed plan (contains parent_scenario_id)
- POST /api/scenarios/{id}/approve or /reject body {approver,note} => full plan with status
- GET /api/scenarios/{id}/calendar.ics => only approved scenario, valid ICS
- GET /api/audit => {events:[...]}
- GET /api/alerts => {alerts:[...]}; POST /api/alerts/{id}/acknowledge
- POST /api/assistant/query body {question,scenario_id,trial_id} => {answer,citations:[{title,url,excerpt,status}],suggested_questions:[]}
- POST /api/rules/import/preview body {records:[atomic rules]} => {preview_id,valid,errors,diff,records}
- POST /api/rules/import/commit body {preview_id,reviewer} => {imported,scenario_id?}
- POST /api/datasets/import/preview body {dataset} and /commit body {preview_id,reviewer}
- POST /api/demo/reset body {fixture?: demo|replacement} => bootstrap
- GET /api/health => {status,provider,calculation_version}
- GET /api/dataset => full loaded dataset
- POST /api/sources/snapshot body {source_id,content} => snapshot/hash/change diff (no network required)
- POST /api/research/extract body {source_id?,content?,source_title?,source_url?,jurisdiction} => exact-quote checked, schema-valid candidate rules forced to needs_review
- POST /api/sources/{id}/analyze-change => stored semantic analysis of latest two snapshots with raw diff, citations, proposed materiality and normalized event
- POST /api/change-analyses/{id}/confirm body {reviewer,note,event?} => human-confirmed change event eligible for deterministic impact analysis

Events list must include `id,title,description,event_type,jurisdiction,synthetic` so UI renders dynamically; all product/country/event content comes from API.
