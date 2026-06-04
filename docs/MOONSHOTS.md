# ESPAI Moonshot Challenge Spec

A collection of ambitious project proposals that stress-test the ESPAI platform, expose gaps, and define the frontier of what's possible with ESP32-class hardware + a local hub. Each entry is assessed against the current platform, hardware limits, and hub infrastructure.

**How to use this file:**
- Use it to prioritize platform features that unlock multiple moonshots at once.
- Use it to calibrate what the ESP32 can and can't do so you don't design yourself into a corner.
- Add new moonshots as you think of them. An entry doesn't need to be buildable today — "impossible with current hardware" is a valid and useful finding.

---

## Assessment Legend

| Symbol | Meaning |
|--------|---------|
| ✅ | ESPai supports this today |
| 🔧 | ESPai needs a feature addition |
| ⚠️ | Possible but fragile — known limitations |
| ❌ | Not feasible with current approach; needs new strategy |
| 🔮 | Requires research / unclear path |

---

## M-01 — Autonomous Weed-Killing Rover

**Vision:** A rover that patrols your property on WiFi, uses an ESP32-CAM to identify weeds via ML inference, then fires a low-power laser at the root. Operates autonomously, reports activity to the hub, and updates its weed map over time.

### Hardware Stack
- ESP32-S3 (dual-core 240 MHz, 512 KB SRAM, PSRAM via SPI)
- OV2640 or OV5640 camera module
- DC motor driver (L298N or DRV8833) + 4WD chassis
- Time-of-flight distance sensor (VL53L1X) for obstacle avoidance
- GPS module (u-blox NEO-M8N) for property mapping
- 5 mW 650 nm laser diode + relay/MOSFET
- 18650 LiPo pack + solar top-up
- WiFi range extender mesh if property is large

### ESP32 Feasibility

| Concern | Assessment |
|---------|-----------|
| On-device ML inference | ⚠️ Tiny models only. ESP32-S3 with PSRAM can run int8 quantized MobileNetV2 at ~1-3 fps via TensorFlow Lite Micro. Detection quality is marginal — expect 60-70% accuracy on a narrow weed dataset trained on your specific plants. |
| Motor control + camera simultaneously | ⚠️ Both compete for SPI/I2C bandwidth and CPU. Use FreeRTOS tasks with priority tuning. Motor PWM must be on hardware timer channels. |
| WiFi while driving | ⚠️ WiFi range drops fast when moving. RSSI-gated behavior ("stop if RSSI < -75 dBm, return home") is essential. |
| Power budget | ❌ Continuous camera + WiFi + motors = ~800 mA. 3000 mAh battery = ~3.5 hours. Solar barely keeps up in motion. |
| GPS accuracy | ⚠️ ±2.5 m CEP — enough to map "which quadrant of the yard" but not precise weed coordinates. |
| Laser safety | ❌ Even 5 mW requires iris-safe targeting logic — the ESP32 cannot guarantee safe laser-off on crash. Hardware interlock required. |

### ESPai Platform Readiness

| Feature | Status |
|---------|--------|
| Device checkin + OTA | ✅ Ready |
| Hub-side weed map (project data store) | ✅ Projects data push/pull works |
| Worker to process camera frames | 🔧 Worker receives frames via HTTP POST; hub-side CV worker needed (opencv-motion-tagger could be adapted) |
| Telemetry stream (position, RSSI, battery) | ✅ data push API |
| Command channel (return home, pause) | 🔧 Needs bidirectional command API — hub can POST a command to the device's `/api/command` endpoint; device must poll or use WebSocket |
| Map visualization card | 🔧 Custom card with Leaflet.js or canvas grid needed |
| Autonomous mission scheduling | 🔧 Recipes could trigger "start patrol" jobs; no waypoint planning in ESPai today |

### Hub Requirements (RockChip OpenWrt)
- OpenCV worker for frame analysis: ~200 MB RAM, 1 CPU core at ~30% for 1 fps analysis
- GPS track storage: trivial (SQLite JSON column)
- Weed map tile rendering: could be done in a worker; Leaflet frontend needs hub-served tiles or GeoJSON

### Platform Gaps Exposed
1. **Bidirectional command channel** — hub needs a way to send real-time commands to a device (not just pull data). Current model is device-driven (device calls hub). A `GET /api/devices/{id}/commands` poll endpoint or WebSocket push would unblock this and many other projects.
2. **Hub-side image processing pipeline** — the data push API accepts JSON but not binary frames. Need multipart/binary upload support or MQTT image streaming.
3. **Mission planner** — recipes are event-driven, not waypoint/time-sequence planners.
4. **Persistent map data** — project data store is a rolling time series, not a spatial/grid structure.

### Moonshot Factor: 🌕🌕🌕🌕 (Very High)
### MVP Path: 6 months with custom firmware + 2 new ESPai features (command channel, binary data push)

---

## M-02 — Anywhere Karaoke Display

**Vision:** A handheld ESP32 device with an LCD screen and microphone. It listens to whatever song is playing nearby, identifies it (Shazam-style), downloads the synchronized lyrics (LRC format), and displays them in real-time scroll so you can jump in and sing anywhere. Works on your local WiFi or hotspot.

### Hardware Stack
- ESP32-S3 (PSRAM required for audio buffering)
- INMP441 I2S MEMS microphone
- ILI9341 2.8" SPI TFT (240×320) or ST7789 round display
- LiPo 1000 mAh + TP4056 charger
- Optional rotary encoder for manual song search
- Optional: small speaker + MAX98357A I2S amp for local audio preview

