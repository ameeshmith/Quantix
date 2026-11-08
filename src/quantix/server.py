"""Quantix FastMCP Server definition with official SEC EDGAR tools."""

import logging
from typing import Any, Dict, List, Literal, Optional

from mcp.server.fastmcp import FastMCP
from starlette.responses import JSONResponse

from quantix import __version__
from quantix.auth import BearerAuthMiddleware
from quantix.config import get_settings
from quantix.db import get_db
from quantix.edgar.client import EdgarClient
from quantix.services.company import list_filings as svc_list_filings
from quantix.services.company import lookup_company as svc_lookup_company
from quantix.services.diff import diff_filings as svc_diff_filings
from quantix.services.llm import get_llm
from quantix.services.metrics import get_financials as svc_get_financials
from quantix.services.sections import get_filing_section as svc_get_filing_section
from quantix.services.summarize import generate_company_brief, summarize_diff_with_llm
from quantix.services.watchlist import (
    check_new_filings as svc_check_new_filings,
)
from quantix.services.watchlist import (
    list_watchlist as svc_list_watchlist,
)
from quantix.services.watchlist import (
    unwatch_ticker as svc_unwatch_ticker,
)
from quantix.services.watchlist import (
    watch_ticker as svc_watch_ticker,
)

logger = logging.getLogger("quantix.server")

# FastMCP Server Initialization
mcp = FastMCP(
    "Quantix SEC EDGAR Server",
    instructions=(
        "Quantix enables AI assistants to query, analyze, and diff official SEC EDGAR filings "
        "(10-K, 10-Q, 8-K) with verified citations and financial trends for public US companies."
    ),
)


# Shared Singletons
def _get_deps():
    settings = get_settings()
    db = get_db(settings.db_path)
    client = EdgarClient(settings=settings, db=db)
    llm = get_llm(settings=settings)
    return settings, db, client, llm


# ------------------------------------------------------------------------------
# Health Check Endpoint
# ------------------------------------------------------------------------------
@mcp.custom_route("/health", methods=["GET"])
async def health_endpoint(request) -> JSONResponse:
    """Service health and connectivity probe."""
    settings, db, _, _ = _get_deps()
    db_status = "ok"
    try:
        conn = await db.connect()
        await conn.execute("SELECT 1")
    except Exception as exc:
        db_status = f"error: {str(exc)}"

    return JSONResponse({
        "status": "healthy" if db_status == "ok" else "degraded",
        "service": "quantix",
        "version": __version__,
        "transport": settings.mcp_transport,
        "database": db_status,
        "llm_provider": settings.llm_provider,
        "llm_model": settings.llm_model,
    })


# ------------------------------------------------------------------------------
# MCP Tool 1: lookup_company
# ------------------------------------------------------------------------------
@mcp.tool()
async def lookup_company(query: str) -> Dict[str, Any]:
    """Look up a US public company by ticker symbol or company name in official SEC records.

    Args:
        query: Ticker symbol (e.g. 'AAPL', 'NVDA') or company legal name (e.g. 'Apple Inc.').

    Returns:
        Dictionary with verified ticker, company name, 10-digit CIK, and source URL.
    """
    _, _, client, _ = _get_deps()
    return await svc_lookup_company(client, query)


