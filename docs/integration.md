# Integration: one application, one API, one authority

Branch `connect`, cut from `origin/integration` at `dd7d903`. Component sources already
colocated on that commit: planner = `chihiro-branch` `90f9689` + `chalk-logistics` `e3a831d`;
messaging = `anna-branch` `e113ef9`; frontend = `frontend-v12` `a9ef649`.

## Architecture

```
 Browser (Garima's frontend, the only UI)
   │  every request: same origin, /api/*
   ▼
 cleared-for-takeoff-app/server.js  :3000
   ├─ static files
   ├─ POST /api/route-analysis      (Google Routes + GDACS; key stays server-side)
   └─ proxy every other /api/*  ──►  planner/apps/api/server.py --integrated  :8000
                                       IntegratedService
                                         ├─ Frontend adapter (frontend.py) + schemas (schemas.py)
                                         ├─ Governance (governance.py): proposals, current-plan
                                         │    pointer, atomic approve/reject, idempotency, rebase
                                         ├─ MessagingLink (messaging_link.py) ──► messaging/planner_conversation.py
                                         │    (Anna's state machine; optional inbound photon_bridge thread)
                                         ├─ Service (Oliver + Chihiro planner engine, evidence, audit)
                                         └─ Feature provider (Chalk online query, parity-checked; local fallback)
                                       SQLite (.local/cleared.sqlite3): the one durable database
```

Anna's FastAPI app (`messaging/api.py`) and Vite dashboard (`messaging/frontend`) and the
planner's own web UI (`planner/apps/web`) are kept as standalone tools with their tests, but are
**not** started by `start.py` and are not user-facing in the integrated application.

## Endpoint mapping

| Frontend endpoint | Request | Response | Backend source | Adapter | Status |
|---|---|---|---|---|---|
| `GET /api/warnings` | – | `Warning[]` newest first | planner events + their proposals | `Frontend.warning` | done |
| `GET /api/warnings/:id` | – | `Warning` + `evidence[]`, `options[]`, `currentPlan`, `audit[]` | same + audit | `Frontend.warning(detail)` | done |
| `GET /api/warnings/:id/options` | – | `Option[]` (remediation options with before/after) | `Governance.option_views` | `Frontend.option` | done |
| `GET /api/shipments` | – | `Shipment[]` | current plan (`settings.approved_scenario_id`) | `Frontend.shipment` | done |
| `GET /api/inventory` | – | `{configured:false, items:[], message, provenance}` | none (no inventory source) | – | intentional empty state |
| `GET /api/photon/chats` | – | `Chat[]` most recent first | `chats` + `chat_messages` tables | `Frontend.chats` | done |
| `GET /api/photon/chats/:id/messages` | – | `Message[]` oldest first | `chat_messages` | stored in frontend shape | done |
| `POST /api/photon/chats/:id/messages` | `{text, clientMessageId}` | `{message, replies[], replayed}` | Anna's `planner_conversation` → governance | `MessagingLink.receive` | done (scripted replies removed from real path) |
| `GET /api/calendar?month=YYYY-MM` | – | `{month, events[{date, level, label}]}` | current-plan milestones, ship-by, targets, warnings | `Frontend.calendar` | done |
| `GET /api/schedule/:date` | – | `{date, items[]}` | same, one day | `Frontend.schedule` | done |
| `GET /api/chalk/insights?date=` | – | `{date, risk, summary, recommendations[], source, available}` | outlook features stored in the current plan (Chalk or local fallback) | `Frontend.insight` | done |
| `GET /api/tracking`, `/api/tracking/:id` | – | `Tracking[]` / `Tracking` | modeled from current-plan milestones (no telemetry) | `Frontend.tracking` | done, labeled modeled |
| `POST /api/route-analysis` | `{origin, destination, proximityKm}` | analysis | `server.js` (Google Routes + GDACS) | none | unchanged; needs `GOOGLE_MAPS_API_KEY` |
| `GET /api/context` | – | `{today, trial, currentPlan, providers}` | dataset + pointer | – | new |
| `GET /api/evidence?warningId=` / `?country=` | – | `Evidence[]` with citation, excerpt, status | event + scenario rules | `Frontend.evidence_*` | new |
| `GET /api/proposals[?warningId=]`, `/api/proposals/:id` | – | `Proposal` | `scenarios` + `proposal_options` | `Frontend.proposal` | new |
| `GET /api/proposals/:id/comparison` | – | before/after comparison | `engine.compare_plans` | `camelize` | new |
| `POST /api/proposals/:id/approve` | `{actorId, actorRole, rationale, channel, idempotencyKey, expectedCurrentPlanId}` | `DecisionResult` | `Governance.decide` | – | new |
| `POST /api/proposals/:id/reject` | same (expected plan optional) | `DecisionResult` | `Governance.decide` | – | new |
| `POST /api/warnings/:id/evidence/review` | `{actorId, status: verified\|retired, note}` | `Warning` | `Governance.review_evidence` | – | new |
| `GET /api/current-plan` | – | `{planId, version, approvedAt, approvedBy, status, appliedEventIds}` | pointer | – | new |
| `GET /api/audit-history[?entityId=a,b]` | – | `AuditEntry[]` newest first | append-only `audit` table | `camelize` | new |
| `POST /api/change-events` | planner event | `Warning` + `proposalIds` | planner validation → proposals → chat alerts | – | integrated (was planner-only) |