### ESP32 Feasibility

| Concern | Assessment |
|---------|-----------|
| Audio capture (I2S mic) | ✅ ESP-IDF I2S peripheral handles this natively at 44.1 kHz |
| Audio fingerprinting on-device | ❌ Shazam-style fingerprinting requires FFT + hash lookup against millions of entries. Way beyond ESP32. Must offload to hub. |
| Lyrics sync display | ✅ Render LRC timestamps against millis() timer — easily doable |
| WiFi + display simultaneously | ✅ No conflict; SPI display and WiFi are independent |
| Response time (song ID → display) | ⚠️ Hub round-trip + API call + lyrics download = 3-8 seconds. Acceptable if lyrics are pre-cached. |
| Offline operation | ❌ Song ID requires a cloud API (ACRCloud, AudD, or local Dejavu). Lyrics require network too. |

### ESPai Platform Readiness

| Feature | Status |
|---------|--------|
| Audio clip upload from device | 🔧 Binary data upload needed (same gap as M-01) |
| Hub worker: audio fingerprint via ACRCloud API | 🔧 New worker; http-poller could POST the clip if binary upload existed |
| Hub worker: fetch LRC lyrics (lrclib.net is free) | ✅ http-poller can fetch lyrics JSON |
| Lyrics push to device | 🔧 Command channel needed to push LRC to device |
| Song history / favorites | ✅ Project data store |
| Offline lyrics cache | 🔧 Hub could pre-cache lyrics for known songs in project data |

### Hub Requirements (RockChip OpenWrt)
- Audio fingerprint worker: sends 3-5s PCM clip to ACRCloud; ~5 KB upload; minimal CPU
- Lyrics worker: fetches LRC from lrclib.net; trivial
- Total hub overhead: negligible — this is mostly network latency

### Platform Gaps Exposed
1. **Binary upload from device** — same as M-01. Critical for any media/sensor project.
2. **Push channel to device** — device needs to receive the lyrics from the hub.
3. **Streaming data display cards** — a hub-hosted web card that can push lyrics to the device display via WebSocket proxy would be elegant.

### Moonshot Factor: 🌕🌕🌕 (High)
### MVP Path: 3 months. Two main blockers: binary upload + command push. Song ID can use a free tier API (ACRCloud 100 req/day free).

---

## M-03 — Swarm Mesh Sensor Network

**Vision:** 20-50 ESP32 nodes deployed across a large property (farm, workshop, greenhouse) forming a self-healing WiFi mesh. Each node measures temperature, humidity, CO2, light, and soil moisture. The hub builds a real-time spatial map and detects anomalies (frost alert, CO2 spike, irrigation failure).

### Hardware Stack
- ESP32 (standard, not S3 needed)
- BME680 (temp/humidity/air quality) + capacitive soil sensor
- Battery + solar charging per node
- ESP-NOW mesh or WiFi direct to AP (depending on range)

### ESP32 Feasibility

| Concern | Assessment |
|---------|-----------|
| Sensor reading | ✅ Trivial — I2C sensors, sub-1s reads |
| ESP-NOW mesh | ⚠️ ESP-NOW range ~200m line-of-sight. Mesh relay possible but not native — requires custom routing. |
| Deep sleep + periodic checkin | ✅ ESPai firmware already supports sleep_interval_s |
| 50 nodes on one AP | ❌ Standard AP handles ~20-25 concurrent WiFi stations reliably. Mesh AP or multiple APs needed. |
| Battery life (sleep mode) | ✅ 30s wake/5min sleep on 18650 = 3+ months |

### ESPai Platform Readiness

| Feature | Status |
|---------|--------|
| Multi-node project model | ✅ M10 — project_nodes table, roles |
| Per-node data series | ✅ Project data store keyed by source |
| Anomaly detection rules | ✅ Rules engine (evaluate on event) |
| Spatial map card | 🔧 Need custom card with canvas/SVG floor plan overlay |
| Bulk OTA to all nodes | ✅ Staged rollout already exists |
| Node health monitoring | ✅ Last-seen tracking, sleep indicator |

### Hub Requirements (RockChip OpenWrt)
- 50 nodes × 5 checkins/hour = 250 req/hour — trivial for FastAPI
- SQLite handles this easily; no scaling concern
- Spatial interpolation worker (IDW or kriging) for heat map: ~50 MB RAM

### Platform Gaps Exposed
1. **ESP-NOW gateway** — a dedicated "mesh gateway" ESP32 connected via USB to the hub that bridges ESP-NOW to HTTP. ESPai has no concept of a USB-attached gateway device.
2. **Floor plan / spatial data card** — project data store needs a spatial query API (`GET /api/projects/{id}/data/spatial?lat=&lng=&radius=`).
3. **Multi-AP management** — if >25 nodes, need multiple APs; ESPai has no WAP management.

### Moonshot Factor: 🌕🌕🌕 (High)
### MVP Path: 2 months for 10-node version. ESP-NOW gateway is the key unlock for larger deployments.

---

## M-04 — AI Security Doorbell + Access Control

**Vision:** ESP32-CAM doorbell that captures a face, identifies known/unknown visitors via hub-side face recognition, announces via TTS, logs all visitors with thumbnails, and can trigger a relay to unlock the door. Privacy-first — all processing local, no cloud.

### Hardware Stack
- ESP32-S3 with OV5640 camera
- Relay module for door strike
- I2S speaker (MAX98357A) for local TTS/chime
- IR LED array for night vision
- Optional: keypad for PIN entry

### ESP32 Feasibility

