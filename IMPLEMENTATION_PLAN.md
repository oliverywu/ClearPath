# Cleared for Takeoff Implementation Plan

## Executive recommendation

Build **Cleared for Takeoff** as a clinical-supply decision-support application with one core promise: when a regulatory rule or logistics condition changes, the system can show exactly which labels, milestones, routes, and shipments are affected, recompute the plan, explain why, and require human approval before applying changes.

The deliverable is a locally hosted website that runs on the user's laptop and opens in a standard web browser. The complete demo must work over `localhost` without a cloud deployment, managed database, or live third-party API. Cloud services such as Chalk may enhance the application when credentials are configured, but local fallbacks must preserve the full demo workflow.

The project documents contain a strong problem, demo narrative, and feature ladder. They are directionally good, but not yet implementation-ready. The main missing pieces are a canonical data model, a deterministic planning algorithm, precise service boundaries, a defined ingestion contract for teammates' research, and a controlled role for AI. The proposed architecture below supplies those pieces.

The central design rule is:

> External scrapers and APIs collect evidence. The application normalizes and versions it. Chalk computes time-aware shipment-impact features. Deterministic planning code produces schedules. The AI explains results and supports queries, but never invents regulations or silently changes the approved plan.

## Assessment of the current instructions

### What is already strong

- The user problem is concrete: avoid border holds and missed doses caused by scattered country requirements.
- The ambition ladder is excellent for a hackathon: structure rules, plan labels, compute ship-by dates, then catch changes.
- The documents consistently identify the right regulated-data attributes: source, effective date, verification date, permit, documents, label content, language, temperature, and approval lead time.
- The four-screen demo is cohesive: control tower, requirements and timeline, conversation, and scenario comparison.
- The separation between public verified rules and simulated data is explicitly required.
- The planned disruption story gives the demo a visible before-and-after moment.

### What is unclear or risky

- “AI planning agent” is too broad. It needs a strict division between deterministic calculations and language-model explanation.
- Label grouping is described, but compatibility rules and physical booklet constraints are undefined.
- “Monitor regulations” is not a hackathon-sized feature unless limited to a small source registry and snapshot diff.
- Logistics routing lacks a named routing provider and a stable fallback. The demo must work even if live APIs fail.
- Photon remains an optional isolated integration because its final contract may still be uncertain. Calendar export and synchronization should be implemented as an optional user-triggered action rather than omitted from the product.
- The trial-drug example is inconsistent. Metformin is acceptable as a fictional IMP scenario, but the demo must label synthetic product assumptions as simulated.
- Some research references are secondary or generic contact pages. Production-quality records should prefer official regulator text and retain the exact cited excerpt.
- The Japanese research document states a future effective date. It must be stored as a future-effective rule version, not treated as currently active before that date.

### Scope decision

Build the complete product for arbitrary trial footprints, including the intended 20-30-country use case. The initial repository should include enough synthetic fixtures to exercise every workflow while teammate-owned research is pending. When verified records arrive, they replace or supersede fixtures through imports; functionality must not depend on which countries the team ultimately chooses. Do not pretend that synthetic records are legally verified.

## Product behavior

## Implementation handoff rule

The implementation must be fully data-driven. Countries, source URLs, source excerpts, rule dates, product attributes, trial sites, routes, lead times, disruptions, thresholds, and planted regulatory changes are input data, not constants embedded in application or planning code.

Build the complete product immediately. Implement every architecture component, screen, workflow, adapter contract, planning algorithm, change-analysis path, assistant tool, import flow, audit trail, test suite, and optional calendar action described in this plan. Do not wait for teammates to finalize countries or datasets.

Use deterministic synthetic fixtures wherever teammate-owned inputs are not yet available. The seed data should support a realistic 20-30-country footprint and include at least 5 detailed country records, one fictional trial and product, baseline and alternative routes, and multiple regulatory and logistics changes. Every unsupported fixture record must be marked `synthetic` unless it is backed by an approved source record.

