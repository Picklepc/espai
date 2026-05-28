"""
Optional MQTT event publisher for ESPAI Hub.

When paho-mqtt is installed and ESPAI_MQTT_HOST is set in the environment,
every published event is forwarded to the configured broker.

Configuration (via .env or environment variables):
    ESPAI_MQTT_HOST          — broker hostname (required to enable)
    ESPAI_MQTT_PORT          — broker port (default 1883)
    ESPAI_MQTT_TOPIC_PREFIX  — topic prefix (default "espai")
    ESPAI_MQTT_CLIENT_ID     — client ID (default "espai-hub")
    ESPAI_MQTT_USERNAME      — optional username
    ESPAI_MQTT_PASSWORD      — optional password

Topic format:
    {prefix}/events/{event_type}
    {prefix}/devices/{device_id}/events/{event_type}   (when source is a device ID)

The publisher silently does nothing when paho-mqtt is not installed or
ESPAI_MQTT_HOST is not configured — no errors, no startup failures.
"""

import json
import logging
import os
import threading

log = logging.getLogger(__name__)

_client       = None
_prefix       = "espai"
_connected    = False
_connect_lock = threading.Lock()


def _mqtt_available() -> bool:
    try:
        import paho.mqtt.client  # noqa: F401
        return True
    except ImportError:
        return False


def init() -> bool:
    """
    Attempt to connect to the configured MQTT broker.
    Returns True if connection was attempted, False if skipped.
    Called once during hub startup.
    """
    global _client, _prefix, _connected

    host = os.environ.get("ESPAI_MQTT_HOST", "").strip()
    if not host:
        return False   # MQTT not configured

    if not _mqtt_available():
        log.warning("ESPAI_MQTT_HOST is set but paho-mqtt is not installed. "
                    "Run: pip install paho-mqtt")
        return False

    import paho.mqtt.client as mqtt

    port     = int(os.environ.get("ESPAI_MQTT_PORT", "1883"))
    _prefix  = os.environ.get("ESPAI_MQTT_TOPIC_PREFIX", "espai").strip("/")
    client_id = os.environ.get("ESPAI_MQTT_CLIENT_ID", "espai-hub")
    username  = os.environ.get("ESPAI_MQTT_USERNAME", "")
    password  = os.environ.get("ESPAI_MQTT_PASSWORD", "")

    def on_connect(client, userdata, flags, rc):
        global _connected
        if rc == 0:
            _connected = True
            log.info("MQTT connected to %s:%d (prefix=%r)", host, port, _prefix)
        else:
            log.warning("MQTT connection failed: rc=%d", rc)

    def on_disconnect(client, userdata, rc):
        global _connected
        _connected = False
        log.info("MQTT disconnected (rc=%d) — will reconnect automatically", rc)

    _client = mqtt.Client(client_id=client_id, clean_session=True)
    _client.on_connect    = on_connect
    _client.on_disconnect = on_disconnect

    if username:
        _client.username_pw_set(username, password or None)

    try:
        _client.connect_async(host, port, keepalive=60)
        _client.loop_start()
        log.info("MQTT publisher initialised — broker %s:%d", host, port)
        return True
    except Exception as exc:
        log.warning("MQTT connect failed: %s", exc)
        _client = None
        return False


def shutdown() -> None:
    """Cleanly disconnect from the broker. Called during hub shutdown."""
    global _client, _connected
    if _client:
        try:
            _client.loop_stop()
            _client.disconnect()
        except Exception:
            pass
        _client = None
        _connected = False


def publish_event(source: str, event_type: str, payload: dict) -> None:
    """
    Forward an event to MQTT.  No-op if not connected or not configured.

    Topics published:
        {prefix}/events/{event_type}
        {prefix}/source/{source}/events/{event_type}
    """
    if not _client or not _connected:
        return
    try:
        msg = json.dumps({
            "source":     source,
            "event_type": event_type,
            "payload":    payload,
        })
        safe_type   = event_type.replace("/", "_").replace(" ", "_")
        safe_source = source.replace("/", "_").replace(" ", "_")
        _client.publish(f"{_prefix}/events/{safe_type}",                        msg, qos=0)
        _client.publish(f"{_prefix}/source/{safe_source}/events/{safe_type}",   msg, qos=0)
    except Exception as exc:
        log.debug("MQTT publish error: %s", exc)
