# ESPAI Agent Rules

Explicit do / do-not list included in every agent prompt.
For full context see `docs/DESIGN_SPEC.md`.

**Check the project's `device_type` first** (in `.ESPAI-project.json` or the
task context banner). Rules marked `(ESP32)` apply only to `esp32` and `hybrid`
projects. Rules marked `(Integration)` apply only to `integration` and `hybrid`
projects. Unmarked rules apply to all project types.

---

## DO

- **Read `.agent/` rules** before starting any task.
- **Use the hub data store** (`POST /api/projects/{id}/data`) for any project that
  needs to persist readings — do not invent ad-hoc storage.
- **Build reusable primitives** (cards, recipes, workers, shared firmware modules)
  when a one-off would do the same job.
- **Test workers** via `POST /api/workers/{name}/test` before marking them ready.
- **Write `data-tip="…"` on every UI element** — buttons, badges, status dots, tags.
- **Commit with descriptive messages** — list every file changed and why.
- **Flag anything requiring human review** before promotion.

### ESP32 projects (`device_type: esp32` or `hybrid`)

- **Keep firmware lean.** Measure/actuate on the ESP32; store/process on the hub.
- **Run `pio run`** after every firmware change. Fix all errors before committing.
- **Import the build to the OTA catalog** after a successful compile — call
  `POST /api/projects/{project_id}/import-build` so the binary appears in the
  OTA menu and can be flashed without a manual import step.
- **Use `\"backslash-escaped\"` quotes** in `platformio.ini` `build_flags` strings.
- **Implement AP fallback** in all project firmware — `ESPAI-{id}` hotspot on WiFi fail.
- **Make hub checkins fire-and-forget** — never block the firmware loop on the hub.

### Integration projects (`device_type: integration` or `hybrid`)

- **Read credentials from environment variables only** — `os.environ.get("KEY")`
  in worker code; document required vars in `integration/config.yaml`.
- **Always handle network errors gracefully** — wrap every external HTTP/MQTT call
  in try/except; log errors to stderr and return a partial result, never crash.
- **Use `mode: service` in worker.yaml** for persistent connections (MQTT,
  WebSocket, BLE) — the hub supervisor will restart on crash.
- **Never block the hub event loop** — workers run in subprocesses; long polling
  is fine inside a worker but never inside a FastAPI route.
- **Scope workers to one device or service** — one worker per integration target
  so they can be tested and quarantined independently.
- **Use project-scoped workers for project-specific customisation** — global
  workers in `workers/` are shared templates; every project that references them
  runs the same code. To customise a worker for one project without affecting
  others, copy it to `projects/{project_id}/workers/{name}/`. The job runner
  checks there first and falls back to the global worker automatically.

---

## DO NOT

- **Never touch `firmware/seed/` or `firmware/provision/`** — these are protected
  platform templates. Edit the project copy in `projects/{id}/firmware/` instead.
- **Never hardcode secrets** — no WiFi credentials, API keys, MAC addresses, GPS
  coords, personal network names, or device IPs anywhere in source files.
- **Never read or write**: `.env`, `secrets/`, `*.private.yaml`, `*.private.json`,
  `data/`, `backups/`, `captures/private/`.
- **Never delete or bypass git history on workers** — changes are tracked automatically; use `POST /api/workers/{name}/git/rollback` to revert, never `git reset --hard`.
- **Never bypass safety checks** — no `--force`, `--no-verify`, or similar flags
  unless the task explicitly permits it and the reason is documented.
- **Never modify pairing state, OTA targets, or release promotion** — human-only.
- **Never push to non-dev devices** from an agent task.
- **Never use `title=""` on UI elements** — use `data-tip="…"` (see CLAUDE.md).
- **Never silently install dependencies** — only with `espai.py install-deps` and
  explicit user approval.
- **Never speculate about closed paths** — if a path is not in `allowed_paths`,
  ask rather than assume.

### ESP32 projects only

- **Never commit code that doesn't compile** — run `pio run` first.
- **Never attempt USB flashing** — in Docker/router deployments USB is not
  available. The only firmware delivery path is OTA via the hub.
