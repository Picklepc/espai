"""
Database helpers for ESPAI Hub.

get_conn() is a context manager that:
  - opens a WAL-mode SQLite connection
  - commits on clean exit
  - rolls back and re-raises on exception
  - always closes the connection

Usage:
    with get_conn() as conn:
        conn.execute("INSERT ...")
        # commit happens automatically on exit — do NOT call conn.commit()
"""
import sqlite3
from contextlib import contextmanager

from .config import DB_PATH


@contextmanager
def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")  # wait up to 5 s if DB is locked
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def _to_hostname(name: str) -> str:
    """
    Convert any string to a valid RFC-1123 DNS hostname label.
    Rules: lowercase letters, digits, hyphens only; no leading/trailing hyphens;
    no consecutive hyphens; max 63 chars.
    """
    import re as _re
    s = name.lower()
    s = _re.sub(r"[\s_]+", "-", s)       # spaces / underscores → hyphen
    s = _re.sub(r"[^a-z0-9\-]", "", s)   # strip everything else
    s = _re.sub(r"-{2,}", "-", s)         # collapse runs of hyphens
    s = s.strip("-")                       # no leading/trailing hyphen
    return s[:63] or "project"


def _migrate(conn) -> None:
    """Additive column migrations — safe to run on any existing DB."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(agent_tasks)").fetchall()}
    for col, ddl in [
        ("context_type",   "ALTER TABLE agent_tasks ADD COLUMN context_type   TEXT"),
        ("context_id",     "ALTER TABLE agent_tasks ADD COLUMN context_id     TEXT"),
        ("parent_task_id", "ALTER TABLE agent_tasks ADD COLUMN parent_task_id TEXT"),
    ]:
        if col not in existing:
            conn.execute(ddl)

    # Add slug column to projects (hostname-safe project identifier)
    proj_cols = {row[1] for row in conn.execute("PRAGMA table_info(projects)").fetchall()}
    if "slug" not in proj_cols:
        conn.execute("ALTER TABLE projects ADD COLUMN slug TEXT")
        # Backfill existing projects
        rows = conn.execute("SELECT id, name FROM projects").fetchall()
        for row in rows:
            conn.execute(
                "UPDATE projects SET slug=? WHERE id=?",
                (_to_hostname(row[1]), row[0]),
            )


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS devices (
            id          TEXT PRIMARY KEY,
            ip          TEXT,
            name        TEXT,
            board       TEXT,
            fw_version  TEXT,
            paired      INTEGER NOT NULL DEFAULT 0,
            last_seen   TEXT,
            capabilities TEXT,
            meta        TEXT
        );

        CREATE TABLE IF NOT EXISTS projects (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            description TEXT,
            devices     TEXT,
            created     TEXT NOT NULL,
            meta        TEXT
        );

        CREATE TABLE IF NOT EXISTS ota_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id   TEXT NOT NULL,
            fw_version  TEXT,
            action      TEXT NOT NULL,
            result      TEXT,
            checksum    TEXT,
            operator    TEXT,
            timestamp   TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS jobs (
            id          TEXT PRIMARY KEY,
            worker_name TEXT NOT NULL,
            status      TEXT NOT NULL DEFAULT 'queued',
            inputs      TEXT,
            outputs     TEXT,
            error       TEXT,
            created     TEXT NOT NULL,
            started     TEXT,
            finished    TEXT
        );

        CREATE TABLE IF NOT EXISTS events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            source      TEXT,
            event_type  TEXT NOT NULL,
            payload     TEXT,
            timestamp   TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS pairing_tokens (
            token       TEXT PRIMARY KEY,
            device_id   TEXT,
            created     TEXT NOT NULL,
            expires     TEXT NOT NULL,
            used        INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS rules (
            id              TEXT PRIMARY KEY,
            name            TEXT NOT NULL,
            enabled         INTEGER NOT NULL DEFAULT 1,
            event_type      TEXT NOT NULL,
            source_filter   TEXT,
            action_type     TEXT NOT NULL,
            action_config   TEXT,
            created         TEXT NOT NULL,
            last_triggered  TEXT
        );

        CREATE TABLE IF NOT EXISTS agent_tasks (
            id                  TEXT PRIMARY KEY,
            project_id          TEXT,
            title               TEXT NOT NULL,
            description         TEXT NOT NULL,
            template            TEXT NOT NULL DEFAULT 'custom',
            status              TEXT NOT NULL DEFAULT 'draft',
            allowed_paths       TEXT,
            acceptance_criteria TEXT,
            context             TEXT,
            context_type        TEXT,
            context_id          TEXT,
            parent_task_id      TEXT,
            lane                TEXT NOT NULL DEFAULT 'dev',
            adapter_id          TEXT,
            created             TEXT NOT NULL,
            updated             TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS agent_task_messages (
            id          TEXT PRIMARY KEY,
            task_id     TEXT NOT NULL,
            role        TEXT NOT NULL DEFAULT 'user',
            content     TEXT NOT NULL,
            timestamp   TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS agent_runs (
            id              TEXT PRIMARY KEY,
            task_id         TEXT NOT NULL,
            adapter_id      TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'running',
            started         TEXT NOT NULL,
            finished        TEXT,
            exit_code       INTEGER,
            log             TEXT,
            snapshot_before TEXT,
            snapshot_after  TEXT
        );

        CREATE TABLE IF NOT EXISTS agent_artifacts (
            id            TEXT PRIMARY KEY,
            task_id       TEXT NOT NULL,
            run_id        TEXT,
            path          TEXT NOT NULL,
            artifact_type TEXT NOT NULL DEFAULT 'file',
            content       TEXT,
            created       TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS agent_reviews (            id          TEXT PRIMARY KEY,
            task_id     TEXT NOT NULL,
            run_id      TEXT,
            decision    TEXT NOT NULL,
            notes       TEXT,
            created     TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS agent_permissions (
            id          TEXT PRIMARY KEY,
            task_id     TEXT NOT NULL,
            permission  TEXT NOT NULL,
            granted_by  TEXT,
            granted_at  TEXT NOT NULL
        );

        -- ── Project data store ────────────────────────────────────────────────
        -- Time-series readings pushed by ESP32 devices.
        -- Each row is one payload (JSON object) from one device at one time.
        -- Keeps a configurable rolling window per project (pruned on insert).
        CREATE TABLE IF NOT EXISTS project_data (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id  TEXT    NOT NULL,
            device_id   TEXT,
            payload     TEXT    NOT NULL,   -- JSON: {"temp":23.5,"unit":"C", ...}
            timestamp   TEXT    NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_project_data_pid_ts
            ON project_data (project_id, timestamp DESC);

        -- Latest reading per (project, device) — upserted on every push.
        -- Web apps query this first for an instant load without scanning history.
        CREATE TABLE IF NOT EXISTS project_data_cache (
            project_id  TEXT NOT NULL,
            device_id   TEXT NOT NULL DEFAULT '',
            payload     TEXT NOT NULL,
            timestamp   TEXT NOT NULL,
            PRIMARY KEY (project_id, device_id)
        );

        -- ── Local Network service registry ────────────────────────────────────
        -- Persists discovered and manually-added LAN services across reloads.
        -- Upserted by the /api/services/discover scan; never auto-deleted.
        CREATE TABLE IF NOT EXISTS local_services (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            host          TEXT NOT NULL,      -- IP or hostname (e.g. jellyfin.local)
            port          INTEGER NOT NULL DEFAULT 80,
            protocol      TEXT NOT NULL DEFAULT 'http',
            label         TEXT,              -- user-set friendly name
            title         TEXT,             -- from <title> tag
            server        TEXT,             -- from Server HTTP header
            favicon_url   TEXT,             -- best-guess favicon URL
            service_type  TEXT NOT NULL DEFAULT 'unknown',
            category      TEXT NOT NULL DEFAULT 'other',  -- projects/smart-home/media/network/tools/other
            is_espai      INTEGER NOT NULL DEFAULT 0,
            project_id    TEXT,             -- linked ESPAI project (if is_espai)
            pinned        INTEGER NOT NULL DEFAULT 0,
            hidden        INTEGER NOT NULL DEFAULT 0,
            discovered_at TEXT NOT NULL,
            last_seen     TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_local_services_host_port
            ON local_services (host, port);
        """)
        _migrate(conn)