| Concern | Assessment |
|---------|-----------|
| Face capture (JPEG) | ✅ ESP32-CAM does this natively |
| On-device face recognition | ❌ ESP32-S3 can barely do face detection. Recognition requires much more compute. |
| Door relay control | ✅ GPIO + relay; simple |
| Local audio playback | ✅ I2S DAC with pre-compiled audio clips |
| Motion-triggered capture | ✅ PIR sensor or frame diff from camera stream |

### ESPai Platform Readiness

| Feature | Status |
|---------|--------|
| Image upload from device | 🔧 Binary upload gap (same as M-01, M-02) |
| Face recognition worker | 🔧 New worker using face_recognition library (dlib); heavy deps (~200 MB) |
| Known face enrollment | 🔧 Needs a face database; project data store could hold face embeddings as JSON |
| Door unlock command | 🔧 Command channel (same as M-01) |
| Visitor log with thumbnails | 🔧 Project data store + media file storage needed |
| Push notification | ✅ SSE/WebSocket notifications exist |

### Hub Requirements (RockChip OpenWrt)
- face_recognition (dlib) worker: ~400 MB RAM, 2-4 seconds per face — RockChip can handle this at low throughput (1-2 visitors/minute)
- ❌ **Real-time streaming recognition** would overwhelm a RockChip at ~30fps. Motion-triggered single-frame is the viable approach.
- Thumbnail storage: ~50 KB per frame × 1000 visitors = ~50 MB — fine

### Platform Gaps Exposed
1. Binary upload (again — this is the most critical missing feature)
2. Media file storage (project-scoped image/binary file store, not just JSON)
3. Face database (need persistent key-value store, not time series)
4. Command channel

### Moonshot Factor: 🌕🌕🌕 (High)
### MVP Path: 4 months. Binary upload is the first blocker. Face recognition on RockChip at single-frame is feasible.

---

## M-05 — Smart Beehive Monitor

**Vision:** Non-invasive hive monitoring via weight (load cells), internal temperature/humidity, and acoustic analysis (buzzing frequency predicts swarm behavior). Alerts beekeeper when swarm is imminent or queen is absent. Solar powered, IP65.

### Hardware Stack
- ESP32 (standard)
- HX711 load cell amplifier × 2 (hive weight)
- DS18B20 waterproof temp probes (inside frames)
- INMP441 I2S microphone (internal acoustic)
- BME280 external ambient (outside hive)
- 18650 × 4 + solar panel + MPPT controller

### ESP32 Feasibility

| Concern | Assessment |
|---------|-----------|
| Load cell (HX711) | ✅ Bit-banging HX711 is well-supported |
| I2S acoustic capture | ✅ Works well on ESP32 |
| On-device acoustic analysis | ⚠️ FFT of audio → frequency peak → rule-based alert. Not full ML but good enough for "high frequency = agitated bees". |
| Deep sleep with periodic wake | ✅ ESPai sleep firmware supports this |
| Waterproof enclosure + solar | Hardware challenge, not software |

### ESPai Platform Readiness

| Feature | Status |
|---------|--------|
| Weight/temp/humidity data push | ✅ Project data push works perfectly |
| Acoustic clip analysis (hub worker) | 🔧 Audio clip upload needed; hub worker runs FFT via numpy |
| Swarm prediction rules | ✅ Rules engine could fire on "frequency_peak > 450 Hz" event |
| Historical weight chart | ✅ Project data history API + custom card |
| Push notification | ✅ Browser notification via existing SSE |
| Bee-specific dashboard card | 🔧 Custom card with weight trend + acoustic spectrogram |

### Hub Requirements (RockChip OpenWrt)
- Acoustic FFT worker: numpy FFT on 3s clip = trivial, <1s, minimal RAM
- Weight trend analysis: pure JSON/SQLite, no compute concern
- This is an excellent fit for the RockChip hub — very light workload

### Platform Gaps Exposed
1. Binary upload (audio clips) — recurring theme
2. Time-series chart card — hub-served web card with Chart.js could cover this; currently requires building a custom card

### Moonshot Factor: 🌕🌕 (Medium)
### MVP Path: 6 weeks. Text telemetry works today. Audio analysis waits on binary upload. This is one of the most buildable moonshots on the list.

---

## M-06 — Off-Grid Mesh Communicator

**Vision:** A network of ESP32 nodes using LoRa radio (via SX1276 module) to relay short text messages across several kilometers without WiFi or cellular. Hub acts as the internet gateway and message store when in range. Think "Meshtastic + ESPai integration."

### Hardware Stack
- ESP32 + SX1276 LoRa (TTGO LoRa32 dev board)
- E-ink display (GDEW0213T5) for message display
- 18650 + solar
- Optional: GPS for position sharing

### ESP32 Feasibility

| Concern | Assessment |
|---------|-----------|
| LoRa radio via SPI | ✅ Well-supported; RadioLib library |
| Mesh routing | ⚠️ Flood routing works but wastes airtime. Proper AODV/DSR routing on ESP32 is complex but doable at small scale. |
| E-ink update speed | ⚠️ Full refresh takes 2s. Partial refresh ~300ms. Fine for messaging. |
| Message encryption | ✅ AES-256 on ESP32 is fast enough for short messages |
| LoRa range | ✅ 2-10 km line-of-sight at SF12, BW=125kHz — excellent |

### ESPai Platform Readiness

