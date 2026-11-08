"""XBRL financial metrics extraction service with GAAP concept fallback mappings."""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple

from quantix.edgar.client import EdgarClient
from quantix.services.company import lookup_company

logger = logging.getLogger(__name__)

# Fallback mapping list per metric to handle different US-GAAP tags across companies
METRIC_FALLBACKS: Dict[str, List[str]] = {
    "revenue": [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
    ],
    "net_income": [
        "NetIncomeLoss",
        "ProfitLoss",
        "NetIncomeLossAvailableToCommonStockholdersBasic",
    ],
    "operating_income": [
        "OperatingIncomeLoss",
    ],
    "gross_profit": [
        "GrossProfit",
    ],
    "total_debt": [
        "LongTermDebtAndCapitalLeaseObligations",
        "LongTermDebtNoncurrent",
        "DebtLongtermAndShorttermCombinedAmount",
        "LongTermDebt",
    ],
    "cash": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        "Cash",
    ],
    "operating_cash_flow": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ],
    "capex": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
        "PaymentsForCapitalImprovements",
    ],
    "eps_diluted": [
        "EarningsPerShareDiluted",
    ],
}

SUPPORTED_METRICS = list(METRIC_FALLBACKS.keys())


def _form_priority(form: str) -> int:
    """Assign higher priority to primary periodic reports over proxy or current reports."""
    f = (form or "").upper()
    if any(k in f for k in ("10-K", "20-F", "40-F")):
        return 3
    if "10-Q" in f:
        return 2
    return 1


def _parse_tag_entries(
    tag_data: Dict[str, Any],
    tag_name: str,
    period_type: Literal["annual", "quarterly"] = "annual",
    periods: int = 8,
) -> Optional[Dict[str, Any]]:
    """Parse a single concept tag's units and extract clean time series."""
    units_dict = tag_data.get("units", {})
    if not units_dict:
        return None

    # Determine unit: USD, USD/shares, pure, etc.
    preferred_unit = "USD"
    if "USD/shares" in units_dict:
        preferred_unit = "USD/shares"
    elif "USD" not in units_dict and units_dict:
        preferred_unit = next(iter(units_dict.keys()))

    items = units_dict.get(preferred_unit, [])
    if not items:
        return None

    # Filter items according to period_type (annual: 10-K / ~365 days; quarterly: 10-Q / ~90 days)
    filtered = []
    seen_periods = set()

    # Sort descending by end date, form priority (10-K/10-Q beats DEF 14A/8-K), and filed date (latest amendment wins)
    sorted_items = sorted(
        items,
        key=lambda x: (
            x.get("end") or "",
            _form_priority(x.get("form")),
            x.get("filed") or "",
        ),
        reverse=True,
    )

    for entry in sorted_items:
        form = (entry.get("form") or "").upper()
        frame = entry.get("frame") or ""  # e.g., CY2023, CY2023Q3
        fp = (entry.get("fp") or "").upper()  # FY, Q1, Q2, Q3, etc.
        val = entry.get("val")
        end = entry.get("end")
        start = entry.get("start")

        if val is None or not end:
            continue

        # Calculate period duration if start date is available (duration metrics like revenue/net income)
        duration_days: Optional[int] = None
        if start and end:
            try:
                duration_days = (datetime.fromisoformat(end) - datetime.fromisoformat(start)).days
            except ValueError:
                pass

        if period_type == "annual":
            # Annual metrics must strictly originate from official annual reports (10-K, 20-F, 40-F)
            if not any(k in form for k in ("10-K", "20-F", "40-F")):
                continue

            if duration_days is not None:
                # Annual duration must span approximately one full year (300 to 420 days)
                # Discards 90-day quarterly figures that are reported inside a 10-K footnote
                if not (300 <= duration_days <= 420):
                    continue
            else:
                # Instant balance sheet metrics (Cash, Debt, Assets)
                if not (fp in ("FY", "") or (frame and "Q" not in frame)):
                    continue

        elif period_type == "quarterly":
            if duration_days is not None:
                # Quarterly duration must span approximately 3 months (60 to 125 days)
                if not (60 <= duration_days <= 125):
                    continue
            else:
                if not (any(k in form for k in ("10-Q", "10-Q/A")) or fp.startswith("Q") or (frame and "Q" in frame)):
                    continue

        # Deduplicate by period end date to ensure 1 point per period, highest priority filing wins
        if end in seen_periods:
            continue
        seen_periods.add(end)

        # Consistent fiscal year derivation:
        # SEC EDGAR entry['fy'] often refers to the filing year rather than the period year
        # For an end date of 2024-12-31, the fiscal year is cleanly 2024
        fiscal_year = None
        if frame and len(frame) >= 6 and frame[:2] in ("CY", "FY") and frame[2:6].isdigit():
            fiscal_year = int(frame[2:6])
        elif end and len(end) >= 4 and end[:4].isdigit():
            fiscal_year = int(end[:4])
        else:
            fiscal_year = entry.get("fy")

        filtered.append({
            "end_date": end,
            "fiscal_year": fiscal_year,
            "fiscal_period": "FY" if period_type == "annual" else (fp or "Q"),
            "form": form,
            "frame": frame or None,
            "value": val,
            "accession_number": entry.get("accn"),
            "filed_date": entry.get("filed"),
        })

        if len(filtered) >= periods:
            break

    if not filtered:
        return None

    # Sort chronologically ascending for convenient presentation
    filtered.sort(key=lambda x: x["end_date"])

    return {
        "tag_used": tag_name,
        "label": tag_data.get("label", tag_name),
        "description": tag_data.get("description", ""),
        "unit": preferred_unit,
        "datapoints": filtered,
    }


