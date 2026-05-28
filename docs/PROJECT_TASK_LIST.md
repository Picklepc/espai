# ESPAI Project Task List

## Milestone 0 — Repo Foundation
- [x] MIT license
- [x] `.agent/` rules
- [x] schemas (recipe, worker, theme, card, policy, firmware, device)
- [x] default policy
- [x] design scaffold (default-dark theme, skins, nav)
- [x] recipe scaffold (example-bms)
- [x] worker scaffold (opencv-motion-tagger, ffmpeg-compressor)
- [x] card scaffold (status, trailcam-gallery)

## Milestone 1 — Native Fast Start
- [x] ESPAI init
- [x] ESPAI doctor
- [x] ESPAI serve (auto-uses .venv if present, re-execs with venv Python)
- [x] create workspace folders (data/, projects/, firmware-catalog/)
- [x] detect Git, Python, PlatformIO, Docker, VSCode, FFmpeg
- [x] install dependencies only with explicit approval (ESPAI install-deps, creates .venv)

## Milestone 2 — Hub MVP
- [x] FastAPI backend scaffold
- [x] SQLite DB (devices, projects, ota_log, jobs, events, pairing_tokens, rules)
- [x] dashboard (fleet, projects, recipes, workers, cards, jobs, OTA, design, events, rules)
- [x] device/project/card/recipe/worker registries (YAML folder scans)
- [x] design token loader (theme → CSS custom properties)
- [x] local event bus scaffold (SQLite + SSE stream)
- [x] worker runner (subprocess executor, quarantine check, timeout enforcement)
- [x] project folder structure (files, firmware, config per project — scaffold on create, files API)

## Milestone 3 — ESP32 Seed Firmware
- [x] /api/manifest endpoint
- [x] /api/status endpoint
- [x] /api/checkin endpoint
- [x] /api/reboot endpoint
- [x] OTA endpoint scaffold (/ota/update — 501 placeholder)
- [x] fallback AP mode
- [x] unique node ID (SHA-256 of MAC — no raw MAC stored)
- [x] mDNS advertisement (_ESPAI-node._tcp.local)
- [x] build-flag credential injection (no hardcoded secrets)
- [ ] actual OTA binary receive + apply (TODO)
- [ ] sleep/wake checkin support (TODO)

## Milestone 4 — Discovery and Pairing
- [x] manual IP add (POST /api/devices/manual)
- [x] pairing token flow (initiate + confirm)
- [x] mDNS discovery scaffold (hub side — zeroconf)
- [x] subnet scan (stdlib ThreadPoolExecutor, 64-worker parallel probing, auto-registers)
- [x] mDNS browse active integration (discovered nodes auto-added to DB on startup)
- [x] unpaired device onboarding flow in UI (Pair modal: token display, copy-to-clipboard, device portal link, 2.5s auto-poll for device confirmation)

