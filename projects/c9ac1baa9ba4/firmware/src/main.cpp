/**
 * Jingle Bells — ESPAI Project Firmware
 *
 * Blinks the built-in LED to the Jingle Bells tune.
 * Exposes CORS-enabled REST endpoints for web synchronization:
 *   POST /api/jingle/start  — begin LED blink sequence
 *   POST /api/jingle/stop   — stop sequence and extinguish LED
 *   GET  /api/jingle/state  — {playing, elapsed_ms, beat_index, start_ms}
 */

#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include <ESPmDNS.h>
#include <ArduinoJson.h>

#ifndef NODE_NAME
#define NODE_NAME "jingle-bells"
#endif
#ifndef FW_VERSION
#define FW_VERSION "0.1.0"
#endif
#ifndef WIFI_SSID
#define WIFI_SSID ""
#endif
#ifndef WIFI_PASS
#define WIFI_PASS ""
#endif
#ifndef BOARD_ID
#define BOARD_ID "esp32dev"
#endif

// XIAO ESP32S3 built-in user LED: GPIO 21, active LOW.
// If using a different board, set LED_PIN and swap LED_ON/LED_OFF.
#ifndef LED_PIN
#define LED_PIN 21
#endif
#define LED_ON  LOW
#define LED_OFF HIGH

static const uint32_t WIFI_TIMEOUT_MS  = 15000;
static const uint32_t BLINK_MS         = 150;    // LED flash duration per beat
static const uint32_t SONG_DURATION_MS = 17500;  // full loop length

WebServer server(80);

// ── Node ID (hashed MAC) ──────────────────────────────────────────────────
#include <mbedtls/md.h>
String deriveNodeId() {
  uint8_t mac[6], hash[32];
  WiFi.macAddress(mac);
  mbedtls_md_context_t ctx;
  mbedtls_md_init(&ctx);
  mbedtls_md_setup(&ctx, mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), 0);
  mbedtls_md_starts(&ctx);
  mbedtls_md_update(&ctx, mac, 6);
  mbedtls_md_finish(&ctx, hash);
  mbedtls_md_free(&ctx);
  String id = "node-";
  for (int i = 0; i < 6; i++) { if (hash[i] < 0x10) id += "0"; id += String(hash[i], HEX); }
  return id;
}

String nodeId;

// ── Jingle Bells beat table (ms from song start) ──────────────────────────
// Two full passes of the chorus at ~120 BPM.
// Must match the BEATS array in workers/public/index.html exactly.
static const uint32_t BEATS[] = {
  // Chorus pass 1 ——————————————————————————————
  // "Jingle bells, jingle bells,"
  0, 500, 1000, 1500,
  // "Jingle all the way,"
  2000, 2500, 2750, 3000,
  // "Oh, what fun it is to ride"
  4000, 4250, 4500, 4750, 5000, 5250, 5500,
  // "In a one-horse open sleigh!"
  6000, 6250, 6500, 7000, 7500,
  // Chorus pass 2 ——————————————————————————————
  // "Jingle bells, jingle bells,"
  8500, 9000, 9500, 10000,
  // "Jingle all the way,"
  10500, 11000, 11250, 11500,
  // "Oh, what fun it is to ride"
  12500, 12750, 13000, 13250, 13500, 13750, 14000,
  // "In a one-horse open sleigh!"
  14500, 14750, 15000, 15500, 16000,
};
static const uint32_t NUM_BEATS = sizeof(BEATS) / sizeof(BEATS[0]);

// ── Playback state ────────────────────────────────────────────────────────
struct PlayState {
  bool     playing    = false;
  uint32_t startMs    = 0;
  uint32_t cycleCount = 0;
  int      nextBeat   = 0;
  bool     ledActive  = false;
  uint32_t ledOnMs    = 0;
} state;

void jingleStart() {
  state.playing    = true;
  state.startMs    = millis();
  state.cycleCount = 0;
  state.nextBeat   = 0;
  state.ledActive  = false;
  digitalWrite(LED_PIN, LED_OFF);
}

void jingleStop() {
  state.playing   = false;
  state.ledActive = false;
  digitalWrite(LED_PIN, LED_OFF);
}

