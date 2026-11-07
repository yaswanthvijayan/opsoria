"""SQLite persistence layer for Opsoria incidents.

Provides robust, crash-resilient storage for incidents and investigation analyses
using Python stdlib sqlite3 with Write-Ahead Logging (WAL) mode.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

DEFAULT_DB_PATH = os.getenv("OPSORIA_DB_PATH", "opsoria.db")


def _ensure_tables(conn: sqlite3.Connection) -> None:
    """Ensure the incidents table and associated indexes exist (self-healing)."""
    with conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS incidents (
                incident_id TEXT PRIMARY KEY,
                service TEXT NOT NULL,
                environment TEXT NOT NULL,
                status TEXT NOT NULL,
                symptoms TEXT NOT NULL,
                possible_causes TEXT NOT NULL,
                metadata TEXT NOT NULL,
                confirmed_resolution TEXT NULL,
                memory_status TEXT NOT NULL,
                is_synthetic INTEGER NOT NULL DEFAULT 0,
                last_analysis TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_incidents_created_at ON incidents(created_at DESC);"
        )


def get_connection(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open a new SQLite connection configured for safe concurrent access and self-healing schema."""
    conn = sqlite3.connect(db_path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA foreign_keys=ON;")
    _ensure_tables(conn)
    return conn


def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    """Create the incidents table and associated indexes if they do not exist."""
    conn = get_connection(db_path)
    conn.close()


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Convert an SQLite Row to a dictionary with parsed JSON fields."""
    d = dict(row)
    if "possible_causes" in d and isinstance(d["possible_causes"], str):
        try:
            d["possible_causes"] = json.loads(d["possible_causes"])
        except Exception:
            d["possible_causes"] = []
    if "metadata" in d and isinstance(d["metadata"], str):
        try:
            d["metadata"] = json.loads(d["metadata"])
        except Exception:
            d["metadata"] = {}
    if "last_analysis" in d and isinstance(d["last_analysis"], str):
        try:
            d["last_analysis"] = json.loads(d["last_analysis"])
        except Exception:
            d["last_analysis"] = {}
    d["is_synthetic"] = bool(d.get("is_synthetic", 0))
    return d


def save_or_upsert_incident(
    incident_id: str,
    service: str,
    environment: str,
    status: str,
    symptoms: str,
    possible_causes: list[str],
    metadata: dict[str, Any],
    confirmed_resolution: str | None,
    memory_status: str,
    last_analysis: dict[str, Any],
    db_path: str = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """Save an incident or upsert if existing.

    Never downgrades a 'resolved' incident: if stored status is 'resolved',
    keeps status, confirmed_resolution, and memory_status unchanged and only
    refreshes last_analysis, service, environment, symptoms, possible_causes,
    metadata, and updated_at.
    """
    now = datetime.now(timezone.utc).isoformat()
    # is_synthetic is 1 when metadata.type == 'synthetic_test' or explicitly flagged
    meta_type = str(metadata.get("type", "")).strip().lower()
    is_synth_int = 1 if meta_type == "synthetic_test" else 0

    causes_json = json.dumps(possible_causes)
    metadata_json = json.dumps(metadata)
    analysis_json = json.dumps(last_analysis)

    conn = get_connection(db_path)
    try:
        with conn:
            existing = conn.execute(
                "SELECT status, confirmed_resolution, memory_status, created_at FROM incidents WHERE incident_id = ?",
                (incident_id,),
            ).fetchone()

            if existing:
                created_at = existing["created_at"]
                if existing["status"] == "resolved":
                    # Preserve resolved status and confirmed resolution
                    final_status = "resolved"
                    final_resolution = existing["confirmed_resolution"]
                    final_mem_status = existing["memory_status"]
                else:
                    final_status = status
                    final_resolution = confirmed_resolution
                    final_mem_status = memory_status

                conn.execute(
                    """
                    UPDATE incidents
                    SET service = ?,
                        environment = ?,
                        status = ?,
                        symptoms = ?,
                        possible_causes = ?,
                        metadata = ?,
                        confirmed_resolution = ?,
                        memory_status = ?,
                        is_synthetic = ?,
                        last_analysis = ?,
                        updated_at = ?
                    WHERE incident_id = ?
                    """,
                    (
                        service,
                        environment,
                        final_status,
                        symptoms,
                        causes_json,
                        metadata_json,
                        final_resolution,
                        final_mem_status,
                        is_synth_int,
                        analysis_json,
                        now,
                        incident_id,
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO incidents (
                        incident_id, service, environment, status, symptoms,
                        possible_causes, metadata, confirmed_resolution,
                        memory_status, is_synthetic, last_analysis,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        incident_id,
                        service,
                        environment,
                        status,
                        symptoms,
                        causes_json,
                        metadata_json,
                        confirmed_resolution,
                        memory_status,
                        is_synth_int,
                        analysis_json,
                        now,
                        now,
                    ),
                )

            row = conn.execute(
                "SELECT * FROM incidents WHERE incident_id = ?", (incident_id,)
            ).fetchone()
            return _row_to_dict(row)
    finally:
        conn.close()


def resolve_incident_in_db(
    incident_id: str,
    confirmed_resolution: str,
    memory_status: str,
    last_analysis: dict[str, Any],
    db_path: str = DEFAULT_DB_PATH,
) -> dict[str, Any] | None:
    """Update an incident to resolved status with its confirmed resolution and memory_status."""
    now = datetime.now(timezone.utc).isoformat()
    analysis_json = json.dumps(last_analysis)

    conn = get_connection(db_path)
    try:
        with conn:
            existing = conn.execute(
                "SELECT incident_id FROM incidents WHERE incident_id = ?", (incident_id,)
            ).fetchone()
            if not existing:
                return None

            conn.execute(
                """
                UPDATE incidents
                SET status = 'resolved',
                    confirmed_resolution = ?,
                    memory_status = ?,
                    last_analysis = ?,
                    updated_at = ?
                WHERE incident_id = ?
                """,
                (
                    confirmed_resolution,
                    memory_status,
                    analysis_json,
                    now,
                    incident_id,
                ),
            )
            row = conn.execute(
                "SELECT * FROM incidents WHERE incident_id = ?", (incident_id,)
            ).fetchone()
            return _row_to_dict(row) if row else None
    finally:
        conn.close()


def get_incident_by_id(
    incident_id: str, db_path: str = DEFAULT_DB_PATH
) -> dict[str, Any] | None:
    """Retrieve full incident record by ID, or None if not found."""
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM incidents WHERE incident_id = ?", (incident_id,)
        ).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def list_incidents_from_db(
    status: str | None = None, db_path: str = DEFAULT_DB_PATH
) -> list[dict[str, Any]]:
    """List incidents ordered newest first, with optional status filter."""
    conn = get_connection(db_path)
    try:
        if status and status.strip():
            cursor = conn.execute(
                "SELECT * FROM incidents WHERE status = ? ORDER BY created_at DESC",
                (status.strip(),),
            )
        else:
            cursor = conn.execute(
                "SELECT * FROM incidents ORDER BY created_at DESC"
            )
        return [_row_to_dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


def get_incident_stats(db_path: str = DEFAULT_DB_PATH) -> dict[str, Any]:
    """Compute aggregate statistics over all stored incidents."""
    conn = get_connection(db_path)
    try:
        total = conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]
        resolved_count = conn.execute(
            "SELECT COUNT(*) FROM incidents WHERE status = 'resolved'"
        ).fetchone()[0]
        persisted_count = conn.execute(
            "SELECT COUNT(*) FROM incidents WHERE memory_status = 'persisted'"
        ).fetchone()[0]
        not_persisted_count = conn.execute(
            "SELECT COUNT(*) FROM incidents WHERE memory_status = 'not_persisted'"
        ).fetchone()[0]
        synthetic_count = conn.execute(
            "SELECT COUNT(*) FROM incidents WHERE is_synthetic = 1"
        ).fetchone()[0]

        # Counts by status
        status_rows = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM incidents GROUP BY status"
        ).fetchall()
        by_status = {r["status"]: r["cnt"] for r in status_rows}

        # Most recent 5 incidents
        recent_rows = conn.execute(
            "SELECT * FROM incidents ORDER BY created_at DESC LIMIT 5"
        ).fetchall()
        recent_incidents = [_row_to_dict(r) for r in recent_rows]

        return {
            "total": total,
            "by_status": by_status,
            "resolved_count": resolved_count,
            "persisted_count": persisted_count,
            "not_persisted_count": not_persisted_count,
            "synthetic_count": synthetic_count,
            "recent_incidents": recent_incidents,
        }
    finally:
        conn.close()


def seed_demo_if_empty(
    db_path: str = DEFAULT_DB_PATH, seed_path: str | None = None
) -> int:
    """Seed the database with demo incidents if the incidents table is empty.

    Does not alter any stored memory_status value.
    Returns the count of seeded rows.
    """
    if seed_path is None:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        seed_path = os.path.join(base_dir, "seed_demo.json")

    if not os.path.exists(seed_path):
        return 0

    conn = get_connection(db_path)
    try:
        with conn:
            count = conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]
            if count > 0:
                return 0

            with open(seed_path, "r", encoding="utf-8") as f:
                records = json.load(f)

            if not isinstance(records, list):
                return 0

            inserted = 0
            for r in records:
                causes_json = (
                    json.dumps(r.get("possible_causes", []))
                    if isinstance(r.get("possible_causes"), list)
                    else (r.get("possible_causes") or "[]")
                )
                metadata_json = (
                    json.dumps(r.get("metadata", {}))
                    if isinstance(r.get("metadata"), dict)
                    else (r.get("metadata") or "{}")
                )
                analysis_json = (
                    json.dumps(r.get("last_analysis", {}))
                    if isinstance(r.get("last_analysis"), dict)
                    else (r.get("last_analysis") or "{}")
                )
                is_synth = 1 if r.get("is_synthetic") else 0
                created_at = r.get("created_at") or datetime.now(timezone.utc).isoformat()
                updated_at = r.get("updated_at") or created_at

                conn.execute(
                    """
                    INSERT INTO incidents (
                        incident_id, service, environment, status, symptoms,
                        possible_causes, metadata, confirmed_resolution,
                        memory_status, is_synthetic, last_analysis,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        r["incident_id"],
                        r["service"],
                        r["environment"],
                        r["status"],
                        r["symptoms"],
                        causes_json,
                        metadata_json,
                        r.get("confirmed_resolution"),
                        r["memory_status"],
                        is_synth,
                        analysis_json,
                        created_at,
                        updated_at,
                    ),
                )
                inserted += 1
            return inserted
    finally:
        conn.close()
