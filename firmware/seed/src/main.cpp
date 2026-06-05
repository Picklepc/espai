/**
 * ESPAI Seed Firmware
 *
 * Provides the minimal node API that the ESPAI hub expects:
 *   GET  /api/manifest  — node identity and capabilities
 *   GET  /api/status    — runtime status (uptime, heap, etc.)
 *   POST /api/checkin   — hub-initiated checkin acknowledgement
 *   POST /api/reboot    — controlled reboot (paired hub only)
 *   POST /ota/update    — OTA binary upload (multipart/form-data)
 *
 * Node ID is derived from the MAC address (hashed) — never exposes raw MAC.
 * Wi-Fi credentials come from build flags. No credentials are hardcoded here.
 *
 * Fallback AP mode activates if STA connection fails after WIFI_TIMEOUT_MS.
 * mDNS advertises _ESPAI-node._tcp.local so the hub can discover this node.
 *
 * Build flags (set in platformio.ini or via environment):
 *   -D WIFI_SSID=\"MyNetwork\"
 *   -D WIFI_PASS=\"mypassword\"
 *   -D NODE_NAME=\"my-node\"
 *   -D FW_VERSION=\"0.1.0\"
 */

#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include <ESPmDNS.h>
#include <Update.h>
#include <Preferences.h>
#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <mbedtls/md.h>
#include <esp_sleep.h>

// ── Build-flag defaults ────────────────────────────────────────────────────

#ifndef WIFI_SSID
#define WIFI_SSID ""
#endif

#ifndef WIFI_PASS
#define WIFI_PASS ""
#endif

#ifndef NODE_NAME
#define NODE_NAME "ESPAI-node"
#endif

#ifndef FW_VERSION
#define FW_VERSION "0.1.0"
#endif

#ifndef BOARD_ID
#define BOARD_ID "esp32"
#endif

// SLEEP_INTERVAL_S — seconds between deep-sleep wake-ups.
// Set to 0 (default) to disable deep sleep and run a continuous web server.
// Set via platformio.ini: -D SLEEP_INTERVAL_S=60
#ifndef SLEEP_INTERVAL_S
#define SLEEP_INTERVAL_S 0
#endif

static const uint32_t WIFI_TIMEOUT_MS     = 15000;
static const uint32_t CHECKIN_INTERVAL_MS = 60000;

// ── Globals ────────────────────────────────────────────────────────────────

WebServer server(80);
String    nodeId;
bool      wifiConnected = false;
bool      apMode        = false;
uint32_t  lastCheckin   = 0;
bool      paired        = false;
int       sleepIntervalS = SLEEP_INTERVAL_S;  // updated from hub checkin response
int       awakeWindowS   = 5;                 // seconds to stay awake after checkin; read from NVS then updated from hub

// OTA state — reset on each new upload
static bool                  g_otaError  = false;
static mbedtls_md_context_t  g_shaCtx;
static bool                  g_shaActive = false;

// ── Node ID — derived from MAC, not the raw MAC ─────────────────────────────

String deriveNodeId() {
  uint8_t mac[6];
  WiFi.macAddress(mac);
  uint8_t hash[32];
  mbedtls_md_context_t ctx;
  mbedtls_md_init(&ctx);
  mbedtls_md_setup(&ctx, mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), 0);
  mbedtls_md_starts(&ctx);
  mbedtls_md_update(&ctx, mac, 6);
  mbedtls_md_finish(&ctx, hash);
  mbedtls_md_free(&ctx);
  String id = "node-";
  for (int i = 0; i < 6; i++) {
    if (hash[i] < 0x10) id += "0";
    id += String(hash[i], HEX);
  }
  return id;
}

// ── API helpers ────────────────────────────────────────────────────────────

void sendJson(int code, JsonDocument& doc) {
  String body;
  serializeJson(doc, body);
  server.send(code, "application/json", body);
}

void sendError(int code, const char* msg) {
  JsonDocument doc;
  doc["error"] = msg;
  sendJson(code, doc);
}

// ── Route handlers ─────────────────────────────────────────────────────────

