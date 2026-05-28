"""
Worker permission enforcement for the ESPAI runner.

Checks declared permissions in worker.yaml against active policy,
and sanitizes the subprocess environment to prevent secret leakage.

Permission levels:
  filesystem  — none | project-media-only | restricted | any
  network     — none | restricted | any
  secrets     — none | restricted | any

Enforcement is two-phase:
  1. Pre-run: check declared levels vs. policy caps → refuse job if exceeded
  2. Env sanitization: strip secrets/ESPAI internals unless explicitly granted
"""

import logging
import re

log = logging.getLogger(__name__)

# Patterns that identify secret-like env var names
_SECRET_RE = re.compile(
    r"(SECRET|KEY|TOKEN|PASSWORD|PASS(?:WORD)?|CREDENTIAL|APIKEY|PRIVATE)",
    re.IGNORECASE,
)

# Env vars always forwarded — safe OS/Python process primitives
_ALWAYS_PASS = frozenset({
    "PATH", "PATHEXT", "COMSPEC",
    "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR",
    "TEMP", "TMP", "USERPROFILE", "HOMEDRIVE", "HOMEPATH",
    "COMPUTERNAME", "PROCESSOR_ARCHITECTURE",
    "NUMBER_OF_PROCESSORS", "OS",
    "PYTHONPATH", "PYTHONHOME", "PYTHONDONTWRITEBYTECODE",
    "PYTHONUTF8", "VIRTUAL_ENV",
    # Injected by runner — not secrets
    "ESPAI_JOB_ID", "ESPAI_INPUTS",
})

# Ordered capability ranks (higher index = more permissive)
_FS_RANK  = {"none": 0, "project-media-only": 1, "restricted": 2, "any": 3}
_NET_RANK = {"none": 0, "restricted": 1, "any": 2}
_SEC_RANK = {"none": 0, "restricted": 1, "any": 2}


# ── Policy helpers ──────────────────────────────────────────────────────────

def _policy_net_cap(policy: dict) -> str:
    return "any" if policy.get("workers", {}).get("allow_network_by_default") else "none"


def _policy_sec_cap(policy: dict) -> str:
    return "any" if policy.get("workers", {}).get("allow_secret_access_by_default") else "none"


# ── Public API ──────────────────────────────────────────────────────────────

def check_permissions(worker: dict, policy: dict) -> list[str]:
    """
    Validate worker's declared permissions against policy caps.
    Returns a list of human-readable violation strings.
    Empty list means the worker is cleared to run.
    """
    violations: list[str] = []
    declared = worker.get("permissions") or {}
    if not isinstance(declared, dict):
        return violations

    net_want = declared.get("network", "none")
    net_cap  = _policy_net_cap(policy)
    if _NET_RANK.get(net_want, 0) > _NET_RANK.get(net_cap, 0):
        violations.append(
            f"network='{net_want}' exceeds policy cap ('{net_cap}'). "
            f"Set allow_network_by_default: true in policy, or declare network: none."
        )

    sec_want = declared.get("secrets", "none")
    sec_cap  = _policy_sec_cap(policy)
    if _SEC_RANK.get(sec_want, 0) > _SEC_RANK.get(sec_cap, 0):
        violations.append(
            f"secrets='{sec_want}' exceeds policy cap ('{sec_cap}'). "
            f"Set allow_secret_access_by_default: true in policy, or declare secrets: none."
        )

    return violations


def build_sandbox_env(worker: dict, policy: dict, base_env: dict) -> dict:
    """
    Return a sanitized copy of *base_env* safe for the worker subprocess.

    Strips:
    - Env vars with secret-like names (KEY/TOKEN/PASSWORD/etc.)
    - ESPAI_ internal vars that reveal hub config (db path, URLs, etc.)

    Unless the worker's declared secrets permission is > none AND policy allows it.
    """
    declared = worker.get("permissions") or {}
    if not isinstance(declared, dict):
        declared = {}

    sec_want    = declared.get("secrets", "none")
    sec_allowed = _SEC_RANK.get(_policy_sec_cap(policy), 0) > 0
    secrets_ok  = _SEC_RANK.get(sec_want, 0) > 0 and sec_allowed

    sanitized: dict = {}
    stripped:  list = []

    for key, val in base_env.items():
        upper = key.upper()

        if key in _ALWAYS_PASS:
            sanitized[key] = val
            continue

        # Strip ESPAI internals (hub URL, DB path, theme, etc.) unless secrets granted
        if upper.startswith("ESPAI_") and not secrets_ok:
            stripped.append(key)
            continue

        # Strip anything that looks like a secret
        if _SECRET_RE.search(upper) and not secrets_ok:
            stripped.append(key)
            continue

        sanitized[key] = val

    if stripped:
        log.debug(
            "Worker %r: stripped %d env var(s) (%s)",
            worker.get("name", "?"),
            len(stripped),
            ", ".join(stripped[:10]) + ("…" if len(stripped) > 10 else ""),
        )

    return sanitized


def process_flags(worker: dict) -> dict:
    """
    Return kwargs for subprocess.run() that encode resource limits.
    Uses worker.yaml resource_cost to set Windows process priority.
    """
    import subprocess
    cost = worker.get("resource_cost") or {}
    cpu  = str(cost.get("cpu", "medium")).lower()

    flags: dict = {}
    if cpu == "low":
        flags["creationflags"] = subprocess.IDLE_PRIORITY_CLASS
    elif cpu in ("medium", "normal"):
        flags["creationflags"] = subprocess.BELOW_NORMAL_PRIORITY_CLASS
    # high → normal priority (no flag needed)

    return flags
