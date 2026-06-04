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
- [x] project folder structure (workers/, captures/, notes.md, ESPAI.md, .gitignore — scaffold on create, files API; firmware/ added for esp32/hybrid projects; integration/ added for integration/hybrid projects — see M13 device_type)

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
- [x] actual OTA binary receive + apply — `Update.begin/write/end` + incremental SHA-256 verify in `firmware/seed/src/main.cpp`; reboot on success, error logged to Serial
- [x] sleep/wake checkin support — `SLEEP_INTERVAL_S` build flag (default 0 = always-on); on boot posts identity to `HUB_URL/api/devices/checkin` and reads back hub-side `sleep_interval_s` override; serves HTTP for 5 s window then calls `esp_deep_sleep()`; hub stores `sleep_interval_s` in `devices` table (additive migration); checkin response includes `sleep_interval_s` so hub can override node's compiled-in value

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
- [x] Multi-node project model — `project_nodes` table `(project_id, device_id, role, label, node_index)`; backfill migration from `projects.devices` JSON on startup; node roles: coordinator/sensor/actuator/gateway/observer/hub-agent/relay/node; topology: standalone/star/mesh/hub-spoke/pipeline/custom; `app_type: firmware/hub/hybrid` stored in `.ESPAI-project.json` as topology metadata — **distinct from `device_type`** (M13) which drives scaffold and agent template filtering; backward-compat: `projects.devices` JSON kept in sync on all writes
  - `GET/PUT/DELETE /api/projects/{id}/nodes/{device_id}` — per-node role management
  - `GET /api/projects/{id}/nodes` — list nodes with roles
  - `GET/PUT /api/projects/{id}/topology` — topology and app_type
  - `GET /api/devices/{id}/projects` — reverse lookup: which projects a device belongs to and with what role
  - Project detail: Nodes section shows topology/app-type dropdowns, per-node role badges (color-coded by role), "⚙ Role" modal, role-aware Find Node + Link dialogs
  - Dashboard project cards: topology badge in hero, node count, app-type indicator
  - Fleet device pills: project membership chips (clickable, color matches role)
- [x] secondary service advertisement — `MDNSManager.register_project(slug, project_id)` advertises `{slug}._http._tcp.local.` with `server={slug}.local.`; called on project create/rename/delete; `register_all_projects()` called at hub startup; `unregister_project(slug)` on delete/rename
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
- [x] Docker appliance — `docker-compose.yml` + `hub/Dockerfile` + `.dockerignore` + `.env.example`; headless service targeting FriendlyElec/OpenWrt ARM64; `network_mode: host` for mDNS; SSD bind-mounts via `ESPAI_SSD_PATH`; Node.js + Claude Code CLI pre-installed (`ARG INSTALL_CLAUDE=true`); fixed data path (`/app/data` not `/data`); `restart: unless-stopped`
- [x] **Multi-arch Docker CI with worker variants** (v0.2.0) — matrix `build-docker` job; three variants built in parallel: `latest` (hub + Claude CLI), `workers` (+ OpenCV/FFmpeg/numpy/scipy/Pillow), `slim` (hub only); QEMU `linux/amd64` + `linux/arm64`; pushed to `ghcr.io/picklepc/espai:{version}{suffix}`; per-variant GHA cache scopes; `ESPAI_IMAGE` env var in docker-compose selects variant; `INSTALL_WORKER_DEPS` and `INSTALL_CLAUDE` build args in Dockerfile
- [x] Windows tray app (hub/tray/tray.py — pystray + PIL icon; Start/Stop/Restart/Open Dashboard/Open Logs/Start at Login/Exit; dynamic enabled state; teal↔gray icon reflects hub state; hub stdout→data/espai-hub.log; Open Logs spawns live PowerShell tail console; winreg autostart toggle; frozen-exe auto-starts tray on double-click; console=False in spec so no terminal window appears)
- [x] backup/restore (GET /api/admin/backup + download; POST /api/admin/restore with column allowlist guard; GET /api/admin/status; ⬇ Backup + ⬆ Restore buttons in OTA view)
- [x] future VSCode extension API readiness (GET /api/meta — capabilities list, endpoint map, schema versions)

