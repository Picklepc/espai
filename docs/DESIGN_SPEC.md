# ESPAI — Detailed Design Specification

> **Living document.** Update this file whenever a milestone ships, a major pattern
> changes, or a new subsystem is added. Agents load this at task start to orient
> themselves; keep it accurate and precise rather than aspirational.

---

## 1. What ESPAI Is

ESPAI is a **local-first ESP32 fleet management and edge-processing platform**.
It runs entirely on your LAN — no cloud dependency, no subscription. A Python
FastAPI hub provides fleet oversight, persistent storage, a worker pipeline, and
a vanilla JS dashboard. ESP32-class nodes run minimal firmware, report in via
HTTP, and receive OTA updates. Python workers process data (images, sensor
streams, etc.) as background jobs.

The guiding philosophy: **the hub is a resource platform, not just a dashboard.**
ESP32 hardware measures and actuates; the hub stores, aggregates, schedules, and
serves. Keep firmware lean; push complexity to the hub.

---

## 2. Execution Zones

```
┌──────────────────────────────────────────────────────────────────┐
│  HUB  (this machine — always on)                                 │
│  FastAPI  · SQLite  · Worker runner  · mDNS  · WebSocket broker  │
│  Vanilla JS dashboard · Static project web apps                  │
└──────────────┬───────────────────────────────────────────────────┘
               │  HTTP / WebSocket (LAN)
       ┌───────┴──────────┐           ┌──────────────────┐
       │   WORKERS        │           │   NODES (ESP32)  │
       │  Python subproc  │           │  Arduino/PIO     │
       │  quarantined     │           │  mDNS · OTA      │
       │  by default      │           │  WebServer :80   │
       └──────────────────┘           └──────────────────┘
```

**Hub** — everything in `hub/`. FastAPI + SQLite + vanilla JS. Always on, always
reachable at `http://espai.local:7888/` (or the machine IP).

**Workers** — Python scripts in `workers/`. Executed as subprocesses by the hub's
job runner. Quarantined by default; policy-gated; optionally Docker-isolated (TODO).

**Nodes** — ESP32-class devices flashed with PlatformIO firmware. Expose a REST
API on port 80. Communicate with the hub over the local network. Must function
independently when the hub is unreachable.

---

## 3. Repository Layout

```
ESPai/
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
| `/api/projects` | `routers/projects.py` | Project CRUD, file API, theme overrides |
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
| `projects` | id, name, description, devices (JSON list), slug, created, meta |
| `ota_log` | Audit trail: device_id, fw_version, action, result, checksum, operator, timestamp |
| `jobs` | worker_name, status, inputs, outputs, error, created/started/finished |
| `events` | source, event_type, payload, timestamp |
| `pairing_tokens` | token, device_id, created, expires, used |
| `rules` | name, enabled, event_type, source_filter, action_type, action_config |
| `project_data` | project_id, device_id, payload (JSON), timestamp — rolling window, 10 000 rows max |
| `project_data_cache` | Latest reading per (project_id, device_id) — instant load |

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

## 19. Current Build State (as of 2026-05-28)

Milestones 0–13 are substantially complete. Key shipped capabilities:

- Full fleet registry with mDNS auto-discovery, subnet scan, pairing token flow
- Project workspace: firmware, web app, files, hub data store, theme overrides
- OTA: catalog, push, staged rollout, known-good tracking, rollback
- Worker pipeline: quarantine, permission enforcement, job queue, test harness
- Event bus: WebSocket, SSE, MQTT output, rules engine with theme/webhook/worker actions
- Design system: themes, skins, nav, time/event-based theme scheduling
- Agent Bench v2: contextual tasks, thread follow-ups, diff review, claude-code + manual adapters
- PTY terminal (browser-based, WebSocket)
- Project data store: push/pull API for ESP32 sensor readings
- Simulators for all major node types

**Next priorities (Milestones 14–18):**
- Registry content packs (BMS/temp/motion recipes, hotdog worker, card suite)
- In-hub code editor (Monaco/CodeMirror)
- Auto-generated `ESPAI.md` per project (injected into agent prompts)
- Caddy integration for `{project}.local` routing
- Per-project Git version control
