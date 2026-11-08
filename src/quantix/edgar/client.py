"""Async, rate-limited, retrying, and cached SEC EDGAR client."""

import asyncio
import json
import logging
import ssl
import time
from typing import Any, Dict, Optional, Tuple, Union

import httpx

from quantix.config import Settings, get_settings
from quantix.db import Database, get_db
from quantix.exceptions import ConfigurationError, EdgarAPIError, EdgarRateLimited

logger = logging.getLogger(__name__)

SEC_BASE_URL = "https://www.sec.gov"
DATA_BASE_URL = "https://data.sec.gov"

# Cache TTLs in seconds
TTL_TICKERS = 86400.0  # 24 hours
TTL_SUBMISSIONS = 3600.0  # 1 hour
TTL_FACTS = 21600.0  # 6 hours
TTL_DOCUMENTS = None  # Immutable (Forever)


def get_ssl_context(verify: bool = True) -> Union[ssl.SSLContext, bool]:
    """Create SSL context with Windows system certificates loaded, or False if unverified."""
    if not verify:
        return False
    try:
        ctx = ssl.create_default_context()
        if hasattr(ssl, "enum_certificates"):
            for store in ("ROOT", "CA"):
                try:
                    for cert, encoding, _ in ssl.enum_certificates(store):
                        if encoding == "x509_asn":
                            try:
                                ctx.load_verify_locations(cadata=cert)
                            except Exception:
                                pass
                except Exception:
                    pass
        return ctx
    except Exception as exc:
        logger.warning("Failed to initialize enhanced SSL context: %s. Using default.", exc)
        return True


class AsyncRateLimiter:
    """Async token bucket rate limiter to stay strictly under SEC limit of 10 req/s."""

    def __init__(self, rate: float = 8.0, capacity: float = 8.0):
        self.rate = rate  # tokens added per second
        self.capacity = capacity  # max bucket burst
        self.tokens = capacity
        self.updated_at = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Acquire a single request token, sleeping if necessary."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.updated_at
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            self.updated_at = now

            if self.tokens < 1.0:
                needed = 1.0 - self.tokens
                wait_time = needed / self.rate
                await asyncio.sleep(wait_time)
                self.tokens = 0.0
                self.updated_at = time.monotonic()
            else:
                self.tokens -= 1.0


