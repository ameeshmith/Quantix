"""Tests for FastMCP server tools and HTTP Bearer token authentication."""

import json
from pathlib import Path

import httpx
import pytest
import respx
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from quantix.auth import BearerAuthMiddleware
from quantix.config import Settings
from quantix.db import Database
from quantix.edgar.client import EdgarClient
from quantix.services.company import list_filings, lookup_company
from quantix.services.diff import diff_filings
from quantix.services.metrics import get_financials
from quantix.services.sections import get_filing_section
from quantix.services.summarize import generate_company_brief
from quantix.services.watchlist import (
    check_new_filings,
    list_watchlist,
    unwatch_ticker,
    watch_ticker,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_server.db"
    return Database(str(db_file))


@pytest.fixture
def valid_settings(tmp_path):
    return Settings(
        edgar_user_agent="QuantixTest test@example.com",
        db_path=str(tmp_path / "test_server.db"),
        mcp_api_key="secret-token-123",
    )


@pytest.fixture
def sample_html():
    with open(FIXTURES_DIR / "sample_10k_aapl.html", "r", encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def tickers_payload():
    with open(FIXTURES_DIR / "company_tickers.json", "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def submissions_payload():
    with open(FIXTURES_DIR / "submissions_aapl.json", "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def facts_payload():
    with open(FIXTURES_DIR / "company_facts_aapl.json", "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.asyncio
async def test_auth_middleware_health_whitelisted():
    async def sample_endpoint(request):
        return JSONResponse({"data": "protected"})

    async def health_endpoint(request):
        return JSONResponse({"status": "healthy"})

    routes = [
        Route("/health", health_endpoint, methods=["GET"]),
        Route("/mcp/endpoint", sample_endpoint, methods=["POST"]),
    ]
    raw_app = Starlette(routes=routes)
    app = BearerAuthMiddleware(raw_app, api_key="secret-token-123")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # /health requires no auth
        r_health = await client.get("/health")
        assert r_health.status_code == 200
        assert r_health.json()["status"] == "healthy"

        # Protected endpoint without header -> 401
        r_unauth = await client.post("/mcp/endpoint")
        assert r_unauth.status_code == 401
        assert "Missing Authorization" in r_unauth.json()["detail"]

        # Protected endpoint with bad token -> 401
        r_bad = await client.post("/mcp/endpoint", headers={"Authorization": "Bearer wrong"})
        assert r_bad.status_code == 401

        # Protected endpoint with valid token -> 200
        auth_hdr = {"Authorization": "Bearer secret-token-123"}
        r_good = await client.post("/mcp/endpoint", headers=auth_hdr)
        assert r_good.status_code == 200
        assert r_good.json()["data"] == "protected"


@pytest.mark.asyncio
@respx.mock
async def test_all_tools_integration(
    valid_settings,
    temp_db,
    tickers_payload,
    submissions_payload,
    facts_payload,
    sample_html,
):
    # Mock SEC endpoints
    respx.get("https://www.sec.gov/files/company_tickers.json").respond(
        status_code=200,
        json=tickers_payload,
    )
    respx.get("https://data.sec.gov/submissions/CIK0000320193.json").respond(
        status_code=200,
        json=submissions_payload,
    )
    respx.get("https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json").respond(
        status_code=200,
        json=facts_payload,
    )
    # Mock filing HTML document
    respx.get(
        "https://www.sec.gov/Archives/edgar/data/320193/000032019324000106/aapl-20240928.htm"
    ).respond(status_code=200, text=sample_html)
    respx.get(
        "https://www.sec.gov/Archives/edgar/data/320193/000032019323000106/aapl-20230930.htm"
    ).respond(status_code=200, text=sample_html)

    client = EdgarClient(settings=valid_settings, db=temp_db)

    try:
        # Tool 1: lookup_company
        comp = await lookup_company(client, "AAPL")
        assert comp["ticker"] == "AAPL"
        assert comp["cik"] == "0000320193"

        # Tool 2: list_filings
        filings = await list_filings(client, "AAPL", form_type="10-K", limit=2)
        assert len(filings) == 2

        # Tool 3: get_financials
        fin = await get_financials(client, "AAPL", "revenue", periods=2)
        assert fin["status"] == "available"

        # Tool 4: get_filing_section
        sec = await get_filing_section(client, "AAPL", form_type="10-K", section="risk_factors")
        assert sec["section"] == "risk_factors"
        assert "Global economic conditions" in sec["text"]

        # Tool 5: diff_filings
        diff = await diff_filings(client, "AAPL", section="risk_factors", form_type="10-K")
        assert diff["ticker"] == "AAPL"
        assert diff["counts"]["unchanged"] > 0

        # Tool 6: Watchlist Tools
        w_add = await watch_ticker(client, temp_db, "AAPL")
        assert w_add["status"] == "success"

        w_list = await list_watchlist(temp_db)
        assert w_list["count"] == 1
        assert w_list["watchlist"][0]["ticker"] == "AAPL"

        # Tool 7: check_new_filings
        new_f = await check_new_filings(client, temp_db, ticker="AAPL")
        assert "new_filings_count" in new_f

        # Tool 8: company_brief
        brief = await generate_company_brief(client, "AAPL")
        assert brief["ticker"] == "AAPL"
        assert "brief_overview" in brief
        assert "Informational only, not investment advice." in brief["disclaimer"]

        # Unwatch
        w_rm = await unwatch_ticker(temp_db, "AAPL")
        assert w_rm["status"] == "success"
        w_list2 = await list_watchlist(temp_db)
        assert w_list2["count"] == 0

    finally:
        await client.close()
        await temp_db.close()
