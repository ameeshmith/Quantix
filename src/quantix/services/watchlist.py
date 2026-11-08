"""Watchlist management and new filing detection services."""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from quantix.db import Database
from quantix.edgar.client import EdgarClient
from quantix.services.company import list_filings, lookup_company

logger = logging.getLogger(__name__)


async def watch_ticker(
    client: EdgarClient,
    db: Database,
    ticker: str,
) -> Dict[str, Any]:
    """Add a company to the watched watchlist."""
    company = await lookup_company(client, ticker)
    ticker_sym = company["ticker"]
    name = company["name"]
    cik = company["cik"]

    await db.add_to_watchlist(ticker_sym, name, cik)
    return {
        "status": "success",
        "message": f"Successfully added {ticker_sym} ({name}) to watchlist.",
        "ticker": ticker_sym,
        "name": name,
        "cik": cik,
        "source_url": company["source_url"],
        "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "disclaimer": "Informational only, not investment advice.",
    }


async def unwatch_ticker(db: Database, ticker: str) -> Dict[str, Any]:
    """Remove a company from the watched watchlist."""
    ticker_sym = ticker.strip().upper()
    removed = await db.remove_from_watchlist(ticker_sym)
    return {
        "status": "success" if removed else "not_found",
        "message": (
            f"Removed {ticker_sym} from watchlist."
            if removed
            else f"Ticker {ticker_sym} was not in the watchlist."
        ),
        "ticker": ticker_sym,
        "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }


async def list_watchlist(db: Database) -> Dict[str, Any]:
    """List all companies currently being tracked in the watchlist."""
    items = await db.get_watchlist()
    return {
        "count": len(items),
        "watchlist": items,
        "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }


async def check_new_filings(
    client: EdgarClient,
    db: Database,
    ticker: Optional[str] = None,
) -> Dict[str, Any]:
    """Check for new 8-K, 10-K, and 10-Q filings since last check for watchlist or one ticker."""
    target_tickers = []
    if ticker:
        comp = await lookup_company(client, ticker)
        target_tickers.append({"ticker": comp["ticker"], "name": comp["name"]})
    else:
        watched = await db.get_watchlist()
        target_tickers = [{"ticker": w["ticker"], "name": w["name"]} for w in watched]

    if not target_tickers:
        return {
            "message": "Watchlist is empty. Use watch_ticker(ticker) to start monitoring.",
            "new_filings": [],
            "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        }

    new_filings_found: List[Dict[str, Any]] = []

    for entry in target_tickers:
        t_sym = entry["ticker"]
        # Fetch 10 most recent filings of any type
        try:
            recent_filings = await list_filings(client, t_sym, form_type=None, limit=10)
        except Exception as exc:
            logger.warning("Error fetching filings for %s: %s", t_sym, exc)
            continue

        for f in recent_filings:
            f_form = f["form_type"].upper()
            if f_form not in ("8-K", "10-K", "10-Q"):
                continue

            accn = f["accession_number"]
            already_alerted = await db.is_alerted(accn)
            if not already_alerted:
                new_filings_found.append({
                    "ticker": t_sym,
                    "company_name": entry["name"],
                    "form_type": f_form,
                    "filing_date": f["filing_date"],
                    "report_date": f.get("report_date"),
                    "accession_number": accn,
                    "document_url": f["document_url"],
                    "items": f.get("items"),
                    "description": f.get("description"),
                })

    return {
        "new_filings_count": len(new_filings_found),
        "new_filings": new_filings_found,
        "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "disclaimer": "Informational only, not investment advice.",
    }
