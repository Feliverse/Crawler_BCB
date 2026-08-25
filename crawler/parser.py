"""Parsing utilities for the BCB metals page."""
from typing import List, Dict
from bs4 import BeautifulSoup
import logging
import json

logger = logging.getLogger(__name__)


def parse_table_rows(html: str) -> List[Dict[str, str]]:
    """Extract table rows into list of dicts (header->value).

    This is a best-effort generic parser that finds the first HTML table and
    extracts header cells as keys.
    """
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table")
    if not table:
        logger.debug("No <table> found in HTML")
        return []

    # extract headers
    headers = []
    header_row = table.find("tr")
    if header_row:
        for th in header_row.find_all(["th", "td"]):
            headers.append(th.get_text(strip=True))

    rows = []
    for tr in table.find_all("tr")[1:]:
        cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
        if not cells:
            continue
        # map into dict
        if len(headers) == len(cells):
            row = dict(zip(headers, cells))
        else:
            # fallback: use numeric keys
            row = {str(i): v for i, v in enumerate(cells)}
        rows.append(row)

    return rows


def to_json(rows: List[Dict[str, str]]) -> str:
    return json.dumps(rows, ensure_ascii=False)
