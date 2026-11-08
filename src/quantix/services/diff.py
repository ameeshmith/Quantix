"""Paragraph-level diffing between SEC filings with similarity classification."""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from rapidfuzz import fuzz

from quantix.edgar.client import EdgarClient
from quantix.exceptions import FilingNotFound
from quantix.services.company import list_filings, lookup_company
from quantix.services.sections import extract_section

logger = logging.getLogger(__name__)

SIMILARITY_IDENTICAL_THRESHOLD = 96.0  # Above this is deemed unchanged
SIMILARITY_REWORDED_THRESHOLD = 65.0   # Above this is deemed materially reworded


def compute_paragraph_diff(
    prior_paragraphs: List[str],
    current_paragraphs: List[str],
) -> Dict[str, Any]:
    """Compare two sets of paragraphs and identify added, removed, and reworded blocks.

    Uses rapidfuzz similarity matching to find best-fit paragraph alignments.
    """
    matched_current_indices = set()
    matched_prior_indices = set()

    reworded_paragraphs: List[Dict[str, Any]] = []
    unchanged_count = 0

    # 1. Match each current paragraph with its best counterpart in prior paragraphs
    for curr_idx, curr_p in enumerate(current_paragraphs):
        best_match_idx: Optional[int] = None
        best_score = 0.0

        for prior_idx, prior_p in enumerate(prior_paragraphs):
            if prior_idx in matched_prior_indices:
                continue

            score = fuzz.token_sort_ratio(curr_p, prior_p)
            if score > best_score:
                best_score = score
                best_match_idx = prior_idx

        if best_match_idx is not None and best_score >= SIMILARITY_REWORDED_THRESHOLD:
            matched_current_indices.add(curr_idx)
            matched_prior_indices.add(best_match_idx)

            if best_score >= SIMILARITY_IDENTICAL_THRESHOLD:
                unchanged_count += 1
            else:
                reworded_paragraphs.append({
                    "similarity_score": round(best_score, 1),
                    "prior_text": prior_paragraphs[best_match_idx],
                    "current_text": curr_p,
                })

    # 2. Collect added paragraphs (current paragraphs with no match)
    added_paragraphs = [
        p for idx, p in enumerate(current_paragraphs) if idx not in matched_current_indices
    ]

    # 3. Collect removed paragraphs (prior paragraphs with no match)
    removed_paragraphs = [
        p for idx, p in enumerate(prior_paragraphs) if idx not in matched_prior_indices
    ]

    return {
        "added": added_paragraphs,
        "removed": removed_paragraphs,
        "reworded": reworded_paragraphs,
        "counts": {
            "added": len(added_paragraphs),
            "removed": len(removed_paragraphs),
            "reworded": len(reworded_paragraphs),
            "unchanged": unchanged_count,
            "total_current": len(current_paragraphs),
            "total_prior": len(prior_paragraphs),
        },
    }


async def diff_filings(
    client: EdgarClient,
    ticker: str,
    section: str = "risk_factors",
    form_type: str = "10-K",
    max_chars: int = 35000,
) -> Dict[str, Any]:
    """Compare the two most recent filings paragraph-by-paragraph.

    Returns added, removed, and materially reworded paragraphs between the two periods.
    """
    company = await lookup_company(client, ticker)
    ticker_sym = company["ticker"]
    company_name = company["name"]
    cik = company["cik"]

    filings = await list_filings(client, ticker_sym, form_type=form_type, limit=2)
    if len(filings) < 2:
        raise FilingNotFound(
            f"Need at least 2 filings of type '{form_type}' to diff for {ticker_sym}. "
            f"Found {len(filings)}."
        )

    current_filing = filings[0]
    prior_filing = filings[1]

    # Fetch HTML documents
    curr_html = await client.get_filing_document(current_filing["document_url"])
    prior_html = await client.get_filing_document(prior_filing["document_url"])

    # Extract sections
    curr_sec = extract_section(curr_html, section, form_type=form_type, max_chars=max_chars)
    prior_sec = extract_section(prior_html, section, form_type=form_type, max_chars=max_chars)

    diff_result = compute_paragraph_diff(
        prior_paragraphs=prior_sec["paragraphs"],
        current_paragraphs=curr_sec["paragraphs"],
    )

    return {
        "ticker": ticker_sym,
        "company_name": company_name,
        "cik": cik,
        "section": section,
        "section_title": curr_sec["title"],
        "form_type": form_type.upper(),
        "current_filing": {
            "accession_number": current_filing["accession_number"],
            "filing_date": current_filing["filing_date"],
            "document_url": current_filing["document_url"],
        },
        "prior_filing": {
            "accession_number": prior_filing["accession_number"],
            "filing_date": prior_filing["filing_date"],
            "document_url": prior_filing["document_url"],
        },
        "added_paragraphs": diff_result["added"],
        "removed_paragraphs": diff_result["removed"],
        "reworded_paragraphs": diff_result["reworded"],
        "counts": diff_result["counts"],
        "source_urls": [
            current_filing["document_url"],
            prior_filing["document_url"],
        ],
        "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "disclaimer": "Informational only, not investment advice.",
    }
