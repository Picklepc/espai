# ESPAI Hub

Backend and frontend for the ESPAI local platform.

## Quick start

```bash
# 1. Install dependencies
python ESPAI.py install-deps

# 2. Initialize workspace
python ESPAI.py init

# 3. Check environment
python ESPAI.py doctor

# 4. Start the hub
python ESPAI.py serve
```

Dashboard: http://localhost:7888/
API docs:  http://localhost:7888/docs

## Structure

```
hub/
  backend/
    main.py          FastAPI app entry point
    config.py        Paths and env-var config
    db.py            SQLite init and connection helper
    requirements.txt Python dependencies
    routers/
      devices.py     Device registry, checkin, pairing
      projects.py    Project CRUD
      recipes.py     Recipe registry (reads recipes/ folder)
      workers.py     Worker registry (reads workers/ folder)
      cards.py       Card registry (reads cards/ folder)
      design.py      Theme/token loader (reads design/ folder)
      ota.py         OTA catalog and push scaffold
      jobs.py        Worker job queue
      events.py      Local event bus + SSE stream
    registry/
      loader.py      YAML manifest scanner for all primitives
    discovery/
      mdns.py        mDNS hub advertisement + node discovery
      scanner.py     Subnet scan scaffold (HTTP probe)
  frontend/
    index.html       Dashboard shell
    static/
      css/app.css    Design-token-driven stylesheet
      js/api.js      API client (fetch wrapper)
      js/app.js      Dashboard app logic
```

## Environment variables

| Variable       | Default     | Description             |
|----------------|-------------|-------------------------|
| ESPAI_HOST     | 0.0.0.0     | Bind address            |
| ESPAI_PORT     | 7888        | Bind port               |
| ESPAI_DEBUG    | 0           | Enable debug logging    |

Set in `.env` at the repo root (gitignored).

## API summary

| Method | Path                      | Description                  |
|--------|---------------------------|------------------------------|
| GET    | /api/status               | Hub health check             |
| GET    | /api/devices/             | List fleet devices           |
| POST   | /api/devices/checkin      | Node checkin (called by node)|
| POST   | /api/devices/manual       | Add device by IP             |
| POST   | /api/devices/pair/initiate/{id} | Generate pairing token |
| POST   | /api/devices/pair/confirm | Confirm pairing              |
| GET    | /api/recipes/             | List recipes                 |
| GET    | /api/workers/             | List workers                 |
| GET    | /api/cards/               | List cards                   |
| GET    | /api/design/tokens        | Active theme tokens          |
| POST   | /api/jobs/submit          | Queue a worker job           |
| GET    | /api/ota/catalog          | Firmware catalog             |
| POST   | /api/ota/push             | Push firmware to device      |
| GET    | /api/events/stream        | SSE event stream             |
