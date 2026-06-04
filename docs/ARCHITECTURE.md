# ESPAI Architecture

> For full detail see `docs/DESIGN_SPEC.md`. This document is the high-level map;
> DESIGN_SPEC is the implementer's reference.

---

## Three Execution Zones

```
┌─────────────────────────────────────────────────────────────────────┐
│  HUB  (always-on LAN host)                                          │
│  FastAPI :7888 · SQLite WAL · WebSocket broker · mDNS browse        │
│  Vanilla JS SPA · Static project web apps at /app/{slug}/           │
│  Worker subprocess pool · Cron scheduler · MQTT optional output     │
│  Matter bridge (Node.js :5580) · Command channel · Media store      │
└──────────────────┬──────────────────────────────────────────────────┘
                   │  HTTP / WebSocket (LAN)
       ┌───────────┴──────────┐          ┌───────────────────────────┐
       │   WORKERS            │          │   NODES  (ESP32-class)    │
       │  Python subprocesses │          │  Arduino / PlatformIO     │
       │  policy-capped perms │          │  REST API on port 80      │
       │  git rollback        │          │  mDNS · OTA · AP fallback │
       └──────────────────────┘          └───────────────────────────┘
                                                    │  Matter (fabric)
                                         ┌──────────┴────────────────┐
                                         │  Google Home / HomeKit /  │
                                         │  Alexa  (Matter fabric)   │
                                         └───────────────────────────┘
```

---

## Hub Architecture

### Backend (`hub/backend/`)

| File / Package | Role |
|---|---|
| `main.py` | App factory; lifespan (DB init, mDNS, MQTT, scheduler, WebSocket broker); project proxy `/proxy/`; project web app `/app/`; offline page |
| `db.py` | `get_conn()` context manager (WAL, FK, 5 s busy timeout); `init_db()` schema; `_migrate()` for additive column additions |
| `config.py` | Path constants (`ROOT`, `PROJECTS_DIR`, …), env-var config (`PORT`, `ACTIVE_THEME`, `ESPAI_AGENT_BENCH`) |
| `routers/` | One file per API prefix — see table below |
| `registry/loader.py` | `scan_folder(path, kind)` — scans a directory for YAML manifests |
| `workers/runner.py` | Background thread; dequeues `queued` jobs; spawns subprocesses; parses stdout events |
| `workers/permissions.py` | Validates worker permissions against policy caps; sanitizes env; sets process priority |
| `discovery/mdns.py` | mDNS browse for `_ESPAI-node._tcp.local`; on-found callback upserts into DB |
| `discovery/scanner.py` | 64-worker ThreadPoolExecutor subnet probe; registers responding ESPAI nodes |
| `rules/engine.py` | Evaluates rules on every event publish; rate-limit check via `rule_fires` table; dispatches log/run_worker/webhook/theme_change/send_command |
| `rules/scheduler.py` | Cron scheduler — fires `system.clock` events; timezone-aware via `schedule_tz`; 5-field cron parser |
| `matter_bridge.py` | Matter bridge process manager; spawns `hub/matter/bridge.mjs`; thin HTTP client to bridge API on port 5580 |
| `theme_scheduler.py` | Time-based and event-based theme switching; evaluates every 60 s |
| `mqtt_publisher.py` | Optional paho-mqtt output; publishes all events to `{prefix}/events/{type}` |
| `ws_broker.py` | `ConnectionManager`; `broadcast_event_sync()` thread-safe bridge via captured asyncio loop |

### API Surface

