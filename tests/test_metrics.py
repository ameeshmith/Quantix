"""Tests for XBRL financial metrics extraction and fallback mappings."""

import json
from pathlib import Path

import pytest
import respx

from quantix.config import Settings
from quantix.db import Database
from quantix.edgar.client import EdgarClient
from quantix.services.metrics import get_financials

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_metrics.db"
    return Database(str(db_file))


@pytest.fixture
def valid_settings(tmp_path):
    return Settings(
        edgar_user_agent="QuantixTest test@example.com",
        db_path=str(tmp_path / "test_metrics.db"),
    )


@pytest.fixture
def tickers_payload():
    with open(FIXTURES_DIR / "company_tickers.json", "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def facts_aapl_payload():
    with open(FIXTURES_DIR / "company_facts_aapl.json", "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.asyncio
@respx.mock
async def test_get_financials_annual_revenue(
    valid_settings,
    temp_db,
    tickers_payload,
    facts_aapl_payload,
):
    respx.get("https://www.sec.gov/files/company_tickers.json").respond(
        status_code=200,
        json=tickers_payload,
    )
    respx.get("https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json").respond(
        status_code=200,
        json=facts_aapl_payload,
    )

    client = EdgarClient(settings=valid_settings, db=temp_db)
    try:
        data = await get_financials(client, "AAPL", "revenue", period_type="annual")
        assert data["status"] == "available"
        assert data["ticker"] == "AAPL"
        assert data["metric"] == "revenue"
        assert data["unit"] == "USD"
        assert data["tag_used"] == "RevenueFromContractWithCustomerExcludingAssessedTax"
        assert len(data["datapoints"]) == 2
        # Verify chronological order
        assert data["datapoints"][0]["fiscal_year"] == 2023
        assert data["datapoints"][0]["value"] == 383285000000
        assert data["datapoints"][1]["fiscal_year"] == 2024
        assert data["datapoints"][1]["value"] == 391035000000
        assert "filing_url" in data["datapoints"][0]
        assert "0000320193-23-000106" in data["datapoints"][0]["filing_url"]
        assert data["disclaimer"] == "Informational only, not investment advice."
    finally:
        await client.close()
        await temp_db.close()


@pytest.mark.asyncio
@respx.mock
async def test_get_financials_quarterly_revenue(
    valid_settings,
    temp_db,
    tickers_payload,
    facts_aapl_payload,
):
    respx.get("https://www.sec.gov/files/company_tickers.json").respond(
        status_code=200,
        json=tickers_payload,
    )
    respx.get("https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json").respond(
        status_code=200,
        json=facts_aapl_payload,
    )

    client = EdgarClient(settings=valid_settings, db=temp_db)
    try:
        data = await get_financials(client, "AAPL", "revenue", period_type="quarterly")
        assert data["status"] == "available"
        assert len(data["datapoints"]) == 1
        assert data["datapoints"][0]["fiscal_period"] == "Q3"
        assert data["datapoints"][0]["value"] == 85777000000
    finally:
        await client.close()
        await temp_db.close()


@pytest.mark.asyncio
@respx.mock
async def test_get_financials_eps_diluted(
    valid_settings,
    temp_db,
    tickers_payload,
    facts_aapl_payload,
):
    respx.get("https://www.sec.gov/files/company_tickers.json").respond(
        status_code=200,
        json=tickers_payload,
    )
    respx.get("https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json").respond(
        status_code=200,
        json=facts_aapl_payload,
    )

    client = EdgarClient(settings=valid_settings, db=temp_db)
    try:
        data = await get_financials(client, "AAPL", "eps_diluted", period_type="annual")
        assert data["status"] == "available"
        assert data["unit"] == "USD/shares"
        assert data["tag_used"] == "EarningsPerShareDiluted"
        assert data["datapoints"][0]["value"] == 6.13
        assert data["datapoints"][1]["value"] == 6.08
    finally:
        await client.close()
        await temp_db.close()


@pytest.mark.asyncio
@respx.mock
async def test_get_financials_missing_metric_handled(
    valid_settings,
    temp_db,
    tickers_payload,
    facts_aapl_payload,
):
    respx.get("https://www.sec.gov/files/company_tickers.json").respond(
        status_code=200,
        json=tickers_payload,
    )
    respx.get("https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json").respond(
        status_code=200,
        json=facts_aapl_payload,
    )

    client = EdgarClient(settings=valid_settings, db=temp_db)
    try:
        # Capex not in our mock payload
        data = await get_financials(client, "AAPL", "capex", period_type="annual")
        assert data["status"] == "unavailable"
        assert "not available" in data["message"].lower()
        assert len(data["datapoints"]) == 0
        assert data["disclaimer"] == "Informational only, not investment advice."
    finally:
        await client.close()
        await temp_db.close()


@pytest.mark.asyncio
@respx.mock
async def test_get_financials_unsupported_metric_name(
    valid_settings,
    temp_db,
):
    client = EdgarClient(settings=valid_settings, db=temp_db)
    try:
        data = await get_financials(client, "AAPL", "ebitda_custom_adjusted")
        assert data["status"] == "unavailable"
        assert "Unsupported metric" in data["error"]
    finally:
        await client.close()
        await temp_db.close()