void handleManifest() {
  JsonDocument doc;
  doc["schema"]     = "ESPAI.device.v1";
  doc["id"]         = nodeId;
  doc["name"]       = NODE_NAME;
  doc["board"]      = BOARD_ID;
  doc["fw_version"] = FW_VERSION;
  doc["paired"]     = paired;

  JsonObject caps = doc["capabilities"].to<JsonObject>();
  caps["ota"]    = true;
  caps["sleep"]  = true;
  caps["camera"] = false;
  caps["ble"]    = false;

  // Advertise registered config keys so hub can build the settings schema
  if (_configCount > 0) {
    JsonArray cfg = doc["config"].to<JsonArray>();
    for (int i = 0; i < _configCount; i++) {
      JsonObject entry = cfg.add<JsonObject>();
      entry["key"]         = _configRegistry[i].key;
      entry["type"]        = _configRegistry[i].type;
      entry["default"]     = _configRegistry[i].default_val;
      entry["description"] = _configRegistry[i].description;
      if (_configRegistry[i].flags == ESPAI_CONFIG_SECRET)
        entry["secret"] = true;
    }
  }

  sendJson(200, doc);
}

void handleStatus() {
  JsonDocument doc;
  doc["id"]        = nodeId;
  doc["uptime_s"]  = millis() / 1000;
  doc["heap_free"] = ESP.getFreeHeap();
  doc["wifi_rssi"] = wifiConnected ? WiFi.RSSI() : 0;
  doc["ip"]        = wifiConnected ? WiFi.localIP().toString() : WiFi.softAPIP().toString();
  doc["ap_mode"]   = apMode;
  doc["paired"]    = paired;
  sendJson(200, doc);
}

void handleCheckin() {
  lastCheckin = millis();
  JsonDocument doc;
  doc["status"] = "ok";
  doc["id"]     = nodeId;
  doc["paired"] = paired;
  doc["sleep_interval_s"] = sleepIntervalS;
  sendJson(200, doc);
}

void handleReboot() {
  JsonDocument doc;
  doc["status"] = "rebooting";
  sendJson(200, doc);
  delay(200);
  ESP.restart();
}

// OTA — receives multipart/form-data POST from the hub (two-handler pattern)
void handleOtaComplete() {
  if (g_otaError) {
    sendError(500, "OTA write failed — see serial");
    return;
  }

  // Verify SHA-256 if the hub sent the header
  if (g_shaActive) {
    uint8_t computed[32];
    mbedtls_md_finish(&g_shaCtx, computed);
    mbedtls_md_free(&g_shaCtx);
    g_shaActive = false;

    String expected = server.header("X-Firmware-SHA256");
    if (expected.length() == 64) {
      char hexBuf[65];
      for (int i = 0; i < 32; i++) sprintf(hexBuf + i * 2, "%02x", computed[i]);
      hexBuf[64] = '\0';
      if (expected != String(hexBuf)) {
        Serial.printf("[OTA] SHA-256 mismatch — rejecting\n");
        Serial.printf("[OTA]   expected: %s\n", expected.c_str());
        Serial.printf("[OTA]   computed: %s\n", hexBuf);
        sendError(400, "SHA-256 mismatch — firmware rejected");
        return;
      }
      Serial.printf("[OTA] SHA-256 verified OK\n");
    }
  }

  JsonDocument doc;
  doc["status"] = "ok";
  sendJson(200, doc);
  // Flush TCP buffer and give hub time to read the response before we reset.
  // Without this, ESP.restart() tears down the stack before the hub reads "ok".
  server.client().flush();
  delay(1500);
  ESP.restart();
}

