# ESPAI Agent Rules

You are developing ESPAI, a local-first ESP32 development, fleet, and edge-processing platform.

## Prime Directive

Do not build one-off features when a reusable primitive is appropriate.

Reusable primitives:
- cards
- recipes
- workers
- schemas
- policies
- templates
- shared firmware modules
- simulators

## Architecture

Hub owns web UI, cards, recipes, workers, firmware catalog, OTA, logs, telemetry, database, notifications, reverse proxy, project scaffolding, and design system.

ESP32 owns realtime IO, safety logic, fallback, sleep/wake, minimal APIs, OTA receiver, and offline autonomy.

## Rules

- Local-first by default.
- No hardcoded personal networks or secrets.
- Imported workers start quarantined.
- OTA must be paired, explicit, checksummed, and logged.
- Cards consume design tokens.
- Recipes and workers must be plain folder/text formats.
- Prefer clear scaffolds over fake complete features.
