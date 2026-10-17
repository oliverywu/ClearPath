# Cleared for Takeoff — frontend (v5)

Plain HTML/CSS and ES modules. No build step or npm dependencies. Most app content is sample data; the shipment calendar and day schedules now persist in local SQLite.

## Run
For live route analysis and the persistent schedule calendar, run the included Node backend (Node 22.13+):
```bash
cd cleared-for-takeoff/cleared-for-takeoff-app
cp .env.example .env.local
# Put the rotated key in .env.local, then run:
npm start
# open http://localhost:8000
```
The key is read only by the backend from `.env.local` or its environment; it is never sent to the browser. `.env.local` is git-ignored. Enable Google Routes API and restrict the key in Google Cloud. `GDACS_EVENTS_URL`, `DISASTER_MAX_AGE_DAYS`, and `PORT` can also be set as environment variables. The default GDACS source is its recent-events GeoJSON endpoint. The older static preview can still be served with `python3 -m http.server 8000`, but route analysis requires the Node server.
Debug flags: `?fail=1` makes every API call fail (error states), and `?empty=1` makes every list come back empty (empty states).

## Routes (hash router in `src/main.js`)
| Hash | View |
|---|---|
| `#/` | Landing: tilted pill image and the "Drug late" capsule. Scrolling down shows *Routes draw as kits move* and then the *Inventory* grid |
| `#/warnings` | All recent warnings: severity and status filters |
| `#/warnings/:id` | Same view with the detail panel open |
| `#/chats` | Photon chats: searchable conversation list and thread pane |
| `#/chats/:id` | Same view with that thread open |

Clicking the capsule plays the orange burst and goes to `#/warnings`. The floating **Photon chats** orb goes to `#/chats`. Esc goes back one level.

## Structure
```
app/
  index.html          shell: landing art, scroll sections, view containers, Photon orb
  styles.css          all styles
  pills.png
  src/
    config.js         USE_MOCK, API_BASE, MOCK_LATENCY_MS   ← switch to the real backend here
    api.js            the only module that touches data (mock JSON or REST)
    ui.js             helpers: load() with loading/empty/error states, burst, cursor, formatters
    main.js           router + boot
    views/landing.js  pill parallax, route drawing, inventory grid (filters, sort, FLIP, expand)
    views/warnings.js warnings list, filters, detail
    views/chats.js    chat list, search, unread, thread, send (optimistic, with failure state)
    mock/*.json       warnings, shipments, inventory, chats, messages
```

## Plugging in the backend
1. In `src/config.js` set `USE_MOCK = false` and set `API_BASE` (default `/api`).
2. Implement the endpoints below so they return the shapes shown. The views never call `fetch` themselves, so nothing else needs to change.
3. Auth: add headers such as `Authorization` inside `http()` in `src/api.js`.

| Function (`src/api.js`) | Endpoint | Returns |
|---|---|---|
| `getWarnings()` | `GET /api/warnings` | `Warning[]`, newest first |
| `getWarning(id)` | `GET /api/warnings/:id` | `Warning` |
| `getShipments()` | `GET /api/shipments` | `Shipment[]` |
| `getInventory()` | `GET /api/inventory` | `InventoryItem[]` |
| `getPhotonChats()` | `GET /api/photon/chats` | `Chat[]`, most recent first |
| `getChatMessages(chatId)` | `GET /api/photon/chats/:id/messages` | `Message[]`, oldest first |
| `sendChatMessage(chatId, text)` | `POST /api/photon/chats/:id/messages` body `{"text": "..."}` | the created `Message` |

A non-2xx response throws, and the view shows its error state with a Retry button.

## Disaster route monitor
Open **Analyze route hazards** in the shipment section (or navigate to `#/monitor`). Choose a current shipment to check recent GDACS events, or choose one of the sourced historical case studies to see a known past disaster along a Google Maps route. Historical examples are clearly labeled and are not presented as current alerts. The frontend posts the shipment endpoints or historical scenario ID and selected corridor radius to `POST /api/route-analysis`. The backend gets route geometry from Google Routes API, loads and caches recent GDACS GeoJSON events for ten minutes for live shipments, and returns only events within the selected corridor. It includes GDACS alert level (red/orange/green), event type, location, timestamp, affected area, and details when present. Live events older than `DISASTER_MAX_AGE_DAYS` (30 by default) are excluded. Historical examples include a direct GDACS source link. The API response includes route distance, duration, route point count, number of events checked, matched events, analysis mode, and analysis timestamp.

