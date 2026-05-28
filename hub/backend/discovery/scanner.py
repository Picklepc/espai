"""
Subnet scanner scaffold.

Probes LAN hosts for ESPAI nodes by hitting /api/manifest on port 80.
Does NOT do ICMP ping — uses HTTP only so no raw-socket privileges needed.

Usage is async-friendly: run_scan() returns a coroutine.
"""
import asyncio
import logging
from typing import AsyncIterator

log = logging.getLogger(__name__)

NODE_PORT = 80
NODE_PATH = "/api/manifest"
TIMEOUT   = 1.5  # seconds per host


async def _probe(ip: str, session) -> dict | None:
    url = f"http://{ip}:{NODE_PORT}{NODE_PATH}"
    try:
        async with session.get(url, timeout=TIMEOUT) as resp:
            if resp.status == 200:
                data = await resp.json(content_type=None)
                data["ip"] = ip
                return data
    except Exception:
        pass
    return None


async def run_scan(subnet: str) -> AsyncIterator[dict]:
    """
    Yield node manifests found on *subnet* (e.g. '192.168.1').
    Requires: aiohttp  (pip install aiohttp)
    """
    try:
        import aiohttp
    except ImportError:
        log.warning("aiohttp not installed — subnet scan unavailable")
        return

    log.info("Subnet scan starting on %s.0/24", subnet)
    targets = [f"{subnet}.{i}" for i in range(1, 255)]

    async with aiohttp.ClientSession() as session:
        tasks = [_probe(ip, session) for ip in targets]
        for coro in asyncio.as_completed(tasks):
            result = await coro
            if result:
                log.info("Scan: found node at %s", result.get("ip"))
                yield result

    log.info("Subnet scan complete for %s.0/24", subnet)
