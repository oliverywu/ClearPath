# Cleared for Takeoff

Local clinical-supply decision support: dated regulatory evidence, compatible label groups, dependency schedules, change scenarios, human approval and audit history. The packaged trial and requirements are **synthetic demonstrations**, not verified regulations or legal advice.

The product deliberately combines two kinds of intelligence. Deterministic code owns calculations that must be reproducible. AI is reserved for uncertain, language-heavy work such as interpreting source documents, identifying meaningful changes, and explaining scenarios. A human remains responsible for evidence verification and plan approval.

## Product decision levels

```mermaid
flowchart TB
    L1["Level 1: Evidence and inputs<br/>Regulations, routes, product data, disruptions"]
    L2["Level 2: AI research and analysis<br/>Extract, compare, translate, classify, explain<br/>Partially implemented"]
    L3["Level 3: Deterministic planning<br/>Rule selection, label grouping, dates, slack, risk, repairs<br/>Implemented"]
    L4["Level 4: Human governance<br/>Verify evidence, review trade-offs, approve or reject<br/>Implemented"]
    L5["Level 5: Coordination<br/>Dashboard, calendar, Photon alerts and follow-up<br/>Photon remaining"]

    L1 --> L2 --> L3 --> L4 --> L5
```

AI may propose structured candidates and scenario questions, but it may not verify a regulation, perform the authoritative schedule calculation, or approve a plan. This boundary keeps the system useful when model access is unavailable and makes every operational result reproducible.

## Architecture

```mermaid
flowchart LR
    A["Official regulatory sources"] --> I["Source ingestion and snapshots"]
    B["Weather and logistics reports"] --> I
    C["Trial and product data"] --> V["Schema validation"]

    I --> R["AI Research Copilot<br/>planned"]
    R -->|candidate rules and change events| V
    I -->|manual structured import| V
    V --> H["Human evidence review"]
    H --> S["Versioned SQLite store"]

    S --> P["Deterministic planner"]
    P --> F["Local or Chalk feature provider"]
    F --> Q["Immutable proposed scenario"]
    Q --> D["Dashboard comparison"]
    Q --> X["Grounded planner assistant"]
    D --> G["Human approval or rejection"]
    G --> K["Approved calendar and audit history"]
    Q --> N["Photon notification and follow-up<br/>planned"]
```

The current implementation is complete from validated structured inputs through planning, comparison, approval, audit, and calendar export. AI-assisted research/change analysis and live Photon delivery are the main remaining hackathon features. Detailed product decisions and the prioritized work list are in [`PLANNING_NOTES.txt`](PLANNING_NOTES.txt).

## Start

Prerequisite: **Python 3.11+**. No runtime package installation, Docker, cloud service, model key, Chalk or Photon credentials are needed. The Windows launcher also detects Codex's bundled Python.

Clone the team branch on any laptop, then enter the repository:

```powershell
git clone --branch cleared-for-takeoff https://github.com/oliverywu/hackharvard.git
cd hackharvard
```

From the repository root in PowerShell:

```powershell
.\start.ps1
```

If PowerShell blocks scripts, run `powershell -ExecutionPolicy Bypass -File .\start.ps1`. Portable equivalent: `python start.py` (or `python3 start.py`).

The command initializes/migrates SQLite, loads the demo if empty, generates the baseline, starts both services, and prints:

- Website: **http://localhost:3000**
- API: **http://localhost:8000**
- Database: `.local/cleared.sqlite3`

Both services bind to loopback. Keep the terminal running; Ctrl+C stops both. Normal restart preserves data. Choose alternate ports with `-WebPort 3001 -ApiPort 8001` or Python's `--web-port 3001 --api-port 8001`. An occupied port produces a clear error. `HOST` must be changed explicitly to expose the app beyond the laptop.

## Run the demo

1. Open **Control tower**: 24 countries, Boston origin, a fictional blinded oral-tablet product, sites, depots, enrollment and demand. The baseline is feasible. The data supplies a frozen planning date for repeatability.
2. Open Germany in the country grid. Select a requirement for its exact source excerpt, effective interval and review state. Inspect the milestone timeline.
3. In **Scenarios**, analyze the Japanese mandatory-label-field event. Inspect the shared label and delayed review, packaging and dispatch. Create the recommended separate-label repair and review its cost/schedule trade-offs.
4. **Approve** with your reviewer name and decision note. Only this human decision updates the current approved plan.
5. Analyze the Boston–Frankfurt weather event. Compare its delayed customs/depot/site dates with the configured Amsterdam alternative. Creating an alternative remains a proposal until approved.
6. In **Planner assistant**, select the proposal and ask why the destination is at risk. Answers use stored calculations and evidence.
7. View **Audit history**, then download **Approved calendar (.ics)** in Scenarios.