## Milestone 13 — Agent Bench v2 (Contextual Tasks)

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
- [x] Thread grouping in Agent Bench list — root tasks with children show a "▶ N follow-ups" toggle button; children rendered indented under parent; orphaned children (parent filtered out) shown flat; works alongside context and status filters
- [ ] Cross-domain path inheritance — when a project task needs to create/modify a shared worker, prompt user to grant `workers/` access inline
- [x] Worker quarantine auto-lift — after agent task approved, `_checkQuarantineLift` checks allowed_paths for worker folders, finds quarantined workers, shows modal with "Lift Quarantine" (calls `PATCH /api/workers/{name}/quarantine?quarantine=false`) or "Keep Quarantined"
- [x] Agent Bench filter by context_type in sidebar — second filter row (All contexts / Project / Worker / Standalone); client-side filter applied after status-filter fetch
- [x] **Project `device_type`** — `device_type TEXT DEFAULT 'esp32'` column in projects; `ProjectCreate.device_type` field; scaffold branches on type (`firmware/` for esp32/hybrid, `integration/` for integration/hybrid); `_generate_espai_md()` generates type-appropriate docs; `GET /api/agent-bench/templates?device_type=` filters templates by `applicable_types`; new `api-integration` task template; `applicable_types` on existing templates; type picker in new project modal; device type badge on project cards

## Milestone 14 — Registry Content Packs

### Recipes
- [x] BLE integration recipe — `recipes/ble-peripheral-bridge/recipe.yaml`; BLE Central scan by UUID/name/MAC; characteristic decode (int16_le/uint16_le); NimBLE-Arduino notes; variants: BLE UART tunnel + BLE HID forwarder; security: MAC hashing
- [x] Additional starter recipes — `recipes/temperature-pipeline/recipe.yaml`, `recipes/motion-alert-pipeline/recipe.yaml`, `recipes/battery-monitor/recipe.yaml`

### Workers
- [x] Flesh out existing opencv-motion-tagger scaffold — full implementation: video (MOG2), image sequence (frame diff), single image (Canny edge proxy); bounding-box regions, motion scores, thumbnail generation, ESPAI event emission; updated worker.yaml with typed inputs and test_inputs
- [x] ffmpeg-compressor — `workers/ffmpeg-compressor/main.py`; H.264/H.265/VP9 via subprocess ffmpeg; configurable CRF/preset/scale/audio; thumbnail extraction; ffprobe metadata; compression ratio; emits media.compressed event

### Cards
- [x] Card preview system — `GET /api/cards/{name}/preview`; serves hand-authored `preview.html` if present, else generates retro-styled preview from card YAML; sensor-dashboard has animated live preview with sparklines + dummy readings; Cards view has "👁 Preview" button per card opening an iframe modal
- [x] Theme selector card — `cards/theme-selector/card.yaml`; hub-only card; documents GET/PUT `/api/design/themes`, GET/PUT `/api/design/theme/active`, GET/PUT `/api/projects/{id}/theme` endpoints
- [x] Network manager card — `cards/network-manager/card.yaml`; WiFi STA/AP, SSID scan, hostname editor; device endpoint spec included
- [x] File manager card — `cards/file-manager/card.yaml`; browse LittleFS/SPIFFS/SD via device REST API; device endpoint spec included; interactive `preview.html` with directory navigation, storage bar, mock file tree (7 KB)
- [x] Device log card — `cards/device-log/card.yaml`; WebSocket log stream + polling fallback; level filter; ring buffer; auto-scroll
- [x] Sensor dashboard card — `cards/sensor-dashboard/card.yaml`; hub data store source; configurable field list with units and sparkline; alert thresholds; firmware push pattern documented
- [x] OTA status card — `cards/ota-status/card.yaml`; reads device manifest and OTA log; one-click push from card; channel filter

### Themes
- [x] Theme manager UI — Design view has theme grid with palette swatches, Activate/Delete buttons; GET/PUT `/api/design/theme/active`; DELETE `/api/design/themes/{name}`; `hub_settings` DB table persists active theme; built-in themes undeletable
- [x] Theme color editor — "＋ Create Theme" in Design view; color pickers for all `color.*` tokens; text fields for radii/fonts; auto-slug from name; `POST /api/design/themes` creates YAML in `design/themes/custom/`; `design/themes/.gitignore` excludes custom/ from git
- [x] Project-level theme selector — 🎨 Theme button replaced: shows hub theme cards with palette swatches (same style as Design view); click card to load tokens into JSON editor; "Save & Apply" applies them as project overrides
- [x] Theme official/custom pack flags — `_pack: official` for `design/themes/*/`, `_pack: custom` for `design/themes/custom/*/`; theme manager cards show "official" (teal) vs "custom" (amber) badge; new themes from color editor always go to custom/
- [x] Light theme — `design/themes/light/theme.yaml`; clean light palette for bright environments
- [x] Ocean theme — `design/themes/ocean/theme.yaml`; abyssal dark blues, bioluminescent cyan/seafoam accents
- [x] Warm Amber theme — `design/themes/warm-amber/theme.yaml`; forge-lit darks, hammered-copper and molten-gold accents

