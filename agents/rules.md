# ESPAI Agent Rules

Explicit do / do-not list included in every agent prompt.
For full context see `docs/DESIGN_SPEC.md`.

---

## DO

- **Read `.agent/` rules** before starting any task.
- **Keep firmware lean.** Measure/actuate on the ESP32; store/process on the hub.
- **Use the hub data store** (`POST /api/projects/{id}/data`) for any project that
  needs to persist readings — do not invent ad-hoc storage.
- **Build reusable primitives** (cards, recipes, workers, shared firmware modules)
  when a one-off would do the same job.
- **Run `pio run`** after every firmware change. Fix all errors before committing.
- **Test workers** via `POST /api/workers/{name}/test` before marking them ready.
- **Write `data-tip="…"` on every UI element** — buttons, badges, status dots, tags.
- **Use `\"backslash-escaped\"` quotes** in `platformio.ini` `build_flags` strings.
- **Implement AP fallback** in all project firmware — `ESPAI-{id}` hotspot on WiFi fail.
- **Make hub checkins fire-and-forget** — never block the firmware loop on the hub.
- **Commit with descriptive messages** — list every file changed and why.
- **Flag anything requiring human review** before promotion.

---

## DO NOT

- **Never touch `firmware/seed/` or `firmware/provision/`** — these are protected
  platform templates. Edit the project copy in `projects/{id}/firmware/` instead.
- **Never hardcode secrets** — no WiFi credentials, API keys, MAC addresses, GPS
  coords, or personal network names anywhere in source files.
- **Never read or write**: `.env`, `secrets/`, `*.private.yaml`, `*.private.json`,
  `data/`, `backups/`, `captures/private/`.
- **Never mark a worker trusted/unquarantined** — quarantine is lifted by a human.
- **Never bypass safety checks** — no `--force`, `--no-verify`, or similar flags
  unless the task explicitly permits it and the reason is documented.
- **Never modify pairing state, OTA targets, or release promotion** — human-only.
- **Never push to non-dev devices** from an agent task.
- **Never use `title=""` on UI elements** — use `data-tip="…"` (see CLAUDE.md).
- **Never silently install dependencies** — only with `espai.py install-deps` and
  explicit user approval.
- **Never commit code that doesn't compile** — run `pio run` first.
- **Never speculate about closed paths** — if a path is not in `allowed_paths`,
  ask rather than assume.
- **Never attempt USB flashing** — in Docker/router deployments USB is not
  available. The only firmware delivery path is OTA via the hub.
- **Never `pip install` directly** — use `ESPAI_PREINSTALL` or the
  `worker-requirements.txt` preload mechanism; packages installed directly
  into the container layer are lost on restart.

---

## Firmware Pattern Reference

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

## Hub Data Push Pattern (firmware → hub)

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

## Web App Read Pattern (hub → browser)

```javascript
// Works from hub (/app/{slug}/) or direct device access
const HUB = location.pathname.startsWith("/app/");
const slug = HUB ? location.pathname.split("/")[2] : null;
const HUB_API = HUB ? `` : `http://espai.local:7888`;
// Loads instantly from cache — device can be asleep
const { devices } = await fetch(`${HUB_API}/api/projects/${PROJECT_ID}/data/latest`)
    .then(r => r.json());
```
