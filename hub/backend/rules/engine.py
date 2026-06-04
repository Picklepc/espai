"""
ESPAI Rules Engine.

evaluate_rules(event) is called synchronously after each event is persisted.
Rules are loaded from the DB on every call (small table, fast read).

Supported action types:
  log_event  — write a log entry (always safe, no side-effects)
  run_worker — queue a job for a named worker
  webhook    — HTTP POST the event payload to a URL
"""
import json
import logging
import secrets
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from ..db import get_conn

log = logging.getLogger(__name__)


def evaluate_rules(event: dict) -> None:
    """Check all enabled rules against event. Called after event is inserted into DB."""
    try:
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM rules WHERE enabled=1 AND event_type=?",
                (event["event_type"],),
            ).fetchall()
        rules = [dict(r) for r in rows]
    except Exception:
        log.exception("rules: error loading rules for event_type=%s", event.get("event_type"))
        return

    for rule in rules:
        source_filter = rule.get("source_filter")
        if source_filter and source_filter != event.get("source"):
            continue
        _execute_action(rule, event)


def _execute_action(rule: dict, event: dict) -> None:
    action_type = rule.get("action_type")
    try:
        config = json.loads(rule["action_config"]) if rule.get("action_config") else {}
    except Exception:
        config = {}

    now = datetime.now(timezone.utc).isoformat()

    # Rate limiting — skip if this rule has fired too many times in the last hour
    max_fires = rule.get("max_fires_per_hour")
    if max_fires and max_fires > 0:
        window_start = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        try:
            with get_conn() as conn:
                count = conn.execute(
                    "SELECT COUNT(*) FROM rule_fires WHERE rule_id=? AND fired_at > ?",
                    (rule["id"], window_start),
                ).fetchone()[0]
            if count >= max_fires:
                log.debug("Rule %r: rate limit (%d/%d/hr) — skipping",
                          rule["name"], count, max_fires)
                return
        except Exception:
            log.exception("rules: rate limit check failed for rule %s", rule["id"])

    try:
        if action_type == "log_event":
            log.info(
                "Rule %r triggered: %s from %s",
                rule["name"], event["event_type"], event.get("source"),
            )
            _touch_triggered(rule["id"], now)

        elif action_type == "run_worker":
            worker_name = config.get("worker_name", "")
            if not worker_name:
                log.warning("Rule %r: run_worker action has no worker_name", rule["name"])
                return
            job_id = secrets.token_hex(6)
            with get_conn() as conn:
                conn.execute(
                    "INSERT INTO jobs (id, worker_name, status, inputs, created) VALUES (?,?,?,?,?)",
                    (job_id, worker_name, "queued", json.dumps({"trigger_event": event}), now),
                )
            log.info("Rule %r: queued job %s for worker %r", rule["name"], job_id, worker_name)
            _touch_triggered(rule["id"], now)

        elif action_type == "webhook":
            url = config.get("url", "")
            if not url:
                log.warning("Rule %r: webhook action has no url", rule["name"])
                return
            payload = json.dumps({"rule": rule["name"], "event": event}).encode()
            req = urllib.request.Request(
                url,
                data=payload,
                method="POST",
                headers={"Content-Type": "application/json", "User-Agent": "ESPAI-Hub/0.1"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                resp.read(1024)
            log.info("Rule %r: webhook POST to %s succeeded", rule["name"], url)
            _touch_triggered(rule["id"], now)

        elif action_type == "theme_change":
            from .. import theme_scheduler
            theme_scheduler.trigger_event_rule(rule, event)
            _touch_triggered(rule["id"], now)

        elif action_type == "send_command":
            device_id    = config.get("device_id", "")
            command_type = config.get("command_type", "user_action")
            payload      = config.get("payload", {})
            ttl          = int(config.get("ttl_seconds", 300))
            if not device_id:
                log.warning("Rule %r: send_command has no device_id", rule["name"])
                return
            cmd_id = secrets.token_hex(8)
            with get_conn() as conn:
                conn.execute(
                    """INSERT INTO device_commands
                       (id, device_id, command_type, payload, status, created, ttl_seconds)
                       VALUES (?,?,?,?,?,?,?)""",
                    (cmd_id, device_id, command_type,
                     json.dumps(payload), "pending", now, ttl),
                )
            log.info("Rule %r: queued command %s (%s) for device %r",
                     rule["name"], cmd_id, command_type, device_id)
            _touch_triggered(rule["id"], now)

        else:
            log.warning("Rule %r: unknown action_type %r", rule["name"], action_type)

    except Exception:
        log.exception("Rule %r: action %r failed", rule.get("name"), action_type)


def _touch_triggered(rule_id: str, now: str) -> None:
    try:
        prune_before = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        with get_conn() as conn:
            conn.execute("UPDATE rules SET last_triggered=? WHERE id=?", (now, rule_id))
            conn.execute("INSERT INTO rule_fires (rule_id, fired_at) VALUES (?,?)", (rule_id, now))
            conn.execute("DELETE FROM rule_fires WHERE fired_at < ?", (prune_before,))
    except Exception:
        log.exception("rules: failed to update last_triggered for rule %s", rule_id)
