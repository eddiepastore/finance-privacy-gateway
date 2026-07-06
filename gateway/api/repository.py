"""SQLite data access for the full dataset lifecycle (spec Sections 15, 16).

One Repository instance == one connection. JSON columns keep flexible payloads (packets, mappings,
local facts) without a migration framework. Postgres-ready column choices.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS datasets (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, company_name TEXT,
    reporting_period TEXT NOT NULL, privacy_mode TEXT NOT NULL,
    status TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS uploaded_files (
    id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL, file_type TEXT NOT NULL,
    original_filename TEXT NOT NULL, content TEXT NOT NULL,
    row_count INTEGER, columns_json TEXT, status TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS column_mappings (
    id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL, file_id TEXT NOT NULL,
    mapping_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS calculation_runs (
    id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL, status TEXT NOT NULL,
    summary_json TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS obfuscation_runs (
    id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL, period TEXT, calculation_run_id TEXT,
    privacy_mode TEXT NOT NULL, risk_level TEXT NOT NULL, risk_score INTEGER NOT NULL,
    raw_dollars_sent INTEGER NOT NULL, real_entities_sent INTEGER NOT NULL,
    packet_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS analysis_runs (
    id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL, period TEXT, obfuscation_run_id TEXT NOT NULL,
    provider TEXT, model TEXT, status TEXT NOT NULL, validation_ok INTEGER,
    response_json TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS review_items (
    id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL, period TEXT, analysis_run_id TEXT,
    issue_id TEXT, title TEXT NOT NULL, severity TEXT, status TEXT NOT NULL,
    draft_text TEXT NOT NULL, approved_text TEXT, extra_json TEXT,
    assigned_to TEXT, approved_by TEXT, approved_at TEXT
);
CREATE TABLE IF NOT EXISTS board_narratives (
    id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL, period TEXT, audience TEXT, markdown TEXT NOT NULL,
    status TEXT NOT NULL, created_at TEXT NOT NULL, approved_by TEXT, approved_at TEXT
);
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, dataset_id TEXT NOT NULL, ts TEXT NOT NULL,
    actor TEXT NOT NULL, action TEXT NOT NULL, detail TEXT
);
"""


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Repository:
    # Columns added after the original schema — applied to pre-existing DBs on open.
    _MIGRATIONS = [
        ("obfuscation_runs", "period", "TEXT"),
        ("analysis_runs", "period", "TEXT"),
        ("review_items", "period", "TEXT"),
        ("board_narratives", "period", "TEXT"),
    ]

    def __init__(self, path: str = ":memory:"):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self):
        """Self-healing schema: add later-introduced columns to a pre-existing DB (no migration tool)."""
        for table, column, coltype in self._MIGRATIONS:
            cols = {r["name"] for r in self.conn.execute(f"PRAGMA table_info({table})").fetchall()}
            if column not in cols:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")

    def close(self):
        self.conn.close()

    # --- audit -------------------------------------------------------------------------------
    def log(self, dataset_id: str, action: str, detail: str = "", actor: str = "system"):
        self.conn.execute(
            "INSERT INTO audit_events (dataset_id, ts, actor, action, detail) VALUES (?,?,?,?,?)",
            (dataset_id, _now(), actor, action, detail),
        )
        self.conn.commit()

    def audit(self, dataset_id: str) -> List[Dict[str, Any]]:
        cur = self.conn.execute(
            "SELECT ts, actor, action, detail FROM audit_events WHERE dataset_id=? ORDER BY id", (dataset_id,))
        return [dict(r) for r in cur.fetchall()]

    # --- datasets ----------------------------------------------------------------------------
    def create_dataset(self, name: str, reporting_period: str, privacy_mode: str,
                       company_name: Optional[str] = None) -> Dict[str, Any]:
        did = _id("ds")
        self.conn.execute(
            "INSERT INTO datasets VALUES (?,?,?,?,?,?,?)",
            (did, name, company_name or name, reporting_period, privacy_mode, "created", _now()))
        self.conn.commit()
        self.log(did, "dataset_created", f"name={name}")
        return self.get_dataset(did)

    def get_dataset(self, dataset_id: str) -> Optional[Dict[str, Any]]:
        cur = self.conn.execute("SELECT * FROM datasets WHERE id=?", (dataset_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def set_dataset_status(self, dataset_id: str, status: str):
        self.conn.execute("UPDATE datasets SET status=? WHERE id=?", (status, dataset_id))
        self.conn.commit()

    def set_dataset_privacy_mode(self, dataset_id: str, privacy_mode: str):
        self.conn.execute("UPDATE datasets SET privacy_mode=? WHERE id=?", (privacy_mode, dataset_id))
        self.conn.commit()
        self.log(dataset_id, "privacy_mode_updated", f"privacy_mode={privacy_mode}")

    # --- files / mappings --------------------------------------------------------------------
    def add_file(self, dataset_id: str, file_type: str, filename: str, content: str,
                 row_count: int, columns: List[str]) -> Dict[str, Any]:
        fid = _id("file")
        self.conn.execute(
            "INSERT INTO uploaded_files VALUES (?,?,?,?,?,?,?,?,?)",
            (fid, dataset_id, file_type, filename, content, row_count,
             json.dumps(columns), "uploaded", _now()))
        self.conn.commit()
        self.log(dataset_id, "file_uploaded", f"{file_type}: {filename} ({row_count} rows)")
        return {"file_id": fid, "rows_detected": row_count, "columns_detected": columns, "status": "uploaded"}

    def files(self, dataset_id: str) -> List[Dict[str, Any]]:
        cur = self.conn.execute("SELECT * FROM uploaded_files WHERE dataset_id=?", (dataset_id,))
        return [dict(r) for r in cur.fetchall()]

    def save_mapping(self, dataset_id: str, file_id: str, mapping: Dict[str, str]):
        self.conn.execute("INSERT INTO column_mappings VALUES (?,?,?,?,?)",
                          (_id("map"), dataset_id, file_id, json.dumps(mapping), _now()))
        self.conn.commit()
        self.log(dataset_id, "mapping_saved", f"file={file_id}")

    def mapping_for(self, file_id: str) -> Optional[Dict[str, str]]:
        cur = self.conn.execute(
            "SELECT mapping_json FROM column_mappings WHERE file_id=? ORDER BY created_at DESC LIMIT 1", (file_id,))
        row = cur.fetchone()
        return json.loads(row["mapping_json"]) if row else None

    # --- runs --------------------------------------------------------------------------------
    def add_calculation_run(self, dataset_id: str, summary: Dict[str, Any]) -> str:
        cid = _id("calc")
        self.conn.execute("INSERT INTO calculation_runs VALUES (?,?,?,?,?)",
                          (cid, dataset_id, "completed", json.dumps(summary), _now()))
        self.conn.commit()
        self.log(dataset_id, "calculation_run_created", json.dumps(summary))
        return cid

    def add_obfuscation_run(self, dataset_id: str, calc_id: Optional[str], privacy_mode: str,
                            risk_level: str, risk_score: int, raw_dollars: bool,
                            real_entities: bool, packet: Dict[str, Any], period: Optional[str] = None) -> str:
        oid = _id("obf")
        self.conn.execute(
            "INSERT INTO obfuscation_runs (id,dataset_id,period,calculation_run_id,privacy_mode,"
            "risk_level,risk_score,raw_dollars_sent,real_entities_sent,packet_json,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (oid, dataset_id, period, calc_id, privacy_mode, risk_level, risk_score,
             int(raw_dollars), int(real_entities), json.dumps(packet), _now()))
        self.conn.commit()
        self.log(dataset_id, "obfuscation_run_created",
                 f"period={period} risk={risk_level} raw_dollars={raw_dollars} real_entities={real_entities}")
        return oid

    def get_obfuscation_run(self, oid: str) -> Optional[Dict[str, Any]]:
        cur = self.conn.execute("SELECT * FROM obfuscation_runs WHERE id=?", (oid,))
        row = cur.fetchone()
        return dict(row) if row else None

    def _latest(self, table: str, dataset_id: str, period: Optional[str]) -> Optional[Dict[str, Any]]:
        if period is not None:
            cur = self.conn.execute(
                f"SELECT * FROM {table} WHERE dataset_id=? AND period=? ORDER BY created_at DESC, rowid DESC LIMIT 1",
                (dataset_id, period))
        else:
            cur = self.conn.execute(
                f"SELECT * FROM {table} WHERE dataset_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1",
                (dataset_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def latest_obfuscation_run(self, dataset_id: str, period: Optional[str] = None) -> Optional[Dict[str, Any]]:
        return self._latest("obfuscation_runs", dataset_id, period)

    def latest_analysis_run(self, dataset_id: str, period: Optional[str] = None) -> Optional[Dict[str, Any]]:
        return self._latest("analysis_runs", dataset_id, period)

    def latest_board_narrative(self, dataset_id: str, period: Optional[str] = None) -> Optional[Dict[str, Any]]:
        return self._latest("board_narratives", dataset_id, period)

    def list_datasets(self) -> List[Dict[str, Any]]:
        cur = self.conn.execute("SELECT * FROM datasets ORDER BY created_at DESC")
        return [dict(r) for r in cur.fetchall()]

    def add_analysis_run(self, dataset_id: str, obf_id: str, provider: str, model: str,
                         status: str, validation_ok: Optional[bool], response: Any,
                         period: Optional[str] = None) -> str:
        aid = _id("analysis")
        self.conn.execute(
            "INSERT INTO analysis_runs (id,dataset_id,period,obfuscation_run_id,provider,model,"
            "status,validation_ok,response_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (aid, dataset_id, period, obf_id, provider, model, status,
             None if validation_ok is None else int(validation_ok), json.dumps(response), _now()))
        self.conn.commit()
        self.log(dataset_id, "analysis_run_created", f"period={period} provider={provider} status={status}")
        return aid

    # --- review items ------------------------------------------------------------------------
    def delete_review_items(self, dataset_id: str, period: Optional[str]) -> None:
        """Idempotency: clear a period's review items before re-analyzing it."""
        if period is not None:
            self.conn.execute("DELETE FROM review_items WHERE dataset_id=? AND period=?", (dataset_id, period))
        else:
            self.conn.execute("DELETE FROM review_items WHERE dataset_id=? AND period IS NULL", (dataset_id,))
        self.conn.commit()

    def add_review_item(self, dataset_id: str, analysis_id: str, item: Dict[str, Any],
                        period: Optional[str] = None) -> str:
        rid = _id("rev")
        extra = {k: item.get(k) for k in
                 ("likely_drivers", "management_questions", "recommended_action",
                  "forecast_adjustment_recommendation", "local_forecast_adjustment", "local_facts")}
        self.conn.execute(
            "INSERT INTO review_items (id,dataset_id,period,analysis_run_id,issue_id,title,severity,status,"
            "draft_text,approved_text,extra_json,assigned_to,approved_by,approved_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (rid, dataset_id, period, analysis_id, item.get("issue_id"), item["title"], item.get("severity"),
             "draft", item.get("draft_text", ""), None, json.dumps(extra), None, None, None))
        self.conn.commit()
        return rid

    def review_items(self, dataset_id: str, period: Optional[str] = None) -> List[Dict[str, Any]]:
        if period is not None:
            cur = self.conn.execute(
                "SELECT * FROM review_items WHERE dataset_id=? AND period=? ORDER BY id", (dataset_id, period))
        else:
            cur = self.conn.execute("SELECT * FROM review_items WHERE dataset_id=? ORDER BY id", (dataset_id,))
        out = []
        for r in cur.fetchall():
            d = dict(r)
            d["extra"] = json.loads(d.pop("extra_json") or "{}")
            out.append(d)
        return out

    def approve_review_item(self, rid: str, approved_text: Optional[str], reviewer_id: str) -> Optional[Dict[str, Any]]:
        cur = self.conn.execute("SELECT dataset_id, draft_text FROM review_items WHERE id=?", (rid,))
        row = cur.fetchone()
        if not row:
            return None
        text = approved_text if approved_text is not None else row["draft_text"]
        ts = _now()
        self.conn.execute(
            "UPDATE review_items SET status='approved', approved_text=?, approved_by=?, approved_at=? WHERE id=?",
            (text, reviewer_id, ts, rid))
        self.conn.commit()
        self.log(row["dataset_id"], "review_item_approved", f"{rid} by {reviewer_id}")
        return {"status": "approved", "approved_at": ts}

    def request_revision_review_item(self, rid: str, reason: str, reviewer_id: str) -> Optional[Dict[str, Any]]:
        cur = self.conn.execute("SELECT dataset_id FROM review_items WHERE id=?", (rid,))
        row = cur.fetchone()
        if not row:
            return None
        # Revision reopens the item: any prior approval is withdrawn until it is approved again.
        self.conn.execute(
            "UPDATE review_items SET status='revision_requested', approved_text=NULL, approved_by=NULL, "
            "approved_at=NULL WHERE id=?", (rid,))
        self.conn.commit()
        detail = f"{rid} by {reviewer_id}" + (f": {reason}" if reason else "")
        self.log(row["dataset_id"], "review_item_revision_requested", detail)
        return {"status": "revision_requested"}

    # --- board -------------------------------------------------------------------------------
    def add_board_narrative(self, dataset_id: str, audience: str, markdown: str,
                            period: Optional[str] = None) -> str:
        bid = _id("bn")
        self.conn.execute(
            "INSERT INTO board_narratives (id,dataset_id,period,audience,markdown,status,created_at,"
            "approved_by,approved_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (bid, dataset_id, period, audience, markdown, "draft", _now(), None, None))
        self.conn.commit()
        self.log(dataset_id, "board_narrative_generated", f"period={period} audience={audience}")
        return bid

    def get_review_item(self, rid: str) -> Optional[Dict[str, Any]]:
        cur = self.conn.execute("SELECT * FROM review_items WHERE id=?", (rid,))
        row = cur.fetchone()
        if not row:
            return None
        d = dict(row)
        d["extra"] = json.loads(d.pop("extra_json") or "{}")
        return d
