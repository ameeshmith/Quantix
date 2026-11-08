"""SQLite database connection, schema migration, and async data access."""

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import aiosqlite

logger = logging.getLogger(__name__)


SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS edgar_cache (
        url TEXT PRIMARY KEY,
        status_code INTEGER NOT NULL,
        headers TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at REAL NOT NULL,
        expires_at REAL
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_edgar_cache_expires_at ON edgar_cache(expires_at);
    """,
    """
    CREATE TABLE IF NOT EXISTS watchlist (
        ticker TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        cik TEXT NOT NULL,
        added_at REAL NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS filing_alerts (
        accession_number TEXT PRIMARY KEY,
        ticker TEXT NOT NULL,
        form_type TEXT NOT NULL,
        filing_date TEXT NOT NULL,
        alerted_at REAL NOT NULL,
        summary TEXT
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_filing_alerts_ticker ON filing_alerts(ticker);
    """,
]


class Database:
    """Async database client wrapping aiosqlite."""

    def __init__(self, db_path: str = "quantix.db"):
        self.db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None

    async def connect(self) -> aiosqlite.Connection:
        """Connect to SQLite database and ensure schema is initialized."""
        if self._conn is None:
            p = Path(self.db_path)
            if p.parent and not p.parent.exists():
                p.parent.mkdir(parents=True, exist_ok=True)
            self._conn = await aiosqlite.connect(self.db_path)
            self._conn.row_factory = aiosqlite.Row
            # Enable WAL mode for high concurrency
            await self._conn.execute("PRAGMA journal_mode = WAL;")
            await self._conn.execute("PRAGMA synchronous = NORMAL;")
            await self.init_schema()
        return self._conn

    async def close(self) -> None:
        """Close connection cleanly."""
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def init_schema(self) -> None:
        """Create tables and indexes if they do not exist."""
        assert self._conn is not None
        for statement in SCHEMA_STATEMENTS:
            await self._conn.execute(statement)
        await self._conn.commit()

    # --------------------------------------------------------------------------
    # Cache Methods
    # --------------------------------------------------------------------------
    async def get_cache(self, url: str) -> Optional[Tuple[int, Dict[str, str], str]]:
        """Retrieve valid cached response for a given URL.

        Returns (status_code, headers_dict, content_str) or None if absent or expired.
        """
        conn = await self.connect()
        now = time.time()
        query = """
            SELECT status_code, headers, content, expires_at
            FROM edgar_cache
            WHERE url = ?
        """
        async with conn.execute(query, (url,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            status_code, headers_json, content, expires_at = row[0], row[1], row[2], row[3]
            if expires_at is not None and expires_at < now:
                # Expired
                return None
            try:
                headers = json.loads(headers_json)
            except Exception:
                headers = {}
            return status_code, headers, content

    async def set_cache(
        self,
        url: str,
        status_code: int,
        headers: Dict[str, str],
        content: str,
        ttl_seconds: Optional[float] = None,
    ) -> None:
        """Store or update response in cache with optional TTL."""
        conn = await self.connect()
        now = time.time()
        expires_at = (now + ttl_seconds) if ttl_seconds is not None else None
        headers_json = json.dumps(dict(headers))
        query = """
            INSERT INTO edgar_cache (url, status_code, headers, content, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                status_code = excluded.status_code,
                headers = excluded.headers,
                content = excluded.content,
                created_at = excluded.created_at,
                expires_at = excluded.expires_at
        """
        await conn.execute(query, (url, status_code, headers_json, content, now, expires_at))
        await conn.commit()

    async def purge_expired_cache(self) -> int:
        """Delete all expired entries from cache. Returns count of removed rows."""
        conn = await self.connect()
        now = time.time()
        query = "DELETE FROM edgar_cache WHERE expires_at IS NOT NULL AND expires_at < ?"
        cursor = await conn.execute(query, (now,))
        await conn.commit()
        return cursor.rowcount

    # --------------------------------------------------------------------------
    # Watchlist Methods
    # --------------------------------------------------------------------------
    async def add_to_watchlist(self, ticker: str, name: str, cik: str) -> None:
        """Add or update a ticker in the watchlist."""
        conn = await self.connect()
        now = time.time()
        query = """
            INSERT INTO watchlist (ticker, name, cik, added_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(ticker) DO UPDATE SET
                name = excluded.name,
                cik = excluded.cik
        """
        await conn.execute(query, (ticker.upper(), name, cik, now))
        await conn.commit()

    async def remove_from_watchlist(self, ticker: str) -> bool:
        """Remove a ticker from the watchlist. Returns True if removed."""
        conn = await self.connect()
        query = "DELETE FROM watchlist WHERE ticker = ?"
        cursor = await conn.execute(query, (ticker.upper(),))
        await conn.commit()
        return cursor.rowcount > 0

    async def get_watchlist(self) -> List[Dict[str, Any]]:
        """Return all watched tickers sorted by ticker symbol."""
        conn = await self.connect()
        query = "SELECT ticker, name, cik, added_at FROM watchlist ORDER BY ticker ASC"
        async with conn.execute(query) as cursor:
            rows = await cursor.fetchall()
            return [
                {
                    "ticker": row[0],
                    "name": row[1],
                    "cik": row[2],
                    "added_at": row[3],
                }
                for row in rows
            ]

    # --------------------------------------------------------------------------
    # Alerts Deduplication Methods
    # --------------------------------------------------------------------------
    async def is_alerted(self, accession_number: str) -> bool:
        """Check if an alert was already dispatched for this filing accession number."""
        conn = await self.connect()
        query = "SELECT 1 FROM filing_alerts WHERE accession_number = ?"
        async with conn.execute(query, (accession_number,)) as cursor:
            row = await cursor.fetchone()
            return row is not None

    async def record_alert(
        self,
        accession_number: str,
        ticker: str,
        form_type: str,
        filing_date: str,
        summary: Optional[str] = None,
    ) -> None:
        """Record that an alert was dispatched for a filing accession number."""
        conn = await self.connect()
        now = time.time()
        query = """
            INSERT INTO filing_alerts
                (accession_number, ticker, form_type, filing_date, alerted_at, summary)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(accession_number) DO NOTHING
        """
        await conn.execute(
            query,
            (accession_number, ticker.upper(), form_type, filing_date, now, summary),
        )
        await conn.commit()


# Singleton pattern helper
_db_instance: Optional[Database] = None


def get_db(db_path: str = "quantix.db") -> Database:
    """Get or create singleton Database instance."""
    global _db_instance
    if _db_instance is None or _db_instance.db_path != db_path:
        _db_instance = Database(db_path)
    return _db_instance
