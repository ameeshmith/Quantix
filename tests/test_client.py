"""Tests for SEC EDGAR client, rate limiting, caching, and retry logic."""

import time

import httpx
import pytest
import respx

from quantix.config import Settings
from quantix.db import Database
from quantix.edgar.client import AsyncRateLimiter, EdgarClient
from quantix.exceptions import ConfigurationError, EdgarRateLimited


@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_quantix.db"
    return Database(str(db_file))


@pytest.fixture
def valid_settings(tmp_path):
    return Settings(
        edgar_user_agent="QuantixTest test@example.com",
        db_path=str(tmp_path / "test_quantix.db"),
    )


def test_invalid_user_agent_missing_email():
    with pytest.raises(ConfigurationError):
        Settings(edgar_user_agent="InvalidAgentWithoutEmail")


def test_user_agent_validation_empty():
    with pytest.raises(ConfigurationError):
        Settings(edgar_user_agent="   ")


def test_cik_padding():
    assert EdgarClient.pad_cik(320193) == "0000320193"
    assert EdgarClient.pad_cik("789019") == "0000789019"
    assert EdgarClient.pad_cik("0000320193") == "0000320193"
    assert EdgarClient.pad_cik("0") == "0000000000"


def test_build_urls():
    doc_url = EdgarClient.build_filing_document_url(
        "0000320193",
        "0000320193-24-000106",
        "aapl-20240928.htm",
    )
    expected_doc = (
        "https://www.sec.gov/Archives/edgar/data/320193/000032019324000106/aapl-20240928.htm"
    )
    assert doc_url == expected_doc

    ix_url = EdgarClient.build_interactive_url(
        "320193",
        "0000320193-24-000106",
        "aapl-20240928.htm",
    )
    expected_ix = (
        "https://www.sec.gov/ix?doc=/Archives/edgar/data/320193/000032019324000106/aapl-20240928.htm"
    )
    assert ix_url == expected_ix


@pytest.mark.asyncio
async def test_rate_limiter_tokens():
    limiter = AsyncRateLimiter(rate=10.0, capacity=2.0)
    # First 2 requests should be instantaneous
    start = time.monotonic()
    await limiter.acquire()
    await limiter.acquire()
    elapsed = time.monotonic() - start
    assert elapsed < 0.1

    # 3rd request should wait ~0.1s
    start = time.monotonic()
    await limiter.acquire()
    elapsed = time.monotonic() - start
    assert elapsed >= 0.08


@pytest.mark.asyncio
@respx.mock
async def test_fetch_caching(valid_settings, temp_db):
    url = "https://www.sec.gov/files/company_tickers.json"
    route = respx.get(url).respond(
        status_code=200,
        json={"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}},
    )

    client = EdgarClient(settings=valid_settings, db=temp_db)
    try:
        # First call hits network
        data1 = await client.get_company_tickers()
        assert route.call_count == 1
        assert data1["0"]["ticker"] == "AAPL"

        # Second call hits SQLite cache, not network
        data2 = await client.get_company_tickers()
        assert route.call_count == 1
        assert data2["0"]["ticker"] == "AAPL"
    finally:
        await client.close()
        await temp_db.close()


@pytest.mark.asyncio
@respx.mock
async def test_fetch_retry_on_429(valid_settings, temp_db):
    url = "https://data.sec.gov/submissions/CIK0000320193.json"
    route = respx.get(url)
    # First request: 429 with Retry-After: 0
    # Second request: 200 OK
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "0"}, text="Too Many Requests"),
        httpx.Response(200, json={"cik": "0000320193", "name": "Apple Inc."}),
    ]

    client = EdgarClient(settings=valid_settings, db=temp_db)
    try:
        data = await client.get_submissions("320193")
        assert data["name"] == "Apple Inc."
        assert route.call_count == 2
    finally:
        await client.close()
        await temp_db.close()


@pytest.mark.asyncio
@respx.mock
async def test_fetch_retry_429_exceeded(valid_settings, temp_db):
    url = "https://data.sec.gov/submissions/CIK0000320193.json"
    respx.get(url).respond(
        status_code=429,
        headers={"Retry-After": "0"},
        text="Rate limit exceeded",
    )

    client = EdgarClient(settings=valid_settings, db=temp_db)
    try:
        with pytest.raises(EdgarRateLimited):
            await client.fetch(url, max_retries=2, initial_backoff=0.01)
    finally:
        await client.close()
        await temp_db.close()


@pytest.mark.asyncio
@respx.mock
async def test_fetch_server_error_retry(valid_settings, temp_db):
    url = "https://data.sec.gov/submissions/CIK0000320193.json"
    route = respx.get(url)
    route.side_effect = [
        httpx.Response(503, text="Service Unavailable"),
        httpx.Response(200, json={"cik": "0000320193", "name": "Apple Inc."}),
    ]

    client = EdgarClient(settings=valid_settings, db=temp_db)
    try:
        data = await client.get_submissions("320193")
        assert data["name"] == "Apple Inc."
        assert route.call_count == 2
    finally:
        await client.close()
        await temp_db.close()