## Milestone 5 — Device Recipes
- [x] recipe YAML parser (registry loader)
- [x] recipe registry API
- [x] recipe validator (GET /api/recipes/{name}/validate — jsonschema with fallback)
- [x] local overlays (private/ subfolder) (_deep_merge + _apply_private_overlay in recipes.py; private/*.yaml files merged on top of base recipe; _private_overlay flag; stripped by export)
- [x] sanitizer/export tool (GET /api/recipes/{name}/export — share_policy: public/redacted/private)
- [x] compatibility and implementation metadata (GET /api/recipes/{name}/compat — boards/workers/tools check; GET /api/workers/{name}/compat — entrypoint/tools/docker/policy check)

## Milestone 6 — Python Workers
- [x] worker YAML parser (registry loader)
- [x] worker registry API
- [x] job queue (SQLite-backed, status tracking)
- [x] quarantine state (policy-enforced default)
- [x] native subprocess runner (poll loop, quarantine guard, timeout, job status updates)
- [ ] Docker sidecar runner (TODO)
- [x] permission enforcement at runtime (permissions.py — policy cap check, env sanitization, process priority)

## Milestone 7 — Design System
- [x] static theme loading (YAML → API → CSS custom properties)
- [x] token consumption in dashboard
- [x] nav loading scaffold
- [x] skin scaffold (holiday-winter example)
- [x] project-level theme overrides (GET/PUT /api/projects/{id}/theme; .ESPAI-project.json stores theme_overrides; frontend applies/clears CSS vars on project open/close; 🎨 Theme button with editor modal)
- [x] dynamic theme rules (time-based: theme_scheduler evaluates hour_start/hour_end rules every 60s; event-based: theme_change action type in rules engine calls theme_scheduler.trigger_event_rule with tokens + duration_minutes; UI: Theme Token Override option in New Rule modal)

## Milestone 8 — OTA and Rollback
- [x] firmware catalog (upload + metadata + checksum)
- [x] OTA audit log
- [x] firmware schema (board, version, channel, sha256, known_good, rollback_target)
- [x] actual firmware push to node (HTTP POST binary to /ota/update with SHA-256 header)
- [x] board/project compatibility validation (409 on mismatch, force flag, client-side compat warning)
- [x] staged rollout (POST /api/ota/rollout — device_ids/board_filter/pct targeting; openRolloutModal with device checkboxes, percentage, force flag; results summary)
- [x] known-good tracking and rollback flow (mark-good endpoint + audit log; PATCH catalog; rollback endpoint follows rollback_target pointer; UI: ✓ Mark Known Good + ↩ Set Rollback buttons per catalog entry)

## Milestone 9 — Notifications and Automations
- [x] event rules engine (rules table, REST CRUD, evaluate on publish — actions: log_event, run_worker, webhook)
- [x] local notifications (browser push) (SSE-connected EventSource; bell toggle in sidebar; Notification API; auto-reconnects; also live-refreshes events view)
- [x] MQTT optional output (hub/backend/mqtt_publisher.py; paho-mqtt optional; ESPAI_MQTT_HOST/PORT/TOPIC_PREFIX env vars; auto-connect on startup; publishes to {prefix}/events/{type} and {prefix}/source/{src}/events/{type})
- [x] worker-triggered events (runner publishes events[] from worker stdout; rules engine evaluates them automatically)

## Milestone 10 — Multi-Node Apps and Shared Services
- [ ] multi-node project model
- [ ] secondary service advertisement
- [x] resource cost metadata (jobs view cross-references worker registry for resource_cost; cpu/memory/disk tags with color coding; not-rt-safe badge; click-to-expand job outputs/error)
- [x] direct realtime broker (WebSocket — ws_broker.py ConnectionManager; /api/ws endpoint; broadcast_event_sync wired into events publish; frontend uses WebSocket replacing SSE with auto-reconnect)

## Milestone 11 — Simulation and Testing
- [x] fake ESP32 node (simulators/fake-node/fake_node.py — manifest, status, checkin, reboot, OTA)
- [x] fake BMS node (simulators/fake-bms/fake_bms.py — battery level, voltage, temperature, cell data)
- [x] fake GPIO node (simulators/fake-gpio/fake_gpio.py — 8 pins, set/get state, PWM)
- [x] fake camera node (simulators/fake-camera/fake_camera.py — MJPEG stream, snapshot, motion events, PIL frames)
- [x] worker test harness (POST /api/workers/{name}/test — sandboxed sync run, returns stdout/stderr/outputs/duration; ▶ Test button on worker cards with JSON input editor)
- [x] recipe decoder tests (tests/test_recipes.py — 14 tests: scan_folder, deep_merge, private overlays, export sanitization, schema validation; all passing)

## Milestone 12 — Packaging
- [x] Docker appliance scaffold (docker-compose.yml)
- [x] Hub Dockerfile (hub/Dockerfile — python:3.12-slim, healthcheck, uvicorn)
- [x] Windows tray app scaffold (hub/tray/tray.py — pystray + PIL icon; Start/Stop/Open Dashboard/Exit menu; auto-starts hub; espai.py tray command)
- [x] backup/restore (GET /api/admin/backup + download; POST /api/admin/restore with column allowlist guard; GET /api/admin/status; ⬇ Backup + ⬆ Restore buttons in OTA view)
- [x] future VSCode extension API readiness (GET /api/meta — capabilities list, endpoint map, schema versions)
