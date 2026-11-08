"""Tests for company lookup and filing listing services."""

import json
from pathlib import Path

import pytest
import respx

from quantix.config import Settings
from quantix.db import Database
from quantix.edgar.client import EdgarClient
from quantix.exceptions import CompanyNotFound, FilingNotFound
from quantix.services.company import list_filings, lookup_company

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_company.db"
    return Database(str(db_file))


@pytest.fixture
def valid_settings(tmp_path):
    return Settings(
        edgar_user_agent="QuantixTest test@example.com",
        db_path=str(tmp_path / "test_company.db"),
    )


@pytest.fixture
def tickers_payload():
    with open(FIXTURES_DIR / "company_tickers.json", "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def submissions_payload():
    with open(FIXTURES_DIR / "submissions_aapl.json", "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.asyncio
@respx.mock
async def test_lookup_company_exact_ticker(valid_settings, temp_db, tickers_payload):
    respx.get("https://www.sec.gov/files/company_tickers.json").respond(
        status_code=200,
        json=tickers_payload,
    )
    client = EdgarClient(settings=valid_settings, db=temp_db)
    try:
        res = await lookup_company(client, "AAPL")
        assert res["ticker"] == "AAPL"
        assert res["name"] == "Apple Inc."
        assert res["cik"] == "0000320193"
        assert "as_of" in res
        assert "source_url" in res
    finally:
        await client.close()
        await temp_db.close()


@pytest.mark.asyncio
@respx.mock
async def test_lookup_company_by_name(valid_settings, temp_db, tickers_payload):
    respx.get("https://www.sec.gov/files/company_tickers.json").respond(
        status_code=200,
        json=tickers_payload,
    )
    client = EdgarClient(settings=valid_settings, db=temp_db)
    try:
        # Exact title
        res = await lookup_company(client, "MICROSOFT CORP")
        assert res["ticker"] == "MSFT"
        assert res["cik"] == "0000789019"

        # Partial case-insensitive title
        res2 = await lookup_company(client, "tesla")
        assert res2["ticker"] == "TSLA"
        assert res2["cik"] == "0001318605"
    finally:
        await client.close()
        await temp_db.close()


@pytest.mark.asyncio
@respx.mock
async def test_lookup_company_not_found(valid_settings, temp_db, tickers_payload):
    respx.get("https://www.sec.gov/files/company_tickers.json").respond(
        status_code=200,
        json=tickers_payload,
    )
    client = EdgarClient(settings=valid_settings, db=temp_db)
    try:
        with pytest.raises(CompanyNotFound):
            await lookup_company(client, "NONEXISTENT_CORP_XYZ")
    finally:
        await client.close()
        await temp_db.close()


@pytest.mark.asyncio
@respx.mock
async def test_list_filings_success(valid_settings, temp_db, tickers_payload, submissions_payload):
    respx.get("https://www.sec.gov/files/company_tickers.json").respond(
        status_code=200,
        json=tickers_payload,
    )
    respx.get("https://data.sec.gov/submissions/CIK0000320193.json").respond(
        status_code=200,
        json=submissions_payload,
    )

    client = EdgarClient(settings=valid_settings, db=temp_db)
    try:
        # Filter for 10-K
        filings_10k = await list_filings(client, "AAPL", form_type="10-K", limit=2)
        assert len(filings_10k) == 2
        assert filings_10k[0]["form_type"] == "10-K"
        assert filings_10k[0]["accession_number"] == "0000320193-24-000106"
        expected_part = "Archives/edgar/data/320193/000032019324000106/aapl-20240928.htm"
        assert expected_part in filings_10k[0]["document_url"]
        assert filings_10k[0]["source_url"] == filings_10k[0]["document_url"]
        assert filings_10k[0]["as_of"] is not None

        # Filter for 10-Q
        filings_10q = await list_filings(client, "AAPL", form_type="10-Q", limit=5)
        assert len(filings_10q) == 2
        assert filings_10q[0]["form_type"] == "10-Q"
    finally:
        await client.close()
        await temp_db.close()


@pytest.mark.asyncio
@respx.mock
async def test_list_filings_not_found(
    valid_settings,
    temp_db,
    tickers_payload,
    submissions_payload,
):
    respx.get("https://www.sec.gov/files/company_tickers.json").respond(
        status_code=200,
        json=tickers_payload,
    )
    respx.get("https://data.sec.gov/submissions/CIK0000320193.json").respond(
        status_code=200,
        json=submissions_payload,
    )

    client = EdgarClient(settings=valid_settings, db=temp_db)
    try:
        with pytest.raises(FilingNotFound):
            await list_filings(client, "AAPL", form_type="S-1")
    finally:
        await client.close()
        await temp_db.close()
