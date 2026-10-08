"""Lead storage — SQLite database for persisting leads across runs."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from leadpilot.models import ScoredLead, EmailResult, EmailStatus, ICPScores, FieldProvenance

logger = logging.getLogger(__name__)


class LeadDatabase:
    """SQLite database for lead storage and retrieval."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS leads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_name TEXT NOT NULL,
                    domain TEXT,
                    website_url TEXT,
                    phone TEXT,
                    description TEXT,
                    location TEXT,
                    industry TEXT,
                    product_description TEXT,
                    size_guess TEXT,
                    founder_name TEXT,
                    contact_email TEXT,
                    total_score INTEGER DEFAULT 0,
                    reason TEXT,
                    icp_scores_json TEXT,
                    emails_json TEXT,
                    sources_json TEXT,
                    run_id TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_leads_domain ON leads(domain);
                CREATE INDEX IF NOT EXISTS idx_leads_score ON leads(total_score DESC);
                CREATE INDEX IF NOT EXISTS idx_leads_run ON leads(run_id);

                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    brief TEXT NOT NULL,
                    icp_json TEXT,
                    started_at TEXT,
                    completed_at TEXT,
                    lead_count INTEGER DEFAULT 0,
                    errors_json TEXT
                );
            """)

    def save_lead(self, lead: ScoredLead, run_id: str) -> int:
        """Save a scored lead to the database. Returns the row ID."""
        with self._connect() as conn:
            cursor = conn.execute(
                """INSERT INTO leads (
                    company_name, domain, website_url, phone, description,
                    location, industry, product_description, size_guess,
                    founder_name, contact_email, total_score, reason,
                    icp_scores_json, emails_json, sources_json, run_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    lead.company_name,
                    lead.domain,
                    lead.website_url,
                    lead.phone,
                    lead.description,
                    lead.location,
                    lead.industry,
                    lead.product_description,
                    lead.size_guess,
                    lead.founder_name,
                    lead.contact_email,
                    lead.total_score,
                    lead.reason,
                    lead.icp_scores.model_dump_json() if lead.icp_scores else None,
                    json.dumps([e.model_dump() for e in lead.emails]) if lead.emails else "[]",
                    json.dumps([s.model_dump() for s in lead.sources], default=str) if lead.sources else "[]",
                    run_id,
                ),
            )
            return cursor.lastrowid

    def save_leads(self, leads: list[ScoredLead], run_id: str) -> int:
        """Save multiple leads. Returns count saved."""
        count = 0
        for lead in leads:
            try:
                self.save_lead(lead, run_id)
                count += 1
            except Exception as exc:
                logger.error("Failed to save lead %s: %s", lead.company_name, exc)
        return count

    def save_run(
        self,
        run_id: str,
        brief: str,
        icp_json: str | None = None,
        started_at: str | None = None,
        completed_at: str | None = None,
        lead_count: int = 0,
        errors: list[str] | None = None,
    ) -> None:
        """Save or update a pipeline run record."""
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO runs
                    (id, brief, icp_json, started_at, completed_at, lead_count, errors_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    brief,
                    icp_json,
                    started_at,
                    completed_at,
                    lead_count,
                    json.dumps(errors or []),
                ),
            )

    def get_leads(
        self,
        run_id: str | None = None,
        min_score: int = 0,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Retrieve leads, optionally filtered by run and score."""
        query = "SELECT * FROM leads WHERE total_score >= ?"
        params: list = [min_score]

        if run_id:
            query += " AND run_id = ?"
            params.append(run_id)

        query += " ORDER BY total_score DESC LIMIT ?"
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]

    def get_runs(self) -> list[dict[str, Any]]:
        """List all pipeline runs."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY started_at DESC"
            ).fetchall()
            return [dict(row) for row in rows]