## Milestone 15 — In-Hub Code Editor

- [x] File click → in-hub text editor modal — CodeMirror 5 (dracula theme) via CDN; supports JS, C/C++, Python, YAML, Markdown, HTML, CSS, INI; mode auto-detected by extension; `.bin` and files >512 KB are non-clickable; modal-wide layout (860px)
- [x] Save, delete operations from editor — PUT/DELETE `/api/projects/{id}/files/{path}`; path-traversal and private-file guards; protected files (platformio.ini, ESPAI.md, .ESPAI-project.json) blocked from delete
- [x] New file creation — "+ New File" button; enter relative path; POST `/api/projects/{id}/files/{path}`; opens editor immediately after create
- [x] Project rename from hub portal — `PATCH /api/projects/{id}/rename`; ✎ Rename button in project detail header; live hostname preview
- [x] Card / worker / recipe management from hub portal — `POST /new` scaffold + `DELETE /{name}` + full file CRUD (`GET/PUT/POST/DELETE /{name}/files/{path}`); shared `reg_files.py` helper; "📁 Edit" opens file browser subview with CodeMirror; "＋ New" modal with auto-slug; "✕ Delete" with confirmation; path-traversal guard; bad-slug guard
- [x] Diff view per-file Accept/Reject — diff modal has per-file checkboxes (default: all checked = accept); "✓ Apply Selected" approves task with unchecked paths as `reject_paths` (reverted to snapshot_before); "↩ Revert All" sends all paths as reject_paths; `ReviewCreate.reject_paths` field; `submit_review` restores rejected files from snapshot

## Milestone 16 — ESPAI Context Files

- [x] Auto-generate `ESPAI.md` in every new project — `_generate_espai_md()` in projects.py writes project-specific context (ID, hub data push/pull examples, firmware quickstart, structure, constraints); also `POST /api/projects/{id}/regenerate-context` + "↺ Context" button in project detail
- [x] Include in agent prompt automatically — `_build_prompt()` in agent_bench.py injects `projects/{id}/ESPAI.md` when present, before task description
- [x] Root-level `ESPAI.md` — platform overview for contributors and new developers
- [x] Agent rule file (`agents/rules.md`) — explicit do/do-not list injected into every agent prompt by `_build_prompt()`

## Milestone 17 — Local Project Access (Caddy / mDNS routing)

- [x] Caddy integration — `hub/backend/routers/caddy.py`; `GET /api/caddy/caddyfile` returns generated config; `GET /api/caddy/download` serves as file attachment; `POST /api/caddy/write` writes to `ESPAI_CADDY_PATH` (default `data/Caddyfile`); each project slug gets a `{slug}.local → reverse_proxy localhost:{port}/app/{slug}` block; "⬇ Caddyfile" button in Projects view header
- [x] Project page nav — "🌐 Open App" button in project detail calls `GET /api/projects/{id}/app-url`; priority: hub-hosted web/index.html → linked device IP → mDNS slug.local; opens in new tab
- [x] LAN device browser — `POST /api/devices/browse` probes all 254 subnet hosts on port 80; returns ESPAI nodes (is_espai=True) + any other HTTP device (title from `<title>`, server header); "🔍 Browse LAN" button in Fleet; results modal shows both groups with direct "Open ↗" links
- [x] Device link from fleet — paired and unpaired devices with known IPs show a "🌐" button that opens `http://{ip}/` in a new tab

## Milestone 18 — Git Version Control

