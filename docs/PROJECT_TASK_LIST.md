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

### OTA UX — Project-Centric Flash Flow (follow-on)
- [x] **Project-scoped firmware upload** — "⬆ Upload Firmware" button in project detail header; pre-fills board from linked device, pre-fills project name as label; on success refreshes the project Firmware section rather than navigating to OTA view
- [x] **Firmware label / display name** — `label` field stored in firmware.json on upload; shown in catalog cards ("Jingle Bells v1.0.0" instead of "seeed_xiao_esp32s3-1.0.0") and in project firmware rows
- [x] **Project-linked firmware section in project detail** — "Firmware" section below Linked Devices; shows entries tagged to this project via `project_id`; each row has a "⬆ Flash" button that pre-filters the push modal to this project's linked devices only
- [x] **Firmware catalog `project_id` tag** — stored in firmware.json on upload (auto-set when uploading from project context); `GET /api/ota/catalog/project/{project_id}` endpoint returns filtered entries
- [x] **One-click flash from fleet card** — paired device cards in Fleet view get a "⬆ Flash" button; modal shows only board-compatible firmware sorted newest first with known-good labels; two clicks to push

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

## Milestone 13 — Agent Bench v2 (Contextual Tasks)

### Completed this session
- [x] Context-scoped tasks — `context_type` / `context_id` / `parent_task_id` columns in `agent_tasks` (additive migration)
- [x] Seed and provision firmware path protection — agents blocked from touching `firmware/seed/` and `firmware/provision/`
- [x] Inferred `allowed_paths` — backend derives paths from context (project → `projects/{id}/firmware/ + workers/`; worker → `workers/{name}/`; template YAML fallback; no manual entry required)
- [x] Inferred `acceptance_criteria` — per-template defaults applied when user leaves criteria blank
- [x] `GET /tasks` context filters — `context_type`, `context_id`, `parent_task_id` query params
- [x] Unified `_openAgentTaskModal()` — full form when called from Agent Bench; simplified "scoped" form (paths/criteria hidden, context badge shown) when called from project or worker context
- [x] Project detail → Agent Tasks section — task table with status badge, template label, time, follow-up button; tasks click through to Agent Bench detail view
- [x] Project detail → `+ Agent Task` button — opens scoped modal pre-bound to the current project
- [x] Worker cards → `⚡ Agent Task` button — opens scoped modal for that worker
- [x] Agent Bench list → context and thread badges on task cards
- [x] Thread follow-ups — `parent_task_id` links tasks; follow-up button on project task rows; thread note injected into agent prompt

### Pending / follow-on
- [ ] Thread grouping in Agent Bench list — collapse parent + children to one expandable row with run count
- [ ] Cross-domain path inheritance — when a project task needs to create/modify a shared worker, prompt user to grant `workers/` access inline
- [x] Worker quarantine auto-lift — after agent task approved, `_checkQuarantineLift` checks allowed_paths for worker folders, finds quarantined workers, shows modal with "Lift Quarantine" (calls `PATCH /api/workers/{name}/quarantine?quarantine=false`) or "Keep Quarantined"
- [x] Agent Bench filter by context_type in sidebar — second filter row (All contexts / Project / Worker / Standalone); client-side filter applied after status-filter fetch

## Milestone 14 — Registry Content Packs

### Recipes
- [ ] BLE integration recipe — Bluetooth speaker / BLE sink (common ESP32 + BLE peripheral, e.g. A2DP audio bridge or BLE sensor aggregator)
- [ ] Additional starter recipes — temperature pipeline, motion-alert pipeline, battery monitor

### Workers
- [ ] Hotdog-or-not worker — OpenCV + image classifier; accepts image input (JPEG bytes or path), returns `{is_hotdog: bool, confidence: float, label: str}`; designed for ESP32-CAM integration; fully fleshed out with manifest, entrypoint, test data, and card binding
- [ ] Flesh out existing opencv-motion-tagger scaffold with complete implementation, test fixture, and example card binding
- [ ] ffmpeg-compressor — complete the existing scaffold

### Cards
- [ ] Card preview system — in-hub HTML preview pane using dummy data so cards render without a live device
- [ ] Theme selector card — lets users switch the hub theme, create/delete themes, and pick per-project themes
- [ ] Network manager card — WiFi STA (SSID scan + connect), AP mode toggle, hostname editor, IP display
- [ ] File manager card — browse SD card or LittleFS/SPIFFS on-device file system; navigate, download, delete
- [ ] Sensor dashboard card — live readings from a named event source with configurable fields and sparkline
- [ ] OTA status card — shows current firmware version, channel, last update time, one-click push trigger
- [ ] Device log card — tail of serial/log output from a connected device