- **Never `pip install` directly** — use `ESPAI_PREINSTALL` or the
  `worker-requirements.txt` preload mechanism; packages installed directly
  into the container layer are lost on restart.

### Integration projects only

- **Never write ESP32 firmware** for an integration project — there is no custom
  firmware; all logic lives in hub workers.
- **Never run `pio run`** — PlatformIO is irrelevant for integration projects.
- **Never hardcode device IPs or base URLs** — always read from
  `INTEGRATION_BASE_URL` or equivalent env var so the integration survives a
  device IP change.

---

## Firmware Pattern Reference (ESP32 projects only)

```cpp
// WiFi — use NVS stored creds when no build flag provided
#ifndef WIFI_SSID
#define WIFI_SSID ""
#endif
if (strlen(WIFI_SSID) > 0)
    WiFi.begin(WIFI_SSID, WIFI_PASS);
else
    WiFi.begin();

// AP fallback
void startFallbackAP() {
    WiFi.mode(WIFI_AP);
    WiFi.softAP(("ESPAI-" + nodeId.substring(5,11)).c_str());
    apMode = true;
}

// Hub checkin — fire and forget
void checkin() {
    if (WiFi.status() != WL_CONNECTED) return;
    HTTPClient http;
    http.begin("http://espai.local:7888/api/devices/" + nodeId + "/checkin");
    http.POST("{}");
    http.end();
}
```

```ini
; platformio.ini — CORRECT string quoting
build_flags =
  -D NODE_NAME=\"my-device\"
  -D FW_VERSION=\"1.0.0\"
  -D HUB_PROJECT_ID=\"c9ac1baa9ba4\"
```

---

## Hub Data Push Pattern — firmware → hub (ESP32 projects only)

```cpp
void pushToHub(float temperature, float humidity, int batteryPct) {
    if (WiFi.status() != WL_CONNECTED) return;
    HTTPClient http;
    http.begin("http://espai.local:7888/api/projects/" + String(HUB_PROJECT_ID) + "/data");
    http.addHeader("Content-Type", "application/json");
    http.addHeader("X-Device-ID", nodeId);
    String body = "{\"temperature\":" + String(temperature,1) +
                  ",\"humidity\":"    + String(humidity,1)    +
                  ",\"battery_pct\":" + String(batteryPct)    + "}";
    http.POST(body);
    http.end();
}
```

## Web App Read Pattern (hub → browser, all project types)

```javascript
// Works from hub (/app/{slug}/) or direct device access
const HUB = location.pathname.startsWith("/app/");
const slug = HUB ? location.pathname.split("/")[2] : null;
const HUB_API = HUB ? `` : `http://espai.local:7888`;
// Loads instantly from cache — device can be asleep
const { devices } = await fetch(`${HUB_API}/api/projects/${PROJECT_ID}/data/latest`)
    .then(r => r.json());
```

## Integration Worker Pattern (integration projects only)

```python
# integration/poller.py — one-shot worker, runs on a schedule
import os, sys, json

BASE_URL = os.environ.get("INTEGRATION_BASE_URL", "http://device-ip")
API_KEY  = os.environ.get("INTEGRATION_API_KEY", "")

def run(inputs: dict) -> dict:
    try:
        import urllib.request
        req = urllib.request.Request(
            f"{BASE_URL}/api/status",
            headers={"Authorization": API_KEY},
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read())
    except Exception as exc:
        print(f"fetch failed: {exc}", file=sys.stderr)
        return {"error": str(exc), "events": []}

    push_to_hub(data)
    return {"state": data, "events": [{"type": "device.update", "data": data}]}

if __name__ == "__main__":
    inp = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    print(json.dumps(run(inp)))
```

```yaml
# integration/worker.yaml — persistent MQTT/WebSocket connection
name: my-integration
mode: service          # hub supervisor keeps this running; restart on crash
permissions:
  network: true
env_required:
  - INTEGRATION_BASE_URL
  - INTEGRATION_API_KEY