- [x] Per-project Git init on project create — `git_helper.git_init(proj_dir)` called at end of `_create_project_folder`; uses local `.git` check (not parent repo detection); silent when git unavailable
- [x] Auto-commit on file save — `write_project_file` calls `git_helper.git_commit` with message `edit: {path}` after each save; also on agent task approval via `submit_review` with message `agent: {title} (approved)`
- [x] Version history view in project detail — `GET /api/projects/{id}/git/log`; "📋 History" button shows last 40 commits with hash, message, author, timestamp; shows "no git repo" message for projects without own .git
- [x] OTA firmware version pinned to git SHA — `ota_log.git_sha` column (additive migration); `git_helper.get_head_sha()` captures project HEAD SHA at push time; stored in `push_complete` audit log entry; linked to the firmware's `project_id`
- [x] Git-SHA-tagged OTA rollback — `import_build` stores `git_sha` (HEAD at build time) in `firmware.json`; git history modal loads project catalog in parallel, builds `sha→entry` map, shows 🎯 Flash button on commits with matching catalog entries; `_openGitFlashModal()` shows device picker and calls `POST /api/ota/push`

## Milestone 19 — Standalone Installer and GitHub Releases

### Core packaging
- [x] **Frozen path detection in `config.py`** — `sys.frozen` check; `ROOT = Path(sys.executable).parent` for bundled exe, `Path(__file__).parent.parent.parent` for source
- [x] **`espai.spec`** — PyInstaller one-dir spec; bundles hub/frontend/, recipes/, workers/, cards/, design/, agents/, policies/, schemas/; hidden imports for uvicorn, FastAPI, pydantic, zeroconf, pystray, PIL, winpty; excludes dev tools
- [x] **`requirements-bundle.txt`** — locked requirements including pyinstaller, pystray, pillow, pywinpty (Windows) / ptyprocess (Linux), optional paho-mqtt; opencv commented out (large)

### GitHub Actions release pipeline
- [x] **`.github/workflows/release.yml`** — triggered on tag push `v*.*.*`; parallel `build-windows` (windows-latest) and `build-linux` (ubuntu-latest) jobs; each installs Python 3.12, runs PyInstaller, zips/tars dist; `release` job creates GitHub Release with auto-generated notes from commits; attaches `ESPAI-windows.zip` and `ESPAI-linux.tar.gz`; pre-release flag for tags containing `-`

### Windows experience
- [x] **Windows: launch via `ESPAI.exe`** — `espai.py serve --open` opens dashboard in default browser after 2s startup delay (via background thread); auto-open always on when `sys.frozen` (bundled exe); `--open` flag added to serve subparser
- [x] **Windows: Inno Setup installer** — `installer/espai.iss`; single `ESPAI-Setup-{version}.exe`; installs to `%LOCALAPPDATA%\Programs\ESPAI` (no elevation); Start Menu + optional desktop shortcut; optional startup-at-login task; uninstall removes registry key; CI builds and attaches to GitHub Release

### Linux experience
- [x] **Linux: AppImage** — CI assembles `AppDir` from PyInstaller one-dir output; generates teal-diamond icon via PIL; adds `AppRun` + `.desktop`; builds `ESPAI-{version}-x86_64.AppImage` using appimagetool (FUSE-free extract method for CI compatibility); attached to GitHub Release
- [ ] **Linux: `.deb` package** — installs binary to `/usr/local/bin/espai`, data skeleton to `/etc/espai/` (read-only defaults) and `~/.local/share/espai/` (user data); systemd service unit included
- [x] **Firmware CI builds** — `build-firmware` matrix job in `.github/workflows/release.yml`; PlatformIO matrix over `seeed_xiao_esp32s3`, `esp32dev`, `lolin_s3`; PIO cache keyed by platformio.ini hash; artifacts `ESPAI-firmware-seed-{env}-{version}.bin`; downloaded and attached by `release` job; release notes include firmware section; empty Wi-Fi → AP mode default

### First-run experience
- [x] **First-run scaffold** — `_first_run_scaffold()` in espai.py; when `sys.frozen` and `data/.espai-initialized` absent: copies content packs (recipes/workers/cards/design/agents/policies/schemas) from PyInstaller bundle (_MEIPASS) to exe dir; writes default .env; creates sentinel file; prints welcome message with paths

## Milestone 20 — LAN Services Registry

The hub maintains a persistent registry of every discovered or manually-added LAN service. This is the foundation of the "replace cloud apps" experience — a single pane of glass for all local devices and services.

