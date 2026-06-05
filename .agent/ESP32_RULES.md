# ESP32 Rules

- PlatformIO first.
- Arduino framework acceptable for MVP.
- Minimal fallback UI only.
- Compact JSON.
- Safety-critical loops must work without Wi-Fi.
- Support offline operation.
- Support sleep/wake where practical.
- Unique node ID (SHA-256 of MAC — never expose raw MAC).
- Capability manifest (`GET /api/manifest`).
- OTA paired/authenticated.
- Direct realtime links allowed for RC/video.

## Required patterns (firmware/seed/src/main.cpp)

Use these helpers — never reimplement them from scratch.

| Helper | Use |
|--------|-----|
| `hubCheckin(hubUrl)` | POST device identity to hub on boot; reads back `sleep_interval_s` and `awake_window_s`; persists to NVS |
| `espai_poll_commands(hubUrl)` | Call from `loop()` — self-throttles via `ESPAI_CMD_POLL_MS` (default 2 s); dispatches `reboot`, `set_config`, `run_ota_check`; user callback via `espai_register_cmd_handler()` |
| `espai_register_cmd_handler(fn)` | Register callback for custom command types before built-in dispatch |
| `espai_register_config(key, type, default, desc, cb, flags)` | Declare a configurable NVS key; call in `setup()` before `connectWifi()`. `flags`: `ESPAI_CONFIG_OPERATIONAL` (default) or `ESPAI_CONFIG_SECRET` |
| `espai_init_config()` | Call once in `setup()` after all `espai_register_config()` calls; reads NVS, writes defaults if absent, fires callbacks |
| `espai_upload_jpeg(hubUrl, projectId, buf, len, deviceId, tags)` | Upload JPEG buffer to hub media store; returns HTTP status code |
| `enterDeepSleep(seconds)` | Disconnect WiFi, set RTC timer, call `esp_deep_sleep_start()` |
| `startFallbackAP()` | Start `ESPAI-{node_id_suffix}` hotspot on STA failure |
| `connectWifi()` | Read NVS credentials first, fall back to build flags, then AP mode |

## NVS config key blocklist

**Do not register** the following keys via `espai_register_config()` — they are platform-managed
and will be silently dropped or blocked:

- `sta_ssid`, `sta_pass` — WiFi credentials (provision firmware path only)
- `sleep_s`, `awake_s`, `awake_w` — sleep config (checkin response path only)
- Any key with the prefix `espai_` — reserved for platform internals

The hub's config API returns HTTP 403 for any read or write targeting these keys.

## Firmware hardening (required for any ported or new project)

- **Watchdog**: `esp_task_wdt_init(30, true)` in `setup()`; `esp_task_wdt_reset()` first line of `loop()`
- **Heap guard**: log `ESP.getFreeHeap()` on boot; `ESP.restart()` if heap drops below 20 KB
- **No blocking delays**: replace `delay(N > 100)` with `millis()`-based non-blocking timers
- **WiFi reconnect**: call `WiFi.reconnect()` every 30 s if STA drops — never `ESP.restart()` on disconnect
- **Credentials**: always inject via `${sysenv.ESPAI_WIFI_SSID}` / `${sysenv.ESPAI_WIFI_PASS}` in `platformio.ini` build_flags — never hardcode

## Build flag injection template

```ini
build_flags =
    -D WIFI_SSID=\"${sysenv.ESPAI_WIFI_SSID}\"
    -D WIFI_PASS=\"${sysenv.ESPAI_WIFI_PASS}\"
    -D HUB_URL=\"http://espai.local:7888\"
    -D HUB_PROJECT_ID=\"<project_id>\"
    -D NODE_NAME=\"<node_name>\"
    -D FW_VERSION=\"1.0.0\"
```
