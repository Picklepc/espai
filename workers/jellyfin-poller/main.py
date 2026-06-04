"""
Jellyfin Poller — fetches active sessions and library stats from a local
Jellyfin (or Emby) server and pushes them to the ESPAI hub data store.

Required env vars:
  JELLYFIN_HOST      IP or hostname (e.g. jellyfin.local or 192.168.1.100)
  JELLYFIN_API_KEY   API key from Jellyfin Dashboard → API Keys
Optional env vars:
  JELLYFIN_PORT      Default 8096
  ESPAI_HUB_URL
"""
import json
import os
import sys
import urllib.request


HOST    = os.environ.get("JELLYFIN_HOST", "").rstrip("/")
API_KEY = os.environ.get("JELLYFIN_API_KEY", "")
PORT    = int(os.environ.get("JELLYFIN_PORT", "8096"))
HUB_URL = os.environ.get("ESPAI_HUB_URL", "http://localhost:7888").rstrip("/")

_BASE = f"http://{HOST}:{PORT}"


def _get(path: str) -> dict | list:
    sep  = "&" if "?" in path else "?"
    url  = f"{_BASE}{path}{sep}api_key={API_KEY}"
    req  = urllib.request.Request(url, headers={"User-Agent": "ESPAI-Hub"})
    with urllib.request.urlopen(req, timeout=8) as r:
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
    if not HOST or not API_KEY:
        raise RuntimeError("JELLYFIN_HOST and JELLYFIN_API_KEY env vars are required")

    sessions: list = []
    events:   list = []
    state: dict    = {}

    try:
        raw_sessions = _get("/Sessions?ControllableByUserId=&ActiveWithinSeconds=300")
        if isinstance(raw_sessions, list):
            sessions = [
                {
                    "user":     s.get("UserName", ""),
                    "client":   s.get("Client", ""),
                    "device":   s.get("DeviceName", ""),
                    "playing":  bool(s.get("NowPlayingItem")),
                    "title":    s.get("NowPlayingItem", {}).get("Name", "") if s.get("NowPlayingItem") else "",
                    "media_type": s.get("NowPlayingItem", {}).get("Type", "") if s.get("NowPlayingItem") else "",
                    "progress_pct": round(
                        s.get("PlayState", {}).get("PositionTicks", 0) /
                        max(s.get("NowPlayingItem", {}).get("RunTimeTicks", 1) or 1, 1) * 100, 1
                    ) if s.get("NowPlayingItem") else 0,
                }
                for s in raw_sessions
            ]

        active_playing = [s for s in sessions if s["playing"]]
        state = {
            "online":          True,
            "session_count":   len(sessions),
            "playing_count":   len(active_playing),
            "now_playing":     active_playing[0]["title"] if active_playing else "",
            "active_sessions": sessions,
        }

        for s in active_playing:
            events.append({"type": "media.playing", "source": HOST,
                           "data": {"title": s["title"], "user": s["user"]}})

    except Exception as exc:
        print(f"Jellyfin probe failed: {exc}", file=sys.stderr)
        state = {"online": False, "error": str(exc)}

    if project_id:
        _push_to_hub(project_id, {k: v for k, v in state.items() if k != "active_sessions"})

    return {"sessions": sessions, "state": state, "events": events}


if __name__ == "__main__":
    inp = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    print(json.dumps(run(inp)))
