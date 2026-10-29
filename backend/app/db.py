import hashlib
import json
import sqlite3
from pathlib import Path

from .config import DB_PATH


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def connect():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


def _insert_audit_event(db, event_type, data, created_at, decision_id=None, actor="bhashachain-api", trace_id=None):
    previous = db.execute("SELECT event_hash FROM audit_events ORDER BY id DESC LIMIT 1").fetchone()
    previous_hash = previous[0] if previous and previous[0] else "0" * 64
    body = {"event_type": event_type, "data": data, "created_at": created_at, "decision_id": decision_id,
            "actor": actor, "trace_id": trace_id, "previous_hash": previous_hash}
    event_hash = hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()
    db.execute("INSERT INTO audit_events(decision_id,event_type,data,created_at,actor,trace_id,previous_hash,event_hash) VALUES(?,?,?,?,?,?,?,?)",
               (decision_id, event_type, _canonical(data), created_at, actor, trace_id, previous_hash, event_hash))
    return event_hash


def _backfill_audit_chain(db):
    rows = db.execute("SELECT id,decision_id,event_type,data,created_at,actor,trace_id,event_hash FROM audit_events ORDER BY id").fetchall()
    previous_hash = "0" * 64
    for row in rows:
        if row["event_hash"]:
            previous_hash = row["event_hash"]
            continue
        data = json.loads(row["data"])
        body = {"event_type": row["event_type"], "data": data, "created_at": row["created_at"],
                "decision_id": row["decision_id"], "actor": row["actor"] or "bhashachain-api",
                "trace_id": row["trace_id"], "previous_hash": previous_hash}
        event_hash = hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()
        db.execute("UPDATE audit_events SET actor=?,previous_hash=?,event_hash=? WHERE id=?",
                   (body["actor"], previous_hash, event_hash, row["id"]))
        previous_hash = event_hash


def init_db():
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS datasets(dataset_id TEXT PRIMARY KEY, data TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS decisions(decision_id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL, decision TEXT NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS audit_events(id INTEGER PRIMARY KEY AUTOINCREMENT, decision_id TEXT, event_type TEXT NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL);
        """)
        columns = {row[1] for row in db.execute("PRAGMA table_info(audit_events)")}
        for name, kind in (("actor", "TEXT"), ("trace_id", "TEXT"), ("previous_hash", "TEXT"), ("event_hash", "TEXT")):
            if name not in columns:
                db.execute(f"ALTER TABLE audit_events ADD COLUMN {name} {kind}")
        _backfill_audit_chain(db)


def save_dataset(d):
    with connect() as db:
        db.execute("INSERT INTO datasets VALUES(?,?,?)", (d["dataset_id"], json.dumps(d), d["created_at"]))


def update_dataset(d):
    with connect() as db:
        db.execute("UPDATE datasets SET data=? WHERE dataset_id=?", (json.dumps(d), d["dataset_id"]))


def save_audit_event(event_type, data, created_at, decision_id=None, actor="bhashachain-api", trace_id=None):
    with connect() as db:
        return _insert_audit_event(db, event_type, data, created_at, decision_id, actor, trace_id)


def list_audit_events(limit=100):
    with connect() as db:
        rows = db.execute("SELECT id,decision_id,event_type,data,created_at,actor,trace_id,previous_hash,event_hash FROM audit_events ORDER BY id DESC LIMIT ?", (limit,))
        return [{"event_id": r[0], "decision_id": r[1], "event_type": r[2], "data": json.loads(r[3]), "created_at": r[4],
                 "actor": r[5], "trace_id": r[6], "previous_hash": r[7], "event_hash": r[8]} for r in rows]


def verify_audit_chain():
    with connect() as db:
        rows = db.execute("SELECT id,decision_id,event_type,data,created_at,actor,trace_id,previous_hash,event_hash FROM audit_events ORDER BY id").fetchall()
    expected_previous = "0" * 64
    for row in rows:
        body = {"event_type": row["event_type"], "data": json.loads(row["data"]), "created_at": row["created_at"],
                "decision_id": row["decision_id"], "actor": row["actor"], "trace_id": row["trace_id"],
                "previous_hash": expected_previous}
        expected = hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()
        if row["previous_hash"] != expected_previous or row["event_hash"] != expected:
            return {"valid": False, "checked_events": row["id"] - 1, "first_invalid_event_id": row["id"]}
        expected_previous = row["event_hash"]
    return {"valid": True, "checked_events": len(rows), "head_hash": expected_previous}


def get_dataset(dataset_id):
    with connect() as db:
        row = db.execute("SELECT data FROM datasets WHERE dataset_id=?", (dataset_id,)).fetchone()
    return json.loads(row[0]) if row else None


def list_datasets():
    with connect() as db:
        return [json.loads(row[0]) for row in db.execute("SELECT data FROM datasets ORDER BY dataset_id")]


def save_decision(decision):
    with connect() as db:
        db.execute("INSERT INTO decisions VALUES(?,?,?,?,?)", (decision["decision_id"], decision["dataset_id"], decision["decision"], _canonical(decision), decision["timestamp"]))
        return _insert_audit_event(db, "INGESTION_DECISION", decision, decision["timestamp"], decision["decision_id"], trace_id=decision.get("trace_id"))


def update_decision(decision):
    with connect() as db:
        db.execute("UPDATE decisions SET data=? WHERE decision_id=?", (_canonical(decision), decision["decision_id"]))


def list_decisions():
    with connect() as db:
        return [json.loads(row[0]) for row in db.execute("SELECT data FROM decisions ORDER BY created_at DESC")]


def get_decision(decision_id):
    with connect() as db:
        row = db.execute("SELECT data FROM decisions WHERE decision_id=?", (decision_id,)).fetchone()
    return json.loads(row[0]) if row else None