void handleOtaUpload() {
  HTTPUpload& upload = server.upload();

  if (upload.status == UPLOAD_FILE_START) {
    g_otaError = false;
    Serial.printf("[OTA] Start: %s\n", upload.filename.c_str());

    // Init incremental SHA-256 over received bytes
    mbedtls_md_init(&g_shaCtx);
    mbedtls_md_setup(&g_shaCtx, mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), 0);
    mbedtls_md_starts(&g_shaCtx);
    g_shaActive = true;

    if (!Update.begin(UPDATE_SIZE_UNKNOWN)) {
      Update.printError(Serial);
      g_otaError = true;
    }

  } else if (upload.status == UPLOAD_FILE_WRITE) {
    if (!g_otaError) {
      mbedtls_md_update(&g_shaCtx, upload.buf, upload.currentSize);
      if (Update.write(upload.buf, upload.currentSize) != upload.currentSize) {
        Update.printError(Serial);
        g_otaError = true;
      }
    }

  } else if (upload.status == UPLOAD_FILE_END) {
    if (!g_otaError && !Update.end(true)) {
      Update.printError(Serial);
      g_otaError = true;
    }
    Serial.printf("[OTA] %u bytes written, error=%s\n", upload.totalSize, g_otaError ? "yes" : "no");
  }
}

void handleNotFound() {
  sendError(404, "Not found");
}

// ── Hub self-checkin (node → hub) ─────────────────────────────────────────
// Fire-and-forget: posts identity to hub and optionally reads back sleep_interval_s.
// Returns the hub-recommended sleep interval (0 = keep awake), or -1 on failure.
int hubCheckin(const String& hubUrl) {
  if (!wifiConnected) return -1;
#ifdef HUB_URL
  HTTPClient http;
  String url = hubUrl + "/api/devices/checkin";
  http.begin(url);
  http.addHeader("Content-Type", "application/json");
  String body = "{\"id\":\"" + nodeId + "\",\"name\":\"" NODE_NAME "\",\"board\":\"" BOARD_ID
              + "\",\"fw_version\":\"" FW_VERSION "\",\"ip\":\""
              + WiFi.localIP().toString() + "\",\"sleep_interval_s\":"
              + String(sleepIntervalS) + ",\"awake_window_s\":"
              + String(awakeWindowS) + "}";
  int code = http.POST(body);
  if (code == 200) {
    JsonDocument resp;
    deserializeJson(resp, http.getString());
    // Hub can override both values; persist to NVS so they survive deep sleep
    Preferences prefs;
    prefs.begin("espai", false);
    if (!resp["sleep_interval_s"].isNull()) {
      sleepIntervalS = resp["sleep_interval_s"].as<int>();
      prefs.putInt("sleep_s", sleepIntervalS);
    }
    if (!resp["awake_window_s"].isNull()) {
      awakeWindowS = resp["awake_window_s"].as<int>();
      prefs.putInt("awake_s", awakeWindowS);
    }
    prefs.end();
  }
  http.end();
  return sleepIntervalS;
#else
  return 0;
#endif
}

// ── ESPAI Media Upload ─────────────────────────────────────────────────────
// Upload a binary buffer to the hub media store as multipart/form-data.
// Returns HTTP status code (201 = success, -1 = no HUB_URL / WiFi down).
//
// Usage:
//   camera_fb_t* fb = esp_camera_fb_get();
//   int code = espai_upload_jpeg(String(HUB_URL), "my-project", fb->buf, fb->len);
//   esp_camera_fb_return(fb);
//
// The hub stores the file and returns { "file_id": "...", "url": "..." }.
// Specify device_id and tags as empty strings to omit them.
int espai_upload_jpeg(const String& hubUrl, const String& projectId,
                      const uint8_t* buf, size_t len,
                      const String& deviceId = "", const String& tags = "") {
  if (!wifiConnected || len == 0) return -1;
#ifdef HUB_URL
  const String boundary = "espai" + String(millis());
  String prefix = "--" + boundary + "\r\n"
    "Content-Disposition: form-data; name=\"file\"; filename=\"capture.jpg\"\r\n"
    "Content-Type: image/jpeg\r\n\r\n";
  String suffix = "\r\n";
  if (!deviceId.isEmpty()) {
    suffix += "--" + boundary + "\r\nContent-Disposition: form-data; name=\"device_id\"\r\n\r\n"
           + deviceId + "\r\n";
  }
  if (!tags.isEmpty()) {
    suffix += "--" + boundary + "\r\nContent-Disposition: form-data; name=\"tags\"\r\n\r\n"
           + tags + "\r\n";
  }
  suffix += "--" + boundary + "--\r\n";

  WiFiClient client;
  HTTPClient http;
  http.begin(client, hubUrl + "/api/projects/" + projectId + "/media");
  http.addHeader("Content-Type", "multipart/form-data; boundary=" + boundary);
  http.addHeader("Content-Length", String(prefix.length() + len + suffix.length()));

  // Stream the multipart body: prefix + binary + suffix
  // HTTPClient::sendRequest with stream is the cleanest way on ESP32 Arduino
  size_t totalLen = prefix.length() + len + suffix.length();
  uint8_t* bodyBuf = (uint8_t*)malloc(totalLen);
  if (!bodyBuf) { http.end(); return -1; }
  memcpy(bodyBuf,                       prefix.c_str(), prefix.length());
  memcpy(bodyBuf + prefix.length(),     buf,            len);
  memcpy(bodyBuf + prefix.length() + len, suffix.c_str(), suffix.length());
  int code = http.POST(bodyBuf, totalLen);
  free(bodyBuf);
  http.end();
  return code;  // 201 = created
#else
  return -1;
#endif
}

