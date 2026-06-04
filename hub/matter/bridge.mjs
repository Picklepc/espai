/**
 * ESPAI Matter Bridge (bridge.mjs)
 *
 * Acts as a Matter Bridge/Aggregator device, exposing ESPai projects
 * as first-class Matter endpoints to Google Home, HomeKit, and Alexa.
 *
 * Managed by hub/backend/matter_bridge.py — Python spawns this process,
 * watches for "READY" on stdout, then uses the HTTP API to manage devices.
 *
 * HTTP control API (ESPAI_MATTER_PORT, default 5580):
 *   GET  /status             → bridge and endpoint status
 *   GET  /qrcode             → commissioning QR code
 *   POST /devices            → register/update an endpoint
 *   PUT  /devices/:id/state  → update device state attributes
 *   DELETE /devices/:id      → remove endpoint
 *   POST /shutdown           → graceful shutdown
 *
 * Matter commands flow back to the hub via:
 *   POST http://localhost:{HUB_PORT}/api/matter/command
 *   Body: { device_id, command, args }
 */

import express from "express";
import { createServer } from "http";

// matter-node.js 0.10 imports
import { Environment } from "@project-chip/matter-node.js";
import { StorageBackendDisk } from "@project-chip/matter-node.js/storage";
import { ServerNode } from "@project-chip/matter-node.js";
import { VendorId } from "@project-chip/matter-node.js/datatype";
import { Endpoint } from "@project-chip/matter-node.js/endpoint";
import { AggregatorEndpoint } from "@project-chip/matter-node.js/endpoints/definitions";
import {
  OnOffPlugInUnitEndpoint,
  DimmableLightEndpoint,
  ColorTemperatureLightEndpoint,
  TemperatureSensorEndpoint,
  HumiditySensorEndpoint,
  OccupancySensorEndpoint,
  ContactSensorEndpoint,
} from "@project-chip/matter-node.js/endpoints/definitions";
import { QrCode } from "@project-chip/matter-node.js/schema";

// ── Config ────────────────────────────────────────────────────────────────────

const PORT        = parseInt(process.env.ESPAI_MATTER_PORT     || "5580");
const HUB_PORT    = parseInt(process.env.ESPAI_HUB_PORT        || "7888");
const STORAGE_DIR = process.env.ESPAI_MATTER_STORAGE           || "./data/matter-storage";
const PASSCODE    = parseInt(process.env.ESPAI_MATTER_PASSCODE || "20202021");
const DISCRIMINATOR = parseInt(process.env.ESPAI_MATTER_DISCRIMINATOR || "3840");

// ── State ─────────────────────────────────────────────────────────────────────

const devices    = new Map();   // device_id → { endpoint, device_type, state, name }
let   serverNode = null;
let   aggregator = null;
let   commissioned = false;

// ── Matter Device Type → Endpoint class ───────────────────────────────────────

const ENDPOINT_CLASS = {
  on_off_plug:        OnOffPlugInUnitEndpoint,
  dimmable_light:     DimmableLightEndpoint,
  color_light:        ColorTemperatureLightEndpoint,
  temperature_sensor: TemperatureSensorEndpoint,
  humidity_sensor:    HumiditySensorEndpoint,
  occupancy_sensor:   OccupancySensorEndpoint,
  contact_sensor:     ContactSensorEndpoint,
};

// Default cluster attribute maps per device type
const DEFAULT_STATE = {
  on_off_plug:        { onOff: false },
  dimmable_light:     { onOff: false, currentLevel: 0 },
  color_light:        { onOff: false, currentLevel: 0, currentHue: 0, currentSaturation: 0 },
  temperature_sensor: { measuredValue: null },
  humidity_sensor:    { measuredValue: null },
  occupancy_sensor:   { occupancy: { occupied: false } },
  contact_sensor:     { stateValue: false },
};

// Map hub state keys → Matter cluster attribute names
const STATE_MAP = {
  on_off_plug: {
    on_off: "onOff", on: "onOff", power_on: "onOff", switch: "onOff",
  },
  dimmable_light: {
    on_off: "onOff", on: "onOff",
    brightness: "currentLevel", level: "currentLevel", dim: "currentLevel",
  },
  color_light: {
    on_off: "onOff", on: "onOff",
    brightness: "currentLevel", level: "currentLevel",
    hue: "currentHue", sat: "currentSaturation", saturation: "currentSaturation",
  },
  temperature_sensor: {
    temperature: "measuredValue",
    temp: "measuredValue",
  },
  humidity_sensor: {
    humidity: "measuredValue",
    relative_humidity: "measuredValue",
  },
  occupancy_sensor: {
    occupancy: "occupancy", motion: "occupancy", presence: "occupancy",
  },
  contact_sensor: {
    contact: "stateValue", open: "stateValue", closed: "stateValue",
  },
};