The **Control tower** includes a monthly supply calendar populated from the selected scenario's projected milestones. Select the latest event proposal to see its changed dates before approval. Select any calendar item to add that milestone directly to Google Calendar or Outlook. The full `.ics` export contains every milestone and is available for approved scenarios, so it can be imported into either calendar service.

Selecting a country opens its requirements and delivery progress. The progress tracker shows the current planned stage, business-day duration for every step, projected dates, and remaining shipment slack. Orange delay-exposure labels identify milestones affected by the selected event or a shipment with low slack. These labels explain stored scenario risk; they are not probabilistic forecasts.

The backup event increases Canada's permit lead time. All event names, affected jurisdictions, delays and repairs come from data records.

Reset with the Control tower button, or stop the app and run `.\start.ps1 -Reset`. Reset activates a fresh synthetic baseline while retaining historical scenario/audit snapshots. For the alternative fixture: `python start.py --db .local/replacement.sqlite3 --fixture data/demo/replacement.json`. Add `--reset` to explicitly replace an existing demo database.

## Teammate research and replacement data

Use **Data & research**. Atomic research imports accept one or more JSON or CSV files and combine records across countries into one reviewable preview. The preview reports record, country, addition, supersession, needs-review, and duplicate-conflict counts. Full dataset imports take one complete JSON object because a dataset is an atomic workspace containing all countries and trial inputs. Both paths require **Validate & preview** before **Commit** with reviewer attribution. Downloadable templates are available in the screen and under `data/schemas/`.

See `data/schemas/` and complete working examples `data/demo/trial.json` and `data/demo/replacement.json`. `GET /api/dataset` exports the active dataset as a template. Replace the JSON records or import them; no application changes or fixture-builder execution are required.

| Atomic rule fields | Meaning |
| --- | --- |
| `id`, `jurisdiction`, `rule_type` | Stable record ID, known jurisdiction and category |
| `requirement_key`, `operator`, `value` | Typed requirement and value |
| `effective_from`, optional `effective_to` | Inclusive start, exclusive end; ISO dates |
| `source_url`, `source_title`, `source_excerpt` | Exact citation and retained evidence |
| `retrieved_at`, `source_tier`, `confidence`, `review_status` | Provenance and review state |

Complete datasets contain `id`, `as_of`, `trial` (including `product`), `config`, `jurisdictions`, `country_plans`, `rules`, `routes`, and `events`. Country plans hold site/depot, enrollment, demand/quantity, ready date, delivery target and holidays. Routes hold legs, transit/customs/depot/last-mile durations, temperature band, cost and source. Configuration controls booklet capacity and risk/readiness weights. Events describe normalized changes and repair choices.

The interface distinguishes **verified**, **needs review**, **authoritative secondary** and **synthetic**. New research should remain `needs_review` until qualified human review; synthetic sources cannot be marked verified. Select a requirement in **Requirements**, enter a reviewer name and note, then verify, retain for review, or retire it. The decision creates a new immutable rule version and regenerates a proposed plan. Existing approved snapshots retain their original inputs.

The **Source registry** records official HTTPS pages and supports generic-page, eCFR, and EUR-Lex adapters. **Check now** collects the page, stores a content hash, and creates a diff/change event when content changes. Network access is only used when a teammate clicks the control. Extracted candidates remain `needs_review`; a text diff does not establish a verified legal change. Manual pasted snapshots remain available for pages that block automated collection.

## Planner assistant and AI boundary

The planner assistant works offline by default. Its deterministic answers cite the selected immutable scenario and source records. Ask with a full country name (`Why is Argentina at risk?`) or an uppercase two-letter code (`Why is DE at risk?`). Full names take priority, so ordinary words such as “at” are never interpreted as country codes. Answers lead with the direct cause, dates, slack, and scenario impact; repeated causal text is removed. Negative slack is expressed as business days late rather than a negative number. To enable a model-written answer, copy `.env.example` to `.env` and set:

```dotenv
ASSISTANT_PROVIDER=openai
OPENAI_API_KEY=your-api-key
OPENAI_MODEL=gpt-5.4-mini
```

The integration uses the OpenAI Responses API with one allowlisted, read-only planning-context tool. It cannot approve, reject, or modify plans. Citations still come from stored evidence, API failures fall back visibly to the local assistant, and responses are sent with storage disabled. Never commit `.env` or an API key.

