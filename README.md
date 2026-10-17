# Cleared for Takeoff

Clinical-trial supply planning with governed plan changes. One application:

* **Website** — Garima's frontend (`cleared-for-takeoff/cleared-for-takeoff-app`), the only user-facing UI.
* **Unified API** — the planner (`planner/`, Oliver + Chihiro) serving every `/api` route, with
  Chihiro's Chalk features (`planner/chalk`, `planner/packages/feature_provider`) and Anna's
  messaging and decision agent (`messaging/`) running in-process.
* **One database** — `.local/cleared.sqlite3` owns proposals, the current plan, approvals,
  evidence, conversations and the audit history.

Architecture, endpoint map, schema mappings, planner-feature comparison and data provenance:
[`docs/integration.md`](docs/integration.md).

## Run it (fresh clone)

Prerequisites: **Python 3.11+** and **Node.js 18+**. No packages need installing for the app itself.

```bash
git clone https://github.com/oliverywu/hackharvard.git
cd hackharvard
git checkout connect
python start.py            # macOS / Linux  (python3 start.py if needed)
```

Windows (PowerShell or double-click):

```powershell
.\start.ps1                # or start.cmd
```

`start.py` validates prerequisites and ports, creates or migrates the database, starts the API and
the website, and prints:

```
Website: http://localhost:3000
API:     http://localhost:8000   (browser uses /api on the website origin)
```

Open **http://localhost:3000**. Ctrl+C stops both processes. Options: `--check` (validate only),
`--reset` (re-seed the synthetic demo dataset; history is kept), `--web-port`, `--api-port`, `--db`.

## Try the governed workflow

1. Open **Warnings** (click the "Drug late" capsule): three synthetic disruptions are `in review`.
2. Introduce a new disruption (it calculates proposals but does not change the current plan):
   ```bash
   curl -X POST localhost:3000/api/change-events -H 'Content-Type: application/json' -d '{
     "id":"jp-port-closure","title":"Japan · Narita cargo terminal closure","event_type":"logistics",
     "jurisdiction":"JP","synthetic":true,"description":"Simulated NRT closure adds 6 business days.",
     "transit_delay_days":6,"repair_options":[{"id":"jp-express","action":"alternative_route",
     "route_id":"demo-JP-express","title":"Use the priority direct lane","description":"Express lane.",
     "tradeoffs":"Higher transport cost."}]}'
   ```
3. Open **Max** (bottom-right) → **Kenji** (Japan affiliate): reply `1` to preview, then `APPROVE` —
   refused, because Kenji cannot approve.
4. Open **Maya** (supply lead): reply `1`, then `APPROVE`. The planner moves the current plan to
   version 2; Kenji receives a plan-update message; the warning shows `resolved` with the decision
   in its audit history.

## Configuration (optional, server-side only)

Copy `planner/.env.example` to `.env` at the repository root (gitignored) to enable:

| Variable | Effect |
|---|---|
| `CHALK_CLIENT_ID`, `CHALK_CLIENT_SECRET`, `CHALK_ENVIRONMENT`, `CHALK_QUERY_SERVER` | Chalk online feature queries (parity-checked; local fallback otherwise) |
| `PHOTON_ENABLED=true` + `PHOTON_API_KEY`, `PHOTON_PROJECT_ID`, `PHOTON_AGENT_USER_ID`, `PHOTON_RECIPIENT` | outbound post-approval notifications via Photon |
| `PHOTON_BRIDGE_ENABLED=true` + `PHOTON_API_KEY`, `PHOTON_PROJECT_ID` | inbound iMessage replies routed to Max (needs `pip install -r messaging/requirements.txt`) |
| `ANTHROPIC_API_KEY` | Max answers free-text questions with Anna's cited regulation agent |
| `GOOGLE_MAPS_API_KEY` | route-hazard analysis (Google Routes + GDACS) on the monitor page |

Never commit `.env`, keys, Photon or Google credentials, local state files or databases
(all are in `.gitignore`).

## Tests

```bash
python run_tests.py              # everything below
```

| Suite | Command | What it covers |
|---|---|---|
| Planner + integration | `cd planner && python -m unittest discover -s tests` | planner unit/integration/e2e, Chalk outlook, API contracts, adapters, schemas, governance, authorization, idempotency, stale/conflicting approvals, evidence, messaging integration, provenance, provider failure, planner regression and Chalk parity |
| Messaging | `cd messaging && pip install -r requirements.txt && python -m pytest` | Anna's suite + planner-backed conversation unit tests |
| Browser end-to-end | `python -m unittest tests.e2e.test_browser_workflow` | the full workflow in Chromium via `start.py`; API-down error state; `?mock=1` |
| Fresh clone | `python -m unittest tests.e2e.test_fresh_clone` | clone the committed tree and start it |

Browser tests need `pip install playwright && python -m playwright install chromium`.

## Mock mode

For isolated frontend development without the backend, open the website with `?mock=1`
(uses `src/mock/*.json`; scripted Max replies exist only in this mode).
