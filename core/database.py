import os
import sqlite3
import threading


_local = threading.local()


def get_db(db_path):
    if not hasattr(_local, "connection") or _local.connection is None:
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        _local.connection = sqlite3.connect(db_path, check_same_thread=False, timeout=10)
        _local.connection.row_factory = sqlite3.Row
        _local.connection.execute("PRAGMA journal_mode=WAL")
        _local.connection.execute("PRAGMA foreign_keys=ON")
    return _local.connection


def init_db(db_path):
    schema_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "migrations", "schema.sql"
    )
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    with open(schema_path) as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()


def query_db(db_path, query, args=(), one=False):
    conn = get_db(db_path)
    cur = conn.execute(query, args)
    rv = cur.fetchall()
    return (rv[0] if rv else None) if one else rv


def execute_db(db_path, query, args=()):
    conn = get_db(db_path)
    conn.execute(query, args)
    conn.commit()
