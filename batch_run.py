#!/usr/bin/env python3
import os
import sys
import json
import subprocess
import time
import argparse
from pathlib import Path
from urllib.parse import urlparse

import csv


def normalize_name(url: str) -> str:
    p = urlparse(url)
    key = (p.netloc + p.path).strip('/').replace('/', '_')
    if not key:
        key = p.netloc or 'root'
    # keep only safe chars
    return ''.join(c if c.isalnum() or c in ('_', '-') else '_' for c in key)


def read_urls_from_csv(path: Path, column_name: str = 'BASE_URL'):
    urls = []
    with path.open('r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        if reader.fieldnames:
            # try header-based
            header = [h.strip().upper() for h in reader.fieldnames]
            key = None
            for h in reader.fieldnames:
                if h.strip().upper() == column_name.upper():
                    key = h
                    break
            if key:
                for row in reader:
                    val = row.get(key)
                    if val:
                        urls.append(val.strip())
                return urls
        # fallback: read first column
    with path.open('r', encoding='utf-8') as f:
        for i, line in enumerate(f):
            if i == 0:
                # skip header if it looks like one (contains non-url text)
                first = line.strip()
                if not (first.startswith('http') or first.startswith('https')):
                    continue
            val = line.strip().split(',')[0].strip()
            if val:
                urls.append(val)
    return urls


def run_main_for_url(url: str, project_dir: Path, timeout: int = 300):
    env = os.environ.copy()
    env['BASE_URL'] = url

    proc = subprocess.run([sys.executable, 'main.py'], cwd=str(project_dir), env=env, capture_output=True, text=True, timeout=timeout)
    return proc.returncode, proc.stdout, proc.stderr


def main():
    parser = argparse.ArgumentParser(description='Run main.py for multiple BASE_URL values from an .xlsx file and aggregate outputs.')
    parser.add_argument('csv', nargs='?', default='fuentes.csv', help='Path to CSV file with URLs (column named BASE_URL or first column)')
    parser.add_argument('-o', '--output', default='super_output.json', help='Aggregated output JSON file')
    parser.add_argument('--delay', type=float, default=1.2, help='Delay between runs in seconds')
    args = parser.parse_args()

    project_dir = Path(__file__).parent
    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"CSV file not found: {csv_path}")
        sys.exit(2)

    urls = read_urls_from_csv(csv_path)
    if not urls:
        print("No URLs found in the Excel file.")
        sys.exit(1)

    aggregated = {}
    outputs_dir = project_dir / 'batch_outputs'
    outputs_dir.mkdir(exist_ok=True)

    for url in urls:
        print(f"Running main.py for: {url}")
        try:
            rc, out, err = run_main_for_url(url, project_dir)
        except subprocess.TimeoutExpired as e:
            aggregated[url] = {'error': 'timeout', 'timeout': True}
            continue

        mapa_file = project_dir / 'mapa_global.json'
        if mapa_file.exists():
            try:
                with mapa_file.open('r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception as e:
                data = None
                print(f"Failed to read mapa_global.json for {url}: {e}")

            name = normalize_name(url)
            out_path = outputs_dir / f"{name}.json"
            try:
                with out_path.open('w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"Failed to write individual output for {url}: {e}")

            aggregated[url] = {
                'returncode': rc,
                'stdout': out,
                'stderr': err,
                'data_file': str(out_path.name),
                'data': data
            }
            # remove the mapa file so next run starts fresh
            try:
                mapa_file.unlink()
            except Exception:
                pass
        else:
            aggregated[url] = {
                'returncode': rc,
                'stdout': out,
                'stderr': err,
                'error': 'mapa_global.json not produced'
            }

        time.sleep(args.delay)

    # write aggregated
    out_file = project_dir / args.output
    with out_file.open('w', encoding='utf-8') as f:
        json.dump(aggregated, f, ensure_ascii=False, indent=2)

    print(f"Aggregated results written to: {out_file}")


if __name__ == '__main__':
    main()
