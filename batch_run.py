#!/usr/bin/env python3
import os
import sys
import json
import subprocess
import time
import argparse
from pathlib import Path
from urllib.parse import urlparse

try:
    import openpyxl
except Exception:
    print("Missing dependency 'openpyxl'. Install from requirements.txt")
    raise


def normalize_name(url: str) -> str:
    p = urlparse(url)
    key = (p.netloc + p.path).strip('/').replace('/', '_')
    if not key:
        key = p.netloc or 'root'
    # keep only safe chars
    return ''.join(c if c.isalnum() or c in ('_', '-') else '_' for c in key)


def read_urls_from_xlsx(path: Path, column_name: str = 'BASE_URL'):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []

    # detect header
    first_row = rows[0]
    start_idx = 0
    col_idx = 0
    if any(isinstance(c, str) and c.strip().upper() == column_name.upper() for c in first_row if c is not None):
        # find the header column index
        for i, c in enumerate(first_row):
            if isinstance(c, str) and c.strip().upper() == column_name.upper():
                col_idx = i
                start_idx = 1
                break
    else:
        # assume first column
        col_idx = 0
        start_idx = 0

    urls = []
    for r in rows[start_idx:]:
        if not r:
            continue
        val = r[col_idx]
        if val is None:
            continue
        s = str(val).strip()
        if s:
            urls.append(s)
    return urls


def run_main_for_url(url: str, project_dir: Path, timeout: int = 300):
    env = os.environ.copy()
    env['BASE_URL'] = url

    proc = subprocess.run([sys.executable, 'main.py'], cwd=str(project_dir), env=env, capture_output=True, text=True, timeout=timeout)
    return proc.returncode, proc.stdout, proc.stderr


def main():
    parser = argparse.ArgumentParser(description='Run main.py for multiple BASE_URL values from an .xlsx file and aggregate outputs.')
    parser.add_argument('xlsx', nargs='?', default='urls.xlsx', help='Path to .xlsx file with URLs (column named BASE_URL or first column)')
    parser.add_argument('-o', '--output', default='super_output.json', help='Aggregated output JSON file')
    parser.add_argument('--delay', type=float, default=1.2, help='Delay between runs in seconds')
    args = parser.parse_args()

    project_dir = Path(__file__).parent
    xlsx_path = Path(args.xlsx)
    if not xlsx_path.exists():
        print(f"Excel file not found: {xlsx_path}")
        sys.exit(2)

    urls = read_urls_from_xlsx(xlsx_path)
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

        mapa_file = project_dir / 'mapa_global_bcb.json'
        if mapa_file.exists():
            try:
                with mapa_file.open('r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception as e:
                data = None
                print(f"Failed to read mapa_global_bcb.json for {url}: {e}")

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
                'error': 'mapa_global_bcb.json not produced'
            }

        time.sleep(args.delay)

    # write aggregated
    out_file = project_dir / args.output
    with out_file.open('w', encoding='utf-8') as f:
        json.dump(aggregated, f, ensure_ascii=False, indent=2)

    print(f"Aggregated results written to: {out_file}")


if __name__ == '__main__':
    main()