When teammates deliver their final datasets, replacing files or importing new records must be sufficient to regenerate the plan. No frontend, planning-engine, Chalk-feature, or assistant code should need to change when countries, laws, dates, routes, or the fictional drug change.

Keep these boundaries explicit:

- `domain and planner code`: generic algorithms only;
- `data schemas`: stable contracts for research and demo inputs;
- `data/demo`: small synthetic morning-demo fixtures;
- `data/imports`: teammate-provided records after validation;
- `configuration`: risk thresholds, booklet capacity, default buffers, and provider selection;
- `adapters`: replaceable regulatory, geographic, Chalk, calendar, and notification integrations.

Acceptance test: delete the demo dataset, load a second fixture with different countries, product, dates, languages, routes, and changes, and confirm that the application produces a valid plan and scenario comparison without source-code edits.

### Primary user journey

1. A supply planner creates or opens a trial and selects the manufacturing origin, product profile, countries, site demand, and required delivery dates.
2. The system loads the active regulatory rule versions and baseline logistics features for each destination.
3. The planner generates:
   - country readiness status;
   - compatible label groups;
   - permit, label, packaging, transit, customs, and delivery milestones;
   - risk scores and blocking issues;
   - citations and confidence for every regulatory assertion.
4. A new regulation snapshot or logistics event is ingested.
5. The impact service identifies affected entities and asks Chalk for recomputed shipment-impact features.
6. A new immutable scenario is created and compared with the approved baseline.
7. The user reviews causes, proposed repairs, trade-offs, and sources, then approves or rejects the scenario.

### Required screens

1. **Control tower**
   - KPIs: countries covered, shipments at risk, blocked shipments, deadlines in 14 days.
   - map or country grid colored by status.
   - ranked alerts with severity, cause, affected shipment count, and recommended next action.

2. **Requirements and timeline**
   - country requirements table with verification state and source links.
   - expandable evidence panel showing exact excerpt, jurisdiction, effective date, retrieved date, and reviewer status.
   - milestone timeline from permit filing through site delivery.

3. **Scenario comparison**
   - approved baseline versus proposed scenario.
   - changed dates, label groups, routes, cost proxy, and risk.
   - causal chain such as `new Japanese label field -> label group incompatible -> artwork review +5 days -> dispatch +5 days -> site delivery at risk`.
   - approve and reject actions with audit notes.

4. **Planner assistant**
   - questions such as “Why is Germany at risk?” and “What if we split the EU label group?”
   - responses grounded only in stored plan objects, Chalk features, and source records.
   - citations for legal claims and clear labels for simulated assumptions.

Add an optional **Add approved milestones to calendar** button on the approved-scenario view. It should first generate an ICS file with permit, label review, packaging, dispatch, customs, depot, and delivery milestones. If a calendar provider is later connected, the same button can offer provider synchronization through a `CalendarProvider` interface. Calendar failures must never alter the approved plan.

Photon or another messaging layer may mirror important alerts and deep-link into the scenario screen, but keep it behind a `NotificationProvider` interface and feature flag until its contract is confirmed. The dashboard must remain fully usable without it.

## System architecture

```text
Official regulator pages     Weather/disruption APIs     Trial seed data
          |                           |                        |
          v                           v                        v
 Regulatory adapters          Logistics adapters       CSV/JSON importer
          |                           |                        |
          +------------- Normalization and validation -------+
                                      |
                                      v
                         PostgreSQL canonical store
                        rules, evidence, plans, events
                                      |
                       +--------------+--------------+
                       |                             |
                       v                             v
             Chalk feature layer          Deterministic planner
          time-aware impact features     schedules and label groups
                       |                             |
                       +--------------+--------------+
                                      |
                                      v
                         Scenario and impact service
                                      |
                         +------------+------------+
                         |                         |
                         v                         v
                   Web dashboard             Assistant/Photon
```

### Recommended stack

