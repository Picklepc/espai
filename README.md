# ESPAI

[![Latest Release](https://img.shields.io/github/v/release/Picklepc/espai?label=download&color=teal)](https://github.com/Picklepc/espai/releases/latest)
[![Docker](https://img.shields.io/badge/docker-ghcr.io%2Fpicklepc%2Fespai-blue?logo=docker)](https://github.com/Picklepc/espai/pkgs/container/espai)

ESPAI is a local-first platform for replacing cloud apps with custom LAN-hosted applications — and for building and deploying custom projects with extended support for ESP32 firmware and development.

Tagline: **A local space for custom connected device projects.**

## Download

| Platform | Download | Notes |
|---|---|---|
| **Windows** | [ESPAI-Setup-\*.exe](https://github.com/Picklepc/espai/releases/latest) | Run the installer — no admin required. Installs to `%LOCALAPPDATA%\Programs\ESPAI`. |
| **Linux x86-64** | [ESPAI-\*-x86_64.AppImage](https://github.com/Picklepc/espai/releases/latest) | `chmod +x` then run — no install needed |
| **Docker** (amd64 / arm64) | `ghcr.io/picklepc/espai:latest` | Headless, always-on. Ideal for routers and NAS. |

**Windows:** Run the installer → ESPAI starts silently in the system tray.
Right-click the tray icon to open the dashboard, view logs, or toggle start-at-login.
User data is stored in `%USERPROFILE%\Documents\ESPAI` and survives updates.

**Linux:** Works on Ubuntu, Fedora, Arch, and most x86-64 distros without installation.
System tray requires a compatible desktop environment (GNOME + AppIndicator, KDE Plasma, etc.).
Run `./ESPAI-*.AppImage serve` from a terminal to start the hub directly.

**Docker:**
```bash
# Pull and run (amd64 or arm64 selected automatically)
docker run -d \
  --name espai \
  --network host \
  --restart unless-stopped \
  -v /your/data/path/data:/app/data \
  -v /your/data/path/projects:/app/projects \
  -v /your/data/path/firmware-catalog:/app/firmware-catalog \
  ghcr.io/picklepc/espai:latest

# Update to latest
docker pull ghcr.io/picklepc/espai:latest
docker stop espai && docker rm espai
# re-run the command above
```

Three image variants are available — `:latest` (full dev, includes Claude CLI + PlatformIO),
`:workers` (+ OpenCV/FFmpeg/numpy), and `:slim` (hub only, smallest).
Both `:v0.x.y` and `:0.x.y` tag formats work for pinning to a specific release.

## What It Does

ESPAI runs entirely on your LAN — no cloud required, no subscription, no data leaving your network.
A Python FastAPI hub is the always-on control plane for three project types:

| Type | What it does |
|---|---|
| **ESP32 Node** | Custom firmware (PlatformIO, C++) on an ESP32 — hub stores readings, delivers OTA updates |
| **API Integration** | Hub worker that polls or subscribes to any WiFi device through its local API — no firmware changes needed |
| **Hybrid Bridge** | ESP32 acting as a BLE/serial bridge, plus a hub integration worker that consumes the bridge |

Build a custom local app to replace a vendor cloud dashboard — for your thermostat, smart plugs, camera, NAS, irrigation controller, or any device with a local HTTP/MQTT/WebSocket API. Or build custom ESP32 nodes from scratch. Either way, the hub stores data, runs processing workers, hosts the web UI, and delivers firmware OTA.

## Features

- Custom ESP32 firmware scaffold — PlatformIO projects, per-project build flags, OTA delivery
- API integration scaffold — HTTP polling, MQTT subscription, WebSocket workers out of the box
- Device discovery — mDNS browse, subnet scan, manual IP add, pairing token flow
- Hub data store — time-series push/pull, bulk offline upload, spatial/GPS queries, geofence events
- Python workers — image processing, telemetry, protocol bridging, event generation
- Reusable UI cards, device recipes, design themes, and Python worker definitions
- OTA with SHA-256 verification, board compatibility check, staged rollout, and rollback
- Agent Bench — run Claude and Codex autonomously on project tasks; git rollback for review
- Local event bus, rules engine (cron + timezone, rate limiting), MQTT output, browser push
- Hub → device command channel — enqueue commands, device polls and acks
- Media store — binary file upload from firmware (`espai_upload_jpeg()`), gallery, quota guard
- **Matter bridge** — hub-hosted aggregator; commission once, every opted-in project appears in Google Home, HomeKit, and Alexa automatically
- Per-project Git history and code editor built into the hub
- Docker appliance (ARM64) for always-on router or NAS deployment
- Windows tray app and installer; Linux AppImage

## Mission

ESPAI should make it easy to build, maintain, and deploy custom local applications for any connected device — whether that means writing ESP32 firmware from scratch or writing a worker that talks to a device's existing API — without cloud lock-in, vendor dashboards, or duplicated boilerplate.

ESP32 nodes focus on hardware, real-time loops, safety, sleep/wake, and minimal APIs.
Integration workers focus on HTTP/MQTT/WebSocket protocol bridging and data normalisation.
The hub stores, aggregates, schedules, and serves — for both.

## License

MIT
