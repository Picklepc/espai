# ESPAI — Detailed Design Specification

> **Living document.** Update this file whenever a milestone ships, a major pattern
> changes, or a new subsystem is added. Agents load this at task start to orient
> themselves; keep it accurate and precise rather than aspirational.

---

## 1. What ESPAI Is

ESPAI is a **local-first platform for replacing cloud apps with custom LAN-hosted
applications**. It runs entirely on your LAN — no cloud dependency, no subscription,
no data leaving your network. A Python FastAPI hub is the always-on control plane:
it manages custom ESP32 firmware nodes, integrates with any WiFi device through its
local API, runs Python workers as background jobs, and hosts per-project web apps
that replace the vendor cloud dashboard.

**Three project types** determine the scaffold and agent behavior:

| Type | What it does |
|---|---|
| `esp32` | Custom firmware on an ESP32 node (PlatformIO, C++). Hub stores readings, delivers OTA. |
| `integration` | Hub worker that polls or subscribes to an existing WiFi device or service via its local API. No custom firmware. |
| `hybrid` | ESP32 acting as a BLE/serial bridge, plus a hub integration worker that consumes the bridge. |

The guiding philosophy: **the hub is a resource platform, not just a dashboard.**
Whether the data source is custom ESP32 firmware or a Shelly plug's HTTP API, the
hub stores, aggregates, schedules, and serves. Keep firmware lean; push complexity
to the hub. For integration projects, keep workers stateless and credential-free.

---

## 2. Execution Zones

```
┌──────────────────────────────────────────────────────────────────────────┐
│  HUB  (this machine — always on)                                         │
│  FastAPI  · SQLite  · Worker runner  · mDNS  · WebSocket broker          │
│  Vanilla JS dashboard · Static project web apps · LAN service registry   │
└──────┬──────────────────────────┬────────────────────────────────────────┘
       │  subprocess              │  HTTP / WebSocket / MQTT / BLE (LAN)
┌──────┴──────────┐    ┌──────────┴───────┐    ┌──────────────────────────┐
│   WORKERS       │    │  NODES (ESP32)   │    │  LAN DEVICES             │
│  Python subproc │    │  Arduino/PIO     │    │  Any WiFi device with    │
│  quarantined    │    │  mDNS · OTA      │    │  a local API — Shelly,   │
│  by default     │    │  WebServer :80   │    │  Tasmota, cameras, NAS,  │
│  polls/bridges  │    │  offline fallback│    │  thermostats, media      │
│  LAN devices    │    │                  │    │  servers, routers, etc.  │
└─────────────────┘    └──────────────────┘    └──────────────────────────┘
```

**Hub** — everything in `hub/`. FastAPI + SQLite + vanilla JS. Always on, always
reachable at `http://espai.local:7888/` (or the machine IP).

**Workers** — Python scripts in `workers/`. Executed as subprocesses by the hub's
job runner. Quarantined by default; policy-gated; optionally Docker-isolated (TODO).
For integration projects, workers are the primary logic layer — they poll or
subscribe to LAN devices and push readings to the hub data store.

**Nodes** — ESP32-class devices flashed with PlatformIO firmware. Expose a REST
API on port 80. Communicate with the hub over the local network. Must function
independently when the hub is unreachable.

**LAN Devices** — any third-party WiFi hardware with a local HTTP, MQTT, WebSocket,
Modbus, or proprietary API. ESPAI treats these as data sources and control targets
without requiring any firmware changes to the device. Integration project workers
bridge them into the hub data store.

---

## 3. Repository Layout

```
ESPAI/
├── hub/
│   ├── backend/              # FastAPI application
│   │   ├── main.py           # App factory, lifespan, proxy, /app/* route
│   │   ├── db.py             # SQLite helpers, schema init, migrations
│   │   ├── config.py         # Env vars, path constants
│   │   ├── routers/          # One file per API prefix
│   │   ├── registry/         # YAML folder scanner (recipes/workers/cards/design)
│   │   ├── workers/          # Job runner (subprocess executor)
│   │   ├── discovery/        # mDNS browse + subnet scanner
│   │   ├── rules/            # Event rules engine
│   │   ├── theme_scheduler.py
│   │   ├── mqtt_publisher.py
│   │   └── ws_broker.py
│   ├── frontend/
│   │   ├── index.html        # Single-page dashboard
│   │   └── static/
│   │       ├── js/app.js     # All UI logic, views, tooltip system
│   │       ├── js/api.js     # Thin fetch wrapper
│   │       └── css/app.css
│   └── tray/tray.py          # Windows system-tray launcher
│
├── firmware/
│   ├── seed/                 # Reference firmware — READ-ONLY to agents
│   │   └── src/main.cpp      # Minimal ESPAI node: manifest, status, OTA, AP mode
│   └── provision/            # Provisioning firmware — READ-ONLY to agents
│
├── projects/{project_id}/    # Per-project workspace (auto-created)
│   ├── firmware/             # Copied from seed; agent-editable
│   │   ├── platformio.ini
│   │   └── src/main.cpp
│   ├── web/                  # Hub-hosted web app (optional)
│   │   └── index.html        # Served at /app/{slug}/
│   ├── files/                # General project files
│   └── .ESPAI-project.json   # Project metadata + theme overrides
│
├── firmware-catalog/         # Uploaded firmware binaries + metadata
├── workers/                  # Python worker scripts + YAML manifests
├── recipes/                  # Recipe YAML files + private/ overlays
├── cards/                    # Card YAML files
├── design/
│   ├── themes/               # Theme YAML files (default-dark, retro, …)
│   ├── skins/                # Skin overlays
│   ├── nav/                  # Nav YAML files
│   └── theme_rules.yaml      # Time/event-based theme switching rules
├── agents/
│   ├── adapters/             # claude-code/, codex/ — system prompts + adapter.yaml
│   └── policies/             # default-agent-policy.yaml
├── agent-bench/
│   ├── task-templates/       # YAML task templates (hub-feature, firmware-feature, …)
│   └── review-checklists/    # YAML review checklists per domain
├── simulators/               # fake-node, fake-bms, fake-gpio, fake-camera
├── tests/                    # pytest suite (recipe decoder, …)
├── docs/                     # Architecture, task list, this file
├── .agent/                   # Agent rule files (AGENT_RULES.md, etc.)
├── espai.py                  # CLI entry point: init / doctor / serve / tray
└── CLAUDE.md                 # Mandatory coding conventions (tooltip rule, security)
```