| Feature | Status |
|---------|--------|
| Device checkin over WiFi when in range | ✅ Existing checkin flow |
| Message queue in hub | 🔧 Needs a message/inbox data model (not time series) |
| LoRa gateway worker | 🔧 Hub-attached USB LoRa dongle → Python worker reading serial → message routing |
| Message delivery receipt | 🔧 New concept — no delivery tracking in current data model |
| Position sharing / map | 🔧 Same spatial card need as M-03 |

### Hub Requirements (RockChip OpenWrt)
- LoRa USB gateway serial reader worker: trivial CPU/RAM
- Message store: SQLite is fine; a simple `messages` table needed
- The hub becomes a LoRa ↔ internet bridge — fits perfectly

### Platform Gaps Exposed
1. **USB-attached peripheral gateway** — ESPai has no model for a USB device acting as a gateway/bridge to a radio network. This is a new device type.
2. **Message/inbox data model** — project data store is time-series; a proper inbox (sender, recipient, delivered, read) doesn't map cleanly.
3. Spatial card (recurring)

### Moonshot Factor: 🌕🌕 (Medium — Meshtastic already solves this, but ESPai integration is interesting)
### MVP Path: 3 months if using Meshtastic firmware (already has LoRa mesh) + ESPai Meshtastic integration worker.

---

## M-07 — Passive Acoustic Wildlife Monitor

**Vision:** Weatherproof ESP32 units deployed in woods/fields continuously record audio, detect target species calls (birds, frogs, bats), timestamp and GPS-tag detections, and stream them to the hub for BirdNET-style species identification. Build a biodiversity map of your property over time.

### Hardware Stack
- ESP32-S3 (PSRAM for audio buffer)
- INMP441 + windscreen enclosure
- GPS module
- MicroSD card for local buffering when WiFi out of range
- Solar + LiPo

### ESP32 Feasibility

| Concern | Assessment |
|---------|-----------|
| Continuous audio capture | ⚠️ 44.1 kHz 16-bit = 88 KB/s. PSRAM can buffer ~5s. Need SD card for longer clips. |
| SD card write during WiFi TX | ⚠️ SD (SPI) and WiFi compete. Stagger writes or use SDMMC bus. |
| On-device species detection | ❌ BirdNET requires TensorFlow with models >10 MB. Not feasible on ESP32. |
| Offline buffering → sync when in range | 🔧 Custom firmware with WiFi scan + upload queue |

### ESPai Platform Readiness

| Feature | Status |
|---------|--------|
| Audio file upload | 🔧 Binary upload needed (same critical gap) |
| BirdNET worker (hub side) | 🔧 BirdNET-Analyzer is Python; Docker image or native pip install. Works well on RockChip. |
| Detection event push | ✅ Worker emits `species.detected` event |
| Biodiversity dashboard | 🔧 Custom card; species count by time/location |
| Historical map | 🔧 Spatial card with species overlay |

### Hub Requirements (RockChip OpenWrt)
- BirdNET inference: ~3s per 3s clip on RockChip ARM64 at CPU. Viable for 1-4 nodes.
- ❌ 10+ nodes sending clips simultaneously would saturate the RockChip. Need a queue worker with rate limiting.
- Audio file storage: 3s clips at ~260 KB each × 1000 detections = 260 MB — needs a media storage strategy.

### Platform Gaps Exposed
1. Binary upload (recurring critical gap)
2. Media file storage with metadata
3. Job queue rate limiting / backpressure
4. Spatial biodiversity card

### Moonshot Factor: 🌕🌕🌕 (High — scientifically meaningful)
### MVP Path: 4 months after binary upload is built.

---

## M-08 — ESP32 CNC / Laser Engraver Controller

**Vision:** ESP32 acts as a WiFi-connected G-code controller for a small CNC router or laser engraver. Jobs are uploaded from the hub, queued, and executed. Status is streamed back. Emergency stop via hub or physical button.

### Hardware Stack
- ESP32 (dual-core, standard)
- 3× TMC2209 stepper drivers (X/Y/Z)
- Endstop switches
- Spindle relay or laser PWM
- Optional: webcam for job monitoring

### ESP32 Feasibility

| Concern | Assessment |
|---------|-----------|
| G-code execution | ✅ FluidNC (ESP32 CNC firmware) already exists and is mature. ESPai can integrate with it rather than replace it. |
| Stepper timing (step pulses) | ✅ ESP32 hardware timers handle 100 kHz step pulses — adequate for NEMA17 at normal speeds |
| WiFi during job | ⚠️ WiFi interrupt can cause step timing jitter. Use dedicated core for motion, WiFi on the other. |
| Emergency stop latency | ⚠️ WiFi e-stop is not fast enough for safety-critical stops. Hardware e-stop button required regardless. |

### ESPai Platform Readiness

| Feature | Status |
|---------|--------|
| G-code file upload to device | 🔧 Binary/text file upload needed |
| Job queue management | ✅ Job queue exists but is for worker jobs, not device jobs |
| Live status stream (position, %) | ✅ Data push from device works; status card needed |
| FluidNC integration worker | 🔧 Worker that talks to FluidNC's WebSocket API |
| Emergency stop command | 🔧 Command channel needed |

### Hub Requirements (RockChip OpenWrt)
- G-code file storage: trivial
- FluidNC WebSocket proxy worker: minimal CPU
- Job progress tracking: SQLite, trivial

### Platform Gaps Exposed
1. Device job queue (separate from worker jobs — "jobs for devices, not workers")
2. File upload to device (binary)
3. Command channel (e-stop, pause, resume)
4. Existing FluidNC ecosystem should be integrated via ESPai worker, not replaced

### Moonshot Factor: 🌕🌕 (Medium — FluidNC already solves the hard part)
### MVP Path: 2 months. FluidNC worker + command channel is the path.

