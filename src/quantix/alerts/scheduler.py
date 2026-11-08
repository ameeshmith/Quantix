"""Scheduled watchlist monitoring and 8-K Telegram alert runner using APScheduler."""

import logging
from typing import Any, Dict, List, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from quantix.alerts.telegram import TelegramNotifier
from quantix.config import Settings, get_settings
from quantix.db import Database, get_db
from quantix.edgar.client import EdgarClient
from quantix.services.company import list_filings
from quantix.services.llm import LLMProvider, get_llm
from quantix.services.summarize import summarize_8k_with_llm

logger = logging.getLogger(__name__)


async def check_and_dispatch_alerts(
    client: EdgarClient,
    db: Database,
    llm: LLMProvider,
    notifier: TelegramNotifier,
) -> List[Dict[str, Any]]:
    """Scan watchlist for newly filed 8-Ks, summarize with LLM, and dispatch alerts."""
    watched_tickers = await db.get_watchlist()
    if not watched_tickers:
        logger.info("Watchlist is empty. No tickers to check for 8-K filings.")
        return []

    dispatched_alerts: List[Dict[str, Any]] = []

    for entry in watched_tickers:
        ticker = entry["ticker"]
        name = entry["name"]

        try:
            # Check for recent 8-Ks
            recent_8ks = await list_filings(client, ticker, form_type="8-K", limit=3)
        except Exception as exc:
            logger.warning("Could not check 8-K filings for %s: %s", ticker, exc)
            continue

        for filing in recent_8ks:
            accn = filing["accession_number"]
            # Deduplication check
            if await db.is_alerted(accn):
                logger.debug("Accession %s for %s was already alerted; skipping.", accn, ticker)
                continue

            logger.info("New un-alerted 8-K detected for %s: %s", ticker, accn)
            doc_url = filing["document_url"]

            try:
                html_doc = await client.get_filing_document(doc_url)
            except Exception as exc:
                err_msg = f"Failed to fetch filing {doc_url} for {ticker}: {exc}"
                logger.error(err_msg)
                continue

            # Summarize 8-K with LLM
            summary = await summarize_8k_with_llm(llm, ticker, filing, html_doc)

            # Dispatch via Telegram
            sent = False
            if notifier.is_configured():
                sent = await notifier.send_filing_alert(ticker, name, filing, summary)

            # Record in database for deduplication
            await db.record_alert(
                accession_number=accn,
                ticker=ticker,
                form_type="8-K",
                filing_date=filing["filing_date"],
                summary=summary,
            )

            dispatched_alerts.append({
                "ticker": ticker,
                "company_name": name,
                "accession_number": accn,
                "filing_date": filing["filing_date"],
                "telegram_dispatched": sent,
                "summary": summary,
            })

    return dispatched_alerts


class AlertScheduler:
    """Manages periodic background checking for watchlist filings."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        db: Optional[Database] = None,
        client: Optional[EdgarClient] = None,
        llm: Optional[LLMProvider] = None,
        notifier: Optional[TelegramNotifier] = None,
    ):
        self.settings = settings or get_settings()
        self.db = db or get_db(self.settings.db_path)
        self.client = client or EdgarClient(settings=self.settings, db=self.db)
        self.llm = llm or get_llm(settings=self.settings)
        self.notifier = notifier or TelegramNotifier(settings=self.settings)
        self._scheduler = AsyncIOScheduler()
        self._job = None

    def start(self) -> None:
        """Start the async scheduler using the configured cron schedule."""
        cron_expr = self.settings.alert_schedule.strip()
        try:
            trigger = CronTrigger.from_crontab(cron_expr)
        except Exception as exc:
            logger.error("Invalid ALERT_SCHEDULE ('%s'): %s. Using default.", cron_expr, exc)
            trigger = CronTrigger.from_crontab("0 8 * * 1-5")

        self._job = self._scheduler.add_job(
            self.run_check,
            trigger=trigger,
            id="quantix_8k_alerts",
            replace_existing=True,
        )
        self._scheduler.start()
        logger.info("Quantix AlertScheduler started with cron '%s'.", cron_expr)

    def shutdown(self) -> None:
        """Shut down the background scheduler cleanly."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("Quantix AlertScheduler stopped.")

    async def run_check(self) -> List[Dict[str, Any]]:
        """Execute one immediate alert check cycle."""
        logger.info("Executing scheduled watchlist 8-K check cycle...")
        return await check_and_dispatch_alerts(self.client, self.db, self.llm, self.notifier)
