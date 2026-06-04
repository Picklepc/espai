# ESPAI Release Checklist

This checklist is **reusable** — run it for every release. Before starting:

1. **Reset all boxes** — uncheck every `[x]` and remove any `✓` notes from the previous release.
2. **Update the checklist itself** — add items for features shipped since the last release, and remove items for anything deprecated or deleted. The checklist should always reflect the current surface area of the product; a stale item that can never pass is worse than no item.
3. Then run the checklist top-to-bottom, checking boxes and documenting skipped items.

The checklist as it appears in the repo reflects the **most recently completed release** — checked items are what was verified for that release, not the current state.

---

## 0. Pre-release checklist prep (always first)

- [ ] Reset all `[x]` → `[ ]` and remove `✓` notes from the previous release
- [ ] Add checklist items for new features merged since the last release:
  - New API routers → add endpoint rows to Section 4
  - New UI views or interactive elements → add spot-check items to Section 5
  - New security gates → add rows to Section 2
  - New Docker capabilities → add rows to Section 8
  - New packaging steps → add rows to Section 7 or 9
- [ ] Remove checklist items for deprecated or deleted features — a stale item that can never be checked is worse than no item
- [ ] Update version strings throughout this file (Sections 1, 6, 7, 8e, 9, Sign-off)

---

## 1. Version and Packaging

- [ ] `VERSION` file matches the intended tag — `0.2.9`
- [ ] `hub/backend/__init__.py` imports `VERSION` correctly — reads dynamically from `VERSION` file
- [ ] `GET /api/status` returns `version`, `uptime`, `device_count`
- [ ] `espai.spec` datas: `hub/frontend/`, `recipes/`, `workers/`, `cards/`, `design/`, `agents/`, `agent-bench/`, `policies/`, `schemas/`, `VERSION`
- [ ] `requirements.txt` has `zeroconf`, `fastapi`, `uvicorn`, `pydantic`
- [ ] `requirements-bundle.txt` has `pystray`, `Pillow`, `pywinpty`/`ptyprocess`, `paho-mqtt`, `zeroconf`, `pyinstaller`
- [ ] `.github/workflows/release.yml` triggers on `v*.*.*` tag push
- [ ] Pre-release flag fires for `-beta`/`-rc` tags (verify in next pre-release)

---

## 2. Security

- [ ] No hardcoded credentials — grep clean (known false positives: `tests/test_recipes.py` mock `api_key="sk-1234"`, `projects.py` env-var comment strings — intentional)
- [ ] `.env` and `*.private.yaml` in `.gitignore`, not committed
- [ ] `worker-requirements.txt` in `.gitignore` and `.dockerignore`
- [ ] `design/themes/custom/` in `.gitignore`
- [ ] `docs_url=None` in production (`DEBUG=0`)
- [ ] Worker runner checks `quarantine: true` before executing
- [ ] OTA push gates: SHA-256 computed server-side + board compatibility check
- [ ] Recipe export strips `_private_overlay` keys for `share_policy: public`
- [ ] Path traversal blocked on project file API
- [ ] Bad-slug guard on worker/card/recipe create (422)
- [ ] Backup restore uses column allowlist
- [ ] Integration project credential env vars — no API keys or device IPs in scaffolded source files
- [ ] `ESPAI_CORS_ORIGINS` defaults `"*"` — document in release notes (LAN-only, acceptable)

---

## 3. Database Integrity

- [ ] All 18 tables present in `init_db()`: `devices`, `projects`, `ota_log`, `jobs`, `events`, `pairing_tokens`, `rules`, `agent_tasks`, `agent_task_messages`, `agent_runs`, `agent_artifacts`, `agent_reviews`, `agent_permissions`, `project_nodes`, `project_data`, `project_data_cache`, `local_services`, `hub_settings`
- [ ] `_migrate()` additive — all `ALTER TABLE ADD COLUMN`, no destructive changes
- [ ] `device_type TEXT DEFAULT 'esp32'` column present in `projects` after `_migrate()`
- [ ] Fresh `init_db()` against empty DB — no errors, all tables created
- [ ] `_migrate()` against 0.2.8 DB — no errors, all expected columns present (manual test)
- **Note:** `_migrate()` has duplicate slug migration blocks — backfill in second block is unreachable if first block ran. Pre-existing issue, slug is backfilled lazily. Not blocking.

---

## 4. API Correctness

