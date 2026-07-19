import sqlite3
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    gateway_ok INTEGER,
    gateway_latency REAL,
    external_ok INTEGER,
    external_latency REAL,
    status TEXT NOT NULL,
    reason TEXT
);

CREATE TABLE IF NOT EXISTS outages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_ts INTEGER NOT NULL,
    end_ts INTEGER,
    duration_sec INTEGER,
    type TEXT NOT NULL,
    reason TEXT
);

CREATE TABLE IF NOT EXISTS speedtests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    download_mbps REAL,
    upload_mbps REAL,
    ping_ms REAL
);

CREATE INDEX IF NOT EXISTS idx_checks_ts ON checks(ts);
CREATE INDEX IF NOT EXISTS idx_speedtests_ts ON speedtests(ts);
"""


@contextmanager
def get_conn(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path):
    with get_conn(db_path) as conn:
        conn.executescript(SCHEMA)
        # 舊 DB 沒有 reason 欄位,加上去 (若已存在會 raise,忽略即可)
        for table in ("checks", "outages"):
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN reason TEXT")
            except sqlite3.OperationalError:
                pass


def get_last_speedtest_ts(db_path):
    init_db(db_path)
    with get_conn(db_path) as conn:
        row = conn.execute("SELECT ts FROM speedtests ORDER BY ts DESC LIMIT 1").fetchone()
        return row[0] if row else 0
