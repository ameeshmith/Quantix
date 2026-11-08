"""Tests for scheduled 8-K monitoring, Telegram alerts, and accession deduplication."""

import asyncio
import json
from pathlib import Path

import pytest
import respx

from quantix.alerts.scheduler import AlertScheduler, check_and_dispatch_alerts
from quantix.alerts.telegram import TelegramNotifier
from quantix.config import Settings
from quantix.db import Database
from quantix.edgar.client import EdgarClient
from quantix.services.llm import LLMProvider

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_alerts.db"
    return Database(str(db_file))


@pytest.fixture
def alert_settings(tmp_path):
    return Settings(
        edgar_user_agent="QuantixTest test@example.com",
        db_path=str(tmp_path / "test_alerts.db"),
        telegram_bot_token="fake_bot_token_123",
        telegram_chat_id="fake_chat_id_456",
        alert_schedule="0 8 * * 1-5",
    )


@pytest.fixture
def submissions_8k_payload():
    with open(FIXTURES_DIR / "submissions_8k.json", "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def tickers_payload():
    with open(FIXTURES_DIR / "company_tickers.json", "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.asyncio
@respx.mock
async def test_telegram_send_alert(alert_settings):
    telegram_route = respx.post(
        "https://api.telegram.org/botfake_bot_token_123/sendMessage"
    ).respond(status_code=200, json={"ok": True})

    notifier = TelegramNotifier(settings=alert_settings)
    try:
        assert notifier.is_configured() is True
        sent = await notifier.send_filing_alert(
            ticker="AAPL",
            company_name="Apple Inc.",
            filing_meta={
                "form_type": "8-K",
                "filing_date": "2024-11-05",
                "items": "Item 5.02",
                "accession_number": "0000320193-24-000999",
                "document_url": "https://sec.gov/doc",
            },
            summary="Apple announced the retirement of Chief Financial Officer Luca Maestri.",
        )
        assert sent is True
        assert telegram_route.call_count == 1
        req_json = json.loads(telegram_route.calls.last.request.content)
        assert req_json["chat_id"] == "fake_chat_id_456"
        assert "Luca Maestri" in req_json["text"]
        assert "Informational only, not investment advice." in req_json["text"]
    finally:
        await notifier.close()


@pytest.mark.asyncio
@respx.mock
async def test_check_and_dispatch_alerts_with_deduplication(
    alert_settings,
    temp_db,
    tickers_payload,
    submissions_8k_payload,
):
    # Mock SEC endpoints
    respx.get("https://www.sec.gov/files/company_tickers.json").respond(
        status_code=200,
        json=tickers_payload,
    )
    respx.get("https://data.sec.gov/submissions/CIK0000320193.json").respond(
        status_code=200,
        json=submissions_8k_payload,
    )
    doc_url = (
        "https://www.sec.gov/Archives/edgar/data/320193/000032019324000999/aapl-20241105.htm"
    )
    respx.get(doc_url).respond(
        status_code=200,
        text="<html><body><p>Departure of Directors. Luca Maestri retired.</p></body></html>",
    )

    # Mock Telegram Bot API
    respx.post("https://api.telegram.org/botfake_bot_token_123/sendMessage").respond(
        status_code=200,
        json={"ok": True},
    )

    client = EdgarClient(settings=alert_settings, db=temp_db)
    llm = LLMProvider(settings=alert_settings)
    notifier = TelegramNotifier(settings=alert_settings)

    try:
        # 1. Add AAPL to watchlist
        await temp_db.add_to_watchlist("AAPL", "Apple Inc.", "0000320193")

        # 2. Run first alert cycle
        dispatched1 = await check_and_dispatch_alerts(client, temp_db, llm, notifier)
        assert len(dispatched1) == 1
        assert dispatched1[0]["accession_number"] == "0000320193-24-000999"
        assert dispatched1[0]["telegram_dispatched"] is True

        # Verify DB recorded accession
        is_recorded = await temp_db.is_alerted("0000320193-24-000999")
        assert is_recorded is True

        # 3. Run second alert cycle (should be deduplicated, 0 sent)
        dispatched2 = await check_and_dispatch_alerts(client, temp_db, llm, notifier)
        assert len(dispatched2) == 0

    finally:
        await client.close()
        await llm.close()
        await notifier.close()
        await temp_db.close()


@pytest.mark.asyncio
async def test_alert_scheduler_lifecycle(alert_settings, temp_db):
    scheduler = AlertScheduler(settings=alert_settings, db=temp_db)
    try:
        scheduler.start()
        assert scheduler._scheduler.running is True
    finally:
        scheduler.shutdown()
        await asyncio.sleep(0.02)
        assert scheduler._scheduler.running is False
