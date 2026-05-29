# ESPAI

[![Latest Release](https://img.shields.io/github/v/release/espai/espai?label=download&color=teal)](https://github.com/espai/espai/releases/latest)

ESPAI is a local-first ESP32 development, deployment, and edge-processing platform.

Tagline: **A local space for custom ESP32 projects.**

## Download

| Platform | File | Notes |
|---|---|---|
| **Windows** | [ESPAI-Setup.exe](https://github.com/espai/espai/releases/latest) | Run the installer — no admin required |
| **Linux** | [ESPAI-x86_64.AppImage](https://github.com/espai/espai/releases/latest) | `chmod +x` then run — no install needed |

**Windows:** Run the installer → ESPAI appears silently in the system tray.
Right-click the icon to open the dashboard, view live logs, or toggle start-at-login.

**Linux:** Works on Ubuntu, Fedora, Arch, and most x86-64 distros without installation.
System tray requires a compatible desktop environment (GNOME + AppIndicator extension, KDE Plasma, etc.).
You can always run `./ESPAI-*.AppImage serve` from a terminal to start the hub directly.

ESPAI helps users turn unique ESP32 ideas into deployable projects with reusable infrastructure:
- seed firmware
- device discovery
- OTA and rollback
- reusable UI cards
- portable device recipes
- reusable Python workers
- design themes and skins
- local notifications
- telemetry history
- protocol knowledge sharing without exposing secrets
- Simulated QEMU ESP32 firmware, fake nodes, and/or firmware aware simulators that simulate project behavior from manifests, recipes, test data, and mocked sensors.

## Mission

ESPAI should make custom one-off embedded projects easier to create, maintain, share, and deploy without cloud lock-in or duplicated boilerplate.

ESP32 nodes focus on hardware, realtime loops, safety, sleep/wake, and minimal APIs.

ESPAI Hub hosts the UI, database, project folders, cards, recipes, workers, design system, firmware catalog, OTA orchestration, notifications, and local processing.

## Headline Feature: Python Workers

Let ESP32s collect and control. Let ESPAI think.

ESPAI can process ESP32 data with Python workers using tools like OpenCV, FFmpeg, NumPy, protocol decoders, and local ML models.

## License

MIT
