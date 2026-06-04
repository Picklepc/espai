"""
WLED Controller — reads and optionally writes WLED state via the JSON API.

Required env vars:
  WLED_HOST          IP or hostname of the WLED device
Optional env vars:
  ESPAI_HUB_URL
"""
import json
import os
import sys
import urllib.request


HOST    = os.environ.get("WLED_HOST", "").rstrip("/")
HUB_URL = os.environ.get("ESPAI_HUB_URL", "http://localhost:7888").rstrip("/")


def _get_state() -> dict:
    url = f"http://{HOST}/json/state"
    with urllib.request.urlopen(url, timeout=5) as r:
        return json.loads(r.read())


def _get_info() -> dict:
    url = f"http://{HOST}/json/info"
    with urllib.request.urlopen(url, timeout=5) as r:
        return json.loads(r.read())


def _set_state(payload: dict) -> dict:
    body = json.dumps(payload).encode()
    req  = urllib.request.Request(
        f"http://{HOST}/json/state",
        data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=5) as r:
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


def run(inputs: dict) -> dict:
    project_id = inputs.get("project_id", "")
    action     = inputs.get("action", "poll")
    if not HOST:
        raise RuntimeError("WLED_HOST env var is required")

    events = []
    state: dict = {}

    try:
        if action == "apply":
            apply_state = inputs.get("state", {})
            if apply_state:
                _set_state(apply_state)

        raw   = _get_state()
        info  = _get_info()
        seg   = (raw.get("seg") or [{}])[0]
        state = {
            "online":      True,
            "on":          raw.get("on", False),
            "brightness":  raw.get("bri", 0),
            "effect_id":   seg.get("fx", 0),
            "color":       seg.get("col", [[]])[0] if seg.get("col") else [],
            "palette_id":  seg.get("pal", 0),
            "speed":       seg.get("sx", 128),
            "intensity":   seg.get("ix", 128),
            "version":     info.get("ver", ""),
            "name":        info.get("name", HOST),
        }
    except Exception as exc:
        print(f"WLED probe failed: {exc}", file=sys.stderr)
        state = {"online": False, "error": str(exc)}

    if project_id:
        _push_to_hub(project_id, state)

    events.append({"type": "device.update", "source": HOST, "data": state})
    return {"state": state, "events": events}


if __name__ == "__main__":
    inp = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    print(json.dumps(run(inp)))