void updateJingle() {
  if (!state.playing) return;

  uint32_t now     = millis();
  uint32_t total   = now - state.startMs;
  uint32_t elapsed = total % SONG_DURATION_MS;
  uint32_t cycle   = total / SONG_DURATION_MS;

  if (cycle > state.cycleCount) {
    state.cycleCount = cycle;
    state.nextBeat   = 0;
  }

  if (state.nextBeat < (int)NUM_BEATS) {
    if (elapsed >= BEATS[state.nextBeat]) {
      state.nextBeat++;
      state.ledActive = true;
      state.ledOnMs   = now;
      digitalWrite(LED_PIN, LED_ON);
    }
  }

  if (state.ledActive && (now - state.ledOnMs) >= BLINK_MS) {
    state.ledActive = false;
    digitalWrite(LED_PIN, LED_OFF);
  }
}

// ── HTTP helpers ──────────────────────────────────────────────────────────
void addCors() {
  server.sendHeader("Access-Control-Allow-Origin",  "*");
  server.sendHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  server.sendHeader("Access-Control-Allow-Headers", "Content-Type");
}

void sendJson(int code, JsonDocument& doc) {
  addCors();
  String body; serializeJson(doc, body);
  server.send(code, "application/json", body);
}

// ── API handlers ──────────────────────────────────────────────────────────
void handleManifest() {
  JsonDocument doc;
  doc["schema"]     = "ESPAI.device.v1";
  doc["id"]         = nodeId;
  doc["name"]       = NODE_NAME;
  doc["board"]      = BOARD_ID;
  doc["fw_version"] = FW_VERSION;
  JsonObject caps   = doc["capabilities"].to<JsonObject>();
  caps["ota"]       = true;
  caps["jingle"]    = true;
  sendJson(200, doc);
}

void handleStatus() {
  JsonDocument doc;
  doc["id"]        = nodeId;
  doc["uptime_s"]  = millis() / 1000;
  doc["heap_free"] = ESP.getFreeHeap();
  doc["ip"]        = WiFi.localIP().toString();
  sendJson(200, doc);
}

void handleJingleStart() {
  jingleStart();
  JsonDocument doc;
  doc["status"]   = "playing";
  doc["start_ms"] = state.startMs;
  sendJson(200, doc);
}

void handleJingleStop() {
  jingleStop();
  JsonDocument doc;
  doc["status"] = "stopped";
  sendJson(200, doc);
}

void handleJingleState() {
  uint32_t elapsed = 0;
  int beatIdx = 0;
  if (state.playing) {
    uint32_t total = millis() - state.startMs;
    elapsed  = total % SONG_DURATION_MS;
    beatIdx  = state.nextBeat - 1;
    if (beatIdx < 0) beatIdx = 0;
  }
  JsonDocument doc;
  doc["playing"]    = state.playing;
  doc["elapsed_ms"] = elapsed;
  doc["beat_index"] = beatIdx;
  doc["start_ms"]   = state.startMs;
  sendJson(200, doc);
}

// ── Setup / Loop ──────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);

  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LED_OFF);

  WiFi.begin(WIFI_SSID, WIFI_PASS);
  uint32_t t = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t < WIFI_TIMEOUT_MS) delay(200);

  WiFi.mode(WIFI_STA);
  nodeId = deriveNodeId();
  Serial.printf("Node ID: %s  IP: %s\n", nodeId.c_str(), WiFi.localIP().toString().c_str());

  MDNS.begin(nodeId.c_str());
  MDNS.addService("_ESPAI-node", "_tcp", 80);

  server.on("/api/manifest", HTTP_GET,  handleManifest);
  server.on("/api/status",   HTTP_GET,  handleStatus);
  server.on("/api/reboot",   HTTP_POST, []() {
    JsonDocument d; d["status"] = "rebooting";
    String b; serializeJson(d, b);
    server.send(200, "application/json", b);
    delay(200); ESP.restart();
  });

  // Jingle endpoints — HTTP_ANY catches both OPTIONS preflight and POST
  server.on("/api/jingle/start", HTTP_ANY, []() {
    addCors();
    if (server.method() == HTTP_OPTIONS) { server.send(204); return; }
    handleJingleStart();
  });
  server.on("/api/jingle/stop",  HTTP_ANY, []() {
    addCors();
    if (server.method() == HTTP_OPTIONS) { server.send(204); return; }
    handleJingleStop();
  });
  server.on("/api/jingle/state", HTTP_ANY, []() {
    addCors();
    if (server.method() == HTTP_OPTIONS) { server.send(204); return; }
    handleJingleState();
  });

  server.begin();
  Serial.println("Jingle Bells ready — POST /api/jingle/start to play!");
}

void loop() {
  server.handleClient();
  updateJingle();
  // No delay() so LED timing stays accurate
}
