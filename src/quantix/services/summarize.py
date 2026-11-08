"""LLM summarization service for filing diffs, 8-K alerts, and company briefs."""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from quantix.edgar.client import EdgarClient
from quantix.services.company import list_filings, lookup_company
from quantix.services.diff import diff_filings
from quantix.services.llm import LLMProvider, get_llm
from quantix.services.metrics import get_financials
from quantix.services.sections import clean_html_to_text

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_ANALYST = (
    "You are Quantix, an expert financial analyst. "
    "Your readers are finance newsletter writers, YouTubers, and independent investors. "
    "Explain filings in clear, accessible plain English. "
    "Highlight what changed, why it matters, and cite specific data from the filings. "
    "Never fabricate or guess numbers. If information is missing, say so clearly. "
    "Always end your analysis with the exact statement: "
    "'Informational only, not investment advice.'"
)


async def summarize_diff_with_llm(llm: LLMProvider, diff_result: Dict[str, Any]) -> str:
    """Summarize changed paragraphs using the LLM, explaining what changed and why it matters."""
    counts = diff_result["counts"]
    added: List[str] = diff_result["added_paragraphs"]
    removed: List[str] = diff_result["removed_paragraphs"]
    reworded: List[Dict[str, Any]] = diff_result["reworded_paragraphs"]

    if counts["added"] == 0 and counts["removed"] == 0 and counts["reworded"] == 0:
        return (
            f"No material changes detected in {diff_result['section_title']} between the "
            f"two filings ({diff_result['current_filing']['filing_date']} vs "
            f"{diff_result['prior_filing']['filing_date']}). "
            f"All {counts['unchanged']} paragraphs remained consistent.\n\n"
            "Informational only, not investment advice."
        )

    # Prepare compact prompt containing only the changes
    curr_date = diff_result["current_filing"]["filing_date"]
    curr_url = diff_result["current_filing"]["document_url"]
    prior_date = diff_result["prior_filing"]["filing_date"]
    prior_url = diff_result["prior_filing"]["document_url"]

    prompt_lines = [
        f"Analyze changes in {diff_result['section_title']} for "
        f"{diff_result['company_name']} ({diff_result['ticker']}).",
        f"Current Filing: {curr_date} ({curr_url})",
        f"Prior Filing: {prior_date} ({prior_url})",
        "",
        f"Total Added: {counts['added']}, Removed: {counts['removed']}, "
        f"Reworded: {counts['reworded']}.",
        "",
    ]

    if added:
        prompt_lines.append("### NEWLY ADDED PARAGRAPHS:")
        for idx, p in enumerate(added[:5], 1):
            prompt_lines.append(f"{idx}. {p[:500]}")
        prompt_lines.append("")

    if removed:
        prompt_lines.append("### REMOVED / RETIRED PARAGRAPHS:")
        for idx, p in enumerate(removed[:5], 1):
            prompt_lines.append(f"{idx}. {p[:500]}")
        prompt_lines.append("")

    if reworded:
        prompt_lines.append("### MATERIALLY REWORDED PARAGRAPHS:")
        for idx, r in enumerate(reworded[:5], 1):
            prompt_lines.append(f"{idx}. Prior: {r['prior_text'][:300]}")
            prompt_lines.append(f"   Current: {r['current_text'][:300]}")
            prompt_lines.append(f"   Similarity: {r['similarity_score']}%")
        prompt_lines.append("")

    prompt_lines.append(
        "Please provide a concise 3-4 paragraph synthesis:\n"
        "1. What major new risks or disclosures were introduced?\n"
        "2. What disclosures were removed or deemphasized?\n"
        "3. Why these changes might matter to investors."
    )

    full_prompt = "\n".join(prompt_lines)
    summary = await llm.generate(full_prompt, system_prompt=SYSTEM_PROMPT_ANALYST)

    if "Informational only, not investment advice." not in summary:
        summary = summary.strip() + "\n\nInformational only, not investment advice."

    return summary