---

## 4. Hub Backend

### 4.1 Entry Point

`hub/backend/main.py` — FastAPI app created with `lifespan`:

| Startup action | What it does |
|---|---|
| `init_db()` | Creates all tables; runs additive column migrations |
| Reset stale tasks | Sets `running` → `draft`/`failed` after unclean shutdown |
| `start_runner()` | Launches background job queue (subprocess executor) |
| `mdns_manager.start()` | Browse for `_ESPAI-node._tcp.local`, upsert found nodes |
| `mqtt_publisher.init()` | Optional MQTT output (requires `ESPAI_MQTT_HOST` env var) |
| `theme_scheduler.start()` | Evaluates time-based theme rules every 60 s |
| `ws_broker.set_loop()` | Wires the async loop into the sync-to-async WebSocket bridge |

### 4.2 API Routers

| Prefix | Router file | Domain |
|---|---|---|
| `/api/devices` | `routers/devices.py` | Fleet registry, pairing tokens, scan trigger |
| `/api/projects` | `routers/projects.py` | Project CRUD, file API, theme overrides, node management, topology |
| `/api/projects/{id}/nodes` | `routers/projects.py` | Node role management (GET list, PUT upsert, DELETE remove) |
| `/api/projects/{id}/topology` | `routers/projects.py` | Topology (standalone/star/mesh/hub-spoke/pipeline) + app_type (firmware/hub/hybrid) |
| `/api/projects/{id}/data` | `routers/data.py` | Time-series data push/pull (see §7) |
| `/api/recipes` | `routers/recipes.py` | Recipe registry, validation, export, compat |
| `/api/workers` | `routers/workers.py` | Worker registry, job dispatch, test harness |
| `/api/cards` | `routers/cards.py` | Card registry |
| `/api/design` | `routers/design.py` | Design token loader (theme → CSS vars) |
| `/api/ota` | `routers/ota.py` | Firmware catalog, push, rollback, rollout |
| `/api/jobs` | `routers/jobs.py` | Job queue CRUD |
| `/api/events` | `routers/events.py` | Event bus (publish, SSE stream) |
| `/api/rules` | `routers/rules.py` | Automation rules CRUD + evaluate |
| `/api/admin` | `routers/admin.py` | Backup, restore, status |
| `/api/agent-bench` | `routers/agent_bench.py` | Agent task lifecycle, diff, approval |
| `/api/terminal` | `routers/terminal.py` | PTY WebSocket terminal |
| `/api/meta` | `main.py` | Capabilities + endpoint discovery |
| `/api/ws` | `main.py` | WebSocket real-time event fan-out |

### 4.3 Special Routes

**`/app/{identifier}/`** — Hub-hosted project web app. Serves `projects/{id}/web/`
by project ID or by slug (hostname-safe name). SPA fallback to `index.html`.

**`/proxy/{project_id}/{path}`** — Transparent HTTP proxy to the linked device's
IP. Web apps use this so they never need to know the device IP. Returns a
context-aware offline page (sleeping vs. unreachable) on failure.

### 4.4 Database Schema

File: `data/ESPAI.db` (SQLite, WAL mode). All access through `get_conn()` context
manager — always commits on clean exit, rolls back on exception.

**Core tables:**

| Table | Purpose |
|---|---|
| `devices` | id, ip, name, board, fw_version, paired, last_seen, capabilities, meta |
| `projects` | id, name, description, devices (JSON list — kept in sync with project_nodes), slug, created, meta |
| `project_nodes` | project_id, device_id, role, label, node_index — structured node membership with roles |
| `ota_log` | Audit trail: device_id, fw_version, action, result, checksum, operator, timestamp, git_sha |
| `jobs` | worker_name, status, inputs, outputs, error, created/started/finished |
| `events` | source, event_type, payload, timestamp |
| `pairing_tokens` | token, device_id, created, expires, used |
| `rules` | name, enabled, event_type, source_filter, action_type, action_config |
| `project_data` | project_id, device_id, payload (JSON), timestamp — rolling window, 10 000 rows max |
| `project_data_cache` | Latest reading per (project_id, device_id) — instant load |
| `hub_settings` | key, value — persistent hub config (active_theme, etc.) |

