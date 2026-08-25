"""Async collector using aiohttp and simple retry/backoff."""
import asyncio
from datetime import date
from typing import Optional
import logging
import aiohttp

from .config import BASE_URL, DEFAULT_HEADERS, DATE_FORMAT, RATE_LIMIT_SECONDS

logger = logging.getLogger(__name__)


def _format_date(d: date) -> str:
    return d.strftime(DATE_FORMAT)


async def async_fetch_for_date(d: date, session: aiohttp.ClientSession, attempts: int = 3) -> str:
    """Fetch page HTML for a given date asynchronously with retries.

    Raises RuntimeError if all attempts fail.
    """
    date_str = _format_date(d)
    params = {"fecha": date_str}
    backoff = 1.0
    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            logger.debug("Async request %s attempt %d", date_str, attempt)
            async with session.get(BASE_URL, params=params, headers=DEFAULT_HEADERS, timeout=30) as resp:
                text = await resp.text()
                if resp.status < 400 and ("<table" in text or "tbody" in text or "INDI" in text):
                    return text
                # If no table found, still return content for later inspection
                return text
        except Exception as exc:
            last_exc = exc
            logger.warning("Attempt %d failed for %s: %s", attempt, date_str, exc)
            if attempt < attempts:
                await asyncio.sleep(backoff)
                backoff *= 2

    raise RuntimeError(f"Failed to fetch {date_str}") from last_exc