| Prefix | Purpose |
|---|---|
| `/api/devices` | Fleet registry, mDNS/scan/manual discovery, pairing token flow |
| `/api/projects` | Project CRUD, file API, theme overrides, data store, context regeneration |
| `/api/projects/{id}/data` | Time-series push + bulk offline upload + latest/history pull + spatial query |
| `/api/projects/{id}/geofences` | Geofence polygon CRUD; push hook fires `geofence.enter` / `geofence.exit` |
| `/api/projects/{id}/matter` | Per-project Matter config (device type, state map, command actions, per-device mode) |
| `/api/projects/{id}/media` | Binary file upload/download (images, audio); quota-guarded; `espai_upload_jpeg()` compatible |
| `/api/matter` | Matter bridge control (start/stop/sync/status/qrcode) + command webhook |
| `/api/devices/{id}/commands` | Hub→device command channel: enqueue, poll, ack, TTL expiry |
| `/api/recipes` | Recipe YAML registry, validation, export (share_policy), compat check |
| `/api/workers` | Worker YAML registry, job dispatch, quarantine control, test harness, compat |
| `/api/cards` | Card YAML registry |
| `/api/design` | Theme token loader (YAML → CSS custom properties) |
| `/api/ota` | Firmware catalog (label + project_id tagging), push, rollback, staged rollout |
| `/api/ota/catalog/project/{id}` | Project-scoped firmware filter |
| `/api/jobs` | Job queue CRUD |
| `/api/events` | Event bus publish, SSE stream |
| `/api/rules` | Automation rules CRUD + evaluation |
| `/api/admin` | DB backup/restore, hub status |
| `/api/agent-bench` | Agent task lifecycle, diff, approval, quarantine prompts |
| `/api/terminal` | PTY WebSocket sessions (pywinpty / ptyprocess) |
| `/api/meta` | Capabilities + endpoint discovery for IDE extensions / agents |
| `/api/ws` | WebSocket real-time event fan-out |
| `/app/{slug}/` | Hub-hosted project web app (SPA fallback to index.html) |
| `/proxy/{project_id}/` | Transparent HTTP proxy to linked device IP; offline page on failure |

### Database (`data/ESPAI.db`, SQLite WAL)

Key tables: `devices`, `projects`, `ota_log`, `jobs`, `events`, `pairing_tokens`, `rules`,
`rule_fires`, `project_data`, `project_data_cache`, `project_nodes`, `project_media`,
`geofences`, `device_commands`, `local_services`, `hub_settings`,
`agent_tasks`, `agent_runs`, `agent_artifacts`, `agent_reviews`, `agent_permissions`,
`agent_task_messages`.

`get_conn()` is a context manager — **always commits on clean exit, rolls back on exception.
Never call `conn.commit()` inside a `with get_conn()` block.**

Migrations are additive `ALTER TABLE` statements in `db.py::_migrate()` — run on every startup.
Never drop or rename columns in a migration.

---

## Frontend Architecture

Single-page app: `hub/frontend/index.html` + `static/js/app.js` + `static/css/app.css`.
No build step, no bundler, no framework — plain ES2022 + DOM APIs.

- `api.js` — Thin `fetch` wrapper. All API calls go through `api.*` methods.
- `app.js` — Everything else: view router, all UI logic, tooltip system, WebSocket connection,
  all modals, all view renderers.

**Tooltip rule (mandatory):** Every interactive/informational element must carry
`data-tip="…"`. Static HTML: attribute directly. Template literals: inline. `el()` helper:
`btn.dataset.tip = "…"`. Never use `title=""`.

**View routing:** Sidebar `data-view` links toggle `.active` on `<section id="view-*">` elements.

**WebSocket:** `app.js` opens `/api/ws` on load; auto-reconnects. Incoming events trigger
view refreshes and browser Notifications (if permitted).

---

## Firmware Architecture

### Seed (`firmware/seed/`) — READ-ONLY platform template

Reference node firmware. Agents must never modify this directory. Project firmware is
copied from seed on project creation.

Required node API (port 80):

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/manifest` | GET | Identity: node_id (SHA-256 of MAC), name, board, fw_version |
| `/api/status` | GET | Runtime: uptime, heap_free, wifi_rssi, ap_mode |
| `/api/checkin` | POST | Hub-initiated ping acknowledgement |
| `/api/reboot` | POST | Controlled reboot (paired hub only) |
| `/ota/update` | POST | OTA binary upload (multipart/form-data + X-Firmware-SHA256) |

### Required firmware patterns

```cpp
// WiFi — always support NVS-stored credentials
if (strlen(WIFI_SSID) > 0) WiFi.begin(WIFI_SSID, WIFI_PASS);
else                        WiFi.begin();   // uses NVS creds from last flash

// AP fallback — always implement
void startFallbackAP() {
  WiFi.mode(WIFI_AP);
  WiFi.softAP(("ESPAI-" + nodeId.substring(5,11)).c_str());
}

// Hub checkin — always fire-and-forget
void checkin() {
  if (WiFi.status() != WL_CONNECTED) return;
  HTTPClient h; h.begin("http://espai.local:7888/api/devices/" + nodeId + "/checkin");
  h.POST("{}"); h.end();
}
```

### Build flags (PlatformIO)

Always use `\"backslash-escaped\"` inner quotes — PlatformIO strips outer quotes before GCC:
```ini
build_flags =
  -D NODE_NAME=\"my-node\"
  -D HUB_PROJECT_ID=\"c9ac1baa9ba4\"
```

