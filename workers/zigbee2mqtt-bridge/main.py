"""
Zigbee2MQTT Bridge — subscribes to all Zigbee2MQTT device topics and pushes
payloads to the ESPAI hub data store. Runs as a persistent service (mode: service).

Required env vars:
  MQTT_HOST            MQTT broker IP or hostname
Optional env vars:
  MQTT_PORT            Default 1883
  MQTT_USER
  MQTT_PASS
  MQTT_TOPIC_PREFIX    Default zigbee2mqtt
  ESPAI_HUB_URL

Inputs:
  project_id           ESPAI project to push all device readings under
"""
import json
import os
import sys
import urllib.request

MQTT_HOST     = os.environ.get("MQTT_HOST", "localhost")
MQTT_PORT     = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_USER     = os.environ.get("MQTT_USER", "")
MQTT_PASS     = os.environ.get("MQTT_PASS", "")
TOPIC_PREFIX  = os.environ.get("MQTT_TOPIC_PREFIX", "zigbee2mqtt")
HUB_URL       = os.environ.get("ESPAI_HUB_URL", "http://localhost:7888").rstrip("/")


def _push_to_hub(project_id: str, device_id: str, data: dict) -> None:
    body = json.dumps(data).encode()
    req  = urllib.request.Request(
        f"{HUB_URL}/api/projects/{project_id}/data",
        data=body, method="POST",
        headers={"Content-Type": "application/json", "X-Device-ID": device_id},
    )
    try:
        urllib.request.urlopen(req, timeout=3)
    except Exception as exc:
        print(f"hub push failed ({device_id}): {exc}", file=sys.stderr)


def run(inputs: dict) -> dict:
    project_id = inputs.get("project_id", "")

    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        print("paho-mqtt is not installed. Add it via ESPAI_PREINSTALL=paho-mqtt", file=sys.stderr)
        sys.exit(1)

    received: list[dict] = []
    events:   list[dict] = []

    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            client.subscribe(f"{TOPIC_PREFIX}/#")
            print(f"Connected to {MQTT_HOST}:{MQTT_PORT}, subscribed to {TOPIC_PREFIX}/#")
        else:
            print(f"MQTT connect failed: rc={rc}", file=sys.stderr)

    def on_message(client, userdata, msg):
        topic = msg.topic
        # Skip bridge status messages
        if "/bridge/" in topic:
            return
        # Device name is the last path segment
        device_name = topic.split("/")[-1]
        try:
            payload = json.loads(msg.payload)
        except Exception:
            return
        if not isinstance(payload, dict):
            return

        data = {**payload, "_device": device_name, "_topic": topic}
        if project_id:
            _push_to_hub(project_id, device_name, data)

        received.append(data)
        events.append({"type": "device.update", "source": device_name, "data": data})

    client = mqtt.Client()
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_forever()  # blocks — mode: service keeps this alive

    return {"events": events}


if __name__ == "__main__":
    inp = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    run(inp)