**Agent Bench tables:**

| Table | Purpose |
|---|---|
| `agent_tasks` | id, project_id, title, description, template, status, allowed_paths, acceptance_criteria, context_type, context_id, parent_task_id, lane, adapter_id |
| `agent_task_messages` | Conversation thread for a task |
| `agent_runs` | Adapter run record: started, finished, exit_code, log, snapshot_before/after |
| `agent_artifacts` | Files staged by an agent run |
| `agent_reviews` | Human decision on a run (approve/reject + notes) |
| `agent_permissions` | Permissions granted to a task |

**Migrations:** `db.py::_migrate()` runs additive `ALTER TABLE` statements on
every startup. Always add columns as nullable or with defaults — never drop or
rename in a migration.

### 4.5 Key Patterns

**Registry loader** (`registry/loader.py`): Scans a folder for `*.yaml` files,
returns a list of dicts. Used by recipes, workers, cards, design. Call
`scan_folder(path)`.

**Event bus**: `events.py::publish_event(source, event_type, payload)` — inserts
into `events` table, broadcasts over WebSocket via `ws_broker`, evaluates rules
engine, publishes to MQTT if configured.

**Job runner** (`workers/runner.py`): Single background thread pulls `queued` jobs
from the DB, spawns a subprocess per worker, captures stdout/stderr, updates job
status. Workers emit events as JSON lines on stdout.

**Theme scheduler** (`theme_scheduler.py`): Evaluates `design/theme_rules.yaml`
every 60 s for time-based rules (`hour_start`/`hour_end`). Also callable via
`trigger_event_rule(event_type, tokens, duration_minutes)` from the rules engine.

---

## 5. Hub Frontend

### 5.1 Architecture

Single-page app: `hub/frontend/index.html` + `static/js/app.js` +
`static/css/app.css`. No build step, no bundler, no framework — plain ES2022
with `fetch` + DOM APIs.

`api.js` — Thin wrapper around `fetch`. All API calls go through `API.*` methods.
`app.js` — Everything else: view router, all UI logic, tooltip system, WebSocket
connection.

The sidebar nav links activate views (`data-view` attribute). Views are
`<section id="view-*">` elements toggled by CSS class `.active`.

### 5.2 Tooltip System (mandatory)

Every interactive or informational element must carry `data-tip="…"`.

- **Static HTML**: `<button data-tip="…">…</button>`
- **Template literals**: `\`<span data-tip="…">\``
- **`el()` helper**: `btn.dataset.tip = "…"`
- **Never use** `title=""` — inconsistent style, doesn't work on mobile.

The `#appTip` div is a single floating tooltip: 400 ms delay, hides on mouseout/
scroll/click, positioned below the element, flips up near viewport bottom.
Implemented in `app.js` (search `_appTip`). Styled as `.app-tip` in `app.css`.

### 5.3 WebSocket

`app.js` opens `ws://…/api/ws` on load, auto-reconnects. Incoming events trigger
view refreshes and browser Notifications (if permission granted).

---

## 6. Firmware

### 6.1 Seed Firmware (Reference — `firmware/seed/`)

**Protected — agents must not modify this directory.** It is the canonical
template that all project firmware is copied from.

Language: C++ / Arduino framework. Build system: PlatformIO.

Minimal node API (all on port 80):

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/manifest` | GET | Identity: node_id, name, board, fw_version, capabilities |
| `/api/status` | GET | Runtime: uptime_ms, heap_free, wifi_rssi, ap_mode |
| `/api/checkin` | POST | Hub-initiated ping acknowledgement |
| `/api/reboot` | POST | Controlled reboot (paired hub only) |
| `/ota/update` | POST | OTA binary upload (multipart/form-data + X-SHA256 header) |

**Node ID**: SHA-256 of the MAC address — never stores or exposes raw MAC.

**WiFi pattern** (mandatory in all project firmware):
```cpp
if (strlen(WIFI_SSID) > 0)
    WiFi.begin(WIFI_SSID, WIFI_PASS);
else
    WiFi.begin();   // uses NVS-stored credentials from previous flash
```

**AP fallback**: If STA fails after `WIFI_TIMEOUT_MS` (15 s), starts
`ESPAI-{6-char-id}` access point. Always reachable.

**Check-in loop**: Every 60 s, POSTs to `http://espai.local:7888/api/devices/{id}/checkin`.
Fire-and-forget — never blocks on hub.

**mDNS**: Advertises `_ESPAI-node._tcp.local` with properties `id`, `name`,
`board`, `version`.

### 6.2 Build Flags

Always use `\"backslash-escaped\"` inner quotes in `platformio.ini` — PlatformIO
strips outer quotes before passing to GCC:

```ini
build_flags =
  -D NODE_NAME=\"my-device\"
  -D FW_VERSION=\"1.0.0\"
  -D HUB_PROJECT_ID=\"c9ac1baa9ba4\"
```

### 6.3 Project Firmware (`projects/{id}/firmware/`)

Copied from seed on project creation. Agent-editable. Build with `pio run` from
the project firmware directory. Agents must run `pio run` and fix all errors
before committing.

