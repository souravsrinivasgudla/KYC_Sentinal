import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.models.state import KYCState

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "kyc_sentinel.db"


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS intakes (
                intake_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                source TEXT NOT NULL,
                customer_json TEXT NOT NULL,
                case_id TEXT
            );
            CREATE TABLE IF NOT EXISTS cases (
                case_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                source TEXT NOT NULL,
                customer_name TEXT NOT NULL,
                state_json TEXT NOT NULL
            );
            """
        )


def save_intake(intake_id: str, source: str, customer: dict, case_id: str | None = None) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO intakes (intake_id, created_at, source, customer_json, case_id) VALUES (?, ?, ?, ?, ?)",
            (intake_id, datetime.now(timezone.utc).isoformat(), source, json.dumps(customer), case_id),
        )


def link_intake_case(intake_id: str, case_id: str) -> None:
    with _conn() as conn:
        conn.execute("UPDATE intakes SET case_id = ? WHERE intake_id = ?", (case_id, intake_id))


def save_case(state: KYCState, source: str = "custom") -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO cases (case_id, created_at, source, customer_name, state_json) VALUES (?, ?, ?, ?, ?)",
            (
                state.case_id,
                datetime.now(timezone.utc).isoformat(),
                source,
                state.customer_profile.get("name", "Unknown"),
                state.model_dump_json(),
            ),
        )


def get_case(case_id: str) -> KYCState | None:
    with _conn() as conn:
        row = conn.execute("SELECT state_json FROM cases WHERE case_id = ?", (case_id,)).fetchone()
    if not row:
        return None
    return KYCState.model_validate_json(row["state_json"])


def list_cases() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT case_id, created_at, source, customer_name, state_json FROM cases ORDER BY created_at DESC"
        ).fetchall()
    results = []
    for row in rows:
        state = KYCState.model_validate_json(row["state_json"])
        results.append(
            {
                "case_id": row["case_id"],
                "created_at": row["created_at"],
                "source": row["source"],
                "customer_name": row["customer_name"],
                "risk_score": state.risk_assessment.get("risk_score", 0),
                "risk_level": state.risk_assessment.get("risk_level", "Unknown"),
                "decision": state.decision.get("status", "PENDING"),
                "final_status": state.decision.get("final_status"),
                "requires_review": state.decision.get("requires_human_review", False),
                "human_reviewed": state.decision.get("human_reviewed", False),
                "missing_fields": state.document_extraction.get("fields_missing", []),
                "overall_confidence": state.overall_confidence,
                "top_risk_drivers": state.top_risk_drivers,
                "edd_triggered": state.edd_triggered,
                "consistency_score": state.consistency_score,
            }
        )
    return results


def list_intakes() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT intake_id, created_at, source, customer_json, case_id FROM intakes ORDER BY created_at DESC LIMIT 50"
        ).fetchall()
    return [
        {
            "intake_id": r["intake_id"],
            "created_at": r["created_at"],
            "source": r["source"],
            "customer": json.loads(r["customer_json"]),
            "case_id": r["case_id"],
        }
        for r in rows
    ]