The current model integration improves explanation, not the underlying calculation. The next AI work should add a research copilot, semantic change analysis, and constrained conversational what-if tools. Those features must produce reviewable candidates or temporary simulations; deterministic code and human approval remain authoritative.

## Teammate handoff checklist

**The current deterministic demo runs without ChatGPT, OpenAI, Chalk, Photon, Google, or Microsoft credentials.** Planning, risk calculation, scenarios, approvals, audit history, the dashboard calendar, `.ics` export, and the offline planner assistant remain available locally. OpenAI research analysis and Photon are required for the intended final hackathon story but may fail safely without disabling the planning workflow.

Every imported rule should begin as `needs_review`. A qualified reviewer must inspect evidence in the UI. Dataset and rule commits generate proposals; a separate named plan approval is still required.

### Required hackathon completion work

- [ ] **AI Research Copilot:** accept a registered regulator page or pasted source text and extract candidate atomic requirements into the existing schema. Each candidate must include an exact supporting quotation, jurisdiction, effective interval, requirement key, value, confidence, and ambiguity note. AI output must remain `needs_review`; schema validation and a named human review are required before planning can use it.
- [ ] **AI Change Analyst:** compare a new source snapshot with its predecessor, summarize the meaningful semantic change, identify likely requirement keys and affected jurisdictions, and prepare a proposed change event. Preserve the raw diff and citations. The AI may propose materiality, but a reviewer must confirm the normalized change before the deterministic impact calculation runs.
- [ ] **Conversational what-if tool:** allow questions such as “What if Japan receives a separate label?” or “What if Germany uses the Amsterdam route?” The assistant should translate the request into an allowlisted temporary scenario input, call the deterministic planner, and explain the returned comparison. It must never approve, persist, or silently apply the result.
- [ ] **Verified evidence slice:** replace a focused subset of synthetic rules with official or authoritative records for at least the United States, EU/Germany, Canada, and Japan. Prefer a small number of deeply sourced, human-reviewed requirements over superficial coverage. Retain synthetic records for the wider 24-country demonstration and label them clearly.
- [ ] **Live Photon integration:** implement authenticated `NotificationProvider.send`, deliver a scenario alert with its cause and deep link, and support the intended Photon follow-up interaction. A failed delivery must remain visible in diagnostics and must never affect scenario state. Photon is part of the primary hackathon story, not an optional production enhancement.
- [ ] **AI evaluation set:** create a small gold dataset of regulatory passages, source changes, and planner questions. Measure requirement-key extraction, effective-date accuracy, quotation/citation accuracy, material-change classification, grounded-answer quality, and correct abstention. Include adversarial examples where the model should say that evidence is insufficient.
- [ ] **Changed-only scenario view:** make the comparison screen default to affected countries, milestones, label groups, and routes, with unchanged shipments collapsed behind an explicit control. Keep the full plan available for audit, while ensuring the main disruption story can be understood in under three minutes.
- [ ] **Live provider smoke tests:** run one real OpenAI research/assistant flow and one real Photon notification before the demo. If the project is submitted for a Chalk category, also deploy the resolvers and verify one live query against the local parity result. Keep secrets out of Git and preserve local fallbacks.

### Required before using real trial data

- [ ] Country researchers replace synthetic rules with official or authoritative research using the CSV/JSON templates in **Data & research**. Every record needs an exact excerpt, source URL, retrieval date, and effective date.
- [ ] A qualified reviewer imports the research, resolves duplicate conflicts, and records **Verify**, **Keep in review**, or **Retire** for every rule used operationally.
- [ ] The supply-planning owner replaces demo product, demand, quantities, sites, depots, routes, ready dates, delivery targets, holidays, and risk settings in one complete dataset JSON.
- [ ] The team validates the full dataset in **Data & research**, commits it with reviewer attribution, and checks every country for missing or blocked inputs.
- [ ] The team reviews generated proposals in **Scenarios** and records a named approval or rejection with a decision note. Confirm that the dashboard calendar and country progress dates match the approved plan.
- [ ] Before a demo or handoff, run `python -m unittest discover -v`. For full UI verification, also run `npm install`, `npx playwright install chromium`, and `npm run test:browser`.

### Optional infrastructure after the hackathon workflow is complete

- [ ] **Chalk:** deploy the matching feature resolvers, confirm remote/local parity, then add Chalk credentials if hosted feature computation is wanted. Local calculations already work.
- [ ] **Google Calendar / Outlook:** the app already opens individual milestones in either service and exports the complete approved timeline as `.ics`. Implement OAuth account synchronization only if automatic background updates to a shared calendar are required.
- [ ] **Hosting:** choose a deployment host and production data/security approach only if teammates need the app while the host laptop is off. The current app intentionally runs on one laptop with SQLite and local reviewer attribution.

