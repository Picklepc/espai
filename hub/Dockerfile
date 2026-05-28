FROM python:3.12-slim

LABEL org.opencontainers.image.title="ESPai Hub"
LABEL org.opencontainers.image.description="Local-first ESP32 fleet and edge-processing platform"

WORKDIR /app

# Install requirements first (better layer caching)
COPY hub/backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the full project tree
# Runtime volumes (data/, projects/, etc.) are mounted by docker-compose
COPY . .

# The hub writes to /data at runtime — ensure the dir exists
RUN mkdir -p /data /projects /firmware-catalog

EXPOSE 7888

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:7888/api/status')" || exit 1

CMD ["uvicorn", "hub.backend.main:app", \
     "--host", "0.0.0.0", \
     "--port", "7888", \
     "--workers", "1", \
     "--log-level", "info"]