```

## Registry Primitives — when to use what

Every hub-side artefact lives in one of four places. Choose based on what it does, not what it contains.

| Primitive | Location | Use when… |
|---|---|---|
| **Worker** | `workers/{name}/` or `projects/{id}/workers/{name}/` | Code needs to *run* — data processing, API polling, event generation, image/audio analysis, persistent MQTT/WebSocket connections |
| **Card** | `cards/{name}/` | A sensor reading or device state needs a *visual component* — gauge, chart, position map, log viewer, media gallery. Each card has a `preview.html` for testing with simulated data. |
| **Recipe** | `recipes/{name}/` | A multi-step device + hub *workflow* needs to be documented, validated, and shared. Recipes describe *what* a project does; workers implement the logic. |
| **Project-scoped worker** | `projects/{id}/workers/{name}/` | Same as a worker, but only one project uses it. The job runner checks here first and falls back to the global `workers/` copy. |

### Decision tree

1. Does it need to **execute Python code**? → **Worker** (global if reusable, project-scoped if specific to one project)
2. Does it need to **display data visually** in the dashboard? → **Card**
3. Does it describe a **repeatable device + hub workflow** for documentation or sharing? → **Recipe**
4. Could an existing card, recipe, or worker serve the purpose with small config changes? → **Reuse it** — the registry summary at the top of your prompt lists what is available.

### Important rules

- **Check the registry summary in your prompt before creating anything new** — it lists all existing cards, recipes, and workers. Duplicates waste tokens and confuse the hub.
- **Cards read from `/api/projects/{id}/data`** — they never contain business logic. Keep them purely visual.
- **Recipes validate against `schemas/recipe.schema.json`** — run `GET /api/recipes/{name}/validate` after creating one.
- **Workers expose a `run(inputs) → dict` function** — return `{"events": [...], ...}`. Never `sys.exit()` or `os._exit()` inside a worker.
- **Never quarantine** — quarantine was removed. Workers that need review use git rollback instead (`POST /api/workers/{name}/git/rollback`).

---

## Matter Bridge (M23 — hub-hosted, all project types)

The Matter bridge runs as a Node.js process managed by `hub/backend/matter_bridge.py`. Agents working on Matter tasks should understand the following constraints:

- **Never put Matter code on the ESP32** — the hub bridge handles all Matter protocol. The ESP32 continues using lightweight seed firmware and pushing hub data normally.
- **Matter config lives in `.ESPAI-project.json`** — edit `matter_enabled`, `matter_device_type`, `matter_state_map`, and `matter_command_actions`. Never hardcode device IDs or endpoint IDs.
- **Bridge HTTP API is on localhost:5580** — all Python interaction goes through `matter_bridge.py`, never by calling `bridge.mjs` directly.
- **Data push is the sync path** — `matter_state_map` translates hub data keys to Matter attributes automatically on every `POST /api/projects/{id}/data`. Do not write separate sync logic.
- **Commands route through `POST /api/matter/command`** — edit `matter_command_actions` in `.ESPAI-project.json` to add routing for a new Matter command. Do not add command-specific code to the bridge process.
- **Node.js is required** — check `matter_bridge.is_running()` before attempting Matter operations. If Node.js is absent, the bridge is disabled silently.
- **Fabric state is persistent** — `data/matter-storage/` holds commissioning keys. Never delete this directory; re-commissioning invalidates all paired ecosystems.

### Device type → default state map reference

| `matter_device_type` | Default `matter_state_map` keys |
|---|---|
| `on_off_plug` | `power_on`, `on`, `switch` → `on_off` |
| `dimmable_light` | `on` → `on_off`, `brightness` → `level` |
| `color_light` | `on` → `on_off`, `brightness` → `level`, `hue` → `hue`, `saturation` → `sat` |
| `temperature_sensor` | `temperature`, `temp` → `temperature` (hub °C × 100 = Matter int16) |
| `humidity_sensor` | `humidity`, `relative_humidity` → `humidity` (% × 100 = Matter uint16) |
| `occupancy_sensor` | `occupancy`, `motion`, `presence` → `occupancy` |
| `contact_sensor` | `contact`, `open` → `contact` |
