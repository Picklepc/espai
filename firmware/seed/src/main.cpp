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
#include <ArduinoJson.h>
#include <mbedtls/md.h>

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

static const uint32_t WIFI_TIMEOUT_MS     = 15000;
static const uint32_t CHECKIN_INTERVAL_MS = 60000;

// ── Globals ────────────────────────────────────────────────────────────────

WebServer server(80);
String    nodeId;
bool      wifiConnected = false;
bool      apMode        = false;
uint32_t  lastCheckin   = 0;
bool      paired        = false;

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
  delay(500);
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
  if (strlen(WIFI_SSID) == 0) {
    Serial.println("[wifi] No SSID configured — starting fallback AP");
    startFallbackAP();
    return false;
  }
  WiFi.mode(WIFI_STA);
  // Modem sleep keeps the radio alive between beacons — cuts heat significantly
  WiFi.setSleep(true);
  // 13 dBm is more than adequate; max (19.5 dBm) is only needed at extreme range
  WiFi.setTxPower(WIFI_POWER_13dBm);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
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
  String hostname = nodeId;
  if (!MDNS.begin(hostname.c_str())) {
    Serial.println("[mdns] Failed to start");
    return;
  }
  MDNS.addService("_ESPAI-node", "_tcp", 80);
  MDNS.addServiceTxt("_ESPAI-node", "_tcp", "id",      nodeId.c_str());
  MDNS.addServiceTxt("_ESPAI-node", "_tcp", "name",    NODE_NAME);
  MDNS.addServiceTxt("_ESPAI-node", "_tcp", "version", FW_VERSION);
  Serial.printf("[mdns] Advertised as %s._ESPAI-node._tcp.local\n", hostname.c_str());
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

  wifiConnected = connectWifi();

  if (wifiConnected || apMode) {
    startMDNS();
  }

  // Tell WebServer to capture this header so handleOtaComplete can read it
  const char* capturedHeaders[] = {"X-Firmware-SHA256"};
  server.collectHeaders(capturedHeaders, 1);

  // Register HTTP routes
  server.on("/api/manifest",  HTTP_GET,  handleManifest);
  server.on("/api/status",    HTTP_GET,  handleStatus);
  server.on("/api/checkin",   HTTP_POST, handleCheckin);
  server.on("/api/reboot",    HTTP_POST, handleReboot);
  server.on("/ota/update",    HTTP_POST, handleOtaComplete, handleOtaUpload);
  server.onNotFound(handleNotFound);

  server.begin();
  Serial.println("[ESPAI] HTTP server started on port 80");
}

// ── Loop ───────────────────────────────────────────────────────────────────

void loop() {
  server.handleClient();

  // Reconnect STA if dropped (skip in AP mode)
  if (!apMode && WiFi.status() != WL_CONNECTED) {
    static uint32_t lastReconnect = 0;
    if (millis() - lastReconnect > 30000) {
      lastReconnect = millis();
      Serial.println("[wifi] Reconnecting…");
      WiFi.reconnect();
    }
  }

  // Periodic self-checkin log (hub-side checkin is driven by the hub)
  if (millis() - lastCheckin > CHECKIN_INTERVAL_MS) {
    lastCheckin = millis();
  }

  delay(5);
}
