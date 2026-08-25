"""CLI entrypoint for the BCB crawler."""
import argparse
from datetime import datetime, timedelta
from crawler.collector import fetch_for_date
from crawler.async_collector import async_fetch_for_date
from crawler.parser import parse_table_rows
from crawler.storage import Storage
from crawler.config import DB_PATH
import logging
from crawler.storage_sqlalchemy import StorageSQLAlchemy
import time
from crawler.config import RATE_LIMIT_SECONDS

logging.basicConfig(level=logging.INFO)


def parse_date(s: str) -> datetime:
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            continue
    raise argparse.ArgumentTypeError(f"Invalid date: {s}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("start", type=parse_date, help="Start date (YYYY-MM-DD or DD/MM/YYYY)")
    p.add_argument("end", type=parse_date, help="End date")
    p.add_argument("--playwright", action="store_true", help="Use Playwright fallback")
    p.add_argument("--async", dest="async_mode", action="store_true", help="Use async concurrent fetch")
    p.add_argument("--concurrency", type=int, default=5, help="Max concurrent requests when using --async")
    args = p.parse_args()

    cur = args.start
    end = args.end

    if args.async_mode:
        # build list of dates
        dates = []
        tmp = cur
        while tmp <= end:
            dates.append(tmp.date())
            tmp += timedelta(days=1)

        async def _run_async():
            import aiohttp

            results = []
            connector = aiohttp.TCPConnector(limit=args.concurrency)
            async with aiohttp.ClientSession(connector=connector) as session:
                sem = asyncio.Semaphore(args.concurrency)

                async def _task(d):
                    async with sem:
                        try:
                            html = await async_fetch_for_date(d, session)
                        except Exception as exc:
                            logging.error("Async fetch failed %s: %s", d, exc)
                            return (d, [])
                        rows = parse_table_rows(html)
                        # respect rate limit between burst groups
                        await asyncio.sleep(RATE_LIMIT_SECONDS)
                        return (d, rows)

                coros = [_task(d) for d in dates]
                for fut in asyncio.as_completed(coros):
                    d, rows = await fut
                    # If async fetch returned no meaningful rows, mark for sync Playwright fallback
                    results.append((d, rows))

            # insert sequentially, with Playwright fallback for empty parses
            storage = StorageSQLAlchemy(DB_PATH)
            try:
                for d, rows in sorted(results):
                    if not rows:
                        # try sync Playwright fallback per-date
                        try:
                            html = fetch_for_date(d, use_playwright=True)
                            rows = parse_table_rows(html)
                        except Exception as exc:
                            logging.error("Playwright fallback failed for %s: %s", d, exc)
                    storage.insert_rows(d.isoformat(), rows)
            finally:
                storage.close()

        asyncio.run(_run_async())
        return

    storage = Storage(DB_PATH)
    try:
        while cur <= end:
            fecha = cur.date()
            logging.info("Fetching %s", fecha)
            try:
                html = fetch_for_date(fecha, use_playwright=args.playwright)
            except Exception as exc:
                logging.error("Failed to fetch %s: %s", fecha, exc)
                cur += timedelta(days=1)
                continue

            rows = parse_table_rows(html)
            storage.insert_rows(fecha.isoformat(), rows)
            # respect rate limit
            time.sleep(RATE_LIMIT_SECONDS)
            cur += timedelta(days=1)
    finally:
        storage.close()


if __name__ == "__main__":
    main()
