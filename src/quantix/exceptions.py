"""Custom typed exceptions for Quantix."""


class QuantixError(Exception):
    """Base exception for all Quantix errors."""

    pass


class ConfigurationError(QuantixError):
    """Raised when environment or application configuration is invalid."""

    pass


class CompanyNotFound(QuantixError):
    """Raised when a company ticker or name cannot be found in the SEC registry."""

    def __init__(self, query: str):
        super().__init__(f"Company '{query}' was not found in SEC EDGAR registry.")
        self.query = query


class FilingNotFound(QuantixError):
    """Raised when a requested filing or form type cannot be found."""

    def __init__(self, message: str):
        super().__init__(message)


class SectionNotFound(QuantixError):
    """Raised when a specific section cannot be parsed from a filing."""

    def __init__(self, section: str, ticker: str, details: str = ""):
        msg = f"Section '{section}' could not be located in filing for ticker '{ticker}'."
        if details:
            msg += f" {details}"
        super().__init__(msg)
        self.section = section
        self.ticker = ticker


class EdgarRateLimited(QuantixError):
    """Raised when SEC EDGAR returns a 429 rate limit error after retries."""

    def __init__(self, message: str = "SEC EDGAR rate limit exceeded after maximum retries."):
        super().__init__(message)


class EdgarAPIError(QuantixError):
    """Raised when an unrecoverable SEC EDGAR API error occurs."""

    def __init__(self, status_code: int, url: str, message: str = ""):
        super().__init__(f"SEC EDGAR returned HTTP {status_code} for {url}. {message}".strip())
        self.status_code = status_code
        self.url = url
