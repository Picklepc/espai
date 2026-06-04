"""
ESPAI Cron Scheduler — fires synthetic events for time-based rules.

Rules with a non-null `schedule` field (5-field cron: "min hr dom mon dow")
are evaluated every minute. When the expression matches the current UTC time,
a `system.clock` event is fired and the rule's action executes normally.

Cron field syntax (subset): * | number | number-number | */step | list(,)
Example expressions:
  "0 6 * * *"     — daily at 06:00 UTC
  "*/15 * * * *"  — every 15 minutes
  "0 8,20 * * *"  — 08:00 and 20:00 UTC
  "0 12 * * 1"    — every Monday at noon UTC
"""

import logging
import threading
import time
from datetime import datetime, timezone

log = logging.getLogger(__name__)

_thread: threading.Thread | None = None
_stop   = threading.Event()


# ── Cron expression parser ────────────────────────────────────────────────────

def _field_matches(field: str, value: int, lo: int, hi: int) -> bool:
    """Return True if `value` satisfies the cron `field` expression."""
    if field == "*":
        return True
    for part in field.split(","):
        part = part.strip()
        if "/" in part:
            base, step_s = part.split("/", 1)
            step = int(step_s)
            start = lo if base == "*" else int(base.split("-")[0])
            end   = hi if base == "*" else (int(base.split("-")[1]) if "-" in base else int(base))
            if start <= value <= end and (value - start) % step == 0:
                return True
        elif "-" in part:
            a, b = part.split("-", 1)
            if int(a) <= value <= int(b):
                return True
        else:
            if int(part) == value:
                return True
    return False


def cron_matches(expr: str, dt: datetime) -> bool:
    """Return True if the cron expression matches dt (UTC)."""
    try:
        fields = expr.strip().split()
        if len(fields) != 5:
            return False
        f_min, f_hr, f_dom, f_mon, f_dow = fields
        return (
            _field_matches(f_min, dt.minute,     0, 59) and
            _field_matches(f_hr,  dt.hour,        0, 23) and
            _field_matches(f_dom, dt.day,          1, 31) and
            _field_matches(f_mon, dt.month,        1, 12) and
            _field_matches(f_dow, dt.weekday() % 7, 0,  6)  # 0=Mon in Python, 0=Sun in cron → map
        )
    except Exception:
        return False


def next_fires(expr: str, n: int = 5) -> list[str]:
    """Return the next N fire times for a cron expression (UTC ISO strings)."""
    from datetime import timedelta
    results = []
    dt = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    checked = 0
    while len(results) < n and checked < 60 * 24 * 8:  # max 8 days look-ahead
        dt += timedelta(minutes=1)
        checked += 1
        if cron_matches(expr, dt):
            results.append(dt.isoformat())
    return results


# ── Scheduler loop ────────────────────────────────────────────────────────────

def _loop() -> None:
    log.info("Cron scheduler started")
    last_minute = -1

    while not _stop.is_set():
        now = datetime.now(timezone.utc)
        if now.minute == last_minute:
            _stop.wait(timeout=5)
            continue
        last_minute = now.minute

        try:
            _fire_scheduled_rules(now)
        except Exception:
            log.exception("Cron scheduler error")

        # Sleep until the next minute boundary (+ 2 s buffer)
        seconds_left = 60 - now.second + 2
        _stop.wait(timeout=seconds_left)

    log.info("Cron scheduler stopped")


def _localise(now: datetime, tz_name: str | None) -> datetime:
    """Convert UTC now to a local datetime for timezone-aware cron matching."""
    if not tz_name:
        return now
    try:
        from zoneinfo import ZoneInfo
        return now.astimezone(ZoneInfo(tz_name))
    except Exception:
        return now  # unknown timezone — fall back to UTC


def _fire_scheduled_rules(now: datetime) -> None:
    from ..db import get_conn
    from .engine import _execute_action

    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM rules WHERE enabled=1 AND schedule IS NOT NULL AND schedule != ''",
        ).fetchall()

    rules = [dict(r) for r in rows]
    if not rules:
        return

    for rule in rules:
        # Apply timezone before cron match
        check_time = _localise(now, rule.get("schedule_tz"))
        if not cron_matches(rule["schedule"], check_time):
            continue

        log.info("Cron rule %r firing (schedule=%r tz=%r)", rule["name"],
                 rule["schedule"], rule.get("schedule_tz") or "UTC")

        event = {
            "event_type": "system.clock",
            "source":     "scheduler",
            "payload":    {
                "minute":  check_time.minute,
                "hour":    check_time.hour,
                "dom":     check_time.day,
                "month":   check_time.month,
                "dow":     check_time.weekday(),
                "iso":     now.isoformat(),
                "tz":      rule.get("schedule_tz") or "UTC",
            },
        }
        try:
            _execute_action(rule, event)
        except Exception:
            log.exception("Cron rule %r action failed", rule["name"])


# ── Public API ────────────────────────────────────────────────────────────────

def start() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, daemon=True, name="ESPAI-cron-scheduler")
    _thread.start()


def stop() -> None:
    _stop.set()