class EdgarClient:
    """Production client for SEC EDGAR APIs with rate limiting, retries, and caching."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        db: Optional[Database] = None,
        rate_limiter: Optional[AsyncRateLimiter] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        self.settings = settings or get_settings()
        # Ensure user agent is valid upon instantiation
        user_agent = self.settings.edgar_user_agent.strip()
        if not user_agent or "@" not in user_agent:
            msg = (
                f"EDGAR_USER_AGENT ('{user_agent}') is invalid or missing. "
                "Must contain an email address."
            )
            raise ConfigurationError(msg)

        self.user_agent = user_agent
        self.db = db or get_db(self.settings.db_path)
        self.rate_limiter = rate_limiter or AsyncRateLimiter(rate=8.0, capacity=8.0)
        self._client = http_client
        self._owns_client = http_client is None

    async def _get_http_client(self, verify: Optional[bool] = None) -> httpx.AsyncClient:
        """Lazy load or return existing httpx client."""
        ssl_verify = self.settings.sec_verify_ssl if verify is None else verify
        if self._client is None or self._client.is_closed:
            headers = {
                "User-Agent": self.user_agent,
                "Accept-Encoding": "gzip, deflate",
                "Accept": "application/json, text/html, */*",
            }
            self._client = httpx.AsyncClient(
                headers=headers,
                timeout=httpx.Timeout(30.0, connect=10.0),
                follow_redirects=True,
                verify=get_ssl_context(ssl_verify),
            )
        return self._client

    async def close(self) -> None:
        """Close HTTP client session."""
        if self._owns_client and self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    @staticmethod
    def pad_cik(cik: str | int) -> str:
        """Pad CIK to 10 digits as required by data.sec.gov."""
        cleaned = str(cik).strip().lstrip("0")
        if not cleaned:
            cleaned = "0"
        return cleaned.zfill(10)

    @staticmethod
    def build_filing_document_url(
        cik: str | int,
        accession_number: str,
        primary_doc: str,
    ) -> str:
        """Construct SEC Archives direct document URL."""
        cik_clean = str(cik).strip().lstrip("0")
        acc_no_hyphens = accession_number.replace("-", "")
        return f"{SEC_BASE_URL}/Archives/edgar/data/{cik_clean}/{acc_no_hyphens}/{primary_doc}"

    @staticmethod
    def build_interactive_url(
        cik: str | int,
        accession_number: str,
        primary_doc: str,
    ) -> str:
        """Construct SEC Interactive Data Viewer URL (inline XBRL)."""
        cik_clean = str(cik).strip().lstrip("0")
        acc_no_hyphens = accession_number.replace("-", "")
        path = f"/Archives/edgar/data/{cik_clean}/{acc_no_hyphens}/{primary_doc}"
        return f"{SEC_BASE_URL}/ix?doc={path}"

    async def fetch(
        self,
        url: str,
        ttl_seconds: Optional[float] = None,
        max_retries: int = 3,
        initial_backoff: float = 0.5,
    ) -> Tuple[int, Dict[str, str], str]:
        """Fetch URL with SQLite caching, rate limiting, and exponential backoff retry."""
        # 1. Check Cache
        cached = await self.db.get_cache(url)
        if cached is not None:
            status_code, headers, content = cached
            return status_code, headers, content

        client = await self._get_http_client()
        attempt = 0
        backoff = initial_backoff

        while attempt <= max_retries:
            # 2. Rate limit check before outbound request
            await self.rate_limiter.acquire()
            attempt += 1

            try:
                response = await client.get(url)

                if response.status_code == 200:
                    content = response.text
                    headers = dict(response.headers)
                    # Cache successful response
                    await self.db.set_cache(url, 200, headers, content, ttl_seconds)
                    return 200, headers, content

                if response.status_code == 429:
                    logger.warning("SEC EDGAR rate limit (429) hit for URL: %s", url)
                    if attempt > max_retries:
                        err = f"Rate limit (429) exceeded for {url} after {max_retries} retries."
                        raise EdgarRateLimited(err)
                    # Check Retry-After header
                    hdr = response.headers.get("Retry-After")
                    sleep_time = float(hdr) if hdr and hdr.isdigit() else backoff
                    await asyncio.sleep(sleep_time)
                    backoff *= 2.0
                    continue

                if 500 <= response.status_code < 600:
                    logger.warning("SEC server error (%d) for: %s", response.status_code, url)
                    if attempt > max_retries:
                        err = f"Server error {response.status_code} after {max_retries} retries."
                        raise EdgarAPIError(response.status_code, url, err)
                    await asyncio.sleep(backoff)
                    backoff *= 2.0
                    continue

                # Client errors (404, 403, etc.) - don't retry blindly
                raise EdgarAPIError(response.status_code, url, response.text[:200])

            except (httpx.RequestError, httpx.TimeoutException) as exc:
                err_str = str(exc)
                if ("CERTIFICATE_VERIFY_FAILED" in err_str or "certificate verify failed" in err_str or "SSLCertVerificationError" in err_str):
                    logger.warning("SSL verification failed for %s. Retrying with fallback unverified SSL...", url)
                    try:
                        if self._owns_client and self._client:
                            await self._client.aclose()
                        headers = {
                            "User-Agent": self.user_agent,
                            "Accept-Encoding": "gzip, deflate",
                            "Accept": "application/json, text/html, */*",
                        }
                        self._client = httpx.AsyncClient(
                            headers=headers,
                            timeout=httpx.Timeout(30.0, connect=10.0),
                            follow_redirects=True,
                            verify=False,
                        )
                        client = self._client
                        continue
                    except Exception as fallback_exc:
                        logger.error("Fallback unverified SSL client failed: %s", fallback_exc)

                if attempt > max_retries:
                    raise EdgarAPIError(500, url, f"Network failed: {str(exc)}") from exc
                await asyncio.sleep(backoff)
                backoff *= 2.0

        raise EdgarAPIError(500, url, "Max retries exceeded without successful response.")

    async def get_company_tickers(self) -> Dict[str, Any]:
        """Fetch mapping of tickers and names to CIK from company_tickers.json."""
        url = f"{SEC_BASE_URL}/files/company_tickers.json"
        _, _, content = await self.fetch(url, ttl_seconds=TTL_TICKERS)
        return json.loads(content)

    async def get_submissions(self, cik: str | int) -> Dict[str, Any]:
        """Fetch company submission history by CIK."""
        cik10 = self.pad_cik(cik)
        url = f"{DATA_BASE_URL}/submissions/CIK{cik10}.json"
        _, _, content = await self.fetch(url, ttl_seconds=TTL_SUBMISSIONS)
        return json.loads(content)

    async def get_company_facts(self, cik: str | int) -> Dict[str, Any]:
        """Fetch all XBRL facts for a company by CIK."""
        cik10 = self.pad_cik(cik)
        url = f"{DATA_BASE_URL}/api/xbrl/companyfacts/CIK{cik10}.json"
        _, _, content = await self.fetch(url, ttl_seconds=TTL_FACTS)
        return json.loads(content)

    async def get_filing_document(self, url: str) -> str:
        """Fetch raw HTML or text filing document from SEC archives (immutable)."""
        _, _, content = await self.fetch(url, ttl_seconds=TTL_DOCUMENTS)
        return content
