You are developing ESPAI.

ESPAI is a local-first ESP32 development, deployment, fleet management, protocol research, and edge-processing platform.

ESPAI should feel like:
- a local GitHub for ESP32 projects
- a fleet manager for embedded nodes
- a protocol workshop for weird hardware
- a Python edge-processing platform
- a reusable dashboard/card ecosystem
- a Tasmota-like starting point for custom one-off projects
- a local appliance similar to Jellyfin or Home Assistant

ESPAI is NOT:
- cloud-first
- enterprise SaaS
- ad-supported
- telemetry-harvesting
- dependent on remote servers
- tightly coupled to one editor or OS

Core philosophy:

ESP32 nodes should focus on:
- hardware IO
- realtime loops
- safety-critical behavior
- local autonomy
- sleep/wake behavior
- lightweight APIs
- OTA receiver
- direct realtime sessions when needed

ESPAI Hub should focus on:
- web UI
- project management
- reusable cards
- reusable workers
- reusable recipes
- design system
- telemetry storage
- notifications
- OTA orchestration and rollback
- Python processing
- simulations
- logs/history
- reverse proxy
- event bus
- automation
- protocol knowledge organization

Primary architecture rule:

Do not build one-off project logic when a reusable platform primitive is more appropriate.

Reusable primitives include:
- cards
- recipes
- workers
- themes
- skins
- templates
- schemas
- policies
- simulators
- shared firmware modules

Always look for opportunities to generalize reusable infrastructure.

==================================================
REPOSITORY STRUCTURE
==================================================

Read and respect the `.agent/` folder before making changes.

The `.agent/` folder is the behavioral and architectural constitution of ESPAI.

Important files:
- .agent/AGENT_RULES.md
- .agent/PROJECT_PERSONALITY.md
- .agent/SECURITY_RULES.md
- .agent/WORKER_RULES.md
- .agent/DESIGN_RULES.md
- .agent/ESP32_RULES.md

The filesystem is intentionally plain-text and VSCode-friendly.

Major folders:

hub/
- backend
- frontend
- APIs
- database
- event bus
- OTA coordination
- notifications
- registry
- project manager

firmware/
- ESP32 seed firmware
- shared ESP32 libraries
- OTA support
- node APIs

recipes/
Portable protocol/interface definitions.

Recipes support:
- BLE
- CAN
- RS485
- UART
- I2C
- SPI
- GPIO
- HTTP
- MQTT
- Modbus
- IR
- OneWire
- custom transports

Recipes separate:
- public protocol knowledge
- compatibility metadata
- implementation status
- references
- sanitized examples
- private overlays
- local secrets

workers/
Reusable processing modules.

Workers may use:
- Python
- OpenCV
- FFmpeg
- NumPy
- Pandas
- local ML
- telemetry analysis
- protocol decoding
- metadata extraction

Workers are reusable modules similar to recipes.

Workers must declare:
- runtime
- inputs
- outputs
- permissions
- resource cost
- sandbox preferences
- network access
- secret access

Imported workers start quarantined until reviewed.

cards/
Reusable UI components.

Cards:
- consume capability data
- consume worker outputs
- use design tokens
- avoid project-specific styling

design/
Global design system.

Contains:
- themes
- skins
- nav layouts
- design tokens
- dynamic theme rules

Dynamic skins/themes may eventually respond to:
- time of day
- season
- holiday
- weather
- alerts
- device states
- project modes

policies/
Security and runtime policies.

schemas/
JSON schemas for:
- recipes
- workers
- themes
- cards
- projects
- firmware metadata
- policies

simulators/
Simulation and testing infrastructure.

Simulator types:
- fake API nodes
- telemetry replay
- fake BMS
- fake camera
- fake GPIO node
- QEMU-based ESP32 simulation
- worker testing harnesses

deploy/
Deployment modes:
- native fast-start
- Docker appliance
- future Windows tray app

docs/
Architecture, setup, roadmap, and platform documentation.

==================================================
PLATFORM GOALS
==================================================

ESPAI must support:
- native local execution
- Docker appliance deployment
- future Windows tray app
- offline-first operation
- LAN-only operation
- VSCode workflows
- Codex workflows
- Git-friendly editing
- portable project folders

ESPAI should eventually support:
- OTA staging
- rollback
- firmware channels
- project templates
- simulation labs
- multi-node applications
- distributed low-cost node services
- local event automation
- local AI workflows
- realtime direct node sessions
- future VSCode extension support

==================================================
SIMULATION MODEL
==================================================

ESPAI should support multiple simulation tiers:

Tier 1:
Fake API nodes for dashboard/testing.

Tier 2:
Behavior-aware simulators using replayed telemetry/media.

Tier 3:
QEMU-based ESP32 simulation where practical.

Do NOT assume all ESP32 hardware/peripherals can be fully emulated.

Simulators should expose the same fleet APIs as real nodes.

==================================================
SECURITY MODEL
==================================================

Unsafe actions must be deliberate.

OTA:
- requires pairing
- requires compatibility validation
- requires checksum validation
- requires audit logging

Recipes:
- must support sanitization
- must separate public and private knowledge

Workers:
- may execute arbitrary code
- therefore require permissions and sandboxing
- imported workers default to quarantined

Never expose secrets in Git.

Never hardcode:
- Wi-Fi credentials
- API keys
- MAC addresses
- GPS locations
- personal infrastructure names
- local network topology

==================================================
DESIGN MODEL
==================================================

Cards must consume design tokens.

Do not hardcode major visual styling inside cards.

ESPAI should support:
- global themes
- project overrides
- skins
- nav presets
- future dynamic/seasonal themes

Default UI feel:
- dark
- clean
- garage-lab
- touch friendly
- mobile friendly
- low clutter
- fast loading

==================================================
PYTHON WORKERS
==================================================

Python workers are a headline ESPAI feature.

Motto:
“Let ESP32s collect. Let ESPAI think.”

ESP32 nodes should offload:
- image processing
- video transcoding
- ML inference
- protocol analysis
- telemetry analysis
- report generation
- metadata extraction

Workers should run:
- natively
- or as Docker sidecars

Workers must use a job queue.
Do not block the hub with heavy processing.

==================================================
DEVELOPMENT RULES
==================================================

Prefer:
- clear architecture
- schemas
- reusable interfaces
- TODOs for incomplete systems
- buildable scaffolds
- incremental milestones

Avoid:
- fake completeness
- giant monolithic commits
- hardcoded project logic
- tightly coupled modules
- cloud dependencies
- duplicated implementations

Every major change should explain:
- what changed
- why
- how to test
- what remains TODO

==================================================
CURRENT TASK
==================================================

First focus:
1. Buildable scaffold
2. Native fast-start CLI
3. Hub/backend structure
4. Seed firmware compilation
5. Registry systems
6. Recipes/workers/cards/design parsers
7. Basic dashboard
8. Discovery/pairing scaffolding
9. Worker/job scaffolding
10. OTA metadata scaffolding

Do not overbuild advanced features yet.
Provision them cleanly with schemas/docs/placeholders.

Prioritize architecture and maintainability over flashy UI.