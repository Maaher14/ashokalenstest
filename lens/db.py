import sqlite3
from contextlib import contextmanager
from pathlib import Path
from flask import current_app, g

LOCATIONS = [
    "Amphitheatre",
    "Academic Block",
    "Library",
    "Sports Complex",
    "Student Commons",
    "Residence Halls",
    "Dining Hall",
    "Campus Grounds",
]


def db():
    if "db" not in g:
        conn = sqlite3.connect(
            current_app.config["DATABASE"], timeout=15, isolation_level=None
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        g.db = conn
    return g.db


@contextmanager
def transaction():
    conn = db()
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def one(sql, args=()):
    row = db().execute(sql, args).fetchone()
    return dict(row) if row else None


def rows(sql, args=()):
    return [dict(r) for r in db().execute(sql, args).fetchall()]


def initialise():
    db().executescript(Path(__file__).with_name("schema.sql").read_text())
    db().executemany(
        "INSERT OR IGNORE INTO locations(name) VALUES (?)", [(x,) for x in LOCATIONS]
    )


def close(_=None):
    if conn := g.pop("db", None):
        conn.close()
