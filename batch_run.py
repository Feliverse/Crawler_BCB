#!/usr/bin/env python3
import argparse
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlparse


def normalize_name(url: str) -> str:
    p = urlparse(url)
    key = (p.netloc + p.path).strip('/').replace('/', '_')
    if not key:
        key = p.netloc or 'root'
    return ''.join(c if c.isalnum() or c in ('_', '-') else '_' for c in key)


def read_urls_from_csv(path: Path, column_name: str = 'BASE_URL') -> list[str]:
    urls = []
    with path.open('r', encoding='utf-8') as f:
        reader = csv.reader(f)
        rows = [row for row in reader if row]

    if not rows:
        return urls

    header = [cell.strip().upper() for cell in rows[0]]
    valid_columns = {column_name.upper(), 'URL', 'LINK', 'WEBSITE'}
    col_idx = None

    for idx, name in enumerate(header):
        if name in valid_columns:
            col_idx = idx
            break

    if col_idx is not None:
        for row in rows[1:]:
            if len(row) > col_idx and row[col_idx].strip():
                urls.append(row[col_idx].strip())
        return urls

    start_idx = 0
    first_val = rows[0][0].strip().lower()
    if not (first_val.startswith('http://') or first_val.startswith('https://')):
        start_idx = 1

    for row in rows[start_idx:]:
        if row and row[0].strip():
            urls.append(row[0].strip())

    return urls


def process_url(
    url: str,
    project_dir: Path,
    outputs_dir: Path,
    extra_args: list[str],
    depth: int,
    timeout: int,
) -> tuple[str, dict]:
    """Worker function executed in parallel by each thread."""
    name = normalize_name(url)
    out_path = outputs_dir / f"{name}.json"
    tables_dir = outputs_dir / 'tables' / name

    # Build command line arguments for main.py
    cmd = [
        sys.executable,
        'main.py',
        '--url',
        url,
        '--depth',
        str(depth),
        '--output',
        str(out_path),
        '--tables-dir',
        str(tables_dir),
    ]
    if extra_args:
        cmd.extend(extra_args)

    print(f"[START] Scraping: {url}")

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        print(f"[TIMEOUT] {url}")
        return url, {'error': 'timeout', 'timeout': True}

    if out_path.exists():
        try:
            with out_path.open('r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            data = None
            print(f"[ERROR] Failed to read output JSON for {url}: {e}")

        print(f"[DONE] Finished: {url}")
        return url, {
            'returncode': proc.returncode,
            'stdout': proc.stdout,
            'stderr': proc.stderr,
            'data_file': str(out_path.name),
            'data': data,
        }
    else:
        print(f"[FAILED] No output produced for: {url}")
        return url, {
            'returncode': proc.returncode,
            'stdout': proc.stdout,
            'stderr': proc.stderr,
            'error': f"Output file {out_path.name} was not generated",
        }


def main():
    parser = argparse.ArgumentParser(
        description='Run main.py for multiple URLs concurrently from a CSV file.'
    )
    parser.add_argument(
        'csv',
        nargs='?',
        default='fuentes.csv',
        help='Path to CSV file with URLs',
    )
    parser.add_argument(
        '-o',
        '--output',
        default='super_output.json',
        help='Aggregated output JSON file',
    )
    parser.add_argument(
        '-w',
        '--workers',
        type=int,
        default=4,
        help='Number of concurrent threads/crawlers to run in parallel (default: 4)',
    )
    parser.add_argument(
        '--timeout',
        type=int,
        default=300,
        help='Timeout per URL in seconds (default: 300)',
    )
    parser.add_argument(
        '--depth',
        type=int,
        default=4,
        help='Maximum crawl depth for each URL (default: 4)',
    )
    parser.add_argument(
        '--exclude-keywords',
        default='',
        help='Exclude keywords string or file path to pass down to main.py',
    )
    parser.add_argument(
        '--ignore-robots',
        action='store_true',
        help='Bypass robots.txt checks across all target sites'
    )
    args = parser.parse_args()

    project_dir = Path(__file__).parent
    csv_path = Path(args.csv)

    if not csv_path.exists():
        print(f"CSV file not found: {csv_path}")
        sys.exit(2)

    urls = read_urls_from_csv(csv_path)
    if not urls:
        print("No valid URLs found in the CSV file.")
        sys.exit(1)

    outputs_dir = project_dir / 'batch_outputs'
    outputs_dir.mkdir(exist_ok=True)

    extra_crawler_args = []
    if args.exclude_keywords:
        extra_crawler_args.extend(['--exclude-keywords', args.exclude_keywords])

    print(
        f"Starting batch crawler: {len(urls)} URLs across {args.workers} worker threads.\n"
    )

    aggregated = {}

    # Execute crawler instances in parallel
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [
            executor.submit(
                process_url,
                url,
                project_dir,
                outputs_dir,
                extra_crawler_args,
                args.depth,
                args.timeout,
            )
            for url in urls
        ]

        for future in as_completed(futures):
            url, result = future.result()
            aggregated[url] = result

    out_file = project_dir / args.output
    with out_file.open('w', encoding='utf-8') as f:
        json.dump(aggregated, f, ensure_ascii=False, indent=2)

    print(f"\nCompleted all sites! Aggregated results written to: {out_file}")


if __name__ == '__main__':
    main()