async def summarize_8k_with_llm(
    llm: LLMProvider,
    ticker: str,
    filing_meta: Dict[str, Any],
    html_content: str,
) -> str:
    """Summarize an 8-K major event filing in 3 to 5 plain sentences with source citation."""
    clean_text = clean_html_to_text(html_content)
    excerpt = clean_text[:5000].strip()

    prompt = (
        f"The company {ticker} submitted an official Form 8-K filing to the SEC on "
        f"{filing_meta.get('filing_date', 'recent')}.\n"
        f"Items Triggered: {filing_meta.get('items', 'Unspecified')}\n"
        f"Source Document: {filing_meta.get('document_url', '')}\n\n"
        f"Document Excerpt:\n{excerpt}\n\n"
        "Explain what happened in exactly 3 to 5 plain sentences. "
        "Focus on the core material event (e.g. executive departure, earnings, acquisition, "
        "material agreement) and what it means for the business."
    )

    summary = await llm.generate(prompt, system_prompt=SYSTEM_PROMPT_ANALYST)
    if "Informational only, not investment advice." not in summary:
        summary = summary.strip() + "\n\nInformational only, not investment advice."
    return summary


async def generate_company_brief(
    client: EdgarClient,
    ticker: str,
    llm: Optional[LLMProvider] = None,
) -> Dict[str, Any]:
    """Generate a sourced comprehensive company brief combining financials, diffs, and filings."""
    llm_instance = llm or get_llm(settings=client.settings)

    # 1. Company Identity
    company = await lookup_company(client, ticker)
    ticker_sym = company["ticker"]
    company_name = company["name"]
    cik = company["cik"]

    # 2. Key Financials (Revenue, Net Income, Cash, Total Debt)
    rev_data = await get_financials(client, ticker_sym, "revenue", periods=3)
    ni_data = await get_financials(client, ticker_sym, "net_income", periods=3)
    cash_data = await get_financials(client, ticker_sym, "cash", periods=3)
    debt_data = await get_financials(client, ticker_sym, "total_debt", periods=3)

    financial_summary = {
        "revenue": rev_data.get("datapoints", []),
        "net_income": ni_data.get("datapoints", []),
        "cash": cash_data.get("datapoints", []),
        "debt": debt_data.get("datapoints", []),
    }

    # Format points safely for prompt
    rev_strs = [
        f"FY{d.get('fiscal_year')}: ${d.get('value'):,}" for d in rev_data.get("datapoints", [])
    ]
    ni_strs = [
        f"FY{d.get('fiscal_year')}: ${d.get('value'):,}" for d in ni_data.get("datapoints", [])
    ]

    # 3. Recent Filings
    all_filings = await list_filings(client, ticker_sym, form_type=None, limit=5)
    filing_strs = [f"{f['form_type']} ({f['filing_date']})" for f in all_filings[:3]]

    # 4. Risk Factors Diff Highlights
    diff_data = None
    diff_summary_text = ""
    try:
        diff_data = await diff_filings(
            client,
            ticker_sym,
            section="risk_factors",
            form_type="10-K",
        )
        diff_summary_text = await summarize_diff_with_llm(llm_instance, diff_data)
    except Exception as exc:
        logger.warning("Could not compute diff for %s: %s", ticker_sym, exc)
        diff_summary_text = "Filing diff requires at least two 10-K filings."

    # 5. LLM Synthesis of overall picture
    synth_prompt = (
        f"Synthesize an executive briefing for {company_name} ({ticker_sym}).\n\n"
        f"Financial Trajectory (Annual):\n"
        f"- Revenue: {', '.join(rev_strs)}\n"
        f"- Net Income: {', '.join(ni_strs)}\n\n"
        f"Recent Filings: {', '.join(filing_strs)}\n\n"
        f"Risk Factors Diff Summary:\n{diff_summary_text[:1200]}\n\n"
        "Draft a compelling 3-section brief:\n"
        "1. Business & Financial Performance Overview\n"
        "2. Key Disclosures & Risk Evolution Highlights\n"
        "3. Watchlist Takeaway for Investors"
    )

    overview_text = await llm_instance.generate(synth_prompt, system_prompt=SYSTEM_PROMPT_ANALYST)
    if "Informational only, not investment advice." not in overview_text:
        overview_text = overview_text.strip() + "\n\nInformational only, not investment advice."

    source_urls = [company["source_url"]]
    if rev_data.get("source_url"):
        source_urls.append(rev_data["source_url"])
    for f in all_filings[:3]:
        source_urls.append(f["document_url"])

    return {
        "ticker": ticker_sym,
        "company_name": company_name,
        "cik": cik,
        "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "brief_overview": overview_text,
        "financial_trends": financial_summary,
        "recent_filings": all_filings[:5],
        "diff_highlights": {
            "counts": diff_data["counts"] if diff_data else {},
            "summary": diff_summary_text,
        },
        "source_urls": list(dict.fromkeys(source_urls)),
        "disclaimer": "Informational only, not investment advice.",
    }
