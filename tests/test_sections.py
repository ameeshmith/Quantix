"""Tests for HTML 10-K and 10-Q section splitting and TOC skipping across 5 companies."""

from pathlib import Path

import pytest

from quantix.exceptions import SectionNotFound
from quantix.services.sections import extract_section

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def read_fixture(filename: str) -> str:
    path = FIXTURES_DIR / filename
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def test_extract_risk_factors_apple():
    html_doc = read_fixture("sample_10k_aapl.html")
    res = extract_section(html_doc, "risk_factors", form_type="10-K")
    assert res["section"] == "risk_factors"
    assert "Global economic conditions could materially adversely affect" in res["text"]
    assert "Item 1B" not in res["text"]
    # Ensure Table of Contents page dots were excluded
    assert "..........." not in res["text"]
    assert len(res["paragraphs"]) == 3


def test_extract_business_apple():
    html_doc = read_fixture("sample_10k_aapl.html")
    res = extract_section(html_doc, "business", form_type="10-K")
    assert res["section"] == "business"
    assert "Apple designs, manufactures and markets smartphones" in res["text"]
    assert "Item 1A" not in res["text"]


def test_extract_mdna_apple():
    html_doc = read_fixture("sample_10k_aapl.html")
    res = extract_section(html_doc, "mdna", form_type="10-K")
    assert res["section"] == "mdna"
    assert "Total net sales increased 2% during fiscal 2024" in res["text"]
    assert "Item 7A" not in res["text"]


def test_extract_risk_factors_microsoft():
    html_doc = read_fixture("sample_10k_msft.html")
    res = extract_section(html_doc, "risk_factors", form_type="10-K")
    assert res["section"] == "risk_factors"
    assert "cybersecurity threats, including sophisticated threat actors" in res["text"]
    assert "TABLE OF CONTENTS" not in res["text"]


def test_extract_risk_factors_nvidia():
    html_doc = read_fixture("sample_10k_nvda.html")
    res = extract_section(html_doc, "risk_factors", form_type="10-K")
    assert res["section"] == "risk_factors"
    assert "accelerated computing and AI infrastructure" in res["text"]
    assert "Page 12" not in res["text"]


def test_extract_risk_factors_amazon():
    html_doc = read_fixture("sample_10k_amzn.html")
    res = extract_section(html_doc, "risk_factors", form_type="10-K")
    assert res["section"] == "risk_factors"
    assert "retail, e-commerce, cloud computing" in res["text"]


def test_extract_risk_factors_google():
    html_doc = read_fixture("sample_10k_goog.html")
    res = extract_section(html_doc, "risk_factors", form_type="10-K")
    assert res["section"] == "risk_factors"
    assert "artificial intelligence technologies and large language models" in res["text"]


def test_section_not_found():
    html_doc = "<html><body><p>Short general text without items</p></body></html>"
    with pytest.raises(SectionNotFound) as exc_info:
        extract_section(html_doc, "risk_factors")
    assert "risk_factors" in str(exc_info.value)


def test_invalid_section_name():
    html_doc = read_fixture("sample_10k_aapl.html")
    with pytest.raises(SectionNotFound) as exc_info:
        extract_section(html_doc, "nonexistent_section_name")
    assert "Invalid section name" in str(exc_info.value)


def test_section_truncation():
    html_doc = read_fixture("sample_10k_aapl.html")
    res = extract_section(html_doc, "risk_factors", max_chars=100)
    assert res["is_truncated"] is True
    assert res["truncation_note"] is not None
    assert len(res["text"]) <= 100
