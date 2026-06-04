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

# ── Seed bundled content packs into empty bind-mounts ────────────────────────
# When workers/, recipes/, or cards/ are bind-mounted from the NVMe they start
# empty, hiding the bundled starters.  Copy them in on first run (sentinel guards
# against overwriting user edits on subsequent restarts).
SENTINEL=/app/data/.content-seeded
if [ ! -f "$SENTINEL" ]; then
    for dir in workers recipes cards; do
        target="/app/${dir}"
        # Only seed if the bind-mount exists but is empty (no subdirectories)
        if [ -d "$target" ] && [ -z "$(find "$target" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | head -1)" ]; then
            src="/app-bundled/${dir}"
            if [ -d "$src" ]; then
                echo "[ESPAI] Seeding ${dir}/ from bundled image content…"
                cp -rn "${src}/." "${target}/" 2>/dev/null || true
            fi
        fi
    done
    mkdir -p /app/data && touch "$SENTINEL"
fi

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

# ── Network share permissions ─────────────────────────────────────────────────
# Docker runs as root, so bind-mounted directories are root-owned.
# Samba/NFS on the host runs as a different user and can't delete root files.
# Setting g+rwX,o+rwX makes the share fully writable from the host.
# Opt out by setting ESPAI_SKIP_SHARE_CHMOD=1 in docker-compose environment.
if [ "${ESPAI_SKIP_SHARE_CHMOD:-0}" != "1" ]; then
    for d in /app/data /app/projects /app/firmware-catalog \
              /app/workers /app/recipes /app/cards; do
        [ -d "$d" ] && chmod -R g+rwX,o+rwX "$d" 2>/dev/null || true
    done
fi

# ── Git identity ─────────────────────────────────────────────────────────────
# Required for project auto-commit and Agent Bench task commits.
# Override via GIT_USER_EMAIL / GIT_USER_NAME env vars in docker-compose.
git config --global user.email "${GIT_USER_EMAIL:-espai@hub}" 2>/dev/null || true
git config --global user.name  "${GIT_USER_NAME:-ESPAI Hub}"  2>/dev/null || true

# ── Start hub ─────────────────────────────────────────────────────────────────
exec uvicorn hub.backend.main:app \
    --host 0.0.0.0 \
    --port 7888 \
    --workers 1 \
    --log-level info
