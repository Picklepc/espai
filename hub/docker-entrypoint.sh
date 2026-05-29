#!/bin/bash
# ESPAI Hub — Docker entrypoint
#
# Runs optional worker dependency pre-installation before starting uvicorn.
# Two mechanisms are supported (both may be used together):
#
#   1. ESPAI_PREINSTALL env var — space or comma-separated package list
#      Good for simple cases directly in docker-compose.yml:
#        ESPAI_PREINSTALL: "opencv-python-headless numpy scipy"
#
#   2. Mounted requirements file — full pip requirements.txt format
#      Good for version-pinned or complex dependency lists:
#        volumes:
#          - ./worker-requirements.txt:/preload/requirements.txt
#
# Packages installed here are ephemeral (container layer only).
# To make them permanent, rebuild using the :workers image variant or
# add them to your own Dockerfile that extends the ESPAI base image.

set -e

# ── File-based preload ────────────────────────────────────────────────────────
if [ -f /preload/requirements.txt ]; then
    echo "[ESPAI] Pre-installing worker dependencies from /preload/requirements.txt…"
    pip install --no-cache-dir -r /preload/requirements.txt
    echo "[ESPAI] Pre-install complete."
fi

# ── Env-var preload ───────────────────────────────────────────────────────────
if [ -n "$ESPAI_PREINSTALL" ]; then
    # Allow comma or space separated: "opencv-python-headless,numpy scipy"
    PKGS=$(echo "$ESPAI_PREINSTALL" | tr ',' ' ')
    echo "[ESPAI] Pre-installing: $PKGS"
    pip install --no-cache-dir $PKGS
    echo "[ESPAI] Pre-install complete."
fi

# ── Start hub ─────────────────────────────────────────────────────────────────
exec uvicorn hub.backend.main:app \
    --host 0.0.0.0 \
    --port 7888 \
    --workers 1 \
    --log-level info