- [x] **Services view** — dedicated "Services" nav tab (`view-services`); groups services by category (Projects / Smart Home / Media / Network / Tools / Other); pinned items float to top; Discover, Add, and Show Hidden buttons; `loadServicesView()` in app.js
- [x] **Pin / hide / label** — "⋯" menu on every service tile opens edit modal: set label, category, pin/unpin, hide, or delete; all stored in `local_services.pinned/.hidden/.label`; edit modal reloads both home and services view
- [x] **Category auto-detect** — `_detect()` in `services.py` fingerprints by `<title>` and Server header; recognises Tasmota, ESPHome, Home Assistant, OpenWrt, Pi-hole, Proxmox, Jellyfin, Plex, Emby, Kodi, Grafana, Portainer, Gitea, Nextcloud, Synology
- [ ] **Link service to project** — "Link to Project" button on service card sets `local_services.project_id`; shows project badge on service; clicking opens project detail
- [ ] **Service health polling** — background task pings pinned services every 60 s; updates `last_seen`; shows online/offline dot in the Services view

## Milestone 21 — Integration Template Library

Pre-built integration workers for the most common local-API devices. Each ships as a worker YAML + Python file in `workers/` so agents can extend them rather than starting from scratch.

- [x] **Tasmota** — `workers/tasmota-poller/`; `Status 0` full probe; power, energy, relay state, generic sensors; `TASMOTA_HOST` + optional `TASMOTA_PASSWORD` env vars
- [x] **Shelly** — `workers/shelly-poller/`; gen1 (`/status`) and gen2 (`/rpc/Shelly.GetStatus`) auto-detect; power, energy, temperature, switch state; `SHELLY_HOST` env var
- [x] **WLED** — `workers/wled-controller/`; `/json/state` + `/json/info` read; optional state write (action=apply); brightness, color, effect, palette; `WLED_HOST` env var
- [x] **Zigbee2MQTT** — `workers/zigbee2mqtt-bridge/`; MQTT subscribe to `{prefix}/#`; forwards all device payloads to hub data store keyed by device name; `mode: service` persistent connection; `MQTT_HOST` env var
- [x] **Jellyfin** — `workers/jellyfin-poller/`; active sessions, now-playing title/user/progress; `media.playing` events; `JELLYFIN_HOST` + `JELLYFIN_API_KEY` env vars (also works with Emby)
- [x] **Generic HTTP poller** — `workers/http-poller/`; `base_url`, `path`, `method`, `body`, `field_map` inputs; `HTTP_AUTH_HEADER` env var; reusable base for any REST device

## Milestone 22 — Hub-Hosted Web App Framework

Make it easy to build and deploy a full custom web app as the local replacement for a device's cloud dashboard. The app lives in `projects/{id}/web/` and is served at `/app/{slug}/`.

- [x] **Starter web app scaffold** — `web/index.html` generated on project create; type-specific templates for esp32 (sensor readings grid), integration (tile grid), hybrid (two-section layout); auto-refreshes on hub data push; 5 s polling fallback
- [x] **Hub API client snippet** — `web/hub-api.js` generated on project create; `espai.getLatest()`, `espai.pushData()`, `espai.connectWS()`; works from hub (`/app/{slug}/`) or direct device access; live-reload handler built in
- [x] **Live-reload in dev** — `write_project_file` in `projects.py` broadcasts `project.web.reload` WebSocket event when any `web/` file is saved; `hub-api.js` `connectWS` handler reloads the page if the slug matches
- [x] **App manifest** — `web/app.json` written on project create: `name`, `description`, `project_id`, `entry_point`, `theme_color`
- [x] **Caddy auto-config** (links Milestone 17) — completed above; Caddyfile contains `{slug}.local` blocks for all projects

## Milestone 22.5 — Infrastructure and Quality (v0.3.x)

Cleanup, polish, and M18/M19/M20 follow-ons before the 0.4.0 Matter release.

### Shipped in 0.3.0
- [x] **Worker sync on every startup** — `_sync_workers()` in `espai.py`; per-worker version-aware copy; installs missing workers, overwrites only when bundle version is strictly higher than installed; runs every startup (not sentinel-gated); preserves user-modified workers with matching or higher version
- [x] **Project-scoped worker lookup** — `_resolve_worker()` in `runner.py`; checks `projects/{project_id}/workers/{name}/` before global `workers/`; `project_id` sourced from job `inputs` dict; enables per-project worker customisation without breaking other projects