---

## M-09 — Live Livestock Location Tracker

**Vision:** Solar-powered collar nodes on cattle/goats track GPS position every 30 seconds and transmit via WiFi mesh or LoRa. Hub builds herd map, detects fence breaches, predator proximity alerts (via acoustic detection of distress calls), and tracks grazing patterns.

### Hardware Stack
- ESP32 + u-blox NEO-M8N GPS
- SX1276 LoRa for long-range (WiFi range too limited for large pasture)
- MEMS microphone for distress call detection
- Lightweight LiPo + flexible solar panel
- IP67 enclosure (must survive livestock abuse)

### ESP32 Feasibility

| Concern | Assessment |
|---------|-----------|
| GPS accuracy | ⚠️ ±2.5m CEP. Fine for "which paddock" but not sub-meter positioning. |
| LoRa + GPS simultaneously | ✅ Different radios; no conflict |
| Power budget on collar | ❌ 30s GPS fix + LoRa TX every 5min at 10mA average. 500mAh = 50+ hours. Solar top-up needed for multi-day operation. |
| Distress call detection | ⚠️ Simple audio level threshold for rapid FFT — feasible. Not as good as trained ML. |
| Animal-safe construction | Hardware challenge — not a software problem |

### ESPai Platform Readiness
Same gaps as M-03 (spatial map) and M-06 (LoRa gateway). GPS tracking is a strong use case for ESPai once those pieces exist.

### Platform Gaps Exposed
1. LoRa USB gateway (recurring from M-06)
2. Spatial/GPS query API
3. Geofence rule type — "fire alert when device GPS crosses polygon boundary" — doesn't exist yet
4. Herd management data model (animal ID, collar ID, health notes)

### Moonshot Factor: 🌕🌕🌕 (High — real commercial value)
### MVP Path: 3 months with LoRa gateway + geofence rules. Needs custom firmware for low-power GPS duty cycle.

---

## M-10 — Multiplayer Escape Room Controller

**Vision:** An ESP32 orchestrates an escape room with 8-12 puzzles, each triggered by physical actions (RFID, buttons, weight sensors, lasers). Puzzle state is tracked on the hub with a live GM dashboard. Hints are pushed to in-room displays. Timer runs on hub with real-time WebSocket updates. Supports multiple simultaneous rooms.

### Hardware Stack
- 1× ESP32 per room (I2C expander for GPIO expansion)
- RC522 RFID readers
- Reed switches, buttons, weight cells
- 7-segment / OLED displays per puzzle
- Relay board for locks, lights, props
- Optional: addressable LED strips (WS2812B)

### ESP32 Feasibility

| Concern | Assessment |
|---------|-----------|
| 12+ I/O with I2C expanders | ✅ PCF8574 expanders give 8 GPIO each; multiple on same I2C bus |
| RFID reads | ✅ RC522 via SPI; well supported |
| Real-time state reporting | ✅ WiFi + HTTP POST per event is fast enough |
| WS2812B LED strips | ✅ RMT peripheral handles this perfectly |
| Multi-room hub management | ✅ Each room is an ESPai project |

### ESPai Platform Readiness

| Feature | Status |
|---------|--------|
| Per-room project with puzzle state | ✅ Project data store maps naturally |
| GM dashboard (custom web card) | 🔧 Custom card with WebSocket updates |
| Hint push to room displays | 🔧 Command channel needed (hub → device text message) |
| Timer managed by hub | ✅ Server-side timer with data push |
| Multi-room hub-hosted web app | ✅ M22 hub-hosted web app framework |
| Puzzle automation rules | ✅ Rules engine — "when puzzle_3.solved AND puzzle_5.solved → fire unlock_door" |

### Hub Requirements (RockChip OpenWrt)
- Trivial. No compute-heavy workloads. FastAPI handles WebSocket + rules engine easily.
- This is a perfect ESPai use case — the platform was basically designed for this.

### Platform Gaps Exposed
1. Command channel (hub → device) — only gap for hint pushing
2. Custom card framework needs better documentation/scaffolding

### Moonshot Factor: 🌕🌕 (Medium — highly buildable today)
### MVP Path: 6 weeks. Buildable NOW except for hint-push command channel. Rules engine + multi-room projects make this elegant.

---

## M-11 — Distributed Amateur Radio APRS Digipeater Network

**Vision:** Network of ESP32 nodes with SA818 VHF radio modules acting as APRS digipeaters and i-gates. Hub aggregates position reports, maps local amateur radio activity, and integrates with APRS-IS internet backbone.

### Hardware Stack
- ESP32 + SA818 2m VHF module (serial AT commands)
- TNC modem (could be software modem on ESP32)
- License required: Technician class (USA)

### ESP32 Feasibility

| Concern | Assessment |
|---------|-----------|
| APRS packet encode/decode | ✅ AX.25 + APRS encoding is doable in firmware. TinyAPRS library exists. |
| Audio FSK modem | ⚠️ ESP32 DAC/ADC can handle 1200/2400 baud Bell 202 AFSK. Needs careful timing. |
| SA818 radio control | ✅ UART AT commands |
| APRS-IS connection via hub | ✅ TCP socket from hub to rotate.aprs.net |

### ESPai Platform Readiness

| Feature | Status |
|---------|--------|
| APRS-IS worker | 🔧 Python worker connecting to rotate.aprs.net:14580, filtering local area |
| APRS map card | 🔧 Custom card with Leaflet + APRS symbol set |
| VHF radio station management | 🔧 New device type concept needed |
| Frequency/power management | 🔧 Command channel to adjust SA818 params |

