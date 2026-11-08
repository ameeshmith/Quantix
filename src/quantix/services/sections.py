"""HTML section extraction for SEC 10-K and 10-Q filings with TOC skipping."""

import html
import logging
import re
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

from quantix.edgar.client import EdgarClient
from quantix.exceptions import FilingNotFound, SectionNotFound
from quantix.services.company import list_filings, lookup_company

logger = logging.getLogger(__name__)

# Section mapping definitions for 10-K and 10-Q
SECTION_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "business": {
        "title": "Item 1. Business",
        "start_pattern": r"item\s+1\b[\s\.\:\-]*(?:business)?",
        "end_pattern": r"item\s+1a\b",
        "form": "10-K",
    },
    "risk_factors": {
        "title": "Item 1A. Risk Factors",
        "start_pattern": r"item\s+1a\b[\s\.\:\-]*(?:risk\s+factors)?",
        "end_pattern": r"item\s+(?:1b|2)\b",
        "form": ["10-K", "10-Q"],
    },
    "legal_proceedings": {
        "title": "Item 3. Legal Proceedings",
        "start_pattern": r"item\s+3\b[\s\.\:\-]*(?:legal\s+proceedings)?",
        "end_pattern": r"item\s+4\b",
        "form": "10-K",
    },
    "mdna": {
        "title": "Item 7. Management's Discussion and Analysis",
        "start_pattern_10k": (
            r"item\s+7\b[\s\.\:\-]*"
            r"(?:management(?:'s)?\s+discussion\s+and\s+analysis)?"
        ),
        "end_pattern_10k": r"item\s+7a\b",
        "start_pattern_10q": (
            r"item\s+2\b[\s\.\:\-]*"
            r"(?:management(?:'s)?\s+discussion\s+and\s+analysis)?"
        ),
        "end_pattern_10q": r"item\s+3\b",
        "form": ["10-K", "10-Q"],
    },
}

DEFAULT_MAX_CHARS = 35000


def clean_html_to_text(html_content: str) -> str:
    """Clean raw SEC filing HTML, removing scripts/styles and decoding entities."""
    soup = BeautifulSoup(html_content, "lxml")

    # Remove script, style, and hidden elements
    for element in soup(["script", "style", "meta", "noscript"]):
        element.decompose()

    # Convert breaks and paragraphs to newlines
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for p in soup.find_all(["p", "div", "tr"]):
        p.insert_before("\n")

    text = soup.get_text()
    # Unescape HTML entities (e.g. &nbsp;, &#160;)
    text = html.unescape(text)
    # Replace non-breaking spaces with standard space
    text = text.replace("\xa0", " ").replace("\u200b", " ")
    return text


def extract_paragraphs(text: str) -> List[str]:
    """Split text into normalized paragraphs, discarding whitespace noise."""
    lines = text.split("\n")
    paragraphs: List[str] = []
    current_para: List[str] = []

    for line in lines:
        cleaned = re.sub(r"\s+", " ", line).strip()
        if cleaned:
            current_para.append(cleaned)
        elif current_para:
            joined = " ".join(current_para).strip()
            if len(joined) > 20:  # Skip trivial fragments/headers/page numbers
                paragraphs.append(joined)
            current_para = []

    if current_para:
        joined = " ".join(current_para).strip()
        if len(joined) > 20:
            paragraphs.append(joined)

    return paragraphs


def find_section_body(
    text: str,
    start_regex: str,
    end_regex: str,
) -> Optional[str]:
    """Extract section body between start and end regex headings, skipping TOC entries."""
    start_flags = re.IGNORECASE
    end_flags = re.IGNORECASE

    # Find all start heading matches
    start_matches = list(re.finditer(start_regex, text, start_flags))
    if not start_matches:
        return None

    # Filter out Table of Contents matches:
    # A TOC match usually occurs early in the document (within the first 25% or within ~15k chars),
    # or is followed immediately by leader dots (....) or page numbers.
    body_text: Optional[str] = None

    for m in start_matches:
        start_pos = m.end()
        # Look ahead 100 characters to check if it's a TOC entry
        lookahead = text[start_pos : start_pos + 150].lower()
        if "...." in lookahead or re.search(r"\.{3,}|\b\d+\s*$", lookahead):
            continue

        # Look for the end heading after this start
        end_match = re.search(end_regex, text[start_pos:], end_flags)
        if end_match:
            candidate_body = text[start_pos : start_pos + end_match.start()].strip()
            # If the candidate body is suspiciously short (< 300 chars), it's likely a TOC entry
            if len(candidate_body) > 300:
                body_text = candidate_body
                break

    # Fallback: if no match passed the TOC heuristic, use the last start match that has an end match
    if body_text is None:
        for m in reversed(start_matches):
            start_pos = m.end()
            end_match = re.search(end_regex, text[start_pos:], end_flags)
            if end_match:
                candidate_body = text[start_pos : start_pos + end_match.start()].strip()
                if len(candidate_body) > 200:
                    body_text = candidate_body
                    break

    return body_text