---

## Project Data Flow

```
ESP32 firmware
  └─ POST /api/projects/{id}/data {"temp":23.5}
       └─ project_data row (rolling 10k max)
       └─ project_data_cache upsert (latest per device)

Hub-hosted web app /app/{slug}/
  └─ GET /api/projects/{id}/data/latest   ← instant, always works (device can sleep)
  └─ GET /api/projects/{id}/data?limit=N  ← history, filtered by device/key/since
```

Web apps access device APIs through the hub proxy:
```
/proxy/{project_id}/api/sensor  →  http://{device_ip}/api/sensor
```

Offline page served automatically when device is unreachable (context-aware: sleeping vs. down).

---

## Agent Prompt Construction

`agent_bench.py::_build_prompt(task, project)` assembles the agent prompt in layers:

1. `agents/adapters/claude-code/prompts/system.md` — platform system prompt
2. `agents/rules.md` — explicit DO/DO NOT list (auto-injected)
3. `projects/{id}/ESPAI.md` — per-project context (auto-injected when present)
4. Task metadata: title, template, scope, description, allowed paths, acceptance criteria
5. Protected paths list

Per-project `ESPAI.md` is generated on project create and can be regenerated via
`POST /api/projects/{id}/regenerate-context` (or the "↺ Context" button in project detail).

---

## OTA System

**Catalog** — `firmware-catalog/{board}-{version}/firmware.json` + `firmware.bin`.
Each entry now carries `label` (display name) and `project_id` (project tag) fields.

**Push flow**: board compat check → read binary → multipart POST to `/ota/update` →
SHA-256 verify on device → reboot → hub polls `/api/manifest` to confirm.

**Project-scoped UX**: "⬆ Upload Firmware" in project detail pre-fills board from
linked device; "Firmware" section shows project-tagged entries with one-click "⬆ Flash".
Fleet device cards show "⬆ Flash" for paired devices.

---

## Agent Bench Security Model

- `ESPAI_AGENT_BENCH=true` required — disabled by default.
- **Dev lane only** — agents cannot push OTA to non-dev devices.
- **Blocked paths** (always, regardless of task config):
  `firmware/seed/`, `firmware/provision/`, `secrets/`, `data/`, `backups/`,
  `*.private.yaml`, `*.private.json`, `.env`, `captures/private/`
- All runs logged in `agent_runs` with snapshot before/after.
- Workers created by agents are subject to the same permission policy caps as all workers.
  Changes are tracked in git — rollback via `POST /api/workers/{name}/git/rollback`.
- Release promotion, pairing state, and OTA targeting are human-only actions.

---

## Design System

Themes: `design/themes/{name}/theme.yaml` → CSS custom properties via `/api/design/tokens`.
Skins: overlay YAML on top of active theme.
Nav: `design/nav/{name}/nav.yaml` defines sidebar structure.
Theme rules: `design/theme_rules.yaml` — time-based (`hour_start`/`hour_end`) and
event-based rules evaluated by `theme_scheduler.py` every 60 s.
Project overrides: stored in `.ESPAI-project.json`; applied as inline CSS vars when
project is opened; cleared on Back.

---

## Event Bus

`events.py::publish_event(source, event_type, payload)`:
1. Inserts into `events` table.
2. Broadcasts over WebSocket via `ws_broker`.
3. Evaluates rules engine → log / run_worker / webhook / theme_change actions.
4. Publishes to MQTT if `ESPAI_MQTT_HOST` is set.

Workers emit events as JSON lines on stdout; runner calls `publish_event` for each.

---

## Discovery and Pairing

**mDNS browse** — on startup, browses `_ESPAI-node._tcp.local`. Nodes found are
upserted into `devices` (paired state preserved).

**Subnet scan** — `POST /api/devices/scan`; 64-worker parallel probe; auto-registers
nodes responding to `/api/manifest`.

**Pairing token flow**:
1. Hub generates token → `POST /api/devices/pair/initiate/{device_id}`
2. Token shown in dashboard with copy button and device portal link
3. User enters token on device; hub confirms → `POST /api/devices/pair/confirm`
4. Device marked `paired=1`; dashboard polls every 2.5 s

Only paired devices accept reboot and OTA commands.
