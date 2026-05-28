"""
mDNS advertisement and discovery scaffold.

Hub advertises:  _ESPAI._tcp.local  (port 7888)
Nodes advertise: _ESPAI-node._tcp.local  (port 80)

Requires: zeroconf  (pip install zeroconf)
If zeroconf is not installed the hub still starts — discovery is degraded.
"""
import logging
import socket
from typing import Callable

log = logging.getLogger(__name__)

try:
    from zeroconf import ServiceBrowser, ServiceInfo, Zeroconf
    _ZEROCONF_OK = True
except ImportError:
    _ZEROCONF_OK = False
    log.info("zeroconf not installed — mDNS discovery unavailable (pip install zeroconf)")

_NODE_SERVICE_TYPE = "_ESPAI-node._tcp.local."
_HUB_SERVICE_TYPE  = "_ESPAI._tcp.local."


class NodeDiscoveryListener:
    """Receives mDNS events and calls *on_found* with a node info dict."""

    def __init__(self, on_found: Callable[[dict], None], zeroconf: "Zeroconf"):
        self._on_found = on_found
        self._zc = zeroconf

    def add_service(self, zc, stype, name):
        info = zc.get_service_info(stype, name)
        if not info:
            return
        addresses = [socket.inet_ntoa(a) for a in info.addresses]
        node = {
            "mdns_name": name,
            "ip": addresses[0] if addresses else None,
            "port": info.port,
            "properties": {k.decode(): v.decode() for k, v in info.properties.items()},
        }
        log.info("mDNS: discovered node %s at %s", name, node["ip"])
        self._on_found(node)

    def remove_service(self, zc, stype, name):
        log.info("mDNS: node left %s", name)

    def update_service(self, zc, stype, name):
        pass


class MDNSManager:
    def __init__(self):
        self._zc: "Zeroconf | None" = None
        self._browser = None
        self._hub_info = None

    def start(self, hub_port: int, on_node_found: Callable[[dict], None]) -> None:
        if not _ZEROCONF_OK:
            return
        self._zc = Zeroconf()
        # advertise hub
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        self._hub_info = ServiceInfo(
            _HUB_SERVICE_TYPE,
            f"ESPAI Hub.{_HUB_SERVICE_TYPE}",
            addresses=[socket.inet_aton(local_ip)],
            port=hub_port,
            properties={"version": "0.1.0"},
        )
        self._zc.register_service(self._hub_info)
        log.info("mDNS: hub advertised as %s:%d", local_ip, hub_port)
        # browse for nodes
        self._browser = ServiceBrowser(
            self._zc, _NODE_SERVICE_TYPE,
            NodeDiscoveryListener(on_node_found, self._zc),
        )

    def stop(self) -> None:
        if self._zc:
            if self._hub_info:
                self._zc.unregister_service(self._hub_info)
            self._zc.close()
            self._zc = None


mdns_manager = MDNSManager()