### Moonshot Factor: 🌕🌕 (Medium — niche but technically elegant)
### MVP Path: 3 months. Already near feasibility with SA818 library.

---

## M-12 — Hydroponic Farm Controller

**Vision:** A full climate/nutrient control system for a vertical hydroponic setup. ESP32 controls pH dosing pumps, EC dosing, irrigation cycles, LED grow lighting schedules, exhaust fans, and CO2 injection. Hub monitors all sensors, detects drift, and auto-corrects. AI agent can optimize nutrient formulas based on plant growth data.

### Hardware Stack
- ESP32 (standard)
- Atlas Scientific pH + EC sensors (I2C)
- DS18B20 water temperature probes
- Flow sensors (YF-S201)
- Relay board (8-channel for pumps + lights)
- CO2 sensor (MH-Z19B UART)
- Camera for plant growth timelapse (ESP32-CAM secondary)

### ESP32 Feasibility

| Concern | Assessment |
|---------|-----------|
| pH/EC I2C sensors | ✅ Atlas Scientific EZO circuits are ESP32-compatible |
| Relay control (8 channels) | ✅ Simple GPIO |
| PID control loop (pH/EC) | ✅ Runs easily on one FreeRTOS task |
| Camera timelapse | ✅ Separate ESP32-CAM node; upload via existing image flow |
| Power management | ✅ 24/7 AC-powered system — no battery concern |

### ESPai Platform Readiness

| Feature | Status |
|---------|--------|
| Sensor data push + history | ✅ Perfect fit |
| Rule-based auto-correction | ✅ Rules engine: "pH < 5.8 → trigger pH_up_pump job" |
| Lighting schedule | ✅ Recipes with time-based rules |
| Growth tracking (agent task) | ✅ Agent Bench — "analyze pH/EC trends and suggest adjustments" |
| Custom grow dashboard | 🔧 Custom card with multi-series charts |
| Dosing pump safety limits | 🔧 Rules need a "max trigger count per hour" guard |

### Hub Requirements (RockChip OpenWrt)
- Pure data + rules — trivial compute. This is the ESPai platform's sweet spot.

### Platform Gaps Exposed
1. **Rule rate limiting** — prevent a rule from firing 100× in a minute (safety critical for dosing pumps). Need `max_fires_per_hour` on rules.
2. Custom multi-series chart card
3. Recipe scheduling with cron-like time expressions (currently event-driven only)

### Moonshot Factor: 🌕🌕 (Medium — highly practical, mostly buildable today)
### MVP Path: 4 weeks for a functional 2-pump system. Rules engine + data store cover 80% of this.

---

## M-13 — ESP32 Submarine ROV

**Vision:** Tethered underwater vehicle with ESP32 brain, brushless thrusters, camera, and depth/pressure sensor. WiFi via tether cable (cat5e with PoE). Hub streams video and telemetry; operator controls via hub web interface with gamepad input.

### Hardware Stack
- ESP32-S3 (camera + control)
- BlueRobotics T200 thrusters × 4 (via ESC)
- MS5837 depth/pressure sensor (I2C)
- OV5640 camera
- Cat5e tether (data over Ethernet-via-copper, not WiFi)
- Waterproof enclosure (pressure-rated acrylic tube)

### ESP32 Feasibility

| Concern | Assessment |
|---------|-----------|
| Tethered WiFi | ❌ WiFi doesn't work over cat5e. Need a media converter (MoCA, EoP, or RS-485) or a single-pair Ethernet (T1L). Actually: short tether + WiFi repeater at water surface works for <30m. |
| Camera streaming | ⚠️ ESP32-S3 MJPEG at 320×240 @ 15fps over WiFi — acceptable for ROV piloting |
| Thruster ESC control | ✅ PWM signals to standard RC ESCs |
| Depth sensor | ✅ MS5837 I2C — well supported |
| Pressure housing for ESP32 | Hardware challenge |

### ESPai Platform Readiness

| Feature | Status |
|---------|--------|
| Camera MJPEG stream display | 🔧 Hub-hosted card with `<img>` tag streaming from device IP |
| Gamepad input → device commands | 🔧 Hub frontend needs Gamepad API → WebSocket → command channel |
| Depth/heading telemetry | ✅ Data push works |
| Dive log | ✅ Project data store |

### Platform Gaps Exposed
1. **Real-time video streaming** — ESPai has no video proxy; device MJPEG stream must be accessed directly (not through hub). Hub-proxied streaming would saturate it.
2. **Gamepad API in hub frontend** — browser Gamepad API + WebSocket relay to device command channel
3. **Command channel** (recurring)

### Moonshot Factor: 🌕🌕🌕🌕 (Very High — but hardware complexity is extreme)
### MVP Path: 6 months for tethered ROV with manual control. Tether comms is the primary technical challenge.

---

## M-14 — Predictive HVAC Optimizer

**Vision:** Multi-room temperature/humidity/CO2/occupancy sensor network feeds an ML model that learns your household's thermal behavior and pre-conditions rooms before you need them. Integrates with existing thermostat (Ecobee/Nest API or direct ESP32 thermostat replacement). Reports energy savings.

### Hardware Stack
- ESP32 nodes per room (BME680 + PIR)
- ESP32 thermostat controller (relay for HVAC staging)
- Optional: Shelly for existing thermostat integration

### ESP32 Feasibility
Simple sensor nodes — fully feasible. Thermostat relay control is simple GPIO. The intelligence lives entirely on the hub.

