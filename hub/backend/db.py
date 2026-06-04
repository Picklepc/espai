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
    # Add updated + slug columns to projects (additive)
    proj_cols = {row[1] for row in conn.execute("PRAGMA table_info(projects)").fetchall()}
    for col, ddl in [
        ("updated", "ALTER TABLE projects ADD COLUMN updated TEXT"),
        ("slug",    "ALTER TABLE projects ADD COLUMN slug    TEXT"),
    ]:
        if col not in proj_cols:
            conn.execute(ddl)

    # Add git_sha column to ota_log (records project HEAD at push time)
    ota_cols = {row[1] for row in conn.execute("PRAGMA table_info(ota_log)").fetchall()}
    if "git_sha" not in ota_cols:
        conn.execute("ALTER TABLE ota_log ADD COLUMN git_sha TEXT")

    # Backfill project_nodes from projects.devices JSON if the table is empty
    node_count = conn.execute("SELECT COUNT(*) FROM project_nodes").fetchone()[0]
    if node_count == 0:
        import json as _json
        for row in conn.execute("SELECT id, devices FROM projects WHERE devices IS NOT NULL").fetchall():
            try:
                ids = _json.loads(row["devices"] or "[]")
            except Exception:
                ids = []
            for idx, did in enumerate(ids):
                conn.execute(
                    "INSERT OR IGNORE INTO project_nodes (project_id, device_id, role, node_index) VALUES (?,?,?,?)",
                    (row["id"], did, "node", idx),
                )

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
        rows = conn.execute("SELECT id, name FROM projects").fetchall()
        for row in rows:
            conn.execute(
                "UPDATE projects SET slug=? WHERE id=?",
                (_to_hostname(row[1]), row[0]),
            )

    # Add device_type — governs scaffold, ESPAI.md content, and agent templates
    proj_cols = {row[1] for row in conn.execute("PRAGMA table_info(projects)").fetchall()}
    if "device_type" not in proj_cols:
        conn.execute("ALTER TABLE projects ADD COLUMN device_type TEXT DEFAULT 'esp32'")

    # Add reachable column to local_services for health polling
    svc_cols = {row[1] for row in conn.execute("PRAGMA table_info(local_services)").fetchall()}
    if "reachable" not in svc_cols:
        conn.execute("ALTER TABLE local_services ADD COLUMN reachable INTEGER DEFAULT 1")

    # Add sleep_interval_s + awake_window_s to devices
    dev_cols = {row[1] for row in conn.execute("PRAGMA table_info(devices)").fetchall()}
    if "sleep_interval_s" not in dev_cols:
        conn.execute("ALTER TABLE devices ADD COLUMN sleep_interval_s INTEGER")
    if "awake_window_s" not in dev_cols:
        conn.execute("ALTER TABLE devices ADD COLUMN awake_window_s INTEGER DEFAULT 5")

    # Add schedule / schedule_tz columns to rules (cron + timezone support)
    rules_cols = {row[1] for row in conn.execute("PRAGMA table_info(rules)").fetchall()}
    if "schedule" not in rules_cols:
        conn.execute("ALTER TABLE rules ADD COLUMN schedule TEXT")
    if "schedule_tz" not in rules_cols:
        conn.execute("ALTER TABLE rules ADD COLUMN schedule_tz TEXT")

    # Add lat/lng columns to project_data for spatial queries (M26c)
    pd_cols = {row[1] for row in conn.execute("PRAGMA table_info(project_data)").fetchall()}
    if "lat" not in pd_cols:
        conn.execute("ALTER TABLE project_data ADD COLUMN lat REAL")
    if "lng" not in pd_cols:
        conn.execute("ALTER TABLE project_data ADD COLUMN lng REAL")
    # Index to make spatial bbox queries fast
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_project_data_location
        ON project_data (project_id, lat, lng)
        WHERE lat IS NOT NULL
    """)

    # Add max_fires_per_hour to rules (M12 / 0.4.3 rate limiting)
    rules_cols = {row[1] for row in conn.execute("PRAGMA table_info(rules)").fetchall()}
    if "max_fires_per_hour" not in rules_cols:
        conn.execute("ALTER TABLE rules ADD COLUMN max_fires_per_hour INTEGER")

    # Rule fire log table (created in schema above; index is idempotent)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rule_fires (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_id  TEXT    NOT NULL,
            fired_at TEXT    NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_rule_fires_rule_time
        ON rule_fires (rule_id, fired_at DESC)
    """)


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
            updated     TEXT,
            slug        TEXT,
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
            id                  TEXT PRIMARY KEY,
            name                TEXT NOT NULL,
            enabled             INTEGER NOT NULL DEFAULT 1,
            event_type          TEXT NOT NULL,
            source_filter       TEXT,
            action_type         TEXT NOT NULL,
            action_config       TEXT,
            created             TEXT NOT NULL,
            last_triggered      TEXT,
            max_fires_per_hour  INTEGER    -- NULL = unlimited
        );

        -- ── Rule fire log ─────────────────────────────────────────────────────
        -- Rolling log used to enforce max_fires_per_hour.
        -- Pruned to a 2-hour window on every write.
        CREATE TABLE IF NOT EXISTS rule_fires (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_id  TEXT    NOT NULL,
            fired_at TEXT    NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_rule_fires_rule_time
            ON rule_fires (rule_id, fired_at DESC);

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

        -- ── Hub-level persistent settings ─────────────────────────────────────
        -- Simple key-value store for hub configuration (active theme, etc.).
        CREATE TABLE IF NOT EXISTS hub_settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        -- ── Geofence zones ───────────────────────────────────────────────────
        -- Named polygon zones per project. The data push hook fires
        -- geofence.enter / geofence.exit events when a device crosses a boundary.
        CREATE TABLE IF NOT EXISTS geofences (
            id          TEXT PRIMARY KEY,
            project_id  TEXT NOT NULL,
            name        TEXT NOT NULL,
            device_id   TEXT,           -- NULL = all devices in project
            polygon     TEXT NOT NULL,  -- JSON: [[lat,lng], ...]
            event_enter TEXT NOT NULL DEFAULT 'geofence.enter',
            event_exit  TEXT NOT NULL DEFAULT 'geofence.exit',
            enabled     INTEGER NOT NULL DEFAULT 1,
            created     TEXT NOT NULL,
            last_state  TEXT            -- 'inside' | 'outside' | NULL (first reading)
        );
        CREATE INDEX IF NOT EXISTS idx_geofences_pid
            ON geofences (project_id, enabled);

        -- ── Device command queue ─────────────────────────────────────────────
        -- Hub enqueues commands; devices poll and ack. TTL-based expiry.
        CREATE TABLE IF NOT EXISTS device_commands (
            id           TEXT PRIMARY KEY,
            device_id    TEXT NOT NULL,
            command_type TEXT NOT NULL,       -- reboot | set_config | user_action | run_ota_check
            payload      TEXT,               -- JSON
            status       TEXT NOT NULL DEFAULT 'pending',  -- pending | delivered | acked | expired | cancelled
            created      TEXT NOT NULL,
            ttl_seconds  INTEGER NOT NULL DEFAULT 300,
            delivered_at TEXT,
            acked_at     TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_device_commands_device
            ON device_commands (device_id, status, created DESC);

        -- ── Project media store ───────────────────────────────────────────────
        -- Binary files (images, audio, etc.) uploaded by devices or hub workers.
        CREATE TABLE IF NOT EXISTS project_media (
            id           TEXT PRIMARY KEY,
            project_id   TEXT NOT NULL,
            filename     TEXT NOT NULL,
            content_type TEXT,
            size_bytes   INTEGER NOT NULL DEFAULT 0,
            file_path    TEXT NOT NULL,      -- relative to MEDIA_DIR/{project_id}/
            created      TEXT NOT NULL,
            metadata     TEXT               -- JSON: device_id, tags, etc.
        );
        CREATE INDEX IF NOT EXISTS idx_project_media_pid
            ON project_media (project_id, created DESC);

        -- ── Project nodes ─────────────────────────────────────────────────────
        -- Structured node membership with per-node roles and labels.
        -- Replaces the flat projects.devices JSON array while staying backward-
        -- compatible (devices column is kept in sync on all writes).
        CREATE TABLE IF NOT EXISTS project_nodes (
            project_id  TEXT    NOT NULL,
            device_id   TEXT    NOT NULL,
            role        TEXT    NOT NULL DEFAULT 'node',
            label       TEXT,
            node_index  INTEGER NOT NULL DEFAULT 0,
            meta        TEXT,
            PRIMARY KEY (project_id, device_id)
        );
        CREATE INDEX IF NOT EXISTS idx_project_nodes_dev
            ON project_nodes (device_id);
        """)
        _migrate(conn)


def get_setting(key: str, default: str | None = None) -> str | None:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM hub_settings WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def set_setting(key: str, value: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO hub_settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
