"""SQLite data model for the practice app.

The events table uses the same shape as the raw event stream in
product-metrics-layer, so app data can be loaded straight into the
metrics warehouse.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
create table if not exists accounts (
    account_id text primary key,
    name       text not null
);
create table if not exists users (
    user_id    text primary key,
    account_id text not null references accounts(account_id),
    email      text not null unique,
    name       text not null,
    team       text not null check (team in ('sales', 'service'))
);
create table if not exists scenarios (
    scenario_id text primary key,
    title       text not null,
    prompt      text not null,
    keywords    text not null            -- JSON list used by the scorer
);
create table if not exists sessions (
    session_id   text primary key,
    user_id      text not null references users(user_id),
    scenario_id  text not null references scenarios(scenario_id),
    status       text not null check (status in ('started', 'completed', 'abandoned')),
    started_at   text not null,
    completed_at text,
    answer       text,
    score        integer
);
create table if not exists goals (
    user_id           text primary key references users(user_id),
    sessions_per_week integer not null,
    set_at            text not null
);
create table if not exists events (
    event_id    text primary key,
    user_id     text not null,
    event_type  text not null,
    session_id  text,
    scenario_id text,
    event_ts    text not null,
    properties  text not null default '{}'
);
"""

SCENARIOS = [
    ("scn_price", "Handling a price objection",
     "The customer says your offer is 20% more expensive than a competitor. Respond.",
     ["value", "understand", "cost", "question", "example"]),
    ("scn_complaint", "Calming an upset customer",
     "A customer is angry because a delivery is three days late. Respond.",
     ["sorry", "understand", "next", "update", "solution"]),
    ("scn_discovery", "Opening a discovery call",
     "Open a first call with a new prospect and find out what they need.",
     ["goal", "challenge", "question", "team", "priority"]),
]


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat(sep=" ")


def connect(path: Path | str) -> sqlite3.Connection:
    con = sqlite3.connect(str(path), check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("pragma foreign_keys = on")
    return con


def init(path: Path | str) -> None:
    with connect(path) as con:
        con.executescript(SCHEMA)
        con.execute("insert or ignore into accounts values ('acc_001', 'Demo Insurance AG')")
        con.executemany("insert or ignore into users values (?, 'acc_001', ?, ?, ?)", [
            ("usr_001", "lena@demo.test", "Lena", "sales"),
            ("usr_002", "tom@demo.test", "Tom", "service"),
        ])
        con.executemany("insert or ignore into scenarios values (?, ?, ?, ?)",
                        [(s, t, p, json.dumps(k)) for s, t, p, k in SCENARIOS])


def track(con: sqlite3.Connection, user_id: str, event_type: str, session_id: str | None = None,
          scenario_id: str | None = None, **props) -> None:
    con.execute("insert into events values (?, ?, ?, ?, ?, ?, ?)",
                (f"evt_{uuid.uuid4().hex[:12]}", user_id, event_type, session_id, scenario_id,
                 now(), json.dumps(props)))