Available historical route examples are the 2023 Türkiye–Syria M7.8 earthquake, the 2021 western Germany floods, and Cyclone Idai's 2019 landfall near Beira, Mozambique. Their event records are in `src/mock/historical-route-examples.json`. The flood map point is an approximate point in the documented affected district, rather than an official event centroid.

The backend validates request fields and returns JSON errors with appropriate HTTP status codes. It does not return the full global GDACS feed to the client. The Google API key stays server side. Route computation uses Google Routes API's `DRIVE` mode, so origin/destination pairs without a drivable route (for example, across oceans) will return an error; air and sea routing need a transport-specific routing provider.

Example request:
```http
POST /api/route-analysis
Content-Type: application/json

{"origin":"Boston","destination":"New York","proximityKm":50}
```

## Persistent shipment schedule

The calendar and day drawer now read schedule milestones from a local SQLite database at `.data/schedule.sqlite`. On first start, the backend copies the existing sample milestones from `src/mock/day-schedules.json` into the database. New schedule records persist across restarts. The hidden database folder is git-ignored and blocked from static file access; back it up before deleting or replacing it. Node's built-in SQLite support is used, so there is no separate database service or npm dependency to install.

The backend exposes:

- `GET /api/calendar?month=YYYY-MM` — calendar markers for that month
- `GET /api/schedule/YYYY-MM-DD` — ordered milestones for that day
- `POST /api/schedule` — create a milestone
- `PATCH /api/schedule/:id` — update a milestone, including its date/time
- `DELETE /api/schedule/:id` — remove a milestone

Create request example:
```json
{
  "date": "2026-11-12",
  "time": "09:30",
  "type": "customs",
  "title": "Customs documents due",
  "shipmentId": "shp-002",
  "party": "Amara K. · customs broker",
  "dependencies": [],
  "status": "scheduled"
}
```

Use `dependencies` for prerequisite schedule item IDs. The backend rejects missing prerequisites and circular dependencies.

Send your actual milestones as a CSV or JSON file when ready. Useful columns are shipment ID, milestone title/type, date, time, owner, and status; I can map your existing format into this schema. For now the API is intended for the local prototype and has no user authentication or change history, so it should not be exposed publicly until those are added.

## Data schemas
Enums: `status` (shipments/inventory) = `on_track | at_risk | blocked | no_shipment`; warning `severity` = `critical | high | medium | low`; warning `status` = `open | in_review | resolved`; inventory `runs[]` = `on_time | late | missed`.

**Warning**
```json
{ "id":"wrn-001","country":"JP","countryName":"Japan","requirement":"Additional label field",
  "summary":"…","study":"NOVA-24","shipmentsAffected":23,"severity":"high",
  "createdAt":"2026-10-17T07:42:00-04:00","status":"open",
  "recommendedAction":"…","source":"Regulator notice (sample)","shipmentIds":["shp-001"] }
```
**Shipment**
```json
{ "id":"shp-001","country":"JP","countryName":"Japan","study":"NOVA-24","kit":"NV-118 / placebo kit",
  "origin":"Boston","destination":"Tokyo","status":"at_risk","slackDays":-9,
  "targetDelivery":"2026-11-28","projectedDelivery":"2026-12-07","labelGroup":"label-JP-v1" }
```
**InventoryItem** (a recurring shipment)
```json
{ "id":"inv-001","study":"HALO-3","kit":"HL-40 inhaler","storage":"15-30C","country":"US","countryName":"United States",
  "cadenceWeeks":4,"nextShipDate":"2026-10-14","onHand":120,"reorderLevel":70,"status":"on_track",
  "runs":["on_time","late","on_time","on_time","missed","on_time","on_time","on_time"] }
```
**Chat** (Photon conversation; `channel` is whatever Photon reports, e.g. `whatsapp|slack|email|teams|sms`)
```json
{ "id":"cht-001","name":"Yuki T.","role":"Tokyo depot","channel":"whatsapp",
  "lastMessage":"…","updatedAt":"2026-10-17T08:31:00-04:00","unread":2,"links":["wrn-001","shp-001"] }
```
`links` holds warning ids (`wrn-…`, which link to `#/warnings/:id`) and shipment ids (`shp-…`).

**Message**
```json
{ "id":"cht-001-m1","from":"them","text":"…","sentAt":"08:02" }
```
`from` is `me` or `them`. `sentAt` is a display string today; an ISO timestamp is fine if you format it in `views/chats.js`.