### ESPai Platform Readiness

| Feature | Status |
|---------|--------|
| Per-room sensor data | ✅ Multi-node project, data push per node |
| Occupancy tracking | ✅ PIR event → data push |
| Historical data for ML training | ✅ Data history API |
| Prediction worker (scikit-learn/statsmodels) | 🔧 New worker; runs on hub |
| HVAC command via thermostat relay | ✅ Rules engine → run_worker → send command |
| Energy usage dashboard | 🔧 Custom card |

### Hub Requirements (RockChip OpenWrt)
- ML inference: scikit-learn on 30-day rolling window — runs in ~1s, trivial CPU
- The RockChip is well-suited for this workload

### Platform Gaps Exposed
1. **Scheduled recipe triggers** — "run prediction at 06:00 daily" needs cron-style scheduling, not just event-driven rules
2. **Data aggregation API** — "average temperature per room per hour for the last 30 days" query is not currently supported; raw time-series only
3. External API worker (Ecobee/Nest) — http-poller could handle this

### Moonshot Factor: 🌕🌕🌕 (High — practically valuable, mostly buildable)
### MVP Path: 2 months. Primarily needs scheduled recipe triggers and data aggregation.

---

## M-15 — ESP32 Sonar Fish Finder

**Vision:** A floating ESP32 unit with a waterproof ultrasonic transducer (or fish finder module like AT-08) maps water depth profiles as it's pulled across a lake. GPS correlates depth to position. Hub builds a bathymetric map. Works from a kayak or attached to a trolling motor.

### Hardware Stack
- ESP32 + u-blox GPS
- Garmin Chirp sonar transducer or DIY piezo + driver circuit
- Waterproof enclosure
- LiPo + solar (or 12V boat power via buck converter)

### ESP32 Feasibility

| Concern | Assessment |
|---------|-----------|
| Ultrasonic depth measurement | ⚠️ JSN-SR04T works to ~5m. Real fish finder frequencies (50/200 kHz) need dedicated hardware (AT-08 module, $15). |
| GPS position | ✅ Standard GPS module |
| Local SD buffering | ✅ Use SD card for offline logging when no WiFi |
| WiFi range on water | ❌ Water absorbs 2.4 GHz. Range is much shorter than land. Expect <50m from dock. Buffer to SD, sync when docked. |

### ESPai Platform Readiness

| Feature | Status |
|---------|--------|
| Depth + GPS data push | ✅ Works (when in WiFi range) |
| Bathymetric map card | 🔧 Spatial card with interpolation (IDW from GPS+depth points) |
| Trip summary | ✅ Project data + custom card |
| Offline sync (SD→hub when docked) | 🔧 Bulk data upload endpoint needed |

### Platform Gaps Exposed
1. **Bulk historical data upload** — device accumulates data offline, syncs in bulk when docked. No batch upload API exists.
2. Spatial data card (recurring)
3. Bathymetric interpolation worker

### Moonshot Factor: 🌕🌕 (Medium — niche but delightful)
### MVP Path: 3 months after bulk upload + spatial card exist.

---

## Cross-Cutting Platform Gaps

These gaps appear across multiple moonshots. Addressing them in this order would unlock the most projects:

| Priority | Gap | Unlocks |
|----------|-----|---------|
| 1 | **Binary / file upload from device** | M-01, M-02, M-04, M-07, M-08 |
| 2 | **Hub → device command channel** | M-01, M-02, M-04, M-08, M-10, M-13 |
| 3 | **Spatial / GPS data model + map card** | M-03, M-09, M-11, M-13, M-15 |
| 4 | **Scheduled recipe triggers (cron)** | M-12, M-14 |
| 5 | **LoRa/USB gateway device type** | M-06, M-09, M-11 |
| 6 | **Data aggregation API** (sum/avg/resample) | M-03, M-14 |
| 7 | **Bulk offline data upload** | M-07, M-15 |
| 8 | **Rule rate limiting** | M-12 |
| 9 | **Media / binary file store** (images, audio, not just JSON) | M-04, M-07 |

---

## ESP32 Hardware Ceiling

A realistic summary of what the ESP32 family can and can't do, based on the projects above:

| Capability | Verdict |
|-----------|---------|
| Sensor I/O (I2C, SPI, UART, ADC) | ✅ Excellent |
| WiFi + BLE | ✅ Excellent |
| LoRa / 900 MHz radio (with module) | ✅ Good |
| Motor control (PWM, stepper) | ✅ Good |
| Camera capture (JPEG snapshots) | ✅ Good on -S3 |
| MJPEG streaming | ⚠️ Acceptable at 320×240 15fps |
| Audio capture (I2S mic) | ✅ Good |
| Audio playback (I2S DAC) | ✅ Good for pre-encoded clips |
| On-device ML inference (tiny models) | ⚠️ Marginal — tiny datasets, low accuracy |
| On-device audio fingerprinting | ❌ Not feasible |
| On-device face recognition | ❌ Not feasible |
| Real-time video encoding | ❌ Not feasible (no hardware encoder) |
| Long battery life (sleep mode) | ✅ Excellent |
| Deep sleep with wake-on-event | ✅ Excellent |
| Hard real-time (μs-level) | ⚠️ Use hardware timers; WiFi causes jitter |

---

## Hub (RockChip OpenWrt) Ceiling

