"""Minimal SQLite persistence + audit log (subset of spec Section 16 that the pipeline populates).

Postgres-ready column choices; SQLite for the local demo (spec Section 16 allows either).
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS datasets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    reporting_period TEXT NOT NULL,
    privacy_mode TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS obfuscation_runs (
    id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL,
    privacy_mode TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    risk_score INTEGER NOT NULL,
    packet_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS review_items (
    id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL,
    issue_id TEXT,
    title TEXT NOT NULL,
    draft_text TEXT NOT NULL,
    approved_text TEXT,
    status TEXT NOT NULL,
    severity TEXT,
    local_facts_json TEXT
);
CREATE TABLE IF NOT EXISTS board_narratives (
    id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL,
    markdown TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT
);
"""


class Database:
    def __init__(self, path: str = ":memory:"):
        self.conn = sqlite3.connect(path)
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def persist_run(self, result: Any) -> None:
        c = self.conn
        c.execute(
            "INSERT OR REPLACE INTO datasets VALUES (?,?,?,?,?,datetime('now'))",
            (result.dataset_id, f"Operating Review {result.period}", result.period,
             result.privacy_mode, "analyzed"),
        )
        c.execute(
            "INSERT OR REPLACE INTO obfuscation_runs VALUES (?,?,?,?,?,?,datetime('now'))",
            (f"obf_{result.dataset_id}", result.dataset_id, result.privacy_mode,
             result.risk.level, result.risk.score, json.dumps(result.packet)),
        )
        for ri in result.review_items:
            c.execute(
                "INSERT OR REPLACE INTO review_items VALUES (?,?,?,?,?,?,?,?,?)",
                (ri["review_item_id"], ri["dataset_id"], ri.get("issue_id"), ri["title"],
                 ri["draft_text"], None, ri["status"], ri.get("severity"),
                 json.dumps(ri.get("local_facts"))),
            )
        if result.board_markdown:
            c.execute(
                "INSERT OR REPLACE INTO board_narratives VALUES (?,?,?,?,datetime('now'))",
                (f"bn_{result.dataset_id}", result.dataset_id, result.board_markdown, "draft"),
            )
        for e in result.audit_log:
            c.execute(
                "INSERT INTO audit_events (dataset_id, ts, actor, action, detail) VALUES (?,?,?,?,?)",
                (result.dataset_id, e["ts"], e["actor"], e["action"], e.get("detail", "")),
            )
        c.commit()

    def close(self):
        self.conn.close()
