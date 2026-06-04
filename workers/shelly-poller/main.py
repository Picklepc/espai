"""
Shelly Poller — auto-detects gen1 vs gen2 Shelly API and pushes power,
energy, switch state, and temperature to the ESPAI hub data store.

Required env vars:
  SHELLY_HOST        IP or hostname (e.g. 192.168.1.55 or shelly1.local)
Optional env vars:
  SHELLY_AUTH_USER   HTTP basic auth username (gen1)
  SHELLY_AUTH_PASS   HTTP basic auth password (gen1)
  ESPAI_HUB_URL
"""
import base64
import json
import os
import sys
import urllib.error
import urllib.request


HOST      = os.environ.get("SHELLY_HOST", "").rstrip("/")
AUTH_USER = os.environ.get("SHELLY_AUTH_USER", "")
AUTH_PASS = os.environ.get("SHELLY_AUTH_PASS", "")
HUB_URL   = os.environ.get("ESPAI_HUB_URL", "http://localhost:7888").rstrip("/")


def _get(path: str, timeout: float = 5.0) -> dict:
    url = f"http://{HOST}{path}"
    req = urllib.request.Request(url, headers={"User-Agent": "ESPAI-Hub"})
    if AUTH_USER:
        creds = base64.b64encode(f"{AUTH_USER}:{AUTH_PASS}".encode()).decode()
        req.add_header("Authorization", f"Basic {creds}")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _push_to_hub(project_id: str, data: dict) -> None:
    body = json.dumps(data).encode()
    req  = urllib.request.Request(
        f"{HUB_URL}/api/projects/{project_id}/data",
        data=body, method="POST",
        headers={"Content-Type": "application/json", "X-Device-ID": HOST},
    )
    try:
        urllib.request.urlopen(req, timeout=5)
    except Exception as exc:
        print(f"hub push failed: {exc}", file=sys.stderr)


def _parse_gen1(status: dict, channel: int) -> dict:
    state: dict = {"online": True, "generation": "gen1"}
    relays = status.get("relays", [])
    if channel < len(relays):
        state["power_on"] = relays[channel].get("ison", False)
    meters = status.get("meters", [])
    if channel < len(meters):
        m = meters[channel]
        state["watts"]          = m.get("power", 0)
        state["total_wh"]       = m.get("total", 0)
    # Temperature
    for key in ("temperature", "overtemperature"):
        if key in status:
            state[key] = status[key]
    return state


def _parse_gen2(status: dict, channel: int) -> dict:
    state: dict = {"online": True, "generation": "gen2"}
    sw_key = f"switch:{channel}"
    sw = status.get(sw_key, {})
    state["power_on"]    = sw.get("output", False)
    state["watts"]       = sw.get("apower", 0)
    state["voltage"]     = sw.get("voltage", 0)
    state["current"]     = sw.get("current", 0)
    aenergy = sw.get("aenergy", {})
    state["total_wh"]    = aenergy.get("total", 0)
    temp = sw.get("temperature", {})
    if temp:
        state["temperature"] = temp.get("tC", 0)
    return state


def run(inputs: dict) -> dict:
    project_id = inputs.get("project_id", "")
    channel    = int(inputs.get("channel", 0))
    if not HOST:
        raise RuntimeError("SHELLY_HOST env var is required")

    state: dict = {}
    generation  = "unknown"

    # Try gen2 first (more common on new devices)
    try:
        status = _get("/rpc/Shelly.GetStatus")
        state  = _parse_gen2(status, channel)
        generation = "gen2"
    except Exception:
        # Fall back to gen1
        try:
            status = _get("/status")
            state  = _parse_gen1(status, channel)
            generation = "gen1"
        except Exception as exc:
            print(f"Shelly probe failed: {exc}", file=sys.stderr)
            state = {"online": False, "error": str(exc)}

    if project_id:
        _push_to_hub(project_id, state)

    events = [{"type": "device.update", "source": HOST, "data": state}]
    return {"state": state, "generation": generation, "events": events}


if __name__ == "__main__":
    inp = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    print(json.dumps(run(inp)))