// ── ESPAI NVS Config Registration ─────────────────────────────────────────
// Allows firmware code to declare configurable NVS keys with type, default,
// description, and an on-change callback. The hub reads the schema from
// /api/manifest and writes values via the set_config command.

#define ESPAI_CONFIG_OPERATIONAL  0   // readable and writable from hub (default)
#define ESPAI_CONFIG_SECRET       1   // hub can write but NEVER read back

// Platform-managed keys the config API must never expose or accept writes for.
static const char* _CONFIG_BLOCKLIST[] = {
    "sta_ssid", "sta_pass", "sleep_s", "awake_s", "awake_w", nullptr
};

static bool _isBlockedConfigKey(const char* key) {
    for (int i = 0; _CONFIG_BLOCKLIST[i] != nullptr; i++) {
        if (strcmp(key, _CONFIG_BLOCKLIST[i]) == 0) return true;
    }
    // Block any key prefixed "espai_"
    return strncmp(key, "espai_", 6) == 0;
}

typedef void (*espai_config_cb_t)(const char* new_value);

struct _EspaiConfigEntry {
    char      key[16];
    char      type[8];
    char      default_val[32];
    char      description[64];
    espai_config_cb_t cb;
    uint8_t   flags;
};

static _EspaiConfigEntry _configRegistry[24];
static int               _configCount = 0;

// Register a configurable NVS setting. Call once per key in setup() before
// connectWifi(). The callback fires at boot AND on every set_config command.
void espai_register_config(
    const char*       key,
    const char*       type,
    const char*       default_val,
    const char*       description,
    espai_config_cb_t on_change = nullptr,
    uint8_t           flags     = ESPAI_CONFIG_OPERATIONAL
) {
    if (_configCount >= 24 || !key || _isBlockedConfigKey(key)) return;
    _EspaiConfigEntry& e = _configRegistry[_configCount++];
    strncpy(e.key,         key,         sizeof(e.key)         - 1);
    strncpy(e.type,        type,        sizeof(e.type)        - 1);
    strncpy(e.default_val, default_val, sizeof(e.default_val) - 1);
    strncpy(e.description, description, sizeof(e.description) - 1);
    e.key[sizeof(e.key)-1]               = '\0';
    e.type[sizeof(e.type)-1]             = '\0';
    e.default_val[sizeof(e.default_val)-1] = '\0';
    e.description[sizeof(e.description)-1] = '\0';
    e.cb    = on_change;
    e.flags = flags;
}