---

## 7. Project Data Store

The hub acts as a **persistent cache and time-series store** for device readings.
Dashboards load instantly from the hub even when the device is asleep.

**Push** (from ESP32, on every measurement):
```
POST /api/projects/{project_id}/data
Headers: X-Device-ID: <node-id>
Body:    {"temperature": 23.5, "humidity": 65, "battery_pct": 87}
```

**Pull latest** (from web app on page load):
```
GET /api/projects/{project_id}/data/latest
→ {"project_id": "…", "devices": [{"device_id": "…", "payload": {…}, "timestamp": "…"}]}
```

**Pull history**:
```
GET /api/projects/{project_id}/data?limit=200&key=temperature&device_id=…&since=ISO
```

Rolling window: 10 000 rows per project. Oldest pruned on each push.

**Web app pattern** (works from hub or device directly):
```javascript
const HUB = location.pathname.startsWith("/app/");
const slug = HUB ? location.pathname.split("/")[2] : null;
const API  = HUB ? `/proxy/${slug}/api` : "http://NODE_NAME.local/api";
const HUB_API = HUB ? `` : `http://espai.local:7888`;
// Load from hub data store (always works, even when device is asleep)
const { devices } = await fetch(`${HUB_API}/api/projects/${PROJECT_ID}/data/latest`).then(r=>r.json());
```

---

## 8. Device Discovery and Pairing

### Discovery
1. **mDNS browse** — on startup, `discovery/mdns.py` browses for
   `_ESPAI-node._tcp.local`. Found nodes are upserted into `devices` via
   `_on_mdns_node_found()` in `main.py`.
2. **Subnet scan** — `POST /api/devices/scan` triggers a 64-worker parallel
   probe of the local `/24` subnet. Any node responding to `/api/manifest` is
   auto-registered.
3. **Manual add** — `POST /api/devices/manual` with `{"ip": "…"}`.

### Pairing Token Flow
1. Hub generates a token: `POST /api/devices/pairing/initiate` → `{token}`.
2. User enters token in device's web portal or via the device's `/api/pair` endpoint.
3. Hub confirms: `POST /api/devices/pairing/confirm` → marks device `paired=1`.
4. Dashboard polls for confirmation every 2.5 s during the Pair modal.

Only paired devices accept reboot and OTA commands from the hub.

---

## 9. OTA System

**Catalog** — `firmware-catalog/` holds uploaded `.bin` files + metadata YAML:
```
firmware-catalog/{board}-{version}/
    firmware.bin
    metadata.yaml    # board, version, channel, sha256, known_good, rollback_target