### Pending (0.3.x targets)
- [ ] **Fleet view sleep indicator** — show `💤 {n}s` badge on fleet device cards when `sleep_interval_s > 0`; allows distinguishing sleeping nodes from offline ones
- [ ] **NVS-configurable awake window** — firmware reads `awake_s` from NVS Preferences (key `awake_s`, default 5); hub checkin response includes `awake_window_s` field; device saves it to NVS; new `awake_window_s` column in `devices` table; editable in fleet device detail
- [ ] **Link service to project** (M20) — "⚙ Link Project" in service edit modal; `ServicePatch.project_id` field; hub queries projects list for picker; shows project name badge on linked service tile; double-clicking badge opens project detail
- [ ] **Service health polling** (M20) — background thread in `services.py` started at hub launch; pings pinned services every 60 s with a HEAD or TCP probe; stores result in new `reachable BOOLEAN` column; services view and home grid show green/red dot per tile
- [ ] **`app-url` uses stored slug** — `project_app_url` reads `slug` column directly instead of re-deriving via `_safe_slug(name)`; removes the one divergence point
- [ ] **Remove dead `_origOpenSvcEdit`** — line 822 of `app.js` captures an unused reference; delete it
- [x] **Git-tagged OTA rollback** (M18) — completed; see M18 entry above
- [x] **Firmware CI builds** (M19) — completed; see M19 entry above
- [ ] **RELEASE_CHECKLIST.md** — add Section 4/5 items for M17–M22 features; update version strings to 0.3.x

## Milestone 23 — Matter Bridge (hub-hosted) — target: v0.4.0

The ESPAI hub acts as a **Matter bridge** (aggregator device). Commission it once to Google Home, HomeKit, or Alexa — every ESPai project that opts in appears as a first-class device in that ecosystem automatically. No Matter stack on the ESP32 or other device required.

### Architecture

```
Google Home / HomeKit / Alexa
    ↕  Matter (fabric — one QR-code commissioning)
ESPai Hub — matter.js bridge process (hub/matter/bridge.mjs)
    ↕  HTTP API (localhost:5580, ESPAI_MATTER_PORT)
hub/backend/matter_bridge.py  ←→  hub/backend/routers/matter.py
    ↕  called on every POST /api/projects/{id}/data push
    ↕  called when project matter config changes
ESP32 nodes  |  Shelly  |  WLED  |  Zigbee  |  any integration project
```

The bridge is a separate Node.js process managed by the Python hub. Python calls it via a local HTTP API. When Matter receives a command (toggle, brightness, etc.) the bridge POSTs it back to the hub webhook `POST /api/matter/command` for routing.

### Bridge process — `hub/matter/bridge.mjs`

**Dependencies** (in `hub/matter/package.json`):
- `@project-chip/matter-node.js@^0.10` — Matter SDK for Node.js
- `@project-chip/matter.js@^0.10` — core (pulled in transitively)

**Bridge HTTP API** (port `ESPAI_MATTER_PORT`, default 5580):
- `GET  /status` → `{ running, commissioned, passcode, discriminator, endpoints: [{id, name, device_type, reachable}] }`
- `GET  /qrcode` → `{ qr_code, manual_pairing_code, svg }` (SVG is a 200×200 QR image)
- `POST /devices` → `{ id, name, device_type, state }` — register or update endpoint; returns `{ endpoint_id }`
- `PUT  /devices/:id/state` → `{ ...attributes }` — update endpoint state (on_off, level, temperature, etc.)
- `DELETE /devices/:id` — remove endpoint
- `POST /shutdown` — graceful shutdown

**Device types supported** (Matter device type → clusters):
| `device_type` | Matter type | Settable from hub | Commandable by Matter |
|---|---|---|---|
| `on_off_plug` | On/Off Plug-in Unit | `on_off: bool` | On, Off, Toggle |
| `dimmable_light` | Dimmable Light | `on_off: bool`, `level: 0–254` | On, Off, MoveToLevel |
| `color_light` | Color (XY) Light | `on_off`, `level`, `hue: 0–254`, `sat: 0–254` | On, Off, MoveToLevel, MoveToHueAndSaturation |
| `temperature_sensor` | Temperature Sensor | `temperature: float °C` (stored as int16 × 100) | — (read-only) |
| `humidity_sensor` | Humidity Sensor | `humidity: float %` (stored as uint16 × 100) | — (read-only) |
| `occupancy_sensor` | Occupancy Sensor | `occupancy: bool` | — (read-only) |
| `contact_sensor` | Contact Sensor | `contact: bool` | — (read-only) |