// ── Hub webhook helper ─────────────────────────────────────────────────────────

async function notifyHub(deviceId, command, args = {}) {
  try {
    const res = await fetch(`http://localhost:${HUB_PORT}/api/matter/command`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device_id: deviceId, command, args }),
    });
    if (!res.ok) console.warn(`[hub] command webhook ${res.status}`);
  } catch (e) {
    console.warn(`[hub] command webhook failed: ${e.message}`);
  }
}

// ── Build endpoint options for a device ───────────────────────────────────────

function buildEndpointOptions(deviceId, name, deviceType, initialState = {}) {
  const bridgedBasic = {
    bridgedDeviceBasicInformation: {
      nodeLabel: name.slice(0, 32),
      reachable: true,
      vendorName: "ESPAI",
    },
  };

  const state = { ...DEFAULT_STATE[deviceType], ...initialState };

  switch (deviceType) {
    case "on_off_plug":
    case "dimmable_light":
    case "color_light": {
      const onOffServer = {
        onOff: {
          onOff: state.onOff ?? false,
        },
      };
      const handlers = {
        on:  async () => { notifyHub(deviceId, "on",  {}); },
        off: async () => { notifyHub(deviceId, "off", {}); },
        toggle: async () => { notifyHub(deviceId, "toggle", {}); },
      };
      return { id: deviceId, ...bridgedBasic, onOff: onOffServer, handlers };
    }

    case "temperature_sensor": {
      const measured = state.measuredValue != null
        ? Math.round(state.measuredValue * 100)
        : null;
      return {
        id: deviceId, ...bridgedBasic,
        temperatureMeasurement: { measuredValue: measured },
      };
    }

    case "humidity_sensor": {
      const measured = state.measuredValue != null
        ? Math.round(state.measuredValue * 100)
        : null;
      return {
        id: deviceId, ...bridgedBasic,
        relativeHumidityMeasurement: { measuredValue: measured },
      };
    }

    case "occupancy_sensor": {
      const occupied = state.occupancy?.occupied ?? false;
      return {
        id: deviceId, ...bridgedBasic,
        occupancySensing: { occupancy: { occupied } },
      };
    }

    case "contact_sensor": {
      return {
        id: deviceId, ...bridgedBasic,
        booleanState: { stateValue: state.stateValue ?? false },
      };
    }

    default:
      return { id: deviceId, ...bridgedBasic };
  }
}

// ── Matter server init ─────────────────────────────────────────────────────────

async function initMatter() {
  const storage = new StorageBackendDisk(STORAGE_DIR);
  const env = Environment.default;
  env.set(StorageBackendDisk, storage);

  serverNode = await ServerNode.create({
    id:          "espai-matter-bridge",
    environment: env,
    productDescription: {
      name:       "ESPAI Hub",
      deviceType: 0x000E,   // Matter Bridge device type
    },
    commissioning: {
      passcode:      PASSCODE,
      discriminator: DISCRIMINATOR,
    },
    basicInformation: {
      vendorName:    "ESPAI",
      vendorId:      VendorId(0xFFF1),
      productName:   "ESPAI Matter Bridge",
      productId:     0x8001,
      serialNumber:  "ESPAI-BRIDGE-001",
      hardwareVersion: 1,
      softwareVersion: 1,
    },
  });

  aggregator = new Endpoint(AggregatorEndpoint, { id: "aggregator" });
  await serverNode.add(aggregator);

  // Listen for commissioning state changes
  serverNode.lifecycle.commissioned.on(() => {
    commissioned = true;
    console.log("[matter] Device commissioned to fabric");
  });

  await serverNode.start();
  console.log("[matter] Server started");
}

// ── Register/update a device endpoint ─────────────────────────────────────────

async function registerDevice(deviceId, name, deviceType, initialState = {}) {
  const EndpointClass = ENDPOINT_CLASS[deviceType];
  if (!EndpointClass) throw new Error(`Unknown device type: ${deviceType}`);

  if (devices.has(deviceId)) {
    // Update existing device state
    const { endpoint } = devices.get(deviceId);
    await updateDeviceState(deviceId, initialState);
    devices.get(deviceId).name  = name;
    return { endpoint_id: deviceId, updated: true };
  }

  const opts = buildEndpointOptions(deviceId, name, deviceType, initialState);
  const endpoint = new Endpoint(EndpointClass, opts);
  await aggregator.add(endpoint);

  devices.set(deviceId, { endpoint, device_type: deviceType, state: { ...initialState }, name });
  console.log(`[matter] Registered device: ${deviceId} (${deviceType})`);
  return { endpoint_id: deviceId, created: true };
}

// ── Update device state ────────────────────────────────────────────────────────