### Themes
- [ ] Theme manager UI — hub-level theme switcher: list themes, select active, create new, delete (original default-dark is undeletable)
- [ ] Theme color editor — pick colors per token with live preview, save as new theme or overwrite existing
- [ ] Project-level theme selector — apply any hub theme to one or more projects from the project detail view
- [ ] Additional pre-built themes (e.g. light, high-contrast, ocean, warm-amber)

## Milestone 15 — In-Hub Code Editor

- [ ] File click → in-hub text editor modal — syntax-highlighted code editor (CodeMirror or Monaco lite) for any project file
- [ ] Save, delete, rename/move file operations from editor
- [ ] New file creation within a project directory
- [ ] Project / card / worker name rename from the hub portal (PATCH name in-place)
- [ ] Diff view for staged agent changes with Accept / Reject per-file

## Milestone 16 — ESPAI Context Files

- [x] Auto-generate `ESPAI.md` in every new project — `_generate_espai_md()` in projects.py writes project-specific context (ID, hub data push/pull examples, firmware quickstart, structure, constraints); also `POST /api/projects/{id}/regenerate-context` + "↺ Context" button in project detail
- [x] Include in agent prompt automatically — `_build_prompt()` in agent_bench.py injects `projects/{id}/ESPAI.md` when present, before task description
- [x] Root-level `ESPAI.md` — platform overview for contributors and new developers
- [x] Agent rule file (`agents/rules.md`) — explicit do/do-not list injected into every agent prompt by `_build_prompt()`

## Milestone 17 — Local Project Access (Caddy / mDNS routing)

- [ ] Caddy integration — auto-generate a Caddyfile mapping project names to hub-hosted project pages (e.g. `motion-sensor.local → hub:8080/projects/{id}`)
- [ ] Project page nav — "Open" button on project detail that launches the device's own web UI or the hub proxy URL in a new tab
- [ ] LAN device browser — scan for non-ESPAI HTTP devices (Tasmota, ESPHome, etc.) and list them with a direct link; import option to bring them into the hub
- [ ] Device link from fleet — any discovered device with an HTTP UI gets a "Open Portal" link in Fleet view

## Milestone 18 — Git Version Control

- [ ] Per-project Git init on project create / import (if git available)
- [ ] Auto-commit on file save and agent task approval
- [ ] Version history view in project detail — list commits, show diff, restore to a prior version
- [ ] OTA firmware version pinned to git tag — firmware push records the commit SHA in the audit log
- [ ] Rollback to prior firmware tied to git branch / tag

## Milestone 19 — Standalone Installer and GitHub Releases

### Core packaging
- [ ] **Frozen path detection in `config.py` and `espai.py`** — detect `sys.frozen` (PyInstaller) and set `ROOT = Path(sys.executable).parent` so data dirs (`data/`, `projects/`, `firmware-catalog/`) resolve relative to the exe, not the bundle internals
- [ ] **`espai.spec`** — PyInstaller one-dir spec: entry point `espai.py`, bundles `hub/frontend/`, `recipes/`, `workers/`, `cards/`, `design/`, `agents/`, `agent-bench/` as data files; excludes `.venv`, `__pycache__`, `.git`
- [ ] **`requirements-bundle.txt`** — locked/pinned requirements for reproducible builds; includes `pyinstaller`, `pystray`, `pillow`, `pywinpty` (Windows) or `ptyprocess` (Linux)

### GitHub Actions release pipeline
- [ ] **`.github/workflows/release.yml`** — triggered on tag push `v*.*.*`; two parallel jobs: `build-windows` (runs-on `windows-latest`) and `build-linux` (runs-on `ubuntu-latest`); each installs Python 3.12, runs PyInstaller, zips the dist folder, uploads artifact
- [ ] **Release job** — creates a GitHub Release from the tag; attaches `ESPAI-windows.zip` and `ESPAI-linux.tar.gz` as downloadable assets; auto-generates release notes from commit messages since last tag

### Windows experience
- [ ] **Windows: launch via `ESPAI.exe`** — entry point invokes `espai.py serve` and opens the dashboard in the default browser; optionally starts the tray icon so the hub runs in the background
- [ ] **Windows: optional Inno Setup installer** — wraps the PyInstaller one-dir output in a proper installer wizard; installs to `%LOCALAPPDATA%\ESPAI`, creates Start Menu shortcut and optional autostart entry; uninstall support

### Linux experience
- [ ] **Linux: launch via `./espai`** — single binary entry; `espai serve` starts uvicorn; `espai doctor` checks deps as usual
- [ ] **Linux: optional `.deb` package** — installs binary to `/usr/local/bin/espai`, data skeleton to `/etc/espai/` (read-only defaults) and `~/.local/share/espai/` (user data); systemd service unit included

### First-run experience
- [ ] **First-run scaffold** — on first launch from a bundled exe, copy default `recipes/`, `workers/`, `cards/`, `design/` from the bundle into the user data directory alongside the exe (Windows) or `~/.local/share/espai/` (Linux); show a one-time welcome message with the dashboard URL