- [ ] `GET /api/status` → `version`, `uptime`, `device_count`
- [ ] `GET /api/devices/` → router registered
- [ ] `POST /api/devices/manual` → `devices.py`
- [ ] `PATCH /api/projects/{id}/rename` → `projects.py`
- [ ] `POST /api/projects/` with `device_type=integration` → creates `integration/` scaffold, no `firmware/` folder
- [ ] `POST /api/projects/` with `device_type=hybrid` → creates both `firmware/` and `integration/` scaffolds
- [ ] `GET /api/agent-bench/templates?device_type=esp32` → returns firmware-feature, hub-feature, port-to-hub, bug-fix; excludes api-integration
- [ ] `GET /api/agent-bench/templates?device_type=integration` → returns api-integration, hub-feature, bug-fix; excludes firmware-feature
- [ ] `GET /api/agent-bench/templates?device_type=hybrid` → returns all templates
- [ ] `GET /api/recipes/example-bms/validate` → `recipes.py`
- [ ] `GET /api/recipes/example-bms/export` → `recipes.py`
- [ ] `GET /api/ota/catalog` → `ota.py`
- [ ] `GET /api/admin/backup` → `admin.py`
- [ ] `GET /api/meta` → `main.py`
- [ ] `GET /api/cards/device-log/preview` → `cards.py`
- [ ] `GET /api/workers/` → router registered
- [ ] `GET /api/packages/` → `packages.py` router registered
- [ ] `POST /api/ota/push` — requires paired device + firmware (manual test)
- [ ] WebSocket `/api/ws` — requires running browser (manual test)

---

## 5. Frontend / UI

- [ ] All interactive elements have `data-tip` — spot-check: all HTML buttons have `data-tip`, all `el("button")` calls followed by `dataset.tip =`
- [ ] No `title="…"` attributes remain (iframe keeps `title=` for WCAG accessibility, also has `data-tip`)
- [ ] Modal footer buttons get `data-tip` via `_MODAL_BTN_TIPS` fallback map in `openModal`
- [ ] `#appTip` tooltip system wired globally
- [ ] New Project modal shows three-way type picker: ESP32 Node / API Integration / Hybrid Bridge
- [ ] New Project modal sends `device_type` to backend on create
- [ ] Project cards show device type badge (ESP32 / integration / hybrid) with tooltip
- [ ] Agent task modal template list updates when project selection changes (filtered by project `device_type`)
- [ ] Mobile portrait: hamburger no longer overlaps page title — title starts to the right of button
- [ ] Mobile portrait: floating hamburger opens nav, overlay closes it — manual test
- [ ] Mobile logo: transparent-background PNG renders on all themes — manual test
- [ ] Favicon shows in browser tab — manual test
- [ ] Fleet, Projects, OTA, Design, Agent Bench views render without JS errors — manual test
- [ ] Worker quarantine auto-lift modal — manual test
- [ ] Diff view Accept/Reject checkboxes — manual test

---

## 6. Simulator Smoke Test

```bash
python simulators/fake-node/fake_node.py --port 8001
python simulators/fake-bms/fake_bms.py --port 8002
python espai.py serve
```

- [ ] Hub starts clean, no import errors in first 10 s
- [ ] Fake node appears in Fleet after scan or manual IP add
- [ ] Pairing flow: initiate → confirm → device marked paired
- [ ] `GET /api/status` returns `"version": "0.2.9"`
- [ ] Recipe validate: `example-bms` returns no errors
- [ ] Theme switch: CSS vars update without page reload
- [ ] Project create (ESP32 type) → `firmware/` folder present, `integration/` absent
- [ ] Project create (Integration type) → `integration/poller.py` present, `firmware/` absent
- [ ] Project rename → file CRUD cycle
- [ ] Backup download produces non-empty `.sqlite`

---

## 7. Packaging Smoke Test (Windows)

- [ ] `pyinstaller espai.spec --noconfirm` — no errors
- [ ] `dist\espai\espai.exe` (no args) — tray appears, no terminal window
- [ ] Tray → Open Dashboard → browser opens `http://localhost:7888/`
- [ ] Tray → Open Logs → PowerShell tails `~/Documents/ESPAI/data/espai-hub.log`
- [ ] Tray → Stop/Start/Restart — icon state updates correctly
- [ ] Tray → Start at Login — registry key persists
- [ ] First-run scaffold populates `~/Documents/ESPAI/` (check `.espai-initialized`)
- [ ] `iscc /DMyAppVersion=0.2.9 installer\espai.iss` → `ESPAI-Setup-0.2.9.exe`
- [ ] Installer: no elevation, installs to `%LOCALAPPDATA%\Programs\ESPAI`
- [ ] Uninstaller cleans up registry key

