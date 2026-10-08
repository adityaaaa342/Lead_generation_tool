"""SQLite-backed caching for HTTP responses and LLM calls."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class _SQLiteCache:
    """Base SQLite cache with TTL support."""

    def __init__(self, db_path: Path, table_name: str = "cache"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.table_name = table_name
        self._init_db()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.table_name} (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    domain TEXT,
                    created_at REAL NOT NULL,
                    ttl INTEGER NOT NULL
                )
            """)
            conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{self.table_name}_domain
                ON {self.table_name}(domain)
            """)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db_path), timeout=10)

    def get(self, key: str) -> Optional[str]:
        """Get a cached value if it exists and hasn't expired."""
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT value, created_at, ttl FROM {self.table_name} WHERE key = ?",
                (key,),
            ).fetchone()

        if row is None:
            return None

        value, created_at, ttl = row
        if time.time() - created_at > ttl:
            self.delete(key)
            return None

        return value

    def set(self, key: str, value: str, ttl: int = 86400, domain: str | None = None) -> None:
        """Store a value with TTL."""
        with self._connect() as conn:
            conn.execute(
                f"""INSERT OR REPLACE INTO {self.table_name}
                    (key, value, domain, created_at, ttl)
                    VALUES (?, ?, ?, ?, ?)""",
                (key, value, domain, time.time(), ttl),
            )

    def delete(self, key: str) -> None:
        """Delete a cached entry."""
        with self._connect() as conn:
            conn.execute(f"DELETE FROM {self.table_name} WHERE key = ?", (key,))

    def invalidate_domain(self, domain: str) -> int:
        """Delete all cache entries for a specific domain."""
        with self._connect() as conn:
            cursor = conn.execute(
                f"DELETE FROM {self.table_name} WHERE domain = ?", (domain,)
            )
            return cursor.rowcount

    def clear(self) -> None:
        """Clear all cache entries."""
        with self._connect() as conn:
            conn.execute(f"DELETE FROM {self.table_name}")

    def cleanup_expired(self) -> int:
        """Remove all expired entries."""
        with self._connect() as conn:
            cursor = conn.execute(
                f"DELETE FROM {self.table_name} WHERE (created_at + ttl) < ?",
                (time.time(),),
            )
            return cursor.rowcount

    def stats(self) -> dict[str, int]:
        """Return cache statistics."""
        with self._connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM {self.table_name}").fetchone()[0]
            expired = conn.execute(
                f"SELECT COUNT(*) FROM {self.table_name} WHERE (created_at + ttl) < ?",
                (time.time(),),
            ).fetchone()[0]
        return {"total": total, "active": total - expired, "expired": expired}


class HTTPCache(_SQLiteCache):
    """Cache for HTTP responses, keyed by URL + method + params."""

    def __init__(self, db_path: Path):
        super().__init__(db_path, table_name="http_cache")

    @staticmethod
    def make_key(url: str, method: str = "GET", params: dict | None = None) -> str:
        """Create a deterministic cache key from request parameters."""
        payload = json.dumps(
            {"url": url, "method": method, "params": params or {}},
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def get_response(
        self, url: str, method: str = "GET", params: dict | None = None
    ) -> Optional[dict[str, Any]]:
        """Get a cached HTTP response."""
        key = self.make_key(url, method, params)
        raw = self.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    def set_response(
        self,
        url: str,
        response_data: dict[str, Any],
        method: str = "GET",
        params: dict | None = None,
        ttl: int = 86400,
        domain: str | None = None,
    ) -> None:
        """Cache an HTTP response."""
        key = self.make_key(url, method, params)
        self.set(key, json.dumps(response_data), ttl=ttl, domain=domain)


class LLMCache(_SQLiteCache):
    """Cache for LLM responses, keyed by prompt hash + model."""

    def __init__(self, db_path: Path):
        super().__init__(db_path, table_name="llm_cache")
