"""Opt-in live smoke test querying real SEC EDGAR API (skipped unless RUN_LIVE_TESTS=1)."""

import os

import pytest

from quantix.config import Settings
from quantix.db import Database
from quantix.edgar.client import EdgarClient
from quantix.services.company import list_filings, lookup_company

RUN_LIVE = os.getenv("RUN_LIVE_TESTS") in ("1", "true", "True")


@pytest.mark.skipif(not RUN_LIVE, reason="Live smoke test skipped unless RUN_LIVE_TESTS=1")
@pytest.mark.asyncio
async def test_live_sec_edgar_smoke(tmp_path):
    """Opt-in live integration test verifying live network connection to official SEC EDGAR."""
    test_db = tmp_path / "live_test.db"
    settings = Settings(
        edgar_user_agent="QuantixTestLive analyst@example.com",
        db_path=str(test_db),
    )
    db = Database(str(test_db))
    client = EdgarClient(settings=settings, db=db)

    try:
        # 1. Lookup company live
        comp = await lookup_company(client, "AAPL")
        assert comp["ticker"] == "AAPL"
        assert comp["cik"] == "0000320193"

        # 2. List filings live
        filings = await list_filings(client, "AAPL", form_type="10-K", limit=2)
        assert len(filings) >= 1
        assert filings[0]["form_type"] == "10-K"
        assert "Archives/edgar/data" in filings[0]["document_url"]
    finally:
        await client.close()
        await db.close()