// Called once in setup(). Reads each registered key from NVS, writes the
// compiled-in default if absent, then fires the callback so the app applies
// the value without any extra boot-time code paths.
void espai_init_config() {
    if (_configCount == 0) return;
    Preferences prefs;
    prefs.begin("espai", false);
    for (int i = 0; i < _configCount; i++) {
        _EspaiConfigEntry& e = _configRegistry[i];
        String val = prefs.getString(e.key, e.default_val);
        // Write default to NVS if the key was absent
        if (!prefs.isKey(e.key)) prefs.putString(e.key, e.default_val);
        if (e.cb) e.cb(val.c_str());
        Serial.printf("[cfg] %s = %s%s\n", e.key, val.c_str(),
                      e.flags == ESPAI_CONFIG_SECRET ? " (secret)" : "");
    }
    prefs.end();
}

// ── GET /api/config — operational keys only ───────────────────────────────
void handleConfig() {
    JsonDocument doc;
    Preferences prefs;
    prefs.begin("espai", true);
    for (int i = 0; i < _configCount; i++) {
        _EspaiConfigEntry& e = _configRegistry[i];
        if (e.flags == ESPAI_CONFIG_SECRET) continue;  // never expose secrets
        doc[e.key] = prefs.getString(e.key, e.default_val);
    }
    prefs.end();
    sendJson(200, doc);
}

// ── ESPAI Command Poll ─────────────────────────────────────────────────────
// User-supplied callback invoked for each pending command the hub sends.
// Return true if the command was handled, false to fall through to built-ins.
typedef bool (*espai_cmd_fn_t)(const String& cmdId, const String& cmdType,
                               const JsonObject& payload);
static espai_cmd_fn_t _userCmdHandler = nullptr;

void espai_register_cmd_handler(espai_cmd_fn_t handler) {
  _userCmdHandler = handler;
}

// Poll the hub for pending commands and dispatch them.
// Call this from loop() — it self-throttles to once every POLL_INTERVAL_MS.
#ifndef ESPAI_CMD_POLL_MS
#define ESPAI_CMD_POLL_MS 2000
#endif

void espai_poll_commands(const String& hubUrl) {
  if (!wifiConnected) return;
#ifdef HUB_URL
  static uint32_t lastPoll = 0;
  if (millis() - lastPoll < ESPAI_CMD_POLL_MS) return;
  lastPoll = millis();

  HTTPClient http;
  http.begin(hubUrl + "/api/devices/" + nodeId + "/commands/pending");
  int code = http.GET();
  if (code != 200) { http.end(); return; }

  JsonDocument doc;
  if (deserializeJson(doc, http.getString()) != DeserializationError::Ok) {
    http.end(); return;
  }
  http.end();

  JsonArray cmds = doc["commands"].as<JsonArray>();
  for (JsonObject cmd : cmds) {
    String cmdId   = cmd["id"]           | "";
    String cmdType = cmd["command_type"] | "";
    JsonObject pl  = cmd["payload"]      | JsonObject();

    bool handled = false;

    // User handler first
    if (_userCmdHandler) handled = _userCmdHandler(cmdId, cmdType, pl);

    // Built-in handlers
    if (!handled) {
      if (cmdType == "reboot") {
        Serial.println("[cmd] Reboot command received");
        delay(500);
        ESP.restart();

      } else if (cmdType == "set_config") {
        const char* key = pl["key"] | "";
        const char* val = pl["value"] | "";
        if (key[0]) {
          if (_isBlockedConfigKey(key)) {
            // Blocklisted — NACK (handled=false so ack sends ok:false)
            Serial.printf("[cmd] set_config BLOCKED: %s\n", key);
          } else {
            Preferences prefs;
            prefs.begin("espai", false);
            prefs.putString(key, val);
            prefs.end();
            Serial.printf("[cmd] set_config: %s = %s\n", key,
                          // Don't log secret values
                          ([&](){
                            for(int i=0;i<_configCount;i++)
                              if(strcmp(_configRegistry[i].key,key)==0 &&
                                 _configRegistry[i].flags==ESPAI_CONFIG_SECRET)
                                return "***";
                            return val;
                          })());
            // Fire registered callback immediately — no reboot required
            for (int i = 0; i < _configCount; i++) {
              if (strcmp(_configRegistry[i].key, key) == 0) {
                if (_configRegistry[i].cb) _configRegistry[i].cb(val);
                break;
              }
            }
            handled = true;
          }
        } else {
          handled = true;
        }

      } else if (cmdType == "run_ota_check") {
        hubCheckin(hubUrl);
        handled = true;
      }
    }

    // Ack the command
    if (!cmdId.isEmpty()) {
      HTTPClient ack;
      String ackUrl = hubUrl + "/api/devices/" + nodeId + "/commands/" + cmdId + "/ack";
      ack.begin(ackUrl);
      ack.addHeader("Content-Type", "application/json");
      ack.POST(handled ? "{\"result\":{\"ok\":true}}" : "{\"result\":{\"ok\":false}}");
      ack.end();
    }
  }
#endif
}

