"""Pydantic models for SEC EDGAR API responses and data structures."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, computed_field


class CompanyInfo(BaseModel):
    """Company identification mapped from SEC company_tickers.json."""

    cik_str: int = Field(..., description="Integer CIK as stored in ticker mapping")
    ticker: str = Field(..., description="Ticker symbol")
    title: str = Field(..., description="Company legal name")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cik_10(self) -> str:
        """Zero-padded 10-digit CIK for SEC APIs."""
        return str(self.cik_str).zfill(10)


class FilingItem(BaseModel):
    """Cleaned filing metadata record."""

    accession_number: str = Field(..., description="SEC Accession Number")
    filing_date: str = Field(..., description="Date filing was submitted (YYYY-MM-DD)")
    report_date: Optional[str] = Field(None, description="End of reporting period (YYYY-MM-DD)")
    form: str = Field(..., description="Form type (e.g., 10-K, 10-Q, 8-K)")
    file_number: Optional[str] = Field(None, description="SEC File Number")
    primary_document: str = Field(..., description="Primary document filename")
    primary_doc_description: Optional[str] = Field(None, description="Primary document description")
    document_url: str = Field(..., description="Direct URL to view primary document on SEC EDGAR")
    interactive_data_url: Optional[str] = Field(None, description="Interactive data URL if XBRL")
    items: Optional[str] = Field(None, description="Trigger items for 8-K filings")


class SubmissionsRecent(BaseModel):
    """Raw recent filings array dictionary from data.sec.gov/submissions."""

    accessionNumber: List[str] = Field(default_factory=list)
    filingDate: List[str] = Field(default_factory=list)
    reportDate: List[Optional[str]] = Field(default_factory=list)
    acceptanceDateTime: List[str] = Field(default_factory=list)
    act: List[str] = Field(default_factory=list)
    form: List[str] = Field(default_factory=list)
    fileNumber: List[Optional[str]] = Field(default_factory=list)
    filmNumber: List[Optional[str]] = Field(default_factory=list)
    items: List[Optional[str]] = Field(default_factory=list)
    size: List[Optional[int]] = Field(default_factory=list)
    isXBRL: List[Optional[int]] = Field(default_factory=list)
    isInlineXBRL: List[Optional[int]] = Field(default_factory=list)
    primaryDocument: List[str] = Field(default_factory=list)
    primaryDocDescription: List[Optional[str]] = Field(default_factory=list)


class CompanySubmissions(BaseModel):
    """Full submissions payload from data.sec.gov/submissions/CIK{cik10}.json."""

    cik: str
    entityType: Optional[str] = None
    sic: Optional[str] = None
    sicDescription: Optional[str] = None
    name: str
    tickers: List[str] = Field(default_factory=list)
    exchanges: List[str] = Field(default_factory=list)
    filings: Dict[str, Any] = Field(default_factory=dict)
