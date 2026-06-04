# ESPAI Hub

Backend and frontend for the ESPAI local platform.

## Quick start

```bash
python ESPAI.py install-deps   # create .venv, install dependencies
python ESPAI.py doctor         # verify Git, Python, PlatformIO, Docker
python ESPAI.py serve          # start hub at http://localhost:7888
```

Dashboard: http://localhost:7888/
API docs:  http://localhost:7888/docs (debug mode only)

## Structure

```
hub/
  backend/
    main.py            FastAPI app entry point; lifespan, proxy, project web app
    config.py          Path constants and env-var config
    db.py              SQLite init (WAL), get_conn(), _migrate()
    matter_bridge.py   Matter bridge process manager + HTTP client
    mqtt_publisher.py  Optional paho-mqtt output
    theme_scheduler.py Time- and event-based theme switching
    ws_broker.py       WebSocket ConnectionManager; broadcast_event_sync()
    requirements.txt   Python dependencies
    routers/
      admin.py         DB backup/restore, hub status
      agent_bench.py   Agent task lifecycle, prompt builder, diff, adapters
      caddy.py         Auto-generated Caddyfile for {slug}.local routing
      cards.py         Card YAML registry
      commands.py      Hub→device command channel (enqueue, poll, ack, TTL sweep)
      data.py          Project data store (push, bulk, latest, history, spatial, geofences)
      design.py        Theme/token loader
      devices.py       Fleet registry, checkin, pairing token flow, scan
      events.py        Local event bus + SSE stream
      jobs.py          Worker job queue
      matter.py        Matter bridge control + command webhook
      media.py         Binary file upload/download from devices
      ota.py           Firmware catalog, push, rollback, staged rollout
      packages.py      pip package manager for workers
      projects.py      Project CRUD, file API, Matter config, port-to-hub workflow
      recipes.py       Recipe registry, validation, export
      rules.py         Automation rules CRUD (cron, timezone, rate limiting)
      services.py      LAN service registry + health polling
      terminal.py      PTY WebSocket sessions
      workers.py       Worker registry, job dispatch, git history, enable/disable
    rules/
      engine.py        evaluate_rules() — dispatch log/worker/webhook/command actions
      scheduler.py     Cron scheduler — fires system.clock events; timezone-aware
    workers/
      runner.py        Background thread job dispatcher; ESPAI_HUB_URL injected
      permissions.py   Policy cap validation for worker subprocesses
    discovery/
      mdns.py          mDNS browse + hub advertisement
      scanner.py       Subnet scan (64-worker ThreadPoolExecutor)
  frontend/
    index.html         Dashboard SPA shell
    static/
      css/app.css      Design-token-driven stylesheet
      js/api.js        API client (fetch wrapper, all endpoints)
      js/app.js        All dashboard logic, view routing, modals, tooltip system
  matter/
    bridge.mjs         Node.js Matter bridge process (aggregator, 7 device types)
    package.json       @project-chip/matter-node.js@^0.10 dependency
```

## Environment variables

| Variable                  | Default       | Description                                          |
|---------------------------|---------------|------------------------------------------------------|
| `ESPAI_PORT`              | `7888`        | Bind port                                            |
| `ESPAI_HOST`              | `0.0.0.0`     | Bind address                                         |
| `ESPAI_DEBUG`             | `0`           | Enable debug logging + `/docs` endpoint              |
| `ESPAI_AGENT_BENCH`       | (unset)       | Set to `true` to enable Agent Bench                  |
| `ESPAI_MATTER_AUTOSTART`  | (unset)       | Set to `true` to auto-start Matter bridge on boot    |
| `ESPAI_MATTER_PORT`       | `5580`        | Matter bridge HTTP API port                          |
| `ESPAI_MATTER_PASSCODE`   | `20202021`    | Matter commissioning passcode                        |
| `ESPAI_MATTER_DISCRIMINATOR` | `3840`     | Matter discriminator                                 |
| `ESPAI_MEDIA_MAX_MB`      | `2048`        | Per-project media storage quota (MB)                 |
| `ESPAI_MQTT_HOST`         | (unset)       | MQTT broker hostname — enables MQTT event output     |
| `ESPAI_CORS_ORIGINS`      | `*`           | CORS allowed origins (LAN-only, `*` is acceptable)   |

Set in `.env` at the repo root (gitignored).

## API summary

| Method | Path | Description |
|--------|------|-------------|
| GET    | `/api/status` | Hub health, version, uptime |
| GET    | `/api/meta` | Capability + endpoint discovery |
| GET    | `/api/devices/` | List fleet devices |
| POST   | `/api/devices/checkin` | Node checkin (called by node) |
| POST   | `/api/devices/manual` | Add device by IP |
| POST   | `/api/devices/scan` | Subnet scan |
| POST   | `/api/devices/pair/initiate/{id}` | Generate pairing token |
| POST   | `/api/devices/pair/confirm` | Confirm pairing |
| POST   | `/api/devices/{id}/commands` | Enqueue hub→device command |
| GET    | `/api/devices/{id}/commands/pending` | Device polls pending commands |
| POST   | `/api/devices/{id}/commands/{cmd_id}/ack` | Device acks command |
| GET    | `/api/projects/` | List projects |
| POST   | `/api/projects/` | Create project (esp32/integration/hybrid) |
| POST   | `/api/projects/import-zip` | Import existing ESP32 project from ZIP |
| POST   | `/api/projects/{id}/data` | Push sensor reading (ESP32 / worker) |
| POST   | `/api/projects/{id}/data/bulk` | Push batch of offline-buffered readings |
| GET    | `/api/projects/{id}/data/latest` | Latest reading per device (cached) |
| GET    | `/api/projects/{id}/data` | Reading history |
| GET    | `/api/projects/{id}/data/aggregate` | Bucketed time-series aggregation |
| GET    | `/api/projects/{id}/data/spatial` | Spatial bounding-box + Haversine query |
| GET    | `/api/projects/{id}/track` | Chronological GPS track for a device |
| POST   | `/api/projects/{id}/geofences` | Create named geofence polygon |
| GET    | `/api/projects/{id}/geofences` | List geofences |
| DELETE | `/api/projects/{id}/geofences/{id}` | Delete geofence |
| GET    | `/api/projects/{id}/matter` | Read per-project Matter config |
| PUT    | `/api/projects/{id}/matter` | Write per-project Matter config |
| POST   | `/api/projects/{id}/media` | Upload binary file from device |
| GET    | `/api/projects/{id}/media` | List media files |
| GET    | `/api/projects/{id}/media/{file_id}` | Download media file |
| GET    | `/api/matter/status` | Matter bridge status + endpoints |
| GET    | `/api/matter/qrcode` | Commissioning QR code |
| POST   | `/api/matter/bridge/start` | Start Matter bridge process |
| POST   | `/api/matter/bridge/stop` | Stop Matter bridge process |
| POST   | `/api/matter/sync` | Re-register all matter-enabled projects |
| POST   | `/api/matter/command` | Webhook: bridge → hub command routing |
| GET    | `/api/rules/` | List automation rules |
| POST   | `/api/rules/` | Create rule (cron, timezone, rate limit) |
| GET    | `/api/rules/upcoming` | Next N cron fire times per rule |
| GET    | `/api/events/stream` | SSE event stream |
| GET    | `/api/ota/catalog` | Firmware catalog |
| POST   | `/api/ota/push` | Push firmware to device |
| GET    | `/api/workers/` | List workers |
| POST   | `/api/jobs/submit` | Queue a worker job |
| GET    | `/api/design/tokens` | Active theme CSS tokens |
| GET    | `/api/admin/backup` | DB backup download |
