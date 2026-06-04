"""
Generic HTTP Poller — fetches any JSON endpoint and pushes the response to
the ESPAI hub data store. Parameterised entirely via inputs — no code changes
needed for simple REST devices.

Optional env vars:
  HTTP_AUTH_HEADER   Full Authorization header value (e.g. "Bearer mytoken")
  ESPAI_HUB_URL
"""
import json
import os
import sys
import urllib.request


AUTH_HEADER = os.environ.get("HTTP_AUTH_HEADER", "")
HUB_URL     = os.environ.get("ESPAI_HUB_URL", "http://localhost:7888").rstrip("/")


def _fetch(url: str, method: str = "GET", body: dict | None = None) -> dict | list:
    data    = json.dumps(body).encode() if body else None
    headers = {"User-Agent": "ESPAI-Hub", "Accept": "application/json"}
    if data:
        headers["Content-Type"] = "application/json"
    if AUTH_HEADER:
        headers["Authorization"] = AUTH_HEADER
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def _apply_field_map(data: dict, field_map: dict) -> dict:
    if not field_map:
        return data
    result = {}
    for k, v in data.items():
        result[field_map.get(k, k)] = v
    return result


def _push_to_hub(project_id: str, data: dict, device_id: str) -> None:
    body = json.dumps(data).encode()
    req  = urllib.request.Request(
        f"{HUB_URL}/api/projects/{project_id}/data",
        data=body, method="POST",
        headers={"Content-Type": "application/json", "X-Device-ID": device_id},
    )
    try:
        urllib.request.urlopen(req, timeout=5)
    except Exception as exc:
        print(f"hub push failed: {exc}", file=sys.stderr)


def run(inputs: dict) -> dict:
    project_id = inputs.get("project_id", "")
    base_url   = inputs.get("base_url", "").rstrip("/")
    path       = inputs.get("path", "/")
    method     = inputs.get("method", "GET").upper()
    body_in    = inputs.get("body")
    field_map  = inputs.get("field_map") or {}

    if not base_url:
        raise RuntimeError("base_url input is required")

    url = base_url + path
    raw: dict = {}

    try:
        result = _fetch(url, method=method, body=body_in)
        raw    = result if isinstance(result, dict) else {"data": result}
    except Exception as exc:
        print(f"HTTP fetch failed ({url}): {exc}", file=sys.stderr)
        raw = {"error": str(exc), "online": False}

    mapped = _apply_field_map(raw, field_map)

    if project_id and mapped:
        _push_to_hub(project_id, mapped, base_url)

    events = [{"type": "device.update", "source": base_url, "data": mapped}]
    return {"raw": raw, "mapped": mapped, "events": events}


if __name__ == "__main__":
    inp = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    print(json.dumps(run(inp)))
