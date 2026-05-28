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
        """)
