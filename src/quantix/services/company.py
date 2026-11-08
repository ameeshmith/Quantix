"""Company lookup and SEC filing listing services."""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from quantix.edgar.client import EdgarClient
from quantix.exceptions import CompanyNotFound, FilingNotFound

logger = logging.getLogger(__name__)


async def lookup_company(client: EdgarClient, query: str) -> Dict[str, Any]:
    """Resolve a ticker symbol or company name to CIK, ticker, and company name.

    Searches SEC EDGAR company_tickers.json mapping first by exact ticker symbol,
    then by exact company name match, and finally by case-insensitive name substring.
    """
    clean_query = query.strip()
    if not clean_query:
        raise CompanyNotFound(query)

    tickers_data = await client.get_company_tickers()
    upper_query = clean_query.upper()

    # 1. Exact Ticker Match
    for item in tickers_data.values():
        if str(item.get("ticker", "")).upper() == upper_query:
            cik_int = item["cik_str"]
            return {
                "ticker": item["ticker"].upper(),
                "name": item["title"],
                "cik": EdgarClient.pad_cik(cik_int),
                "source_url": "https://www.sec.gov/files/company_tickers.json",
                "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            }

    # 2. Exact Title / Name Match
    for item in tickers_data.values():
        if str(item.get("title", "")).upper() == upper_query:
            cik_int = item["cik_str"]
            return {
                "ticker": item["ticker"].upper(),
                "name": item["title"],
                "cik": EdgarClient.pad_cik(cik_int),
                "source_url": "https://www.sec.gov/files/company_tickers.json",
                "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            }

    # 3. Partial Substring Title Match
    matches = []
    for item in tickers_data.values():
        title = str(item.get("title", ""))
        if upper_query in title.upper():
            matches.append(item)

    if matches:
        # Prefer shortest name match (closest entity)
        matches.sort(key=lambda x: len(x.get("title", "")))
        best = matches[0]
        return {
            "ticker": best["ticker"].upper(),
            "name": best["title"],
            "cik": EdgarClient.pad_cik(best["cik_str"]),
            "source_url": "https://www.sec.gov/files/company_tickers.json",
            "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        }

    raise CompanyNotFound(clean_query)


async def list_filings(
    client: EdgarClient,
    ticker: str,
    form_type: Optional[str] = "10-K",
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """List recent official SEC filings for a given company.

    Returns compact records containing accession number, filing date, form type,
    and direct SEC EDGAR document URL.
    """
    company = await lookup_company(client, ticker)
    cik = company["cik"]
    company_name = company["name"]
    ticker_sym = company["ticker"]

    submissions = await client.get_submissions(cik)
    recent = submissions.get("filings", {}).get("recent", {})

    forms = recent.get("form", [])
    accession_numbers = recent.get("accessionNumber", [])
    filing_dates = recent.get("filingDate", [])
    report_dates = recent.get("reportDate", [])
    primary_documents = recent.get("primaryDocument", [])
    descriptions = recent.get("primaryDocDescription", [])
    items_list = recent.get("items", [])

    results: List[Dict[str, Any]] = []
    target_form = form_type.strip().upper() if form_type else None

    for idx, f in enumerate(forms):
        if target_form and f.upper() != target_form:
            continue

        acc_num = accession_numbers[idx]
        p_doc = primary_documents[idx]
        doc_url = EdgarClient.build_filing_document_url(cik, acc_num, p_doc)
        interactive_url = EdgarClient.build_interactive_url(cik, acc_num, p_doc)

        item_str = items_list[idx] if idx < len(items_list) else None
        rep_date = report_dates[idx] if idx < len(report_dates) else None
        desc = descriptions[idx] if idx < len(descriptions) else None

        results.append(
            {
                "ticker": ticker_sym,
                "company_name": company_name,
                "accession_number": acc_num,
                "form_type": f,
                "filing_date": filing_dates[idx],
                "report_date": rep_date,
                "description": desc,
                "items": item_str,
                "document_url": doc_url,
                "interactive_data_url": interactive_url,
                "source_url": doc_url,
                "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            }
        )

        if len(results) >= limit:
            break

    if not results and target_form:
        raise FilingNotFound(f"No filings of type '{target_form}' found for {ticker_sym}.")

    return results