- Frontend: Next.js, TypeScript, Tailwind, shadcn/ui, TanStack Query, and a lightweight timeline/chart library.
- API: FastAPI with Pydantic models and SQLAlchemy.
- Database: SQLite by default for the laptop-hosted demo, behind repository interfaces that also support PostgreSQL through configuration.
- Background work: FastAPI background tasks for the demo; a job queue can replace them later.
- AI: a tool-calling model with structured outputs. Its tools read plan data, source evidence, and scenario comparisons.
- Chalk: feature definitions, resolvers, online impact queries, and historical/offline replay.
- Testing: pytest for planning logic and Playwright for the critical demo path.
- Local startup: one documented command that starts the website and API, automatically initializes the local database when needed, and prints the browser URL. Docker Compose may be provided, but it must not be the only supported path if a direct laptop startup is simpler.
- Default local URLs: web interface at `http://localhost:3000` and API at `http://localhost:8000`, unless ports are already occupied and the launcher selects alternatives.
- The application must bind to localhost by default. Exposing it to a local network must require an explicit configuration change.

## Canonical data model

Every teammate-researched rule must be importable through the same schema. Never paste unstructured research directly into prompts as the system of record.

### Regulatory entities

**Jurisdiction**

- `id`, `iso_code`, `name`, `regulator_name`, `regulator_url`.

**SourceDocument**

- `id`, `jurisdiction_id`, `title`, `canonical_url`, `publisher`, `retrieved_at`, `content_hash`, `snapshot_path`, `source_tier`.
- `source_tier`: `official`, `authoritative_secondary`, or `synthetic`.

**RuleVersion**

- `id`, `jurisdiction_id`, `rule_type`, `status`, `effective_from`, `effective_to`, `last_verified_at`, `confidence`, `source_document_id`, `source_excerpt`, `supersedes_id`.
- `status`: `verified`, `needs_review`, `synthetic`, or `retired`.
- `rule_type`: label, import permit, required document, storage, customs, or lead time.

**Requirement**

- `id`, `rule_version_id`, `requirement_key`, `operator`, `value_json`, `unit`, `notes`.
- Example: `label.languages contains ["ja"]` or `permit.lead_time_business_days = 30`.

### Planning entities

**Trial** and **ProductProfile**

- Product fields include dosage form, strength, blinded status, shelf life, storage range, manufacturing origin, and synthetic/verified markers.

**CountryPlan**

- Links a trial and jurisdiction to target date, enrollment demand, depot/site, selected rule versions, and planning status.

**LabelRequirementSet** and **LabelGroup**

- A normalized signature contains language set, mandatory fields, prohibited fields, expiry format, sponsor/address constraints, randomization/blinding constraints, and artwork capacity.
- A label group stores its members, signature, estimated pages, compatibility decision, and reasons.

**Shipment** and **RouteOption**

- Shipment includes origin, destination, target delivery, quantity, temperature band, route selection, status, and scenario.
- Route includes legs, mode, baseline duration, customs buffer, disruption delay, cost proxy, and source.

**Milestone**

- Types: permit application, permit approval, artwork freeze, label approval, packaging start, packaging complete, dispatch, customs release, depot arrival, and site delivery.
- Store planned, projected, and actual timestamps plus dependency IDs.

### Change and governance entities

**ChangeEvent**

- `event_type`, source, detected time, effective window, old/new hashes, normalized diff, affected keys, and review status.

**Scenario**

- Immutable snapshot with `parent_scenario_id`, trigger event, assumptions, generated time, approval status, approver, and approval note.

**ImpactRecord**

- Links an event to affected rules, countries, label groups, shipments, milestones, old value, new value, severity, explanation, and recommended actions.

**AuditEvent**

- Records ingestion, manual edits, plan generation, scenario approval, and notifications.

## Research ingestion contract

Give teammates a CSV or JSON template with one row per atomic rule:

```json
{
  "jurisdiction": "JP",
  "rule_type": "label",
  "requirement_key": "label.languages",
  "operator": "contains_all",
  "value": ["ja"],
  "effective_from": "2026-04-30",
  "source_url": "https://laws.e-gov.go.jp/...",
  "source_title": "Ministerial Ordinance ...",
  "source_excerpt": "...",
  "retrieved_at": "2026-10-17T00:00:00Z",
  "source_tier": "official",
  "confidence": 1.0,
  "review_status": "needs_review",
  "notes": "Human-translated summary; verify wording"
}
```