# ------------------------------------------------------------------------------
# MCP Tool 2: list_filings
# ------------------------------------------------------------------------------
@mcp.tool()
async def list_filings(
    ticker: str,
    form_type: Optional[str] = "10-K",
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """List recent official SEC filings for a company with accession numbers and direct URLs.

    Args:
        ticker: Company ticker symbol (e.g. 'AAPL', 'MSFT').
        form_type: SEC Form type to filter (e.g. '10-K', '10-Q', '8-K', or None for all).
        limit: Maximum number of recent filings to return (default: 5).

    Returns:
        List of filings containing accession number, filing date, form type, and SEC URLs.
    """
    _, _, client, _ = _get_deps()
    return await svc_list_filings(client, ticker, form_type=form_type, limit=limit)


# ------------------------------------------------------------------------------
# MCP Tool 3: get_financials
# ------------------------------------------------------------------------------
@mcp.tool()
async def get_financials(
    ticker: str,
    metric: str,
    periods: int = 8,
    period_type: Literal["annual", "quarterly"] = "annual",
) -> Dict[str, Any]:
    """Retrieve structured time-series financials from official SEC EDGAR XBRL company facts.

    Supported metrics:
      - 'revenue': Total revenue / net sales
      - 'net_income': GAAP Net income / loss
      - 'operating_income': Operating income / EBIT
      - 'gross_profit': Gross profit
      - 'total_debt': Combined long-term & short-term debt
      - 'cash': Cash, cash equivalents & restricted cash
      - 'operating_cash_flow': Net cash from operating activities
      - 'capex': Capital expenditures (payments for PP&E)
      - 'eps_diluted': Diluted earnings per share (USD/shares)

    Args:
        ticker: Company ticker symbol (e.g. 'AAPL', 'NVDA').
        metric: Standard financial metric name from the supported list above.
        periods: Number of recent historical periods to retrieve (default: 8).
        period_type: 'annual' for 10-K / FY reports or 'quarterly' for 10-Q periods.

    Returns:
        Time-series datapoints with fiscal year, period, value, unit, accession, and filing links.
    """
    _, _, client, _ = _get_deps()
    return await svc_get_financials(
        client,
        ticker,
        metric,
        periods=periods,
        period_type=period_type,
    )


# ------------------------------------------------------------------------------
# MCP Tool 4: get_filing_section
# ------------------------------------------------------------------------------
@mcp.tool()
async def get_filing_section(
    ticker: str,
    form_type: str = "10-K",
    section: str = "risk_factors",
    accession_number: Optional[str] = None,
) -> Dict[str, Any]:
    """Retrieve and clean a specific substantive section from an official SEC 10-K or 10-Q filing.

    Supported sections:
      - 'business': Item 1. Business overview and operations
      - 'risk_factors': Item 1A. Principal risks facing the enterprise
      - 'mdna': Item 7 (10-K) or Item 2 (10-Q). Management's Discussion and Analysis
      - 'legal_proceedings': Item 3. Pending material lawsuits and regulatory matters

    Args:
        ticker: Company ticker symbol (e.g. 'AAPL', 'TSLA').
        form_type: '10-K' (annual) or '10-Q' (quarterly).
        section: Section name from the supported list above.
        accession_number: Specific SEC accession number, or None for the most recent filing.

    Returns:
        Cleaned section body text, paragraph breakdown, truncation status, and source link.
    """
    _, _, client, _ = _get_deps()
    return await svc_get_filing_section(
        client,
        ticker,
        form_type=form_type,
        section=section,
        accession_number=accession_number,
    )


# ------------------------------------------------------------------------------
# MCP Tool 5: diff_filings
# ------------------------------------------------------------------------------
@mcp.tool()
async def diff_filings(
    ticker: str,
    section: str = "risk_factors",
    form_type: str = "10-K",
) -> Dict[str, Any]:
    """Compare a section between the two most recent filings paragraph-by-paragraph.

    Identifies added, removed, and materially reworded disclosures, providing an AI synthesis
    explaining what changed year-over-year and why it matters.

    Args:
        ticker: Company ticker symbol (e.g. 'AAPL', 'MSFT').
        section: Section name to compare ('risk_factors', 'business', 'mdna', 'legal_proceedings').
        form_type: Filing form type ('10-K' or '10-Q').

    Returns:
        Structured diff with added/removed/reworded paragraphs, AI explanation, and filing links.
    """
    _, _, client, llm = _get_deps()
    diff_data = await svc_diff_filings(client, ticker, section=section, form_type=form_type)
    explanation = await summarize_diff_with_llm(llm, diff_data)
    diff_data["analysis_summary"] = explanation
    return diff_data


# ------------------------------------------------------------------------------
# MCP Tool 6: Watchlist Tools
# ------------------------------------------------------------------------------
@mcp.tool()
async def watch_ticker(ticker: str) -> Dict[str, Any]:
    """Add a company to the Quantix tracking watchlist for daily monitoring and alert checks.

    Args:
        ticker: Company ticker symbol (e.g. 'AAPL', 'NVDA').
    """
    _, db, client, _ = _get_deps()
    return await svc_watch_ticker(client, db, ticker)


@mcp.tool()
async def unwatch_ticker(ticker: str) -> Dict[str, Any]:
    """Remove a company from the Quantix tracking watchlist.

    Args:
        ticker: Company ticker symbol to remove.
    """
    _, db, _, _ = _get_deps()
    return await svc_unwatch_ticker(db, ticker)


@mcp.tool()
async def list_watchlist() -> Dict[str, Any]:
    """List all company tickers currently tracked in the Quantix watchlist."""
    _, db, _, _ = _get_deps()
    return await svc_list_watchlist(db)


# ------------------------------------------------------------------------------
# MCP Tool 7: check_new_filings
# ------------------------------------------------------------------------------
@mcp.tool()
async def check_new_filings(ticker: Optional[str] = None) -> Dict[str, Any]:
    """Check for new 8-K, 10-K, and 10-Q filings submitted since the last check.

    Args:
        ticker: Optional single ticker to check, or None to check all watched companies.

    Returns:
        List of un-alerted new filings with accession numbers, forms, items, and links.
    """
    _, db, client, _ = _get_deps()
    return await svc_check_new_filings(client, db, ticker=ticker)


# ------------------------------------------------------------------------------
# MCP Tool 8: company_brief
# ------------------------------------------------------------------------------
@mcp.tool()
async def company_brief(ticker: str) -> Dict[str, Any]:
    """Generate a comprehensive, sourced company briefing for finance writers and investors.

    Synthesizes financial trajectory, recent filing activity, and latest risk factor diffs
    into one coherent briefing with verified source links.

    Args:
        ticker: Company ticker symbol (e.g. 'AAPL', 'MSFT', 'NVDA').

    Returns:
        Complete sourced brief with multi-year trends, diff highlights, and disclaimer.
    """
    _, _, client, llm = _get_deps()
    return await generate_company_brief(client, ticker, llm=llm)


# ------------------------------------------------------------------------------
# Server Entrypoint
# ------------------------------------------------------------------------------
def main() -> None:
    """Run the FastMCP server with selected transport (stdio or streamable-http)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    settings = get_settings()

    if settings.mcp_transport == "streamable-http":
        import uvicorn

        logger.info(
            "Starting Quantix Streamable-HTTP server on %s:%d",
            settings.mcp_host,
            settings.mcp_port,
        )
        raw_app = mcp.streamable_http_app()
        app = BearerAuthMiddleware(raw_app, api_key=settings.mcp_api_key)
        uvicorn.run(app, host=settings.mcp_host, port=settings.mcp_port)
    else:
        logger.info("Starting Quantix FastMCP server on stdio transport...")
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