def _extract_metric_values(
    facts: Dict[str, Any],
    concept_tags: List[str],
    period_type: Literal["annual", "quarterly"] = "annual",
    periods: int = 8,
) -> Optional[Dict[str, Any]]:
    """Search for matching concept tags in US-GAAP taxonomy and pick the best series.

    When multiple tags exist, evaluates candidate tags and selects the one that covers
    the most recent filing periods.
    """
    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    if not us_gaap:
        return None

    candidates: List[Tuple[str, int, Dict[str, Any]]] = []

    for tag in concept_tags:
        if tag in us_gaap:
            parsed = _parse_tag_entries(us_gaap[tag], tag, period_type, periods)
            if parsed and parsed["datapoints"]:
                latest_end = parsed["datapoints"][-1]["end_date"]
                candidates.append((latest_end, len(parsed["datapoints"]), parsed))

    if not candidates:
        return None

    # Pick candidate tag with the most recent end date, breaking ties with more data points
    candidates.sort(key=lambda c: (c[0], c[1]), reverse=True)
    return candidates[0][2]


async def get_financials(
    client: EdgarClient,
    ticker: str,
    metric: str,
    periods: int = 8,
    period_type: Literal["annual", "quarterly"] = "annual",
) -> Dict[str, Any]:
    """Retrieve structured financial metric time-series from SEC EDGAR XBRL facts.

    Supports: revenue, net_income, operating_income, gross_profit, total_debt,
    cash, operating_cash_flow, capex, eps_diluted.
    """
    metric_clean = metric.strip().lower()
    if metric_clean not in METRIC_FALLBACKS:
        return {
            "ticker": ticker.upper(),
            "metric": metric,
            "status": "unavailable",
            "error": (
                f"Unsupported metric '{metric}'. "
                f"Supported metrics: {', '.join(SUPPORTED_METRICS)}"
            ),
            "source_url": None,
            "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "datapoints": [],
            "disclaimer": "Informational only, not investment advice.",
        }

    company = await lookup_company(client, ticker)
    cik = company["cik"]
    company_name = company["name"]
    ticker_sym = company["ticker"]

    facts = await client.get_company_facts(cik)
    concept_tags = METRIC_FALLBACKS[metric_clean]
    extracted = _extract_metric_values(
        facts,
        concept_tags,
        period_type=period_type,
        periods=periods,
    )

    facts_source_url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

    if not extracted or not extracted["datapoints"]:
        tags_str = ", ".join(concept_tags)
        return {
            "ticker": ticker_sym,
            "company_name": company_name,
            "cik": cik,
            "metric": metric_clean,
            "status": "unavailable",
            "message": (
                f"Metric '{metric_clean}' is not available in SEC XBRL facts for {ticker_sym}. "
                f"Checked US-GAAP concept tags: {tags_str}."
            ),
            "source_url": facts_source_url,
            "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "datapoints": [],
            "disclaimer": "Informational only, not investment advice.",
        }

    # Annotate datapoints with direct document links when accession number is present
    for dp in extracted["datapoints"]:
        accn = dp.get("accession_number")
        if accn:
            acc_clean = accn.replace("-", "")
            cik_clean = str(int(cik))
            dp["filing_url"] = (
                f"https://www.sec.gov/Archives/edgar/data/{cik_clean}/{acc_clean}/{accn}-index.htm"
            )
        else:
            dp["filing_url"] = None

    return {
        "ticker": ticker_sym,
        "company_name": company_name,
        "cik": cik,
        "metric": metric_clean,
        "status": "available",
        "tag_used": extracted["tag_used"],
        "unit": extracted["unit"],
        "period_type": period_type,
        "source_url": facts_source_url,
        "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "datapoints": extracted["datapoints"],
        "disclaimer": "Informational only, not investment advice.",
    }