```

**Push flow**:
1. Hub reads the binary from catalog.
2. Validates board compatibility with the device (409 on mismatch; `force` flag
   overrides).
3. POSTs binary to device's `/ota/update` with `X-SHA256` header.
4. Device verifies checksum, applies OTA, reboots.
5. Hub logs the action in `ota_log`.

**Staged rollout**: `POST /api/ota/rollout` — filter by board or device list,
apply to a percentage of the fleet.

**Rollback**: Mark a firmware `known_good`, set a `rollback_target` pointer.
`POST /api/ota/{device_id}/rollback` follows the pointer and pushes the prior version.

---

## 10. Recipes, Workers, and Cards

All three are YAML-based registries loaded by the same `registry/loader.py` scanner.

### Recipes (`recipes/`)
YAML files describing device configurations and data pipelines. Support:
- **Private overlays** — `recipes/{name}/private/*.yaml` merged on top of base via
  `_deep_merge`. Stripped on export. Private overlay flag set to `_private_overlay`.
- **Sanitization** — `GET /api/recipes/{name}/export?share_policy=public` strips
  private keys.
- **Validation** — JSON Schema validation via `jsonschema`.
- **Compat check** — `GET /api/recipes/{name}/compat` — reports which boards,
  workers, and tools are present on this hub.

### Workers (`workers/`)
Python scripts with a `manifest.yaml`. Executed by the job runner as subprocesses.
- **Quarantined by default** — policy blocks execution until a human approves.
- **Permission enforcement** — `permissions.py` caps worker permissions against the
  active policy, sanitizes environment, sets process priority.
- **Test harness** — `POST /api/workers/{name}/test` runs synchronously in a sandbox,
  returns stdout/stderr/outputs/duration.

### Cards (`cards/`)
YAML files describing embeddable UI widgets. No processing logic — used by the
dashboard to render device-specific cards.

---

## 11. Design System

### Themes (`design/themes/`)
YAML files defining CSS custom property values (tokens). Loaded by `design.py`
into the hub API as `/api/design/tokens`. Frontend applies tokens as `--token-name`
CSS variables.

### Skins (`design/skins/`)
Overlay YAML files. Applied on top of the active theme for seasonal/contextual
overrides.

### Nav (`design/nav/`)
YAML files defining the sidebar navigation structure.

### Theme Rules (`design/theme_rules.yaml`)
Time-based and event-based rules evaluated by `theme_scheduler.py`:
- `time_based`: `hour_start`/`hour_end` → apply a theme during those hours.
- `event_based`: `event_type` → apply a theme with optional `duration_minutes`.

### Project-level overrides
Each project can override CSS tokens via `PUT /api/projects/{id}/theme`. Stored in
`.ESPAI-project.json`. Applied as inline CSS vars when the project is opened.

---

## 12. Event Bus and Rules Engine

**Publish** (internal): `events.py::publish_event(source, event_type, payload)`.
Called by workers (from stdout JSON lines), by device check-ins, by OTA, etc.

**Consume**:
- **SSE stream** — `GET /api/events/stream` (EventSource in browser)
- **WebSocket** — `/api/ws` (preferred; auto-reconnects)
- **MQTT** — optional output if `ESPAI_MQTT_HOST` env var is set

**Rules engine** (`rules/engine.py`): On every event publish, evaluates all
enabled rules where `event_type` matches. Action types:
- `log_event` — write to events table
- `run_worker` — enqueue a worker job
- `webhook` — HTTP POST to a URL
- `theme_change` — trigger theme scheduler

---

## 13. Agent Bench

The Agent Bench is the hub's built-in AI-assisted development system.
**Enabled only when `ESPAI_AGENT_BENCH=true`.**

### Concepts

| Concept | Description |
|---|---|
| **Task** | A unit of work with a title, description, template, allowed paths, and acceptance criteria |
| **Run** | One adapter's attempt to complete a task (snapshot before/after, log, exit_code) |
| **Artifact** | A file staged by a run, pending review |
| **Review** | Human decision: approve/reject a run |
| **Thread** | Chain of tasks linked by `parent_task_id` |

### Task Templates

Located in `agent-bench/task-templates/`. Each YAML defines:
- `allowed_paths` — default writable paths
- `acceptance_criteria` — default verification checklist
- `template_id` — used in task routing

Current templates: `hub-feature`, `firmware-feature`, `port-to-hub`,
`recipe-feature`, `bug-fix`.

### Protected Paths (always blocked regardless of task config)

```
.env  secrets/  *.private.yaml  *.private.json
data/  backups/  captures/private/
firmware/seed/      ← seed template — project firmware gets its own copy
firmware/provision/ ← provision firmware
```

### Adapters

| Adapter | Description |
|---|---|
| `manual` | Copy prompt, paste results — no CLI needed |
| `claude-code` | Launches `claude` CLI with generated system + task prompts |
| `codex` | Launches OpenAI Codex CLI |

Adapter prompts live in `agents/adapters/{name}/prompts/system.md` and `task.md`.

### Security Rules
- Agents work in `dev` lane only — may not push OTA to non-dev devices.
- Workers created by agents start quarantined.
- All runs logged in `agent_runs`.
- OTA targeting, pairing state, and release promotion are human-only actions.

### Context Scoping

Tasks can be scoped to a `context_type` + `context_id`:
- `project` — task appears in the project detail's "Agent Tasks" section
- `worker` — task appears on the worker card's "⚡ Agent Task" button

The scoped task modal hides the `allowed_paths` and `acceptance_criteria` fields;
the backend infers defaults from the context.

---

## 14. CLI (`espai.py`)

```bash
python espai.py init           # scaffold workspace folders
python espai.py doctor         # detect Git, Python, PIO, Docker, VSCode, FFmpeg
python espai.py serve          # start uvicorn (uses .venv if present)
python espai.py tray           # Windows system-tray launcher
python espai.py install-deps   # explicit dependency install (never silent)
```

Hub runs on port `7888` by default. Set `ESPAI_PORT` env var to override.
Set `ESPAI_AGENT_BENCH=true` to enable the Agent Bench.
Set `ESPAI_MQTT_HOST` + `ESPAI_MQTT_PORT` + `ESPAI_MQTT_TOPIC_PREFIX` for MQTT.

---

## 15. Simulators

For development without physical hardware:

| Simulator | Description |
|---|---|
| `simulators/fake-node/fake_node.py` | Generic ESP32 node: manifest, status, checkin, reboot, OTA |
| `simulators/fake-bms/fake_bms.py` | Battery management: voltage, temperature, cell data |
| `simulators/fake-gpio/fake_gpio.py` | 8-pin GPIO: set/get state, PWM |
| `simulators/fake-camera/fake_camera.py` | MJPEG stream, snapshot, motion events (PIL) |

---

## 16. Security Constraints (Non-negotiable)

- No secrets in Git: no WiFi credentials, API keys, MAC addresses, GPS coords.
- Build-flag credential injection only — never hardcode in source or ini files.
- OTA: requires pairing + board compatibility + SHA-256 checksum validation + audit log.
- Workers: quarantined by default; policy-capped permissions; no silent trust elevation.
- Agent Bench: dev lane only; cannot touch `secrets/`, `data/`, `backups/`,
  `*.private.yaml`, `firmware/seed/`, `firmware/provision/`; cannot promote releases.
- CORS is wide open (`allow_origins=["*"]`) — intentional for LAN use. No auth cookies.

---

## 17. Development Workflows

### Adding a Hub Feature
1. Add/modify a router in `hub/backend/routers/`.
2. Register it in `hub/backend/main.py` with `app.include_router(…)`.
3. If it touches the DB, add the table in `db.py::init_db()` or a migration in `_migrate()`.
4. Wire any new buttons/elements in `hub/frontend/static/js/app.js`.
5. Every new UI element **must** have a `data-tip="…"` attribute.
6. Test: start the hub (`python espai.py serve`), verify in browser.

### Adding a Worker
1. Create `workers/{name}/manifest.yaml` — define `name`, `description`,
   `entrypoint`, `permissions`, `resource_cost`, `inputs`, `outputs`.
2. Create `workers/{name}/{entrypoint}.py` — reads JSON from stdin or argv,
   prints JSON events to stdout, exits 0 on success.
3. Test via `POST /api/workers/{name}/test` with sample input JSON.
4. Worker starts quarantined — a human must approve it before the job runner will
   execute it in production.

### Adding a Recipe
1. Create `recipes/{name}/recipe.yaml` following the recipe schema.
2. Add `recipes/{name}/private/*.yaml` for private overlays if needed.
3. Validate: `GET /api/recipes/{name}/validate`.
4. Test export: `GET /api/recipes/{name}/export?share_policy=public`.

### Adding a Project
1. Hub UI: `Projects → + New Project` — scaffolds `projects/{id}/firmware/` from seed.
2. Or via API: `POST /api/projects` with `{name, description}`.
3. Firmware is in `projects/{id}/firmware/` — build with `pio run`.
4. Push readings from firmware to `POST /api/projects/{id}/data`.
5. Add `projects/{id}/web/index.html` for a hub-hosted dashboard.

### Firmware Task Checklist
1. Never edit `firmware/seed/` — edit the project copy in `projects/{id}/firmware/`.
2. Never hardcode WiFi credentials — use the NVS pattern.
3. Use `\"backslash-escaped\"` quotes in `build_flags`.
4. Run `pio run` and fix all errors before committing.
5. Ensure AP fallback is present.
6. Hub check-in must be fire-and-forget (no blocking wait).

---

## 18. Key Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `ESPAI_PORT` | `7888` | Hub listen port |
| `ESPAI_DEBUG` | `false` | Enable debug logging and `/docs` |
| `ESPAI_AGENT_BENCH` | `false` | Enable Agent Bench feature |
| `ESPAI_MQTT_HOST` | — | MQTT broker host (optional) |
| `ESPAI_MQTT_PORT` | `1883` | MQTT broker port |
| `ESPAI_MQTT_TOPIC_PREFIX` | `espai` | MQTT topic prefix |

---

## 19. OTA — Project-Centric Flash Flow

Firmware catalog entries now carry two extra fields stored in `firmware.json`:

| Field | Purpose |
|---|---|
| `label` | Human-readable display name — shown instead of `board-version` in catalog and project firmware list |
| `project_id` | Links the firmware to a project — enables the project-scoped firmware section |

**Upload from project detail**: "⬆ Upload Firmware" button in project detail header
pre-fills `boardHint` from the linked device and `projectName` as the label. On success,
refreshes the Firmware section rather than navigating to the OTA catalog.

**Project firmware section**: `GET /api/ota/catalog/project/{project_id}` returns
firmware tagged to that project. Rendered in project detail below "Linked Devices".
Each row has a "⬆ Flash" button that pre-filters `openPushModal` to this project's
linked device IDs.

**Fleet one-click flash**: Paired device cards have a "⬆ Flash" button.
`_openFlashDeviceModal(device)` fetches the full catalog, filters to board-compatible
entries, sorts newest first, and allows push in two clicks.

---

## 20. Agent Context Injection

Agent prompts are assembled in layers by `agent_bench.py::_build_prompt()`:

```
1. agents/adapters/claude-code/prompts/system.md   (platform system prompt)
2. agents/rules.md                                  (DO/DO NOT list — auto-injected)
3. projects/{id}/ESPAI.md                           (per-project context — auto-injected when present)
4. Task: title, template, scope, description, allowed paths, acceptance criteria
5. Protected paths
```

**Per-project `ESPAI.md`** is generated by `projects.py::_generate_espai_md()` when a
project is created. It contains the project ID, hub data push/pull code examples, firmware
quickstart, project directory structure, and key constraints. Agents receive it
automatically — no manual copy-paste needed.

Regenerate via `POST /api/projects/{id}/regenerate-context` or the "↺ Context" button
in project detail.

**`agents/rules.md`** contains explicit DO/DO NOT rules with embedded firmware code
snippets. It is injected into every agent prompt regardless of task type.

---

## 21. Agent Bench — Worker Quarantine Lift

After a human approves an agent task, the frontend checks whether any workers in the
task's `allowed_paths` are quarantined:

1. Parse `allowed_paths` for paths matching `workers/{name}/`.
2. Fetch worker list and filter to quarantined workers in those paths.
3. If any found, show "Quarantined Workers Detected" modal with one-click lift.
4. Lift calls `PATCH /api/workers/{name}/quarantine?quarantine=false` which writes
   `quarantine: false, trusted: true` into the worker's `worker.yaml`.

Workers remain quarantined until explicitly lifted — the auto-lift prompt is
advisory, not automatic.

---

## 22. Agent Bench — Context Filter

The Agent Bench task list has two filter rows:
- **Status filter** (existing): All / Draft / Running / Review / Approved / Rejected
- **Context filter** (new): All contexts / Project / Worker / Standalone

Context filtering is client-side — tasks are fetched with the status filter then
filtered in the browser by `context_type`. "Standalone" matches tasks with no `context_type`.

---

## 23. Multi-Node Project Model

Projects support any number of nodes (ESP32 devices) with explicit role assignments,
topology declarations, and app-type metadata. The hub does not implement mesh
protocols — it provides the data model and UI scaffolding so users can represent
arbitrary multi-node architectures.

### 23.1 Data Model

**`project_nodes` table** — one row per (project, device) membership:

| Column | Type | Description |
|---|---|---|
| project_id | TEXT | FK → projects.id |
| device_id  | TEXT | FK → devices.id |
| role       | TEXT | coordinator / sensor / actuator / gateway / observer / hub-agent / relay / node |
| label      | TEXT | Optional human-readable instance name ("North Gateway", "Bedroom Sensor") |
| node_index | INT  | Order within project (for mesh addressing, display order, etc.) |

`projects.devices` (JSON array) is kept in sync on all writes for backward compatibility.
On startup, `_migrate()` backfills `project_nodes` from any existing `projects.devices` data.

**Project metadata (in `.ESPAI-project.json`):**
- `topology`: `standalone` | `star` | `mesh` | `hub-spoke` | `pipeline` | `custom`
- `app_type`: `firmware` (primary logic on ESP32) | `hub` (primary logic in hub worker/web app) | `hybrid`

### 23.2 Node Roles

| Role | Color | Meaning |
|---|---|---|
| coordinator | teal/cyan | Mesh coordinator or gateway to the hub |
| sensor | green | Data collection only |
| actuator | amber | Output / control (LEDs, motors, relays) |
| gateway | blue | Bridges other networks (BLE, Zigbee, CAN bus) |
| observer | muted | Passive monitoring, no state mutation |
| hub-agent | purple | Hub-side logical node (worker or web app, not a physical device) |
| relay | yellow | Packet forwarding in a mesh |
| node | muted | Generic / unassigned |

### 23.3 API Endpoints

```
GET    /api/projects/{id}/nodes                  → list [{device_id, role, label, node_index}]
PUT    /api/projects/{id}/nodes/{device_id}      → upsert role/label/node_index
DELETE /api/projects/{id}/nodes/{device_id}      → remove node from project
GET    /api/projects/{id}/topology               → {topology, app_type}
PUT    /api/projects/{id}/topology               → set topology + app_type
GET    /api/devices/{id}/projects                → [{project_id, name, slug, role, label}]
```

All write endpoints sync `projects.devices` JSON for backward compat.

### 23.4 Use Cases

**Mesh sensor network (5 nodes):**
- topology: `mesh`
- app_type: `firmware` (all logic runs distributed on nodes)
- 1 × coordinator role, 4 × sensor role
- Hub aggregates data via project data store; workers run anomaly detection

**BLE presence detection (hub-side app + multiple static endpoints):**
- topology: `star`
- app_type: `hub` (hub app processes BLE scan data from multiple static nodes)
- Each ESP32 node at a static location has role `observer` or `gateway`
- Hub worker subscribes to BLE beacon events and calculates room presence

**Hybrid door + BLE tracker:**
- topology: `hub-spoke`
- app_type: `hybrid` (ESP32 does local sensing; hub app shows presence map)
- Primary door sensor node: role `sensor`
- Hub dashboard app: role `hub-agent`

---

## 24. Matter Bridge

ESPAI acts as a **Matter bridge (aggregator)** — a single commissioned device that exposes every opted-in project as a Matter endpoint to Google Home, HomeKit, or Alexa. No Matter stack runs on the ESP32 or other physical device. Projects of any type (ESP32, integration, hybrid) can be exposed through the bridge.

### Why hub-hosted instead of device-hosted

Running Matter on an ESP32 (Tasmota-style) consumes ~2 MB flash and significant heap, limits the number of bridged endpoints, and restricts bridge coverage to devices that speak that firmware's sync protocol. The hub-hosted approach:

- **ESP32 runs zero Matter code** — full flash/RAM available for project logic
- **Any ESPai device is bridgeable** — ESP32 nodes, Shelly, WLED, Tasmota, Zigbee, custom HTTP devices
- **No endpoint count limit** — hub hardware imposes no practical cap
- **One commissioning** — add the hub bridge to Google Home once; all opted-in projects appear and update automatically as you add more

### Commissioning model

The bridge is commissioned using a QR code shown in the ESPai dashboard. After that single pairing event:
- Each project with `matter_enabled: true` appears as a named endpoint in Google Home/HomeKit
- New projects that enable Matter are registered dynamically (no re-commissioning)
- Fabric state (cryptographic keys, peer IDs) is persisted to `data/matter-storage/`

### Process architecture

```
hub/matter/bridge.mjs    (Node.js — matter.js SDK)
    ↕  stdout/stderr      process lifecycle
hub/backend/matter_bridge.py   (Python — process manager + HTTP client)
    ↕  HTTP localhost:5580
hub/backend/routers/matter.py  (FastAPI — REST API for UI + internal use)
    ↕  called on every POST /api/projects/{id}/data push
    ↕  called when project matter config changes
hub/backend/routers/data.py    (background thread — non-blocking state sync)
```

The bridge exposes a local HTTP API (port `ESPAI_MATTER_PORT`, default 5580). Python calls it to register/remove devices and push state updates. The bridge calls back to `POST /api/matter/command` when Matter sends a command (on/off, brightness, etc.).

### Project-level Matter config

Stored in `.ESPAI-project.json`:

```json
{
  "matter_enabled": false,
  "matter_device_type": "on_off_plug",
  "matter_label": "",
  "matter_state_map": { "power_on": "on_off" },
  "matter_command_actions": { "on": { "type": "event", "event_type": "relay.on" } },
  "matter_endpoint_id": null
}
```

`matter_device_type` options: `on_off_plug`, `dimmable_light`, `color_light`, `temperature_sensor`, `humidity_sensor`, `occupancy_sensor`, `contact_sensor`.

`matter_state_map` maps hub data keys to Matter attribute names. Default maps are applied per device type if the field is empty (e.g. `temperature → temperature` for `temperature_sensor`).

`matter_command_actions` maps Matter commands to ESPai actions: `type` can be `event` (publish to event bus), `device_api` (call device REST endpoint), `worker` (enqueue job), or `hub_data` (set hub data key).

### Data push → bridge state sync

In `POST /api/projects/{id}/data`, after storing the payload: if the project has `matter_enabled: true` and the bridge is running, apply the `matter_state_map` to the payload and call `matter_bridge.update_state()` in a background thread (fire-and-forget, never blocks the response).

### Node.js dependency

`hub/matter/package.json` specifies `@project-chip/matter-node.js@^0.10`. The Python layer checks for `node` on PATH before starting the bridge — if Node.js is absent, Matter silently stays disabled and the dashboard shows a "Node.js required" message. Docker `:latest` and `:workers` images already have Node.js; Windows users need Node.js 18+ installed separately.

---

## 25. Current Build State (as of 2026-06-04)

Milestones 0–19 (partial) complete. Key shipped capabilities:

- Full fleet registry with mDNS auto-discovery, subnet scan, pairing token flow
- **Multi-node project model** — `project_nodes` table, per-node roles, topology, app_type, reverse device→projects lookup
- Project workspace: firmware, web app, files, hub data store, theme overrides, apply-hub-theme CSS generation
- **Per-project `ESPAI.md`** auto-generated on create; auto-injected into agent prompts
- **`agents/rules.md`** injected into every agent prompt
- OTA: catalog, push, staged rollout, known-good tracking, rollback, **git SHA recorded** at push time
- **Project-centric OTA UX**: project firmware section, one-click flash from project and fleet
- Worker pipeline: quarantine, permission enforcement, job queue, test harness
- **Registry management** — workers/cards/recipes: file browser (CodeMirror), + New scaffold, ✕ Delete
- **Worker quarantine auto-lift prompt** after agent task approval
- **Agent Bench context filter** — filter tasks by project/worker/standalone scope
- **Agent diff view with per-file Accept/Reject** — checkboxes per file, partial revert to snapshot_before
- Event bus: WebSocket, SSE, MQTT output, rules engine with theme/webhook/worker actions
- **Design system** — 6 themes (retro, default-dark, light, ocean, warm-amber + user custom); theme manager UI with color picker; official/custom pack distinction; project theme selector with palette preview
- Agent Bench v2: contextual tasks, thread follow-ups, diff review, claude-code + manual adapters
- PTY terminal (browser-based, WebSocket)
- Project data store: push/pull API for ESP32 sensor readings
- Simulators for all major node types
- **Registry content packs** — BLE recipe, temperature/battery/motion-alert starter recipes; opencv-motion-tagger + ffmpeg-compressor workers; 6 integration workers (tasmota, shelly, wled, zigbee2mqtt, jellyfin, http-poller); 7 cards; card preview system
- **In-hub code editor** (CodeMirror 5) — project files + registry items
- Per-project Git version control with auto-commit on save
- **Standalone packaging** — PyInstaller spec, frozen path detection, requirements-bundle.txt
- **Project types** — `esp32`, `integration`, `hybrid`; type-branched scaffold, ESPAI.md, and agent templates
- **Services view** — full LAN service registry; discover, pin, label, categorise; dedicated nav tab
- **Caddy integration** — auto-generated Caddyfile for `{slug}.local` routing; download button in Projects view
- **Web app scaffold** — type-specific `web/index.html` + `hub-api.js` + `app.json` on project create; live-reload via WebSocket
- **Sleep/wake checkin** — `SLEEP_INTERVAL_S` build flag; hub-override via checkin response; `esp_deep_sleep()` after 5 s serve window
- **Integration template workers** — tasmota-poller, shelly-poller, wled-controller, zigbee2mqtt-bridge, jellyfin-poller, http-poller
- **Worker sync on startup** — per-worker version-aware copy; new workers land on update without reinstall
- **Project-scoped workers** — `projects/{id}/workers/{name}/` takes precedence over global worker for job mode

**Open priorities (M23+):**
- **Matter bridge** (M23) — hub-hosted aggregator; one commissioning for all opted-in projects; see Section 24
- **Matter device type mapping** (M24) — state map editor, command routing editor, inferred device types
- Docker sidecar runner for workers
- Firmware CI builds in release pipeline
- Service health polling for Services view (M20 follow-on)
- Link service to project (M20 follow-on)
