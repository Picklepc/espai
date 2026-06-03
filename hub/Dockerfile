FROM python:3.12-slim

LABEL org.opencontainers.image.title="ESPAI Hub"
LABEL org.opencontainers.image.description="Local-first ESP32 fleet and edge-processing platform"

WORKDIR /app

ENV PYTHONUNBUFFERED=1

# ── Base system dependencies ──────────────────────────────────────────────────
# Node.js 18 LTS (Debian bookworm) — needed for Claude Code CLI.
RUN apt-get update && apt-get install -y --no-install-recommends \
        nodejs \
        npm \
        curl \
        git \
    && rm -rf /var/lib/apt/lists/*

# ── Claude Code CLI (optional) ───────────────────────────────────────────────
# Pass --build-arg INSTALL_CLAUDE=false to skip (produces a ~100 MB smaller image).
# Set ANTHROPIC_API_KEY + ESPAI_AGENT_BENCH=true at runtime to use Agent Bench.
ARG INSTALL_CLAUDE=true
RUN if [ "$INSTALL_CLAUDE" = "true" ]; then \
        npm install -g @anthropic-ai/claude-code --no-audit --no-fund \
        || echo "WARNING: Claude Code CLI install failed — Agent Bench will not work"; \
    fi

# ── Worker dependencies (optional) ───────────────────────────────────────────
# Enables the bundled workers that require OpenCV, FFmpeg, numpy, or Pillow:
#   opencv-motion-tagger   ffmpeg-compressor   (and any user workers using these)
#
# Pass --build-arg INSTALL_WORKER_DEPS=true to include (:workers variant).
# Adds ~400 MB; uses opencv-python-headless (no X11 required).
ARG INSTALL_WORKER_DEPS=false
RUN if [ "$INSTALL_WORKER_DEPS" = "true" ]; then \
        apt-get update && apt-get install -y --no-install-recommends \
            ffmpeg \
            libgl1 \
            libglib2.0-0 \
        && rm -rf /var/lib/apt/lists/* \
        && pip install --no-cache-dir \
            opencv-python-headless \
            numpy \
            Pillow \
            scipy; \
    fi

# ── PlatformIO (optional) ─────────────────────────────────────────────────────
# Enables in-container ESP32 firmware builds for the :dev image variant.
# Pass --build-arg INSTALL_PIO=true to include.
#
# The ESP32 toolchain (~600 MB) is downloaded by PIO on first use — mount
# ESPAI_SSD_PATH/platformio to /root/.platformio in docker-compose so the
# toolchain survives container restarts and isn't re-downloaded each time.
ARG INSTALL_PIO=false
RUN if [ "$INSTALL_PIO" = "true" ]; then \
        pip install --no-cache-dir platformio; \
    fi

# ── Core Python dependencies ──────────────────────────────────────────────────
# Installed before the code copy so this layer is reused on code-only changes.
COPY hub/backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# ── Application code ──────────────────────────────────────────────────────────
COPY . .

# Entrypoint handles optional worker dep preloading before starting uvicorn
COPY hub/docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

# Runtime data directories — override with volume mounts in docker-compose
# so user data lands on the SSD rather than the container layer.
RUN mkdir -p data projects firmware-catalog

EXPOSE 7888

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c \
        "import urllib.request; urllib.request.urlopen('http://localhost:7888/api/status')" \
        || exit 1

ENTRYPOINT ["/docker-entrypoint.sh"]