// ── Deep sleep helper ──────────────────────────────────────────────────────
// Enters deep sleep for `seconds`. GPIO16/RTC0 must be wired to RST for wake-up
// on standard ESP32. ESP32-S3/C3 use the built-in RTC timer — no wire needed.
void enterDeepSleep(int seconds) {
  Serial.printf("[sleep] Entering deep sleep for %d s\n", seconds);
  Serial.flush();
  WiFi.disconnect(true);
  WiFi.mode(WIFI_OFF);
  esp_sleep_enable_timer_wakeup((uint64_t)seconds * 1000000ULL);
  esp_deep_sleep_start();
}

// ── Wi-Fi setup ────────────────────────────────────────────────────────────

void startFallbackAP() {
  String apSsid = "ESPAI-" + nodeId.substring(5, 11);
  WiFi.mode(WIFI_AP);
  WiFi.softAP(apSsid.c_str());
  apMode = true;
  Serial.printf("[wifi] Fallback AP: %s  IP: %s\n",
                apSsid.c_str(), WiFi.softAPIP().toString().c_str());
}

bool connectWifi() {
  // Prefer NVS credentials saved by provision firmware (same namespace/keys).
  // Falls back to build-flag values, then AP mode if neither is available.
  Preferences prefs;
  prefs.begin("espai", true);
  String ssid = prefs.getString("sta_ssid", WIFI_SSID);
  String pass = prefs.getString("sta_pass", WIFI_PASS);
  prefs.end();

  if (ssid.isEmpty()) {
    Serial.println("[wifi] No SSID — starting fallback AP");
    startFallbackAP();
    return false;
  }
  Serial.printf("[wifi] Using SSID from %s\n", ssid == String(WIFI_SSID) ? "build flags" : "NVS");

  WiFi.mode(WIFI_STA);
  // Modem sleep keeps the radio alive between beacons — cuts heat significantly
  WiFi.setSleep(true);
  // 13 dBm is more than adequate; max (19.5 dBm) is only needed at extreme range
  WiFi.setTxPower(WIFI_POWER_13dBm);
  WiFi.begin(ssid.c_str(), pass.c_str());
  Serial.printf("[wifi] Connecting to %s", WIFI_SSID);
  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED && (millis() - start) < WIFI_TIMEOUT_MS) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("[wifi] Connected  IP: %s\n", WiFi.localIP().toString().c_str());
    return true;
  }
  Serial.println("[wifi] Connection failed — starting fallback AP");
  startFallbackAP();
  return false;
}

// ── mDNS ──────────────────────────────────────────────────────────────────

void startMDNS() {
  // Use NODE_NAME as the mDNS hostname so the device is reachable at
  // http://NODE_NAME.local/ — human-readable and stable across reboots.
  // The unique nodeId is still exposed as a TXT record for fleet management.
  String hostname = String(NODE_NAME);
  if (!MDNS.begin(hostname.c_str())) {
    Serial.println("[mdns] Failed to start");
    return;
  }
  MDNS.addService("_ESPAI-node", "_tcp", 80);
  MDNS.addServiceTxt("_ESPAI-node", "_tcp", "id",      nodeId.c_str());
  MDNS.addServiceTxt("_ESPAI-node", "_tcp", "name",    NODE_NAME);
  MDNS.addServiceTxt("_ESPAI-node", "_tcp", "version", FW_VERSION);
  Serial.printf("[mdns] Advertised as http://%s.local/\n", hostname.c_str());
}