def extract_section(
    html_content: str,
    section_name: str,
    form_type: str = "10-K",
    max_chars: int = DEFAULT_MAX_CHARS,
) -> Dict[str, Any]:
    """Extract and clean a specific section from filing HTML."""
    section_key = section_name.strip().lower()
    if section_key not in SECTION_DEFINITIONS:
        valid_keys = ", ".join(SECTION_DEFINITIONS.keys())
        raise SectionNotFound(
            section_name,
            "",
            f"Invalid section name. Supported sections: {valid_keys}",
        )

    norm_form = form_type.strip().upper()
    sec_def = SECTION_DEFINITIONS[section_key]

    if section_key == "mdna":
        if "10-Q" in norm_form:
            start_pat = sec_def["start_pattern_10q"]
            end_pat = sec_def["end_pattern_10q"]
        else:
            start_pat = sec_def["start_pattern_10k"]
            end_pat = sec_def["end_pattern_10k"]
    else:
        start_pat = sec_def["start_pattern"]
        end_pat = sec_def["end_pattern"]

    raw_text = clean_html_to_text(html_content)
    body = find_section_body(raw_text, start_pat, end_pat)

    if not body:
        raise SectionNotFound(
            section_name,
            "",
            f"Could not locate '{section_name}' in filing content using regex: '{start_pat}'.",
        )

    paragraphs = extract_paragraphs(body)
    cleaned_body = "\n\n".join(paragraphs)

    is_truncated = False
    truncation_note = None
    if len(cleaned_body) > max_chars:
        is_truncated = True
        cleaned_body = cleaned_body[:max_chars].rsplit("\n\n", 1)[0]
        truncation_note = (
            f"[Note: Section text truncated at {len(cleaned_body)} characters for model context. "
            "Refer to official source filing URL for the complete document.]"
        )

    return {
        "section": section_key,
        "title": sec_def["title"],
        "text": cleaned_body,
        "paragraphs": extract_paragraphs(cleaned_body),
        "is_truncated": is_truncated,
        "truncation_note": truncation_note,
        "character_count": len(cleaned_body),
    }


async def get_filing_section(
    client: EdgarClient,
    ticker: str,
    form_type: str = "10-K",
    section: str = "risk_factors",
    accession_number: Optional[str] = None,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> Dict[str, Any]:
    """Retrieve and parse a specific cleaned section from an SEC filing.

    Sections: 'business', 'risk_factors', 'mdna', 'legal_proceedings'.
    """
    company = await lookup_company(client, ticker)
    ticker_sym = company["ticker"]
    company_name = company["name"]
    cik = company["cik"]

    filings = await list_filings(client, ticker_sym, form_type=form_type, limit=5)
    if not filings:
        raise FilingNotFound(f"No {form_type} filings found for {ticker_sym}.")

    target_filing = None
    if accession_number:
        clean_acc = accession_number.strip()
        for f in filings:
            if f["accession_number"] == clean_acc:
                target_filing = f
                break
        if not target_filing:
            msg = f"Accession '{accession_number}' not found in filings for {ticker_sym}."
            raise FilingNotFound(msg)
    else:
        target_filing = filings[0]

    doc_url = target_filing["document_url"]
    html_content = await client.get_filing_document(doc_url)

    parsed = extract_section(
        html_content,
        section_name=section,
        form_type=form_type,
        max_chars=max_chars,
    )

    return {
        "ticker": ticker_sym,
        "company_name": company_name,
        "cik": cik,
        "form_type": form_type.upper(),
        "section": parsed["section"],
        "section_title": parsed["title"],
        "accession_number": target_filing["accession_number"],
        "filing_date": target_filing["filing_date"],
        "report_date": target_filing.get("report_date"),
        "text": parsed["text"],
        "character_count": parsed["character_count"],
        "is_truncated": parsed["is_truncated"],
        "truncation_note": parsed["truncation_note"],
        "source_url": doc_url,
        "interactive_data_url": target_filing.get("interactive_data_url"),
        "disclaimer": "Informational only, not investment advice.",
    }
