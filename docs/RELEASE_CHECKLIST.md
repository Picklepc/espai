# ESPAI Release Checklist

Run this checklist top-to-bottom before tagging a release.
Check every box or document why it was skipped.

---

## 1. Version and Packaging

- [ ] `VERSION` file matches the intended tag (e.g. `0.1.0`)
- [ ] `hub/backend/__init__.py` imports `VERSION` correctly — `__version__` should equal the file contents
- [ ] `GET /api/status` response includes `"version": "<semver>"`
- [ ] `espai.spec` datas list includes: `hub/frontend/`, `recipes/`, `workers/`, `cards/`, `design/`, `agents/`, `policies/`, `schemas/`, `agent-bench/`, `VERSION`
- [ ] `requirements.txt` lists `zeroconf` (uncommented), `fastapi`, `uvicorn`, `pydantic`
- [ ] `requirements-bundle.txt` lists `pystray`, `Pillow`, `pywinpty`/`ptyprocess`, `paho-mqtt`, `zeroconf`, `pyinstaller`
- [ ] `requirements-bundle.txt` is up-to-date with all runtime deps for PyInstaller
- [ ] `.github/workflows/release.yml` — confirm `on: push: tags: ['v*.*.*']` matches your intended tag format
- [ ] Pre-release flag fires correctly for tags containing `-` (e.g. `v0.1.0-beta`)

---

## 2. Security

- [ ] No hardcoded credentials anywhere in `hub/`, `firmware/`, `espai.py` — run grep and verify all matches are comments, env-var references, or documentation template strings (known false positives: `projects.py` lines showing `$env:ESPAI_WIFI_SSID = "MyNetwork"` as example usage in platformio.ini and ESPAI.md templates — these are intentional)
- [ ] `.env` and any `*.private.yaml` files are in `.gitignore` and NOT committed
- [ ] `custom/` theme folder is in `.gitignore` (check `design/themes/.gitignore`)
- [ ] `ESPAI_CORS_ORIGINS` defaults to `"*"` (acceptable for LAN-only), but document this in the release notes
- [ ] FastAPI `/docs` endpoint is disabled when `DEBUG=0` — `docs_url=None` in production path of `main.py`
- [ ] Worker runner checks `quarantine: true` before executing any job (`hub/backend/workers/runner.py`)
- [ ] Agent Bench: agents cannot touch `secrets/`, `*.private.yaml`, `data/`, `backups/`, `firmware/seed/`, `firmware/provision/` — verify `allowed_paths` guard in `agent_bench.py`
- [ ] OTA push requires pairing token + SHA-256 header + board compatibility check — verify all three gates in `hub/backend/routers/ota.py`
- [ ] Recipe export strips private overlays — `share_policy: public` removes `_private_overlay` keys; confirm in `hub/backend/routers/recipes.py`
- [ ] Project file API blocks path traversal (`..`) and private files — verify guard in projects.py file write/delete handlers
- [ ] Worker/card/recipe management API has bad-slug guard — verify regex check in `reg_files.py`
- [ ] Backup restore uses column allowlist — no arbitrary SQL injection through `POST /api/admin/restore`

---

## 3. Database Integrity

- [ ] `init_db()` in `db.py` includes all tables: `devices`, `projects`, `ota_log`, `jobs`, `events`, `pairing_tokens`, `rules`, `agent_tasks`, `agent_task_messages`, `agent_runs`, `agent_artifacts`, `agent_reviews`, `agent_permissions`, `project_nodes`, `project_data`, `project_data_cache`, `local_services`, `hub_settings`
- [ ] `_migrate()` runs additive `ALTER TABLE` for: `projects.updated`, `projects.slug`, `ota_log.git_sha`, `agent_tasks.context_type/context_id/parent_task_id`
- [ ] All migrations are additive — no destructive schema changes
- [ ] `python -c "from hub.backend.db import init_db; init_db()"` against a fresh DB file produces no errors and all tables are present

---

## 4. API Correctness

- [ ] `GET /api/status` — returns `version`, `uptime`, `device_count`
- [ ] `GET /api/devices/` — lists registered nodes
- [ ] `POST /api/devices/manual` — adds device by IP
- [ ] `PATCH /api/projects/{id}/rename` — HTTP 200; `updated` column written without error
- [ ] `GET /api/projects/{id}/files/` — lists project files
- [ ] `GET /api/recipes/{name}/export` — strips private keys for `share_policy: public`
- [ ] `GET /api/recipes/{name}/validate` — returns validation result
- [ ] `GET /api/ota/catalog` — lists firmware entries
- [ ] `POST /api/ota/push` — validates pairing, board match, and SHA-256 before pushing
- [ ] `GET /api/admin/backup` — returns a valid SQLite snapshot
- [ ] `GET /api/meta` — returns capabilities list and endpoint map
- [ ] `GET /api/cards/{name}/preview` — returns HTML; 404 for unknown card
- [ ] `POST /api/workers/{name}/test` — sandboxed run, returns stdout/stderr/outputs
- [ ] WebSocket `/api/ws` — connects and receives broadcast events