Never share or commit `.env`, API keys, client secrets, or the local `.local/cleared.sqlite3` database.

### Daily teammate workflow

1. Pull the branch: `git pull origin cleared-for-takeoff`.
2. Start the app with `./start.ps1` in PowerShell or `python start.py` on macOS/Linux.
3. Open `http://localhost:3000`. Keep the terminal open while using the app.
4. Import research in **Data & research**, review evidence in **Requirements**, and assess resulting dates in **Scenarios** and the Control tower calendar.
5. Stop the app with Ctrl+C. Local work is stored in `.local/cleared.sqlite3`; do not commit that database.

## Chalk

Local features support the full workflow by default. To use an existing Chalk environment, copy `.env.example` to `.env` and set:

```dotenv
CHALK_CLIENT_ID=your-client-id
CHALK_CLIENT_SECRET=your-client-secret
CHALK_ENVIRONMENT=your-environment-id
CHALK_QUERY_SERVER=https://your-environment-query-server
```

Deploy `chalk/features.py`, `chalk/resolvers.py`, and shared `packages/feature_provider/formulas.py` in your Chalk project using its SDK/tooling. The local app needs no SDK. It uses OAuth and allowlisted online feature queries from normalized primitive inputs. Resolvers calculate delivery, slack, risk and transit. An existing `CHALK_ACCESS_TOKEN` is also supported. Never commit credentials.

Credentials automatically select `ChalkFeatureProvider`. Remote/local parity is checked; authentication, connectivity, deployment or parity failures explicitly report a local fallback. `FEATURE_PROVIDER=local` forces offline mode. Historical scenario snapshots retain point-in-time feature values. **Live Chalk requires your account and deployed matching resolvers; tests verify mocked contract/formula parity, not a live account.**

## Calendar and Photon

Approved-only RFC 5545 ICS export includes permit filing/approval, label review, artwork freeze, packaging start/completion, dispatch, customs arrival/release, depot arrival and site delivery. Import it into Google Calendar, Outlook or another calendar. `CalendarProvider` defines future direct account synchronization. Provider failures cannot modify approval or plan data.

Photon is isolated behind `NotificationProvider`, disabled by default. `PHOTON_ENABLED=true` selects the tested unconfigured adapter; dashboard alerts remain available and no message delivery is claimed. Actual delivery requires implementing `send(alert)` against the confirmed Photon contract and credentials. Payloads include scenario links.

## Tests

All deterministic, integration, contract and full HTTP demo tests use the standard library:

```powershell
python -m unittest discover -v
```

Use `py` or your Python executable if necessary. Tests use temporary databases and available loopback ports, leaving the running demo database untouched. The HTTP test starts the real launcher and verifies both disruptions, repairs, approval, audit, calendar export and a distinct replacement dataset.

Optional browser acceptance tests require Node.js 20+ and Playwright (downloads are only for test tooling):

```powershell
npm install
npx playwright install chromium
npm run test:browser
```

The browser suite starts an isolated database, exercises the UI, checks mobile overflow and uncaught errors, and writes screenshots into `test-results/`. `CFT_PYTHON` selects a Python executable; `PLAYWRIGHT_CHROMIUM_EXECUTABLE` selects an existing Chromium installation.

## Architecture and limits

The standard-library API, SQLite and buildless browser app keep offline startup simple. SQLite is appropriate for this single-laptop, single-user hackathon workflow: it needs no server or credentials and still provides transactions, constraints, WAL mode, and immutable-snapshot triggers. PostgreSQL would become useful for a hosted multi-user deployment with concurrent writers, account isolation, centralized backups, and operational monitoring. Adding it now would introduce deployment work without improving this demo, so it is intentionally deferred.

This is a single-user local tool. Reviewer names are attribution, not production authentication. Holiday calendars, route estimates and evidence quality depend on imported records. The assistant remains usable without a model-service dependency. Source checks are user-triggered and only run while the application and laptop are on.

AI-assisted research/change analysis and Photon are the main unfinished hackathon features. Live Chalk and direct calendar-account synchronization need external setup; complete local planning, governance, and ICS export work now. See [planning notes](PLANNING_NOTES.txt), [architecture](docs/architecture.md), [provenance](docs/data_provenance.md), [demo script](docs/demo_script.md), and the original [challenge brief](CHALLENGE_BRIEF.txt).