**Commissioning**: On first start the bridge generates a random passcode (20 202 021 default, configurable via `ESPAI_MATTER_PASSCODE`) and discriminator (3840 default, `ESPAI_MATTER_DISCRIMINATOR`). Fabric state is persisted to `data/matter-storage/` via StorageBackendDisk so it survives restarts.

**Command webhook**: When Matter sends a command, bridge POSTs to `http://localhost:{HUB_PORT}/api/matter/command` with body `{ device_id, command, args }`. Hub routes to the appropriate action (fire event, call device API, run worker).

### Hub Python layer — `hub/backend/matter_bridge.py`

Process manager + thin HTTP client:
- `start()` — spawns `node bridge.mjs` as a subprocess; watches for `READY` stdout line; 15 s timeout; silently no-ops if Node.js is not installed (Matter is an optional feature)
- `stop()` — sends `POST /shutdown`; waits for process exit (5 s); force-kills if needed
- `is_running()` → bool
- `get_status()` → calls `GET /status`
- `get_qrcode()` → calls `GET /qrcode`
- `register_device(device_id, name, device_type, initial_state)` → calls `POST /devices`
- `update_state(device_id, state_dict)` → calls `PUT /devices/{id}/state`; non-blocking (threaded)
- `remove_device(device_id)` → calls `DELETE /devices/{id}`
- `sync_project(project_id)` → reads project `.ESPAI-project.json`, calls `register_device` or `remove_device`
- `sync_all_projects()` → iterates all projects, calls `sync_project` for each matter-enabled one

### Hub router — `hub/backend/routers/matter.py`

- `GET  /api/matter/status` — bridge status + endpoint list; returns `{ enabled, running, commissioned, endpoints }`
- `GET  /api/matter/qrcode` — QR code for commissioning; 404 if bridge not running
- `POST /api/matter/bridge/start` — starts bridge process; returns status
- `POST /api/matter/bridge/stop` — stops bridge process
- `POST /api/matter/sync` — re-registers all matter-enabled projects with the bridge
- `POST /api/matter/command` — webhook called by bridge when Matter sends a command; routes to event publish or device API call based on project `matter_command_actions` config

### Per-project Matter config in `.ESPAI-project.json`

```json
{
  "matter_enabled": false,
  "matter_device_type": "on_off_plug",
  "matter_label": "",
  "matter_state_map": {},
  "matter_command_actions": {},
  "matter_endpoint_id": null
}
```

- `matter_enabled` — whether this project is exposed as a Matter endpoint
- `matter_device_type` — one of the supported types above
- `matter_label` — display name in Google Home / HomeKit (defaults to project name)
- `matter_state_map` — maps hub data keys to Matter attribute names, e.g. `{"power_on": "on_off", "dim": "level"}`. If empty, default maps are used per device type
- `matter_command_actions` — maps Matter commands to ESPai actions, e.g. `{"on": {"type": "device_api", "endpoint": "/api/relay/1/on"}, "off": {"type": "event", "event_type": "relay.off"}}`
- `matter_endpoint_id` — assigned by bridge on registration; stored for reference

**Default state maps** (applied when `matter_state_map` is empty):
- `on_off_plug`: `power_on → on_off`, `on → on_off`, `switch → on_off`
- `dimmable_light`: `on → on_off`, `brightness → level`
- `temperature_sensor`: `temperature → temperature`, `temp → temperature`
- `humidity_sensor`: `humidity → humidity`, `relative_humidity → humidity`
- `occupancy_sensor`: `occupancy → occupancy`, `motion → occupancy`, `presence → occupancy`
- `contact_sensor`: `contact → contact`, `open → contact`, `closed → contact` (inverted)

### Project Matter config endpoints in `projects.py`

- `GET  /api/projects/{id}/matter` — reads `matter_*` keys from `.ESPAI-project.json`
- `PUT  /api/projects/{id}/matter` — writes `matter_*` keys; if `matter_enabled` changes, calls `matter_bridge.sync_project()`

### Data push hook in `data.py`

In `push_data()`, after storing the payload:
1. Check if bridge is running (`matter_bridge.is_running()`)
2. Read project matter config (cached in memory, refresh on change)
3. If `matter_enabled`, apply state map to payload, call `matter_bridge.update_state(project_id, mapped)` in a background thread

### Hub startup / lifespan in `main.py`