---

## 5. Frontend / UI

- [ ] All `<button>`, `<input type="…">`, status dots, and badge elements have `data-tip="…"` — spot-check Fleet, Projects, OTA, Workers, Design views
- [ ] No `title="…"` attributes remain — they should be `data-tip` instead
- [ ] `#appTip` tooltip shows after 400 ms hover, disappears on mouseout/scroll/click
- [ ] Fleet view: device cards show correct online/offline dot, last-seen time, and flash button
- [ ] Projects view: project cards show topology badge, node count, app-type indicator
- [ ] OTA view: Backup and Restore buttons present; catalog shows label (not raw filename)
- [ ] Design view: theme grid shows official/custom badges; Activate and Delete buttons work
- [ ] Agent Bench: task list shows context badge and thread toggle for grouped follow-ups
- [ ] Worker quarantine auto-lift modal appears after agent task approval on a quarantined worker
- [ ] Code editor: `.bin` files are non-clickable; files >512 KB show non-clickable indicator
- [ ] Diff view Accept/Reject: per-file checkboxes default checked; revert sends all paths as `reject_paths`

---

## 6. Simulator Smoke Test

Run these against the fake nodes before tagging.

```bash
# Start fake ESP32 node
python simulators/fake-node/fake_node.py --port 8001

# Start fake BMS node  
python simulators/fake-bms/fake_bms.py --port 8002

# Start hub
python espai.py serve
```

- [ ] Hub starts without import errors or uncaught exceptions in the first 10 s
- [ ] Fake node appears in Fleet after subnet scan or manual IP add
- [ ] Pairing flow completes (initiate token → confirm on device portal → device marked paired)
- [ ] `GET /api/status` returns `"version": "0.1.0"`
- [ ] Worker test harness: run `opencv-motion-tagger` test with a sample image path; job completes with status `done`
- [ ] Recipe validate: `GET /api/recipes/example-bms/validate` returns no errors
- [ ] Theme switch: change active theme in Design view; dashboard CSS variables update without page reload
- [ ] Project create → rename → file create → file edit → file delete cycle completes without errors
- [ ] Backup download produces a non-empty `.sqlite` file

---

## 7. Packaging Smoke Test (PyInstaller + Installer)

- [ ] `pyinstaller espai.spec --noconfirm` completes without errors
- [ ] `dist\espai\espai.exe` (no args) — tray icon appears, no terminal window
- [ ] `dist\espai\espai.exe serve` — hub starts from an existing terminal (windowed exe still prints to existing console)
- [ ] Right-click tray → **Open Dashboard** → browser opens to `http://localhost:7888/`
- [ ] Right-click tray → **Open Logs** → new PowerShell window tails `data/espai-hub.log` live
- [ ] Right-click tray → **Stop Hub** → icon turns gray, Stop/Restart grayed out, Start becomes active
- [ ] Right-click tray → **Start at Login** → checked state persists across tray restarts (check `HKCU\...\Run`)
- [ ] First-run scaffold copies content packs to `~/Documents/ESPAI/` on first launch (check for `~/Documents/ESPAI/data/.espai-initialized`)
- [ ] `dist\espai\` directory does not contain `.env`, `*.private.yaml`, or any development credentials
- [ ] `iscc /DMyAppVersion=0.1.0 installer\espai.iss` produces `installer-output\ESPAI-Setup-0.1.0.exe`
- [ ] Installer runs without elevation; installs to `%LOCALAPPDATA%\Programs\ESPAI`
- [ ] Start Menu shortcut launches tray (no terminal window)
- [ ] Uninstaller removes files and cleans up the autostart registry key

---

## 8. GitHub Actions

- [ ] Push a tag locally to a test branch; confirm `release.yml` triggers
- [ ] Both `build-windows` and `build-linux` jobs pass
- [ ] Release artifacts `ESPAI-Setup-{version}.exe` and `ESPAI-{version}-x86_64.AppImage` are attached
- [ ] Pre-release flag is set for `-beta` / `-rc` tags; release flag for clean semver tags

---

## 9. Known Open TODOs (not blocking v0.1.0)

Document these in the release notes so users are not surprised:

- ESP32 OTA binary receive and apply is a 501 placeholder — firmware must be flashed via USB for now
- Docker sidecar worker runner is not implemented — workers run as native subprocesses only
- Caddy/mDNS project routing is not wired up — `Open App` falls back to device IP
- Git-branch rollback for OTA firmware is not implemented
- Cross-domain path inheritance for agent tasks is not implemented
- Linux AppImage tested only in CI (ubuntu-latest); behavior on non-Debian distros should be verified manually before promoting a release as broadly supported
- Theme selector card is not yet implemented

---

## Sign-off

| Check | Initials | Notes |
|---|---|---|
| Code + security review | | |
| DB migration dry-run | | |
| API smoke test | | |
| UI smoke test | | |
| Packaging smoke test | | |
| Release notes written | | |
| Tag pushed and CI green | | |
