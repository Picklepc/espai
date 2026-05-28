"""
ESPAI Dynamic Theme Scheduler

Evaluates time-based rules from design/theme_rules.yaml every 60 seconds
and updates the hub's active theme token overrides accordingly.

Event-based rules are triggered via the rules engine (rules/engine.py) and
stored as timed overrides that expire after their configured duration.

This module exposes:
  start()              — called once during hub startup
  get_active_overrides() — returns current dynamic token overrides (dict)
  trigger_event_rule(event_type, payload) — called by rules engine for event-type actions
"""

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)

_active_overrides: dict[str, str]    = {}   # CSS var name → value
_override_expiry:  dict[str, datetime] = {}  # CSS var name → expiry time
_lock = threading.Lock()

_RULES_PATH = Path(__file__).parent.parent.parent / "design" / "theme_rules.yaml"

# Runtime-mutable active theme name (allows time-based switching)
_dynamic_theme: str | None = None


def _load_rules() -> list[dict]:
    try:
        import yaml
        if not _RULES_PATH.exists():
            return []
        raw = yaml.safe_load(_RULES_PATH.read_text(encoding="utf-8")) or {}
        return raw.get("rules") or []
    except Exception as exc:
        log.debug("theme_scheduler: failed to load rules: %s", exc)
        return []


def _hour_in_range(h: int, start: int, end: int) -> bool:
    """Check if hour h falls in [start, end) wrapping around midnight."""
    if start < end:
        return start <= h < end
    else:  # wraps midnight e.g. 21 → 7
        return h >= start or h < end


def _evaluate_time_rules(rules: list[dict]) -> None:
    global _dynamic_theme
    now_h = datetime.now().hour
    matched_theme: str | None = None

    for rule in rules:
        trigger = rule.get("trigger") or {}
        if trigger.get("type") != "time":
            continue
        h_start = trigger.get("hour_start", 0)
        h_end   = trigger.get("hour_end", 24)
        if _hour_in_range(now_h, h_start, h_end):
            action = rule.get("action") or {}
            if action.get("type") == "apply_theme":
                matched_theme = action.get("theme")
                break

    if matched_theme != _dynamic_theme:
        log.info("theme_scheduler: switching to theme %r", matched_theme)
        _dynamic_theme = matched_theme


def _purge_expired() -> None:
    now = datetime.now(timezone.utc)
    with _lock:
        expired = [k for k, exp in _override_expiry.items() if now >= exp]
        for k in expired:
            _active_overrides.pop(k, None)
            _override_expiry.pop(k, None)
        if expired:
            log.debug("theme_scheduler: expired %d override(s)", len(expired))


def _scheduler_loop() -> None:
    log.info("theme_scheduler: started")
    while True:
        try:
            rules = _load_rules()
            _evaluate_time_rules(rules)
            _purge_expired()
        except Exception as exc:
            log.warning("theme_scheduler: error: %s", exc)
        time.sleep(60)


def start() -> threading.Thread:
    """Start the background scheduler thread. Call once during hub startup."""
    t = threading.Thread(target=_scheduler_loop, daemon=True, name="ESPAI-theme-scheduler")
    t.start()
    return t


def get_active_overrides() -> dict[str, str]:
    """Return the current set of dynamic CSS token overrides."""
    with _lock:
        return dict(_active_overrides)


def get_dynamic_theme() -> str | None:
    """Return the time-rule-selected theme name, or None if using hub default."""
    return _dynamic_theme


def trigger_event_rule(rule: dict, event_payload: dict) -> None:
    """
    Apply a theme_tokens action from an event rule for its configured duration.
    Called by rules/engine.py when an event-based theme rule fires.
    """
    action = rule.get("action_config") or {}
    if isinstance(action, str):
        try:
            import json
            action = json.loads(action)
        except Exception:
            return

    tokens   = action.get("tokens") or {}
    duration = int(action.get("duration_minutes", 5))
    expiry   = datetime.now(timezone.utc) + timedelta(minutes=duration)

    with _lock:
        for k, v in tokens.items():
            _active_overrides[k] = v
            _override_expiry[k]  = expiry

    log.info("theme_scheduler: applied %d event-triggered token(s) for %dm", len(tokens), duration)
