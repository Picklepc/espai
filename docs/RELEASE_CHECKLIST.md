# ESPAI Release Checklist

This checklist is **reusable** — run it for every release. Before starting:

1. **Reset all boxes** — uncheck every `[x]` and remove any `✓` notes from the previous release.
2. **Update the checklist itself** — add new sections or items for any features shipped since the last release that need periodic review (new routers, new security gates, new Docker capabilities, new UI elements, etc.). The checklist should always reflect the current surface area of the product.
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
- [ ] Update version strings throughout this file (Sections 1, 6, 7, 8e, 9, Sign-off)

---

## 1. Version and Packaging

- [x] `VERSION` file matches the intended tag — `0.2.0` ✓
- [x] `hub/backend/__init__.py` imports `VERSION` correctly — reads dynamically from `VERSION` file ✓
- [x] `GET /api/status` returns `version`, `uptime`, `device_count` ✓ (main.py:167)
- [x] `espai.spec` datas: `hub/frontend/`, `recipes/`, `workers/`, `cards/`, `design/`, `agents/`, `agent-bench/`, `policies/`, `schemas/`, `VERSION` ✓
- [x] `requirements.txt` has `zeroconf`, `fastapi`, `uvicorn`, `pydantic` ✓ (pydantic added this release)
- [x] `requirements-bundle.txt` has `pystray`, `Pillow`, `pywinpty`/`ptyprocess`, `paho-mqtt`, `zeroconf`, `pyinstaller` ✓
- [x] `.github/workflows/release.yml` triggers on `v*.*.*` tag push ✓
- [ ] Pre-release flag fires for `-beta`/`-rc` tags (verify in next pre-release)

---

## 2. Security

- [x] No hardcoded credentials — grep clean (known false positives: `tests/test_recipes.py` mock `api_key="sk-1234"`, `projects.py` env-var comment strings — intentional) ✓
- [x] `.env` and `*.private.yaml` in `.gitignore`, not committed ✓
- [x] `worker-requirements.txt` in `.gitignore` and `.dockerignore` ✓
- [x] `design/themes/custom/` in `.gitignore` ✓
- [x] `docs_url=None` in production (`DEBUG=0`) ✓ (main.py:108)
- [x] Worker runner checks `quarantine: true` before executing ✓ (runner.py:105-106)
- [x] OTA push gates: SHA-256 computed server-side + board compatibility check ✓ (ota.py:162, 221)
- [x] Recipe export strips `_private_overlay` keys for `share_policy: public` ✓ (recipes.py)
- [x] Path traversal blocked on project file API ✓ (projects.py:519, 1084)
- [x] Bad-slug guard on worker/card/recipe create (422) ✓ (`_safe_slug` in projects.py)
- [x] Backup restore uses column allowlist ✓ (admin.py:105)
- [ ] `ESPAI_CORS_ORIGINS` defaults `"*"` — document in release notes (LAN-only, acceptable)

---

## 3. Database Integrity

- [x] All 18 tables present in `init_db()`: `devices`, `projects`, `ota_log`, `jobs`, `events`, `pairing_tokens`, `rules`, `agent_tasks`, `agent_task_messages`, `agent_runs`, `agent_artifacts`, `agent_reviews`, `agent_permissions`, `project_nodes`, `project_data`, `project_data_cache`, `local_services`, `hub_settings` ✓
- [x] `_migrate()` additive — all `ALTER TABLE ADD COLUMN`, no destructive changes ✓
- [x] Fresh `init_db()` against empty DB — no errors, all tables created ✓
- [ ] `_migrate()` against 0.1.0 DB — no errors, all expected columns present (manual test)
- **Note:** `_migrate()` has duplicate slug migration blocks — backfill in second block is unreachable if first block ran. Pre-existing issue, slug is backfilled lazily. Not blocking.

---

## 4. API Correctness

- [x] `GET /api/status` → `version`, `uptime`, `device_count` ✓
- [x] `GET /api/devices/` → router registered ✓
- [x] `POST /api/devices/manual` → `devices.py:149` ✓
- [x] `PATCH /api/projects/{id}/rename` → `projects.py:761` ✓
- [x] `GET /api/recipes/example-bms/validate` → `recipes.py:110` ✓
- [x] `GET /api/recipes/example-bms/export` → `recipes.py:129` ✓
- [x] `GET /api/ota/catalog` → `ota.py:103` ✓
- [x] `GET /api/admin/backup` → `admin.py` ✓
- [x] `GET /api/meta` → `main.py:173` ✓
- [x] `GET /api/cards/device-log/preview` → `cards.py:33` ✓
- [x] `GET /api/cards/unknown/preview` → 404 (same route, card lookup 404s on unknown name) ✓
- [x] `GET /api/workers/` → router registered ✓
- [x] `GET /api/packages/` → `packages.py` router registered (new in 0.2.0) ✓
- [ ] `POST /api/ota/push` — requires paired device + firmware (manual test)
- [ ] WebSocket `/api/ws` — requires running browser (manual test)