Errors: `{error, details}` with 400/403/404/409/410/422/500. Governance refusals carry a stable
`details.code` (`unauthorized`, `stale_proposal`, `stale_expected_plan`, `already_decided`,
`idempotency_conflict`, `unverified_evidence`, `missing_fields`). The planner's legacy direct
`POST /api/scenarios/:id/approve|reject` returns **410** in integrated mode so no path can move the
pointer without the governed checks. All other original planner endpoints remain available.

## Schema mappings (canonical → frontend)

Only `planner/apps/api/frontend.py` translates; schemas live in `planner/apps/api/schemas.py`
and every response is validated before it is sent (a violation is a 500, never bad data).

| Canonical (planner) | Frontend |
|---|---|
| `shipment.id` | `id` |
| `country_code` / `country_name` | `country` / `countryName` |
| `slack_days` | `slackDays` |
| `target_delivery` / `projected_delivery` | `targetDelivery` / `projectedDelivery` |
| `label_group_id` | `labelGroup` |
| `risk_band` | `status` (`on_track` / `at_risk` / `blocked`) |
| `route_id`, `route_name`, `gateway_airport` | `route.{id,name,gatewayAirport}` |
| `delivery_range.{best,likely,worst}` | `deliveryRange.{best,likely,worst}` |
| `ship_by.{likely,safe}` | `shipBy.{likely,safe}` |
| `worst_case_slack_days` | `worstCaseSlackDays` |
| `features.agent_answer`, `features.outlook_source` | `outlook.{agentAnswer,source}` |
| current plan id / pending proposals touching the shipment | `currentPlanId` / `proposalIds` |
| `trial.name` (first segment) / `trial.product` | `study` / `kit` |
| `event.id` | `warning.id = "wrn-" + event.id`, `eventId` |
| `event.detected_at` | `createdAt` |
| affected shipment ids (from the no-mitigation proposal) | `shipmentIds`, `shipmentsAffected` |
| audit `entity_id`, `created_at`, payload keys | `entityId`, `createdAt`, camelCase payload |

## Lifecycles (kept separate)

* **Warning** `open | in_review | resolved` — `in_review` while non-stale proposals are pending;
  `resolved` once the current plan includes the event (or its evidence is retired); `open` when
  no decision is possible yet (e.g. a source snapshot without normalized changes, or every option rejected).
* **Evidence** `needs_review | verified | retired | synthetic` — from the event/rule `review_status`
  and source tier. Approval is refused (422) while the triggering evidence is `needs_review` or `retired`.
* **Plan** `proposed | approved | rejected | superseded` — `approved` is only the current pointer;
  a previously approved plan, or a pending proposal calculated from an older plan, is `superseded`.

## Approval: the only path that moves the current plan

`Governance.decide()` runs under the repository lock in one SQLite transaction:
idempotency replay → proposal exists and is `proposed` → `expectedCurrentPlanId` equals the pointer →
proposal's parent equals the pointer → dataset unchanged → actor in the role registry with
`can_approve` and a matching role → evidence reviewed → record decision → move pointer exactly once
→ audit `current_plan.changed` with before/after plan ids, version, actor, role, channel, rationale,
idempotency key → store the result under the idempotency key. Refusals are audited too
(`proposal.approve_refused`). After a successful approval, unresolved disruptions are re-analyzed
against the new plan (new immutable proposals) and one notification is recorded/sent
(`notifications` outbox, keyed `approved:<proposal>`).

Max/Photon calls this with: proposal id from the previewed option, actor id from the chat/Photon
sender, role from the registry, rationale, channel (`web`/`photon`), idempotency key
`<channel>:<inbound message id>:<action>`, and expected plan = the proposal's parent (the plan the
person previewed). Conversation state stores only `selected_proposal_id` / `approved_proposal_id`.
Inbound messages are deduplicated by external id (`inbound_messages`), so a replayed Photon/web
message returns the original reply and never repeats a decision.

Roles: `planner/data/demo/authorized_roles.json` (moved from `messaging/data/authorized_roles.json`;
SIMULATED identities: Maya `supply_lead` can approve; Kenji `affiliate` cannot).

## Planner feature comparison