// ── Setup ──────────────────────────────────────────────────────────────────

void setup() {
  Serial.begin(115200);
  delay(100);
  Serial.println("\n[ESPAI] ESPAI seed firmware " FW_VERSION);

  // Derive node ID before Wi-Fi connects (MAC is available immediately)
  WiFi.mode(WIFI_STA);
  nodeId = deriveNodeId();
  Serial.printf("[ESPAI] Node ID: %s\n", nodeId.c_str());

  // ── Register app-specific config keys here (before connectWifi) ──────────
  // Example — operational key: hub can read and write, value applied live
  //   espai_register_config("rotation", "int", "0",
  //     "Display rotation: 0=0deg 1=90deg 2=180deg 3=270deg",
  //     [](const char* v){ tft.setRotation(atoi(v)); });
  // Example — injected secret: hub can write but never read back
  //   espai_register_config("api_key", "string", "",
  //     "External API key -- write-only from hub",
  //     [](const char* v){ myService.setKey(v); },
  //     ESPAI_CONFIG_SECRET);

  // Read sleep config from NVS (set by hub checkin; survives deep sleep)
  {
    Preferences prefs;
    prefs.begin("espai", true);
    sleepIntervalS = prefs.getInt("sleep_s", SLEEP_INTERVAL_S);
    awakeWindowS   = prefs.getInt("awake_s", 5);
    prefs.end();
  }

  // Apply all registered config keys from NVS (fires callbacks at boot)
  espai_init_config();

  wifiConnected = connectWifi();

  if (wifiConnected || apMode) {
    startMDNS();
  }

  // Tell WebServer to capture this header so handleOtaComplete can read it
  const char* capturedHeaders[] = {"X-Firmware-SHA256"};
  server.collectHeaders(capturedHeaders, 1);

  // Register HTTP routes
  server.on("/api/manifest",  HTTP_GET,  handleManifest);
  server.on("/api/config",    HTTP_GET,  handleConfig);
  server.on("/api/status",    HTTP_GET,  handleStatus);
  server.on("/api/checkin",   HTTP_POST, handleCheckin);
  server.on("/api/reboot",    HTTP_POST, handleReboot);
  server.on("/ota/update",    HTTP_POST, handleOtaComplete, handleOtaUpload);
  server.onNotFound(handleNotFound);

  server.begin();
  Serial.println("[ESPAI] HTTP server started on port 80");

  // Hub checkin on boot — posts identity and retrieves hub-side sleep interval
#ifdef HUB_URL
  if (wifiConnected) {
    hubCheckin(String(HUB_URL));
    Serial.printf("[ESPAI] Hub checkin done. sleep_interval_s=%d\n", sleepIntervalS);
  }
#endif
}

// ── Loop ───────────────────────────────────────────────────────────────────

void loop() {
  server.handleClient();

  // Poll hub for pending commands (throttled by ESPAI_CMD_POLL_MS, default 2s)
#ifdef HUB_URL
  if (!apMode) espai_poll_commands(String(HUB_URL));
#endif

  // Reconnect STA if dropped (skip in AP mode)
  if (!apMode && WiFi.status() != WL_CONNECTED) {
    static uint32_t lastReconnect = 0;
    if (millis() - lastReconnect > 30000) {
      lastReconnect = millis();
      Serial.println("[wifi] Reconnecting…");
      WiFi.reconnect();
    }
  }

  // Deep sleep mode: serve HTTP for a short window so OTA / commands can land,
  // then sleep for the configured interval.
  if (sleepIntervalS > 0) {
    // Stay awake for the configured window (default 5 s) to handle OTA / commands
    if (millis() > (uint32_t)(awakeWindowS * 1000)) {
      enterDeepSleep(sleepIntervalS);
    }
  } else {
    // Awake-always: periodic self-checkin timestamp
    if (millis() - lastCheckin > CHECKIN_INTERVAL_MS) {
      lastCheckin = millis();
    }
  }

  delay(5);
}