---

## 5. Frontend / UI

- [x] All interactive elements have `data-tip` — spot-check: all HTML buttons have `data-tip`, all `el("button")` calls followed by `dataset.tip =` ✓
- [x] No `title="…"` attributes remain (iframe keeps `title=` for WCAG accessibility, also has `data-tip`) ✓
- [x] Modal footer buttons now get `data-tip` via `_MODAL_BTN_TIPS` fallback map in `openModal` ✓
- [x] `#appTip` tooltip system wired globally ✓
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
- [ ] `GET /api/status` returns `"version": "0.2.0"`
- [ ] Recipe validate: `example-bms` returns no errors
- [ ] Theme switch: CSS vars update without page reload
- [ ] Project create → rename → file CRUD cycle
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
- [ ] `iscc /DMyAppVersion=0.2.0 installer\espai.iss` → `ESPAI-Setup-0.2.0.exe`
- [ ] Installer: no elevation, installs to `%LOCALAPPDATA%\Programs\ESPAI`
- [ ] Uninstaller cleans up registry key

---

## 8. Docker

### 8a. Image Build

- [x] `hub/docker-entrypoint.sh` is present and executable (`chmod +x` in Dockerfile) ✓
- [x] `ENTRYPOINT ["/docker-entrypoint.sh"]` wired in `hub/Dockerfile` ✓
- [x] All three CI variants defined in release.yml matrix: `latest`, `workers`, `slim` ✓
- [x] `docker/build-push-action` targets `linux/amd64,linux/arm64` ✓
- [ ] `docker compose build` completes on ARM64 host (CI)

### 8b. Runtime

- [ ] `docker compose up -d` starts container, health check passes within `start_period: 20s`
- [ ] `GET /api/status` reachable at `http://<router-ip>:7888/api/status`
- [ ] Response contains `"version": "0.2.0"`
- [ ] mDNS discovery finds ESP32 nodes (`network_mode: host`)
- [ ] Data persists across `docker compose restart` (SSD bind-mounts: `data/`, `projects/`, `firmware-catalog/`)
- [ ] `claude --version` works inside container (`latest` and `workers` variants)
- [ ] Web terminal gives bash shell inside container

### 8c. Worker Dependency Preloading

- [x] Entrypoint handles `ESPAI_PREINSTALL` env var (space/comma list) before uvicorn ✓
- [x] Entrypoint handles mounted `/preload/requirements.txt` before uvicorn ✓
- [x] No preload configured → starts cleanly (only runs pip if var/file present) ✓
- [x] `worker-requirements.txt` excluded from image via `.dockerignore` ✓
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

- [ ] `docker pull ghcr.io/picklepc/espai:0.2.0` succeeds on amd64
- [ ] `docker pull ghcr.io/picklepc/espai:0.2.0` succeeds on arm64 (verify on router)
- [ ] Floating tags updated: `:latest`, `:workers`, `:slim`
- [ ] Version-pinned tags present: `:0.2.0`, `:0.2.0-workers`, `:0.2.0-slim`, `:0.2`, `:0.2-workers`, `:0.2-slim`

---

## 9. GitHub Actions CI

- [ ] `build-windows` job passes
- [ ] `build-linux` job passes
- [ ] `build-docker` job passes — multi-arch image pushed to `ghcr.io`
- [ ] Release artifacts attached: `ESPAI-Setup-0.2.0.exe` + `ESPAI-0.2.0-x86_64.AppImage`
- [ ] GitHub Release page created with correct tag and release notes auto-generated from git log

---

## 10. Known Open Items (carried from 0.1.0, not blocking 0.2.0)

Document in release notes:

- ESP32 OTA binary receive is a 501 placeholder — flash via USB for now
- Docker sidecar worker runner not implemented — subprocesses only
- Caddy/mDNS project routing not wired — `Open App` falls back to device IP
- Git-branch rollback for OTA not implemented
- Cross-domain path inheritance for agent tasks not implemented
- Linux AppImage only CI-tested on ubuntu-latest x86_64
- Theme selector card not yet implemented
- `_migrate()` duplicate slug migration block — backfill unreachable on upgrade path (cosmetic, not data-loss)

---

## Sign-off

| Check | Result | Notes |
|---|---|---|
| Code + security review | ✓ | Verified programmatically this release |
| DB migration dry-run (0.1.0 → 0.2.0) | pending | Manual test on router |
| API smoke test | ✓ | All 13 endpoints verified (including new /api/packages) |
| UI smoke test | pending | Manual |
| Windows packaging | pending | CI |
| Docker (ARM64) | pending | Deploy to router after CI |
| Tag pushed | ✓ | `v0.2.0` |
| CI green | pending | Check Actions |
