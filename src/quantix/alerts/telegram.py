"""Async Telegram alert dispatcher for newly filed SEC disclosures."""

import logging
from typing import Any, Dict, Optional

import httpx

from quantix.config import Settings, get_settings

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Dispatches formatted SEC filing alerts via Telegram Bot API."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        self.settings = settings or get_settings()
        self._client = http_client
        self._owns_client = http_client is None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0))
        return self._client

    async def close(self) -> None:
        if self._owns_client and self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def is_configured(self) -> bool:
        """Check if Telegram bot token and chat ID are configured."""
        return bool(self.settings.telegram_bot_token and self.settings.telegram_chat_id)

    async def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """Send a message to the configured Telegram chat."""
        if not self.is_configured():
            logger.info("Telegram notifier is not configured; skipping alert dispatch.")
            return False

        token = self.settings.telegram_bot_token
        chat_id = self.settings.telegram_chat_id
        url = f"https://api.telegram.org/bot{token}/sendMessage"

        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": False,
        }

        client = await self._get_client()
        try:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                logger.info("Telegram alert dispatched successfully to chat %s.", chat_id)
                return True
            logger.error("Telegram API returned HTTP %d: %s", resp.status_code, resp.text[:200])
            return False
        except Exception as exc:
            logger.error("Failed to dispatch Telegram message: %s", exc)
            return False

    async def send_filing_alert(
        self,
        ticker: str,
        company_name: str,
        filing_meta: Dict[str, Any],
        summary: str,
    ) -> bool:
        """Format and send a structured filing alert."""
        form = filing_meta.get("form_type", "8-K")
        filing_date = filing_meta.get("filing_date", "Today")
        items = filing_meta.get("items") or "Material Event"
        doc_url = filing_meta.get("document_url", "")
        accn = filing_meta.get("accession_number", "")

        msg = (
            f"🚨 <b>SEC Alert: {ticker} ({company_name})</b>\n\n"
            f"📋 <b>Form:</b> {form}\n"
            f"📅 <b>Filing Date:</b> {filing_date}\n"
            f"🏷️ <b>Items:</b> {items}\n"
            f"🔗 <b>Accession:</b> <code>{accn}</code>\n\n"
            f"📝 <b>Summary:</b>\n{summary}\n\n"
            f"🌐 <a href=\"{doc_url}\">View Official SEC Filing Document</a>\n\n"
            "<i>Informational only, not investment advice.</i>"
        )
        return await self.send_message(msg, parse_mode="HTML")