- On startup: call `matter_bridge.start()` only if `ESPAI_MATTER_AUTOSTART=true` env var is set (default: off — user enables via dashboard)
- On shutdown: call `matter_bridge.stop()`
- Add `matter.router` at `/api/matter`

### Frontend — Matter section in project detail

Added below the Agent Tasks section:

```html
<div id="projMatterSection" style="margin-top:28px">
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">
    <p class="section-heading" style="margin:0">Matter</p>
    <label class="toggle-label">
      <input type="checkbox" id="projMatterToggle">
      <span data-tip="Expose this project as a Matter endpoint — appears in Google Home, HomeKit, and Alexa once the hub bridge is commissioned"></span>
    </label>
    <span id="projMatterStatus" style="font-size:12px;color:var(--color-text-muted)"></span>
  </div>
  <div id="projMatterConfig" style="display:none">
    <!-- device type selector, label field, state map preview, endpoint ID -->
  </div>
</div>
```

**Hub-level Matter view** (new nav item or within a settings panel):
- Bridge status (running / stopped / commissioned)
- "Start Bridge" / "Stop Bridge" buttons
- QR code display for commissioning (shown when bridge running but not yet commissioned)
- Endpoint list (all registered projects)
- `ESPAI_MATTER_AUTOSTART` toggle

### Installation notes

- `hub/matter/package.json` defines the Node.js deps; `npm install` runs in that directory
- Docker `:latest` and `:workers` images already have Node.js — `npm install` runs on first bridge start
- Windows: requires Node.js 18+ (already bundled with Claude Code install; or user installs separately)
- BLE commissioning: requires Bluetooth hardware on the hub machine; IP commissioning (Matter 1.2+) works without BLE on the same LAN
- Thread devices: require a Thread border router on the network; Wi-Fi Matter devices work without it

### Pending items

- [ ] `hub/matter/bridge.mjs` — Matter.js bridge process with HTTP API
- [ ] `hub/matter/package.json` — `@project-chip/matter-node.js@^0.10`
- [ ] `hub/matter/.gitignore` — ignore `node_modules/`, `matter-storage/`
- [ ] `hub/backend/matter_bridge.py` — process manager + HTTP client
- [ ] `hub/backend/routers/matter.py` — FastAPI router (status, qrcode, start/stop, sync, command webhook)
- [ ] `hub/backend/routers/projects.py` — `GET/PUT /api/projects/{id}/matter` config endpoints
- [ ] `hub/backend/routers/data.py` — hook `push_data` to call `matter_bridge.update_state` in background thread
- [ ] `hub/backend/main.py` — register matter router; start/stop bridge in lifespan
- [ ] `hub/frontend/index.html` — Matter section in project detail (toggle, device type, label, state map, endpoint ID)
- [ ] `hub/frontend/static/js/api.js` — `api.matter.*` and `api.projects.getMatter/setMatter`
- [ ] `hub/frontend/static/js/app.js` — `renderProjectMatter()` called from `openProject()`; hub Matter status view
- [ ] Update `espai.spec` to include `hub/matter/` in bundle datas
- [ ] Update Docker `Dockerfile` to run `npm install` in `hub/matter/` during build
- [ ] Update `RELEASE_CHECKLIST.md` — add Matter smoke test section

## Milestone 24 — Matter Device Type Mapping and Command Routing — target: v0.4.0

Fine-grained control over how ESPai data maps to Matter attributes and how Matter commands route to device actions.

- [ ] **State map editor in UI** — per-project UI for editing `matter_state_map`; shows current hub data keys (from last push) alongside the available Matter attribute names for the selected device type; drag-to-map or dropdown selectors
- [ ] **Command action editor in UI** — per-project UI for `matter_command_actions`; dropdown for command type (On/Off, MoveToLevel, etc.); action type selector (call device API endpoint, publish event, run worker, set hub data)
- [ ] **Inferred device type** — when a project's hub data keys match a known pattern (e.g. keys include `temperature` → suggest `temperature_sensor`; keys include `on_off` → suggest `on_off_plug`), pre-fill `matter_device_type` in the UI
- [ ] **Multi-device projects** — for projects with multiple linked devices (multi-node), expose each device as a separate endpoint; `matter_endpoint_per_device: true` in project config
- [ ] **Matter device scenes** — support Matter Scenes cluster for on_off_plug and lighting endpoints; map ESPai event types to scene IDs