| Workload | Verdict |
|---------|---------|
| FastAPI + SQLite serving 50 devices | ✅ Well within limits |
| Python ML inference (scikit-learn, statsmodels) | ✅ Fine for batch |
| OpenCV image processing (1 fps) | ✅ Acceptable |
| BirdNET acoustic inference | ✅ ~3s per clip at CPU |
| Face recognition (dlib, single frame) | ⚠️ 2-4s per frame — OK for doorbell, not streaming |
| Real-time video transcoding | ❌ Not feasible on RockChip |
| Concurrent ML from 10+ nodes simultaneously | ❌ Saturates CPU; needs job queue + rate limiting |
| WebSocket connections (50+) | ✅ Fine |
| Serving hub-hosted web apps | ✅ Trivial |
| Docker containers | ⚠️ Depends on OpenWrt kernel; not all RockChip builds support cgroups v2 |

### When you need more than a RockChip:
- Any project with real-time video processing (face detection at stream rate)
- 10+ concurrent ML inference nodes
- Training ML models locally (send data to a PC or cloud for training)
- Docker-heavy workloads

### Upgrade path:
- **Raspberry Pi 5 (8 GB)** — 4× the CPU, NPU, better Docker support. Drop-in for most RockChip use cases.
- **Dedicated GPU node (RTX 3060 or better)** — unlocks real-time face recognition, BirdNET at 100+ nodes, MJPEG transcoding, local LLM inference.
- **Keep RockChip** for device management, data ingestion, and light workers. Add GPU node for heavy inference via a worker that POSTs to the GPU node's API.

---

## Future Moonshots (Stubs — Needs Full Spec)

- **ESP32 Seismograph** — ADXL355 high-precision accelerometer; detect micro-earthquakes, footsteps, machinery vibration. Hub correlation across multiple nodes to triangulate source.
- **Astronomical Tracking Mount** — ESP32 controls stepper-driven equatorial mount for telescope. Hub calculates RA/Dec targets from GPS + time. Agent suggests objects based on conditions.
- **ESP32 Electroculture Fence** — Pulsed high-voltage DC around garden perimeter to stimulate plant growth and deter pests. ESP32 controls pulse frequency; hub monitors soil sensor responses.
- **Distributed Solar Irradiance Monitor** — Network of TSL2591 light sensors measure solar irradiance across property for PV siting analysis.
- **Smart Compost Monitor** — Temperature probes at multiple depths + moisture + CO2; hub models aerobic decomposition rate; alerts when turning needed; predicts compost readiness date.
- **Amateur Meteor Radio Detection** — SDR dongle via USB hub + worker detects meteor forward scatter signatures on 143.050 MHz (GRAVES radar); logs meteor shower intensity over time.
- **ESP32 Muscle Stimulation / TENS Controller** — (Medical device territory — heavy regulatory caveat) Tunable TENS pulses; hub monitors usage; AI agent suggests protocols based on feedback.
- **Hyperlocal Weather Station Network** — Multiple ESP32 weather stations; hub does spatial interpolation; detects microclimates; integrates with Open-Meteo for bias correction.

---

## Platform Progress Log

Hypothetical ratings against the moonshot test suite. Each entry is a snapshot of how well the current ESPai version handles the moonshot challenge set. Ratings are based on the cross-cutting gap table — how many of the 9 critical gaps are addressed, weighted by impact.

Rating methodology: Start at 10.0. Deduct per-gap based on how many moonshots it blocks and how hard it is to work around without the platform feature. Add back as gaps close.

| Date | Version | Score | Blocking Issues |
|------|---------|-------|----------------|
| 2026-06-04 | 0.3.5 | **4.8/10** | Binary/file upload from device missing (-2.0); no hub→device command channel (-1.5); no spatial/GPS data model (-0.8); no scheduled recipe triggers/cron (-0.4); no bulk offline upload (-0.3); no data aggregation API (-0.2) |

### Gap Score Breakdown (0.3.5)

| Gap | Impact | Status | Deduction |
|-----|--------|--------|-----------|
| Binary upload from device | Blocks 5 moonshots; core media/AI pipeline | ❌ Missing | -2.0 |
| Hub → device command channel | Blocks 6 moonshots; all bidirectional control | ❌ Missing | -1.5 |
| Spatial / GPS data + map card | Blocks 4 moonshots | ❌ Missing | -0.8 |
| Scheduled recipe triggers (cron) | Blocks 2 moonshots | ❌ Missing | -0.4 |
| LoRa / USB gateway device type | Blocks 3 moonshots (niche use cases) | ❌ Missing | -0.2 |
| Data aggregation API (avg/sum/resample) | Limits analytics depth | ❌ Missing | -0.2 |
| Bulk offline data upload | Blocks offline-first mobile nodes | ❌ Missing | -0.3 |
| Rule rate limiting | Safety gap for actuator projects | ❌ Missing | -0.1 |
| Media / binary file store | Blocks image/audio persistence | ❌ Missing | -0.2 |
| Device management, OTA, pairing | Solid foundation | ✅ | +0 (baseline) |
| Project + worker + recipe system | Well-built, agent-integrated | ✅ | +0 (baseline) |
| Rules engine + event bus | Functional for text/JSON events | ✅ | +0 (baseline) |
| Hub-hosted web apps | Good scaffolding | ✅ | +0 (baseline) |
| Git version control (projects + workers) | Excellent developer ergonomics | ✅ | +0 (bonus) |
| Agent Bench (auto-apply, git rollback) | Strong development acceleration | ✅ | +0 (bonus) |

**What lifts the score most:** Binary upload from device and the hub→device command channel together would bring the score to ~8.3/10 and unblock the majority of moonshots. They are the two features with the highest leverage in the entire platform.

*Update this table each release. Track which gaps close and recalculate.*
