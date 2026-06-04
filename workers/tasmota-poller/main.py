"""
Tasmota Poller — fetches device state via the Tasmota HTTP API and pushes
readings to the ESPAI hub data store.

Required env vars:
  TASMOTA_HOST       IP or hostname (e.g. 192.168.1.42)
Optional env vars:
  TASMOTA_PASSWORD   Web UI password (if configured on the device)
  ESPAI_HUB_URL      Hub base URL (default: http://localhost:7888)
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


HOST     = os.environ.get("TASMOTA_HOST", "").rstrip("/")
PASSWORD = os.environ.get("TASMOTA_PASSWORD", "")
HUB_URL  = os.environ.get("ESPAI_HUB_URL", "http://localhost:7888").rstrip("/")


def _tasmota_cmd(cmd: str) -> dict:
    params = {"cmnd": cmd}
    if PASSWORD:
        params["user"] = "admin"
        params["password"] = PASSWORD
    url = f"http://{HOST}/cm?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "ESPAI-Hub"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def _push_to_hub(project_id: str, data: dict, device_id: str = "") -> None:
    body = json.dumps(data).encode()
    req  = urllib.request.Request(
        f"{HUB_URL}/api/projects/{project_id}/data",
        data=body, method="POST",
        headers={"Content-Type": "application/json", "X-Device-ID": device_id or HOST},
    )
    try:
        urllib.request.urlopen(req, timeout=5)
    except Exception as exc:
        print(f"hub push failed: {exc}", file=sys.stderr)


def run(inputs: dict) -> dict:
    project_id = inputs.get("project_id", "")
    if not HOST:
        raise RuntimeError("TASMOTA_HOST env var is required")

    state: dict = {}
    events = []

    # Status 0 — full device status
    try:
        full = _tasmota_cmd("Status 0")
        status = full.get("Status", {})
        status_sns = full.get("StatusSNS", {})
        status_sts = full.get("StatusSTS", {})

        # Power state
        power = status_sts.get("POWER") or status.get("Power")
        if power is not None:
            state["power"] = power == "ON" or power == 1

        # Energy monitoring (if present)
        energy = status_sns.get("ENERGY") or status_sts.get("ENERGY")
        if energy:
            for key in ("Voltage", "Current", "Power", "Today", "Total"):
                if key in energy:
                    state[key.lower()] = energy[key]

        # Generic sensors (AM2301, DS18B20, etc.)
        for sensor_name, sensor_data in status_sns.items():
            if isinstance(sensor_data, dict):
                for k, v in sensor_data.items():
                    if isinstance(v, (int, float)):
                        state[f"{sensor_name}_{k}".lower()] = v

        state["online"] = True
        state["friendly_name"] = status.get("FriendlyName", [HOST])[0] if isinstance(
            status.get("FriendlyName"), list) else status.get("FriendlyName", HOST)

    except Exception as exc:
        print(f"Tasmota probe failed: {exc}", file=sys.stderr)
        state = {"online": False, "error": str(exc)}

    if project_id:
        _push_to_hub(project_id, state)

    events.append({"type": "device.update", "source": HOST, "data": state})
    return {"state": state, "events": events}


if __name__ == "__main__":
    inp = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    print(json.dumps(run(inp)))
