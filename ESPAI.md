# ESPAI

**Local-first platform for replacing cloud apps with custom LAN-hosted applications.**

ESPAI runs entirely on your LAN. A Python FastAPI hub manages a fleet of ESP32
nodes, integrates with any WiFi device through its local API, runs Python workers
as background jobs, hosts per-project web dashboards, and delivers OTA firmware.
No cloud required — no subscription, no vendor lock-in, no data leaving your network.

Build custom apps that talk directly to your devices the way a cloud app would,
except everything runs on hardware you control: a router, a Raspberry Pi, a mini
PC, or a Docker container on any always-on machine.

---

## Quick Start

```bash
python espai.py install-deps   # create .venv, install dependencies (explicit — never silent)
python espai.py doctor         # verify Git, Python, PlatformIO, Docker, FFmpeg
python espai.py serve          # start hub at http://localhost:7888
```

Open the dashboard: **http://localhost:7888/**

---

## Four Execution Zones

| Zone | What runs there | Responsibility |
|---|---|---|
| **Hub** | FastAPI + SQLite + Vanilla JS | Storage, scheduling, dashboards, workers, OTA |
| **Workers** | Python subprocesses | Integration polling, image/video processing, event generation |
| **Nodes** | ESP32 Arduino firmware | Custom sensors, actuators, real-time control, offline fallback |
| **LAN Devices** | Third-party WiFi hardware | Any device with a local API — smart plugs, cameras, thermostats, media servers, NAS, etc. |

---

## Repository Layout

```
hub/              FastAPI backend + Vanilla JS dashboard
firmware/seed/    Reference ESP32 firmware (READ-ONLY — copy for projects)
firmware/provision/  Provisioning firmware (READ-ONLY)
projects/         Per-project workspaces (firmware/, web/, files/)
recipes/          YAML recipes for device configurations and pipelines
workers/          Python workers with YAML manifests
cards/            YAML card definitions for dashboard widgets
design/           Themes, skins, nav YAML files
agents/           AI adapter configs and policy files
agent-bench/      Task templates and review checklists
simulators/       Fake nodes for local development (no hardware required)
docs/             Architecture, task list, design specification
espai.py          CLI entry point
```

---

## Hub Architecture

- **Backend**: FastAPI + SQLite (WAL mode). All DB access via `get_conn()` in `hub/backend/db.py`.
- **Frontend**: Plain HTML/CSS/ES2022 JS. No build step.
- **Default port**: `7888`. Override with `ESPAI_PORT` env var.
- **API docs**: http://localhost:7888/docs

Key API prefixes: `/api/devices`, `/api/projects`, `/api/recipes`, `/api/workers`,
`/api/cards`, `/api/ota`, `/api/jobs`, `/api/events`, `/api/rules`, `/api/design`,
`/api/agent-bench`, `/api/terminal`, `/api/meta`

---

## ESP32 Nodes

Every ESPAI node exposes a REST API on port 80:

| Endpoint | Purpose |
|---|---|
| `GET /api/manifest` | Identity: node_id, name, board, fw_version |
| `GET /api/status` | Runtime: uptime, heap, wifi_rssi |
| `POST /api/checkin` | Hub-initiated ping |
| `POST /api/reboot` | Reboot (paired hub only) |
| `POST /ota/update` | OTA binary upload |

Node ID is SHA-256 of the MAC — raw MAC is never stored or transmitted.

Nodes must:
1. Run their own web server (port 80) — works without the hub.
2. Fall back to AP mode (`ESPAI-xxxxxx`) if WiFi fails.
3. Never block on hub — checkins are fire-and-forget.
4. Reconnect to WiFi every 30 s if STA drops.

---

## Project Data Store

ESP32 devices push readings to the hub; dashboards read them back — even when
the device is asleep.

**Push from firmware:**
```cpp
// POST /api/projects/{HUB_PROJECT_ID}/data
// Headers: X-Device-ID: <node-id>
// Body:    {"temperature": 23.5, "humidity": 65, "battery_pct": 87}
```

**Pull from web app:**
```javascript
// Always loads from hub cache — no need to reach the device
const { devices } = await fetch(`/api/projects/${PROJECT_ID}/data/latest`).then(r=>r.json());
```

---

## Docker / Router Deployment

When ESPAI runs in the `:latest` (dev) Docker image on an OpenWrt router:

**Persistent paths** (bind-mounted to NVMe — survive restarts):
```
/app/data/              → hub database, logs
/app/projects/          → all project workspaces (firmware, web, files)
/app/firmware-catalog/  → uploaded firmware binaries
/root/.platformio/      → PIO toolchain cache (if mounted — see compose file)
```

**Ephemeral paths** (container layer — lost on restart):
```
/app/workers/           → unless explicitly bind-mounted in compose
/app/recipes/           → unless explicitly bind-mounted in compose
/app/cards/             → unless explicitly bind-mounted in compose
/usr/local/lib/python*/ → pip installs done at runtime
```

**Firmware deployment — OTA only.** USB is not available in this environment.
Workflow for firmware changes:
1. Edit `projects/{id}/firmware/` source files
2. Run `pio run` in the project firmware directory (PIO is installed in `:latest`)
3. The compiled `.bin` is in `.pio/build/{env}/firmware.bin`
4. Import via hub UI: OTA → Upload Firmware, or use the project "⬆ Import to OTA" button
5. Flash to device: Fleet → device → "⬆ Flash", or OTA catalog → push

**Do not** `pip install` packages directly — they are lost on restart.
Use `ESPAI_PREINSTALL` env var or mount a `worker-requirements.txt` instead.

---

## Security Constraints

- **No secrets in Git.** Credentials via build flags or NVS only.
- **OTA**: pairing + board compat + SHA-256 checksum + audit log required.
- **Workers**: quarantined by default; policy-capped; no silent trust elevation.
- **Agents**: dev lane only; no access to `secrets/`, `data/`, `backups/`,
  `firmware/seed/`, `firmware/provision/`; no release promotion.

---

## Development Paths

- **Add a hub feature**: new router in `hub/backend/routers/`, register in `main.py`.
- **Add a worker**: `workers/{name}/manifest.yaml` + `{name}/entrypoint.py`.
- **Add a recipe**: `recipes/{name}/recipe.yaml` following the recipe schema.
- **Add an ESP32 project**: hub UI → New Project (type: ESP32 Node); edit `projects/{id}/firmware/`.
- **Add an integration project**: hub UI → New Project (type: API Integration); edit `projects/{id}/integration/poller.py`.
- **Add a hybrid project**: hub UI → New Project (type: Hybrid Bridge); get both firmware and integration scaffolds.
- **Simulate without hardware**: `python simulators/fake-node/fake_node.py`.

See `docs/DESIGN_SPEC.md` for the complete design specification.
