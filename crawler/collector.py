"""Fetching HTML for given dates, try requests first and fallback to Playwright."""
from datetime import date
from typing import Optional
import logging
import requests
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type

from .config import BASE_URL, DEFAULT_HEADERS, DATE_FORMAT

logger = logging.getLogger(__name__)


def _format_date(d: date) -> str:
    return d.strftime(DATE_FORMAT)


def fetch_for_date(d: date, use_playwright: bool = False, session: Optional[requests.Session] = None) -> str:
    """Fetch page HTML for a given date.

    Tries a direct HTTP request first. If the page requires JS to render data and
    `use_playwright` is True, falls back to Playwright browser rendering.
    Returns raw HTML text.
    """
    date_str = _format_date(d)
    sess = session or requests.Session()
    params = {"fecha": date_str}

    @retry(wait=wait_exponential(min=1, max=10), stop=stop_after_attempt(3), retry=retry_if_exception_type(Exception))
    def _http_get():
        logger.debug("Requesting %s with params=%s", BASE_URL, params)
        r = sess.get(BASE_URL, headers=DEFAULT_HEADERS, params=params, timeout=30)
        r.raise_for_status()
        return r

    try:
        r = _http_get()
        # Heuristic: if response contains table/data return it
        text = r.text
        if "<table" in text or "tbody" in text or "INDI" in text:
            return text
        # otherwise, maybe JS renders the data
        logger.info("Response lacks table, switching to Playwright: %s", d)
    except Exception as exc:
        logger.warning("HTTP request failed: %s", exc)

    if not use_playwright:
        raise RuntimeError("Page likely requires JS to render contents; retry with use_playwright=True")

    # Playwright fallback (optional dependency)
    try:
        from playwright.sync_api import sync_playwright

        logger.debug("Launching Playwright to render page for %s", date_str)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(BASE_URL)

            # Best-effort: the page shows two date ranges composed of selects (day, month, year).
            # We'll try to locate all <select> elements and fill them in order:
            # [start_day, start_month, start_year, end_day, end_month, end_year]
            try:
                selects = page.query_selector_all("select")
                logger.debug("Found %d select elements", len(selects))
                day = d.day
                month = d.month
                year = d.year
                values = [str(day), str(month), str(year), str(day), str(month), str(year)]
                for i, sel in enumerate(selects[:6]):
                    try:
                        # try select_option with the option value matching our numeric value
                        sel.select_option(values[i])
                    except Exception:
                        # fallback: try selecting by index or visible text
                        opts = sel.query_selector_all("option")
                        if not opts:
                            continue
                        # try to match by text
                        matched = False
                        for opt in opts:
                            txt = opt.inner_text().strip()
                            if txt == values[i] or txt == str(int(values[i])):
                                val = opt.get_attribute("value")
                                sel.select_option(val)
                                matched = True
                                break
                        if not matched:
                            # as last resort pick first
                            sel.select_option(opts[0].get_attribute("value"))

                # Click the "Ver" button if present
                # Try common selectors
                if page.locator('input[type="submit"][value*="Ver"]').count() > 0:
                    page.click('input[type="submit"][value*="Ver"]')
                elif page.locator('button:has-text("Ver")').count() > 0:
                    page.click('button:has-text("Ver")')
                else:
                    # try any button
                    if page.locator('button').count() > 0:
                        page.click('button')

                page.wait_for_load_state('networkidle', timeout=10000)
            except Exception as pw_exc:
                logger.debug("Playwright form interaction best-effort failed: %s", pw_exc)
            html = page.content()
            browser.close()
            return html
    except ImportError:
        raise RuntimeError("Playwright is not installed. Install with 'pip install playwright' and run 'playwright install'.")