| Calculation | Oliver | Chihiro | Anna | Canonical result | Regression test |
|---|---|---|---|---|---|
| Milestone schedule, projected delivery | deterministic business-day backward/forward chain | – | `calculate_shipment` (calendar days from a ship date) | Oliver's engine; Anna's arrival must equal it | `ArrivalAndBufferRegression.test_anna_arrival_matches_planner_projection_and_risk_sign` |
| Slack / buffer | business days, risk bands | worst-case slack | calendar-day `buffer_days`, `at_risk` | business-day slack + band; Anna's calendar buffer shown as a cross-check in previews | same test (sign agreement) |
| Uncertainty | – | best/likely/worst legs, LPI customs dwell, gateways, holidays | – | Chihiro's `delivery_range` in the engine; likely == main schedule | `UncertaintyRegression` (engine vs Chalk formula, all 24 countries) |
| Ship-by dates | – | likely and safe ship-by | – | Chihiro's, stored in every scenario | `test_safe_ship_by_absorbs_worst_case` |
| Label grouping | evidence-aware compatibility grouping | – | `label_grouping.py` (US/EU/JP/CA scope) | Oliver's (data-driven, all 24 countries); Anna's kept for her standalone dashboard only | planner `test_planner.py` |
| Disruption impact | event → immutable scenario, causal chain | – | `impact_analyzer` (calendar days) | Oliver's scenarios (business days) | `test_disruption_shift_is_business_days_and_anna_transitions_agree` |
| Before/after | `compare_plans` | – | before/after plan snapshots | `compare_plans` → previews and `/comparison` | `ProposalRegression` |
| Remediation options | event `repair_options` | – | numbered options, previews | planner proposals per option + "accept the delay", numbered for chat | integrated `GovernanceTests`, messaging `test_planner_conversation` |
| Risk transitions | risk band | – | `find_newly_at_risk` | Anna's rule applied to planner shipments, stated in previews | `test_disruption_shift…` |
| Approvals, audit | `repo.decide`, append-only audit | – | authorization, explicit APPROVE, idempotent replies | governed `decide()` in the planner DB | `GovernanceTests`, `MessagingTests` |
| Calendar | ICS export of approved milestones | holidays | – | current-plan milestones → `/calendar`, `/schedule` | contract tests |

No second planner produces an authoritative schedule: Anna's functions only read planner shipments.

## Chalk

| Value | Kind | Authority |
|---|---|---|
| `effective_transit_days`, `projected_delivery_at`, `slack_days`, `risk_score`, `risk_band` | deterministic derived feature | must equal the local formula (parity check) or the local value is kept |
| `delivery_*_at`, `ship_by_*`, `worst_case_slack_days` | deterministic derived feature | same parity rule; computed by `logistics.py` (byte-identical to `chalk/logistics_formulas.py`) |
| `agent_answer` | explanation (the only timing sentence Max may state) | same parity rule |
| insight `risk` | deterministic derived feature (from stored bands) | read from the current plan |
| insight `summary`, `recommendations` | explanation / recommendation | never change planner results |
| Chalk online query itself | optional external computation | configured via `CHALK_*`; otherwise local fallback |

Values are computed when a scenario is generated and stored in that immutable scenario, so
`/api/chalk/insights` is reproducible. Without credentials, or on any failure or mismatch, the
plan keeps the local values and `source.label` says "Local deterministic fallback · <reason>".
Tests: `ChalkParity` (matching response used; mismatching/failing response falls back with identical
results), planner `test_chalk_outlook.py`, and the insights contract/provenance tests.

## Data provenance

* All trial, rule, route and event data in the demo dataset (`planner/data/demo/trial_logistics.json`)
  is **synthetic** except Chihiro's public logistics benchmarks (World Bank LPI 2023 customs dwell,
  OurAirports gateways) and the few official/needs-review rules. Responses carry `provenance`
  (`synthetic`, `modeled`, `needs_review`, `live`) and `evidenceStatus`; nothing synthetic is labeled live.
* **Inventory: honest empty state (decision).** No inventory records exist in any component, so
  `/api/inventory` returns `configured:false` with an explanation and the UI shows it. Shipment
  schedules are not presented as stock. Adding a labeled modeled dataset is deferred.
* **Tracking: modeled.** Position/progress is derived from current-plan milestones vs the planning
  date (`telemetry: "none"`, `temperatureC: null`, `statusLabel` starts with "Planned").
* "Today" in the UI is the dataset's planning date (`as_of`, 2026-10-19), from `/api/context`.

## Known limitations

* Identity is simulated: in the web chat each conversation acts as its participant (Maya, Kenji);
  `POST /api/proposals/:id/approve` trusts the supplied `actorId`. There is no login. Real Photon
  messages carry the sender id, which must be listed in the role registry.
* The Photon inbound bridge (`PHOTON_BRIDGE_ENABLED=true`) and outbound notifications
  (`PHOTON_ENABLED=true`) were tested with mocked clients only; no live Photon credentials were available.
* Chalk online queries were tested with mocked responses only; no live Chalk deployment was available.
* Route-hazard analysis needs `GOOGLE_MAPS_API_KEY`, and Google driving routes cannot reach overseas
  destinations (the frontend's original design), so most international shipments return an error.
* Rule/dataset import flows from the planner's legacy UI still create scenarios without
  `proposal_options`; they are visible in the planner API but cannot be approved through governance.
* Free-text questions to Max use the planner's grounded assistant; Anna's Claude-based cited Q&A is
  used only when `ANTHROPIC_API_KEY` is set (not exercised here).

## Intentionally deferred

* Authentication / real user identity and per-role UI.
* A modeled inventory dataset and live carrier telemetry.
* Wiring planner admin imports (rules/datasets) into governed proposals.
* Retiring Anna's standalone FastAPI dashboard and the planner's legacy web UI.