---

## 8. Docker

### 8a. Image Build

- [ ] `hub/docker-entrypoint.sh` is present and executable (`chmod +x` in Dockerfile)
- [ ] `ENTRYPOINT ["/docker-entrypoint.sh"]` wired in `hub/Dockerfile`
- [ ] All three CI variants defined in release.yml matrix: `latest`, `workers`, `slim`
- [ ] `docker/build-push-action` targets `linux/amd64,linux/arm64`
- [ ] `docker compose build` completes on ARM64 host (CI)

### 8b. Runtime

- [ ] `docker compose up -d` starts container, health check passes within `start_period: 20s`
- [ ] `GET /api/status` reachable at `http://<router-ip>:7888/api/status`
- [ ] Response contains `"version": "0.2.9"`
- [ ] mDNS discovery finds ESP32 nodes (`network_mode: host`)
- [ ] Data persists across `docker compose restart` (SSD bind-mounts: `data/`, `projects/`, `firmware-catalog/`)
- [ ] `claude --version` works inside container (`latest` and `workers` variants)
- [ ] Web terminal gives bash shell inside container

### 8c. Worker Dependency Preloading

- [ ] Entrypoint handles `ESPAI_PREINSTALL` env var (space/comma list) before uvicorn
- [ ] Entrypoint handles mounted `/preload/requirements.txt` before uvicorn
- [ ] No preload configured → starts cleanly (only runs pip if var/file present)
- [ ] `worker-requirements.txt` excluded from image via `.dockerignore`
- [ ] **Env-var preload:** end-to-end runtime test on router
- [ ] **File-based preload:** end-to-end runtime test on router

### 8d. Image Variants

| Tag | `INSTALL_CLAUDE` | `INSTALL_WORKER_DEPS` | Expected size |
|---|---|---|---|
| `:latest` | true | false | ~500 MB |
| `:workers` | true | true | ~900 MB |
| `:slim` | false | false | ~350 MB |

- [ ] `:latest` — `claude --version` works; `import cv2` fails (expected)
- [ ] `:workers` — `import cv2` succeeds; `claude --version` works
- [ ] `:slim` — `claude --version` not found; no worker dep packages

### 8e. Registry

- [ ] `docker pull ghcr.io/picklepc/espai:0.2.9` succeeds on amd64
- [ ] `docker pull ghcr.io/picklepc/espai:0.2.9` succeeds on arm64 (verify on router)
- [ ] Floating tags updated: `:latest`, `:workers`, `:slim`
- [ ] Version-pinned tags present: `:0.2.9`, `:0.2.9-workers`, `:0.2.9-slim`, `:0.2`, `:0.2-workers`, `:0.2-slim`

---

## 9. GitHub Actions CI

- [ ] `build-windows` job passes
- [ ] `build-linux` job passes
- [ ] `build-docker` job passes — multi-arch image pushed to `ghcr.io`
- [ ] Release artifacts attached: `ESPAI-Setup-0.2.9.exe` + `ESPAI-0.2.9-x86_64.AppImage`
- [ ] GitHub Release page created with correct tag and release notes auto-generated from git log

---

## 10. Known Open Items (not blocking 0.2.9)

Document in release notes:

- Firmware CI builds not wired — no pre-built `.bin` artifacts in release yet (see PROJECT_TASK_LIST.md Milestone 19)
- Docker sidecar worker runner not implemented — subprocesses only
- Caddy/mDNS project routing not wired — `Open App` falls back to device IP
- Git-branch rollback for OTA not implemented
- Cross-domain path inheritance for agent tasks not implemented
- Linux AppImage only CI-tested on ubuntu-latest x86_64
- Theme selector card not yet implemented
- `_migrate()` duplicate slug migration block — backfill unreachable on upgrade path (cosmetic, not data-loss)
- M20 follow-ons: "Link service to project" button and background service health polling not yet implemented
- M3 sleep/wake: 5 s awake window before deep sleep is a fixed constant — should be NVS-configurable in a future release

---

## Sign-off

| Check | Result | Notes |
|---|---|---|
| Code + security review | pending | |
| DB migration dry-run (0.2.8 → 0.2.9) | pending | Manual test on router |
| API smoke test | pending | |
| UI smoke test | pending | Manual |
| Windows packaging | pending | CI |
| Docker (ARM64) | pending | Deploy to router after CI |
| Tag pushed | pending | `v0.2.9` |
| CI green | pending | Check Actions |
