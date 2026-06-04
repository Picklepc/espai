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

# ── Seed and update bundled content packs ────────────────────────────────────
# Runs on every container start (idempotent):
#   - New items missing from the bind-mount are always copied in.
#   - Existing official items are updated when the bundled YAML version is newer.
#   - User-configured fields (enabled, startup) are preserved on updates.
# This replaces the old single-sentinel approach so pulling a new image
# automatically delivers updated and new bundled workers/recipes/cards.

_yaml_field() {
    # Usage: _yaml_field <file> <field>  — returns first match, strips quotes
    grep -m1 "^${2}:" "$1" 2>/dev/null | awk '{print $2}' | tr -d "\"'"
}

for dir in workers recipes cards; do
    target="/app/${dir}"
    src="/app-bundled/${dir}"
    [ -d "$src" ] && [ -d "$target" ] || continue

    for item_src in "$src"/*/; do
        [ -d "$item_src" ] || continue
        name=$(basename "$item_src")
        item_dst="$target/$name"
        yaml_src=$(ls "$item_src"*.yaml 2>/dev/null | head -1)
        [ -n "$yaml_src" ] || continue

        if [ ! -d "$item_dst" ]; then
            # New item — seed it
            echo "[ESPAI] Seeding new ${dir}/${name}…"
            cp -r "$item_src" "$item_dst"
        else
            # Existing item — update if bundled version is newer
            yaml_dst=$(ls "$item_dst/"*.yaml 2>/dev/null | head -1)
            [ -n "$yaml_dst" ] || continue
            src_ver=$(_yaml_field "$yaml_src" "version")
            dst_ver=$(_yaml_field "$yaml_dst" "version")
            if [ -n "$src_ver" ] && [ -n "$dst_ver" ] && [ "$src_ver" != "$dst_ver" ]; then
                echo "[ESPAI] Updating ${dir}/${name} (${dst_ver} -> ${src_ver})…"
                # Preserve user-configured fields
                u_enabled=$(_yaml_field "$yaml_dst" "enabled")
                u_startup=$(_yaml_field  "$yaml_dst" "startup")
                tmp="${item_dst}.update.$$"
                cp -r "$item_src" "$tmp"
                new_yaml=$(ls "$tmp/"*.yaml 2>/dev/null | head -1)
                if [ -n "$new_yaml" ]; then
                    [ -n "$u_enabled" ] && sed -i "s/^enabled:.*/enabled: $u_enabled/" "$new_yaml"
                    [ -n "$u_startup" ] && sed -i "s/^startup:.*/startup: $u_startup/" "$new_yaml"
                fi
                rm -rf "$item_dst"
                mv "$tmp" "$item_dst"
            fi
        fi
    done
done

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
