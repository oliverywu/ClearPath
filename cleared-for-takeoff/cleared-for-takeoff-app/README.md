# Cleared for Takeoff — frontend (v5)

Plain HTML/CSS and ES modules. No build step and no dependencies. All data is **sample/mock** data.

## Run
ES modules and `fetch()` of the mock JSON don't work from `file://`, so serve the folder locally (works offline):
```bash
cd app && python3 -m http.server 8000   # open http://localhost:8000
```
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