Validation must reject missing citations, impossible date ranges, unknown operators, and verified records that use synthetic sources. Imports should generate a preview and diff before commit.

For automated collection, implement an adapter interface with `fetch`, `extract_metadata`, `snapshot`, and `normalize_candidate_rules`. Extraction results remain `needs_review` until a person approves them. Begin with eCFR and EUR-Lex adapters, then add a generic page-snapshot adapter. Do not let the model mark scraped text as verified.

## Planning algorithms

### Rule selection

For a plan timestamp, select the newest approved RuleVersion whose effective interval contains that timestamp. If no verified version exists, preserve the gap and lower readiness; do not silently fall back to a guessed value.

### Label grouping

1. Convert each country's active label rules into a canonical requirement signature.
2. Test hard incompatibilities: conflicting required/prohibited fields, exclusive national template, incompatible date format, missing mandatory language, or booklet page capacity exceeded.
3. Build a compatibility graph in which an edge means two countries can share a label.
4. Produce groups using a deterministic greedy clique-cover heuristic, prioritizing fewer designs while respecting page capacity and operational preferences.
5. Return both the grouping and machine-readable reasons for every split.

The LLM may explain a result, but must not decide compatibility.

### Backward scheduling

Treat milestones as a directed acyclic graph. Starting from target site delivery, subtract durations and buffers backward:

```text
site delivery
<- last mile
<- depot receipt and release
<- international transit
<- customs buffer
<- packaging complete
<- packaging duration
<- label approval/artwork freeze
<- permit approval
<- permit lead time
<- permit application deadline
```

Use business-day arithmetic and jurisdiction calendars where known. Store every duration, buffer, and source. Slack equals the difference between the required deadline and the earliest feasible completion. Negative slack is blocked; low positive slack is at risk.

### Change impact

1. Normalize a new snapshot and compute field-level diffs against its predecessor.
2. Resolve affected jurisdictions and dependency keys.
3. Traverse dependency links to label groups, shipments, and milestones.
4. Query Chalk for recalculated impact features.
5. Clone the approved scenario, recompute only the affected subgraph, and persist an immutable proposed scenario.
6. Rank repair options: split a label group, expedite review, choose another route, increase buffer, or change dispatch date.
7. Show the proposal; never overwrite the approved scenario automatically.

## Chalk integration

Use a separate scraper/API layer for regulations and geographic data, as required. Chalk begins after normalized source data and events exist.

### Why Chalk fits

Chalk provides typed feature definitions, resolvers, low-latency online queries, historical feature storage, and point-in-time offline queries. That makes it suitable for reproducible impact calculations and before/after scenario analysis. Chalk documentation also describes agent-issued dynamic feature queries, but the first implementation should use an allowlisted application tool and server-side permissions rather than unrestricted feature names.

Primary documentation:

- [Chalk overview](https://docs.chalk.ai/docs/overview)
- [Historical offline store](https://docs.chalk.ai/docs/offline-stores)
- [Dynamic Chalk queries](https://docs.chalk.ai/docs/compute/dynamic-chalk-queries)

### Chalk entities and features

Define feature namespaces such as:

- `shipment`: `baseline_transit_days`, `disruption_delay_days`, `customs_buffer_days`, `permit_ready`, `label_ready`, `projected_delivery_at`, `slack_days`, `risk_score`, `risk_band`.
- `country_plan`: `active_rule_version`, `permit_lead_days`, `required_language_count`, `verification_coverage`, `unresolved_requirement_count`, `readiness_score`.
- `label_group`: `country_count`, `language_count`, `estimated_pages`, `compatible`, `rework_days`, `affected_by_change`.
- `route`: `weather_severity`, `closure_status`, `capacity_risk`, `effective_transit_days`.
- `scenario`: `shipments_at_risk`, `max_delay_days`, `labels_requiring_rework`, `countries_blocked`.

Resolvers should read normalized records and calculate features without calling an LLM. The API asks Chalk for online features when opening a dashboard or recalculating an event. Offline point-in-time queries can replay “what the planner knew” at a prior timestamp, which is valuable for the demo and audit story.

### Demo-safe fallback

Implement a `FeatureProvider` interface with `ChalkFeatureProvider` and `LocalFeatureProvider`. If Chalk credentials are absent, the same feature formulas run locally so the clean clone and judging demo remain functional. Display the active provider in developer diagnostics, and use Chalk in the sponsor demo when credentials are configured.

## API surface

Minimum endpoints:

- `POST /api/trials` and `GET /api/trials/{id}`.
- `POST /api/rules/import/preview` and `POST /api/rules/import/commit`.
- `GET /api/jurisdictions/{iso}/requirements?as_of=`.
- `POST /api/trials/{id}/scenarios/generate`.
- `GET /api/scenarios/{id}/timeline`.
- `GET /api/scenarios/{id}/compare/{other_id}`.
- `POST /api/change-events` and `POST /api/change-events/{id}/analyze`.
- `POST /api/scenarios/{id}/approve` and `/reject`.
- `POST /api/assistant/query` with trial and scenario IDs.
- `GET /api/alerts` and `POST /api/alerts/{id}/acknowledge`.

All planning and impact responses should include `calculation_version`, `scenario_id`, input IDs, assumptions, and evidence references.

## Repository structure

```text
apps/
  web/                       Next.js dashboard
  api/                       FastAPI application
packages/
  domain/                    shared schemas and enums
  planner/                   label grouping and schedule engine
  ingestion/                 regulatory and logistics adapters
  feature_provider/          Chalk and local implementations
  assistant/                 grounded tools and prompts
chalk/
  features.py
  resolvers.py
data/
  demo/                      deterministic public/synthetic seed data
  schemas/                   research import JSON Schema
tests/
  unit/                      algorithms and validation
  integration/               API, DB, and Chalk contract tests
  e2e/                       full demo workflow
docs/
  data_provenance.md
  demo_script.md
  architecture.md
docker-compose.yml
.env.example
README.md
```

## Build sequence

### Phase 0 Foundation

- Scaffold web, API, database, migrations, Docker Compose, environment example, linting, and tests.
- Add the domain enums, source-status rules, scenario immutability, and seed command.
- Define the `FeatureProvider`, `RegulatoryAdapter`, and `LogisticsAdapter` interfaces before vendor-specific work.

Exit criterion: a clean clone starts and displays a seeded empty control tower.

### Phase 1 Canonical rules and evidence

- Implement source documents, rule versions, requirements, import preview, validation, and reviewer state.
- Load deeply sourced records for the United States, EU/Germany, Canada, and Japan; add one more jurisdiction if research is ready.
- Add synthetic records for the rest of the demo footprint with unmistakable badges.

Exit criterion: users can search requirements by country and date, and every displayed rule has evidence or is visibly marked synthetic.

### Phase 2 Deterministic planner

- Build label signatures, compatibility reasons, grouping algorithm, milestone DAG, business-day math, slack, and risk bands.
- Generate a baseline scenario from a trial seed.
- Add unit tests for missing data, future-effective rules, incompatible fields, negative slack, and temperature mismatch.

Exit criterion: the same input always produces the same sourced plan.

### Phase 3 Chalk impact features

- Implement Chalk feature definitions and resolvers plus the local fallback.
- Query shipment and scenario features through one provider interface.
- Store query metadata and calculation version on impact records.

Exit criterion: a seeded disruption changes Chalk-derived risk and projected delivery features, while local fallback matches expected results.

### Phase 4 Change detection and scenarios

- Add regulation snapshot hashes, normalized diffs, logistics events, dependency traversal, scenario cloning, repair options, and approval workflow.
- Create three planted demo events: longer permit lead time, missing/new label language, and route delay.

Exit criterion: each event produces a traceable before/after scenario without mutating the approved baseline.

### Phase 5 User experience and assistant

- Finish the four screens, evidence drawer, causal chain, comparison view, and approve/reject actions.
- Give the assistant read-only tools for requirements, shipment features, scenario comparisons, and citations.
- Add the optional calendar button, ICS generation, and `CalendarProvider` interface.
- Add Photon notification delivery behind a feature flag only if its integration contract is available; otherwise ship a tested notification adapter stub without blocking the product.

Exit criterion: a judge can understand the problem, disruption, impact, and chosen repair in under three minutes, then optionally export the approved milestones to a calendar.

### Phase 6 Hardening

- Add E2E tests, API failure fallbacks, loading/error states, seeded screenshots, audit export, and accessibility checks.
- Document exact startup, Chalk configuration, demo reset, source provenance, and limitations.

Exit criterion: the product runs from a clean clone with one command and the demo works without live external APIs.

## Testing strategy

- Schema tests: reject unsupported operators, missing citations, overlapping active rule intervals, and verified synthetic records.
- Planner golden tests: fixed inputs produce checked label groups and milestone dates.
- Property tests: no milestone can precede its dependency; adding delay cannot improve delivery; removing a required language cannot keep an incompatible label group valid.
- Impact tests: each changed requirement key reaches the correct dependent shipments and no unrelated shipments.
- Point-in-time tests: future-effective Japanese rules are excluded before their start date and included afterward.
- Provider contract tests: Chalk and local providers expose identical response shapes.
- E2E demo test: baseline -> inject event -> analyze -> compare -> approve -> control tower updates.
- Safety tests: assistant refuses uncited legal conclusions, distinguishes verified from simulated content, and cannot approve scenarios.

## Demo scenario

Use a fictional blinded oral-tablet trial manufactured in Boston with 20-30 country destinations. Deeply demonstrate the US, Germany/EU, Canada, Japan, and one additional researched country.

1. Open the control tower: most countries are on track; Japan has a future-effective rule badge.
2. Open Germany to show a sourced rule and the milestone chain.
3. Inject a simulated regulatory change requiring an added language or label field.
4. The system identifies the affected shared label group and shipments.
5. Chalk recalculates label rework days, shipment slack, projected delivery, and scenario risk.
6. Compare baseline and proposal. One country misses its target unless its label is split or review is expedited.
7. Ask the assistant why. It answers with the causal chain and links to evidence.
8. Approve the separate-label repair. The control tower and audit trail update.
9. Optionally show the alert in Photon with a deep link back to the comparison.

## Implementation completeness

The implementation agent should build the full product described in this plan rather than stop at a narrow vertical slice. This includes:

- sourced and dated requirements with versioning, review, search, and import preview;
- regulatory snapshot collection and change detection through adapter contracts;
- geographical and logistics adapters with cached or seeded fallbacks;
- deterministic label compatibility and grouping;
- complete backward scheduling and dependency timelines;
- route alternatives and disruption recalculation;
- immutable before-and-after scenarios and human approval;
- Chalk-powered impact features with a matching local fallback;
- control tower, requirements, timeline, comparison, evidence, audit, and assistant experiences;
- 20-30-country-capable data and UI behavior;
- optional calendar export/synchronization initiated by a button;
- reproducible seed data, clean-clone setup, and full automated tests.

Photon is the only planned product surface that may remain behind a feature flag or adapter stub if its contract is unavailable. Its absence must not leave unfinished application behavior elsewhere.

The following remain prohibited rather than merely deferred:

- autonomous legal or regulatory conclusions without stored evidence;
- silently approving or applying plan changes;
- representing synthetic inputs as verified facts;
- making the application depend on live third-party APIs to run.

## Definition of done

The product is complete for the hackathon when a clean clone can load a realistic seeded trial, display cited country requirements, generate label groups and milestone dates, ingest a planted regulatory or geographic event, use Chalk to recompute shipment impact, show a traceable scenario comparison, answer “why” with evidence, and require a human to approve any plan change.

The interface must state that it is decision support, not regulatory or legal advice, and must never blur verified public rules with synthetic demo assumptions.
