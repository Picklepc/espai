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

from .. import __version__ as _HUB_VERSION
from ..config import MDNS_ENABLED

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
        self._hub_port: int = 7888
        self._local_ip: str = "127.0.0.1"
        self._project_services: dict[str, "ServiceInfo"] = {}

    def start(self, hub_port: int, on_node_found: Callable[[dict], None]) -> None:
        if not _ZEROCONF_OK or not MDNS_ENABLED:
            if not MDNS_ENABLED:
                log.info("mDNS: disabled via ESPAI_MDNS=0 — use manual IP add or subnet scan")
            return
        try:
            self._zc = Zeroconf()
        except Exception as exc:
            log.warning("mDNS: failed to initialise zeroconf: %s", exc)
            return
        self._hub_port = hub_port
        try:
            self._local_ip = socket.gethostbyname(socket.gethostname())
        except socket.gaierror:
            self._local_ip = "127.0.0.1"
        self._hub_info = ServiceInfo(
            _HUB_SERVICE_TYPE,
            f"ESPAI Hub.{_HUB_SERVICE_TYPE}",
            addresses=[socket.inet_aton(self._local_ip)],
            port=hub_port,
            properties={"version": _HUB_VERSION},
        )
        try:
            self._zc.register_service(self._hub_info)
            log.info("mDNS: hub advertised as %s:%d", self._local_ip, hub_port)
        except Exception as exc:
            log.warning("mDNS: hub advertisement failed (discovery degraded): %s", exc)
        try:
            self._browser = ServiceBrowser(
                self._zc, _NODE_SERVICE_TYPE,
                NodeDiscoveryListener(on_node_found, self._zc),
            )
        except Exception as exc:
            log.warning("mDNS: node browser failed: %s", exc)

    def register_project(self, slug: str, project_id: str) -> None:
        """
        Advertise a project on mDNS as {slug}._http._tcp.local. with server={slug}.local.
        This makes the project's hub URL discoverable on the LAN and allows
        browsers/clients to find it at http://{slug}.local:{port}/app/{slug}/.
        """
        if not _ZEROCONF_OK or not self._zc:
            return
        # Unregister any previous advertisement for this slug
        self.unregister_project(slug)
        try:
            info = ServiceInfo(
                "_http._tcp.local.",
                f"{slug}._http._tcp.local.",
                addresses=[socket.inet_aton(self._local_ip)],
                port=self._hub_port,
                properties={
                    b"path":       f"/app/{slug}/".encode(),
                    b"espai":      b"1",
                    b"project_id": project_id.encode(),
                },
                server=f"{slug}.local.",
            )
            self._zc.register_service(info)
            self._project_services[slug] = info
            log.info("mDNS: project '%s' advertised as %s.local:%d", slug, slug, self._hub_port)
        except Exception as exc:
            log.warning("mDNS: failed to advertise project '%s': %s", slug, exc)

    def unregister_project(self, slug: str) -> None:
        """Remove the mDNS advertisement for a project."""
        if not _ZEROCONF_OK or not self._zc:
            return
        info = self._project_services.pop(slug, None)
        if info:
            try:
                self._zc.unregister_service(info)
                log.info("mDNS: project '%s' unregistered", slug)
            except Exception:
                pass

    def register_all_projects(self) -> None:
        """Register all current projects on startup. Called from main.py lifespan."""
        if not _ZEROCONF_OK or not self._zc:
            return
        try:
            from ..db import get_conn
            with get_conn() as conn:
                rows = conn.execute("SELECT id, slug, name FROM projects").fetchall()
            from ..db import _to_hostname
            for row in rows:
                slug = row["slug"] or _to_hostname(row["name"])
                if slug:
                    self.register_project(slug, row["id"])
        except Exception as exc:
            log.warning("mDNS: register_all_projects failed: %s", exc)

    def stop(self) -> None:
        if self._zc:
            for info in self._project_services.values():
                try:
                    self._zc.unregister_service(info)
                except Exception:
                    pass
            self._project_services.clear()
            if self._hub_info:
                self._zc.unregister_service(self._hub_info)
            self._zc.close()
            self._zc = None


mdns_manager = MDNSManager()