async function updateDeviceState(deviceId, stateUpdate) {
  const dev = devices.get(deviceId);
  if (!dev) throw new Error(`Device ${deviceId} not registered`);

  const { endpoint, device_type } = dev;
  const map = STATE_MAP[device_type] || {};

  for (const [hubKey, value] of Object.entries(stateUpdate)) {
    const mattAttr = map[hubKey] || hubKey;
    try {
      switch (device_type) {
        case "on_off_plug":
        case "dimmable_light":
        case "color_light":
          if (mattAttr === "onOff" && endpoint.state?.onOff != null)
            await endpoint.set({ onOff: { onOff: Boolean(value) } });
          if (mattAttr === "currentLevel" && endpoint.state?.levelControl != null)
            await endpoint.set({ levelControl: { currentLevel: Math.round(value) } });
          break;

        case "temperature_sensor":
          if (mattAttr === "measuredValue")
            await endpoint.set({ temperatureMeasurement: { measuredValue: Math.round(value * 100) } });
          break;

        case "humidity_sensor":
          if (mattAttr === "measuredValue")
            await endpoint.set({ relativeHumidityMeasurement: { measuredValue: Math.round(value * 100) } });
          break;

        case "occupancy_sensor":
          if (mattAttr === "occupancy")
            await endpoint.set({ occupancySensing: { occupancy: { occupied: Boolean(value) } } });
          break;

        case "contact_sensor":
          if (mattAttr === "stateValue")
            await endpoint.set({ booleanState: { stateValue: Boolean(value) } });
          break;
      }
    } catch (e) {
      console.warn(`[matter] updateState ${deviceId}.${mattAttr}: ${e.message}`);
    }
  }

  Object.assign(dev.state, stateUpdate);
}

// ── Remove a device ────────────────────────────────────────────────────────────

async function removeDevice(deviceId) {
  const dev = devices.get(deviceId);
  if (!dev) return false;
  try {
    await aggregator.removeEndpoint(dev.endpoint);
  } catch (_) {}
  devices.delete(deviceId);
  console.log(`[matter] Removed device: ${deviceId}`);
  return true;
}

// ── HTTP control API ──────────────────────────────────────────────────────────

const app = express();
app.use(express.json());

app.get("/status", (_req, res) => {
  res.json({
    running:       true,
    commissioned,
    passcode:      PASSCODE,
    discriminator: DISCRIMINATOR,
    endpoints:     [...devices.entries()].map(([id, d]) => ({
      id,
      name:        d.name,
      device_type: d.device_type,
      reachable:   true,
    })),
  });
});

app.get("/qrcode", async (_req, res) => {
  if (!serverNode) return res.status(503).json({ error: "Bridge not initialised" });
  try {
    const { qrCode, manualPairingCode } = serverNode.commissioning.pairingCodes;
    const svg = QrCode.encode(qrCode, "svg");
    res.json({ qr_code: qrCode, manual_pairing_code: manualPairingCode, svg });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.post("/devices", async (req, res) => {
  const { id, name, device_type, state = {} } = req.body || {};
  if (!id || !device_type)
    return res.status(400).json({ error: "id and device_type required" });
  try {
    const result = await registerDevice(id, name || id, device_type, state);
    res.status(201).json(result);
  } catch (e) {
    res.status(400).json({ error: e.message });
  }
});

app.put("/devices/:id/state", async (req, res) => {
  const { id } = req.params;
  try {
    await updateDeviceState(id, req.body || {});
    res.json({ updated: true });
  } catch (e) {
    res.status(404).json({ error: e.message });
  }
});

app.delete("/devices/:id", async (req, res) => {
  const removed = await removeDevice(req.params.id);
  res.json({ removed });
});

app.post("/shutdown", async (_req, res) => {
  res.json({ ok: true });
  setTimeout(async () => {
    try { await serverNode?.close(); } catch (_) {}
    process.exit(0);
  }, 200);
});

// ── Start ─────────────────────────────────────────────────────────────────────

async function main() {
  try {
    await initMatter();
  } catch (e) {
    console.error("[matter] Init failed:", e.message);
    // Run HTTP API even if Matter init fails so Python can query status
  }

  const httpServer = createServer(app);
  httpServer.listen(PORT, "127.0.0.1", () => {
    console.log(`[http] Bridge API listening on port ${PORT}`);
    // Signal to Python that we're ready
    console.log("READY");
    process.stdout.write("READY\n");
  });

  // Graceful shutdown
  process.on("SIGTERM", async () => {
    console.log("[bridge] SIGTERM — shutting down");
    try { await serverNode?.close(); } catch (_) {}
    process.exit(0);
  });
}

main().catch(e => {
  console.error("[bridge] Fatal:", e);
  process.exit(1);
});
