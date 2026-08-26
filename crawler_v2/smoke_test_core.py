from __future__ import annotations

import argparse
import contextlib
import io
import json
import subprocess
import sys
import threading
import time

from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse


BASE_DIR = Path(__file__).resolve().parent
SOURCES_DIR = BASE_DIR / "sources"

EXPECTED_SOURCES = 52

DEFAULT_WORKERS = 4
DEFAULT_SOURCE_TIMEOUT = 120

SMOKE_MAX_PAGES = 25
SMOKE_MAX_DEPTH = 3
SMOKE_MAX_FILES = 3000

RANDOM_DELAY_MIN = 0.05
RANDOM_DELAY_MAX = 0.12

MAX_SITEMAP_URLS = 300
MAX_OPENAPI_ENDPOINTS = 20
API_PAGINATION_MAX_PAGES = 2

TEMP_PREFIXES = (
    "full_",
    "retry_",
    "batch_",
    "temp_",
    "test_",
)

DOMAIN_LOCKS_LOCK = threading.Lock()
DOMAIN_LOCKS: dict[str, threading.Lock] = {}


# ============================================================
# UTILIDADES
# ============================================================

def load_config(
    path: Path,
) -> dict:

    with path.open(
        "r",
        encoding="utf-8-sig",
    ) as file:
        return json.load(
            file
        )


def config_bool(
    value,
    default: bool = True,
) -> bool:

    if value is None:
        return default

    if isinstance(
        value,
        bool,
    ):
        return value

    if isinstance(
        value,
        (int, float),
    ):
        return bool(
            value
        )

    normalized = str(
        value
    ).strip().lower()

    if normalized in {
        "1",
        "true",
        "yes",
        "si",
        "sí",
        "on",
    }:
        return True

    if normalized in {
        "0",
        "false",
        "no",
        "off",
    }:
        return False

    return default


def is_temporary_config(
    path: Path,
) -> bool:

    return path.stem.lower().startswith(
        TEMP_PREFIXES
    )


def discover_configs() -> list[Path]:

    configs: list[Path] = []

    for path in sorted(
        SOURCES_DIR.glob(
            "*.json"
        )
    ):

        if is_temporary_config(
            path
        ):
            continue

        try:
            config = load_config(
                path
            )

        except Exception:
            continue

        if not config.get(
            "id_fuente"
        ):
            continue

        if not config.get(
            "base_url"
        ):
            continue

        configs.append(
            path
        )

    return configs


def find_config(
    source: str,
) -> Path:

    wanted = (
        source
        .strip()
        .lower()
    )

    for path in discover_configs():

        config = load_config(
            path
        )

        source_id = str(
            config.get(
                "id_fuente",
                "",
            )
        ).strip().lower()

        if wanted in {
            path.stem.lower(),
            source_id,
        }:
            return path

    raise SystemExit(
        "No existe configuración para "
        f"'{source}'."
    )


def primary_domain(
    path: Path,
) -> str:

    config = load_config(
        path
    )

    candidates = [
        config.get(
            "base_url",
            "",
        ),
        *(
            config.get(
                "entrypoints",
                [],
            )
            or []
        ),
    ]

    for candidate in candidates:

        hostname = (
            urlparse(
                str(
                    candidate
                )
            ).hostname
            or ""
        ).lower()

        if hostname.startswith(
            "www."
        ):
            hostname = (
                hostname[4:]
            )

        if hostname:
            return hostname

    return (
        path.stem.lower()
    )


def get_domain_lock(
    path: Path,
) -> threading.Lock:

    domain = (
        primary_domain(
            path
        )
    )

    with DOMAIN_LOCKS_LOCK:

        lock = (
            DOMAIN_LOCKS.get(
                domain
            )
        )

        if lock is None:

            lock = (
                threading.Lock()
            )

            DOMAIN_LOCKS[
                domain
            ] = lock

        return lock


# ============================================================
# CONFIGURACIÓN DEL SMOKE
# ============================================================

def smoke_config(
    config: dict,
) -> dict:

    config = dict(
        config
    )

    config[
        "max_pages"
    ] = SMOKE_MAX_PAGES

    config[
        "max_depth"
    ] = SMOKE_MAX_DEPTH

    config[
        "max_files"
    ] = SMOKE_MAX_FILES

    # request_timeout NO se reemplaza:
    # cada fuente mantiene su valor real.

    config[
        "delay_seconds"
    ] = RANDOM_DELAY_MIN

    config[
        "random_delay_min"
    ] = RANDOM_DELAY_MIN

    config[
        "random_delay_max"
    ] = RANDOM_DELAY_MAX

    config[
        "discover_sitemaps"
    ] = True

    config[
        "max_sitemap_urls"
    ] = MAX_SITEMAP_URLS

    config[
        "discover_openapi_endpoints"
    ] = True

    config[
        "max_openapi_endpoints"
    ] = MAX_OPENAPI_ENDPOINTS

    config[
        "crawl_api_documentation"
    ] = True

    config[
        "api_pagination"
    ] = {
        "enabled": True,
        "max_pages": (
            API_PAGINATION_MAX_PAGES
        ),
    }

    return config


# ============================================================
# PRUEBA DE UNA FUENTE
# ============================================================

def test_one(
    config_path: Path,
) -> dict:

    from adapters import build_adapter

    from core.crawler import Crawler
    from core.file_detector import FileDetector
    from core.http_client import HttpClient

    from core.source_resolver import (
        SourceResolver,
        apply_source_resolution,
    )

    started = (
        time.monotonic()
    )

    config = smoke_config(
        load_config(
            config_path
        )
    )

    source_id = str(
        config.get(
            "id_fuente",
            config_path.stem,
        )
    )

    try:
        request_timeout = max(
            1,
            int(
                config.get(
                    "request_timeout",
                    10,
                )
            ),
        )

    except (
        TypeError,
        ValueError,
    ):
        request_timeout = 10

    ca_bundle = str(
        config.get(
            "ca_bundle",
            "",
        )
        or ""
    ).strip()

    try:

        with contextlib.redirect_stdout(
            io.StringIO()
        ):

            with HttpClient(
                timeout=(
                    request_timeout
                ),
                delay_seconds=(
                    RANDOM_DELAY_MIN
                ),
                random_delay_min=(
                    RANDOM_DELAY_MIN
                ),
                random_delay_max=(
                    RANDOM_DELAY_MAX
                ),
                verify_ssl=(
                    config_bool(
                        config.get(
                            "verify_ssl"
                        ),
                        True,
                    )
                ),
                ca_bundle=(
                    ca_bundle
                    or None
                ),
            ) as client:

                resolver = (
                    SourceResolver(
                        client
                    )
                )

                resolution = (
                    resolver.resolve(
                        config
                    )
                )

                attempts = list(
                    getattr(
                        resolution,
                        "attempts",
                        [],
                    )
                    or []
                )

                resolver_denied = any(
                    (
                        getattr(
                            attempt,
                            "status_code",
                            None,
                        )
                        == 403
                    )
                    or (
                        str(
                            getattr(
                                attempt,
                                "status",
                                "",
                            )
                        ).lower()
                        == "forbidden"
                    )
                    for attempt
                    in attempts
                )

                # Igual que main.py:
                # si el resolver no encuentra base, el crawler
                # todavía prueba entrypoints/APIs configurados.
                resolved_config = (
                    apply_source_resolution(
                        config,
                        resolution,
                    )
                )

                crawler = Crawler(
                    config=(
                        resolved_config
                    ),
                    client=client,
                    detector=(
                        FileDetector()
                    ),
                    adapter=(
                        build_adapter(
                            resolved_config
                        )
                    ),
                )

                result = (
                    crawler.crawl()
                )

        pages = len(
            result.pages
        )

        files = len(
            result.files
        )

        data = len(
            result.data_pages
        )

        errors = len(
            result.errors
        )

        api_probes = len(
            getattr(
                result,
                "api_probe_errors",
                [],
            )
            or []
        )

        resources = (
            files
            + data
        )

        stop_reason = str(
            result.stop_reason
        )

        if resources == 0:

            if pages > 0:
                status = "VACIO"

            elif resolver_denied:
                status = "DENEGADA"

            elif errors > 0:
                status = "INACCESIBLE"

            else:
                status = "VACIO"

        elif resources <= 3:
            status = "POBRE"

        elif stop_reason in {
            "max_pages",
            "max_files",
        }:
            status = "OK_LIMITE"

        elif errors > 0:
            status = "OK_ERROR"

        else:
            status = "OK"

        if resolution.final_url:

            if (
                resolution.used_fallback
            ):
                resolver_status = (
                    "fallback"
                )

            else:
                resolver_status = (
                    "ok"
                )

        else:
            resolver_status = (
                "sin_resolver"
            )

        return {
            "source": source_id,
            "status": status,
            "pages": pages,
            "files": files,
            "data": data,
            "errors": errors,
            "api_probes": api_probes,
            "stop": stop_reason,
            "seconds": round(
                time.monotonic()
                - started,
                1,
            ),
            "resolver": resolver_status,
            "fallback": bool(
                getattr(
                    resolution,
                    "used_fallback",
                    False,
                )
            ),
            "sitemap": int(
                getattr(
                    result,
                    "sitemap_urls_discovered",
                    0,
                )
                or 0
            ),
        }

    except Exception as exc:

        return {
            "source": source_id,
            "status": "ERROR",
            "pages": 0,
            "files": 0,
            "data": 0,
            "errors": 1,
            "api_probes": 0,
            "stop": (
                f"{type(exc).__name__}: "
                f"{str(exc)[:100]}"
            ),
            "seconds": round(
                time.monotonic()
                - started,
                1,
            ),
            "resolver": "error",
            "fallback": False,
            "sitemap": 0,
        }


# ============================================================
# SUBPROCESS
# ============================================================

def run_subprocess(
    config_path: Path,
    source_timeout: int,
) -> dict:

    with get_domain_lock(
        config_path
    ):

        try:

            process = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(
                        Path(
                            __file__
                        ).resolve()
                    ),
                    "--child",
                    str(
                        config_path
                    ),
                ],
                cwd=str(
                    BASE_DIR
                ),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=(
                    source_timeout
                ),
            )

        except subprocess.TimeoutExpired:

            return {
                "source": (
                    config_path.stem
                ),
                "status": "TIMEOUT",
                "pages": 0,
                "files": 0,
                "data": 0,
                "errors": 1,
                "api_probes": 0,
                "stop": (
                    f">{source_timeout}s"
                ),
                "seconds": float(
                    source_timeout
                ),
                "resolver": "?",
                "fallback": False,
                "sitemap": 0,
            }

    lines = [
        line.strip()
        for line
        in process.stdout.splitlines()
        if line.strip()
    ]

    if not lines:

        return {
            "source": (
                config_path.stem
            ),
            "status": "ERROR",
            "pages": 0,
            "files": 0,
            "data": 0,
            "errors": 1,
            "api_probes": 0,
            "stop": (
                process.stderr
                .strip()[:120]
                or "sin salida"
            ),
            "seconds": 0.0,
            "resolver": "error",
            "fallback": False,
            "sitemap": 0,
        }

    try:
        return json.loads(
            lines[-1]
        )

    except Exception:

        return {
            "source": (
                config_path.stem
            ),
            "status": "ERROR",
            "pages": 0,
            "files": 0,
            "data": 0,
            "errors": 1,
            "api_probes": 0,
            "stop": (
                "salida no interpretable"
            ),
            "seconds": 0.0,
            "resolver": "error",
            "fallback": False,
            "sitemap": 0,
        }


# ============================================================
# SALIDA
# ============================================================

def print_result(
    result: dict,
) -> None:

    print(
        f"[{result['status']:<11}] "
        f"{result['source']:<28} | "
        f"pag={result['pages']:>3} | "
        f"files={result['files']:>4} | "
        f"data={result['data']:>3} | "
        f"probe={result.get('api_probes', 0):>3} | "
        f"err={result['errors']:>2} | "
        f"resolver={result['resolver']:<12} | "
        f"stop={result['stop']:<18} | "
        f"{result['seconds']:>5.1f}s",
        flush=True,
    )


def run_parent(
    configs: list[Path],
    workers: int,
    source_timeout: int,
) -> None:

    print("=" * 110)
    print(
        "SMOKE TEST OFICIAL - CORE DEL CRAWLER"
    )
    print("=" * 110)

    print(
        f"Configuraciones:          "
        f"{len(configs)}"
    )

    print(
        f"Workers:                  "
        f"{workers}"
    )

    print(
        f"Máx páginas/fuente:       "
        f"{SMOKE_MAX_PAGES}"
    )

    print(
        f"Timeout proceso/fuente:   "
        f"{source_timeout}s"
    )

    print(
        "Timeout HTTP/TLS:         "
        "CONFIGURADO POR FUENTE"
    )

    print(
        "Mismo dominio:            "
        "SECUENCIAL"
    )

    print(
        "Genera output/trace:      "
        "NO"
    )

    print()

    results: list[dict] = []

    with ThreadPoolExecutor(
        max_workers=workers
    ) as executor:

        futures = {
            executor.submit(
                run_subprocess,
                config_path,
                source_timeout,
            ): config_path

            for config_path
            in configs
        }

        for future in as_completed(
            futures
        ):

            result = (
                future.result()
            )

            results.append(
                result
            )

            print_result(
                result
            )

    counts = Counter(
        item["status"]
        for item
        in results
    )

    print()
    print("=" * 110)
    print("RESUMEN")
    print("=" * 110)

    for status in (
        "OK",
        "OK_LIMITE",
        "OK_ERROR",
        "POBRE",
        "VACIO",
        "DENEGADA",
        "INACCESIBLE",
        "TIMEOUT",
        "ERROR",
    ):

        if counts.get(
            status
        ):
            print(
                f"{status:<12}: "
                f"{counts[status]}"
            )

    total_api_probes = sum(
        int(
            item.get(
                "api_probes",
                0,
            )
        )
        for item in results
    )

    print(
        f"Sondeos API fallidos:     "
        f"{total_api_probes}"
    )

    print()
    print("=" * 110)
    print(
        "FUENTES A REVISAR"
    )
    print("=" * 110)

    problematic = [
        item
        for item
        in results
        if item["status"]
        not in {
            "OK",
            "OK_LIMITE",
            "OK_ERROR",
        }
    ]

    if not problematic:

        print(
            "Ninguna."
        )

    else:

        for item in problematic:

            print_result(
                item
            )

    print()
    print(
        "OK_LIMITE = encontró recursos "
        "y el smoke lo cortó deliberadamente."
    )


# ============================================================
# MAIN
# ============================================================

def main() -> None:

    parser = argparse.ArgumentParser(
        description=(
            "Prueba rápida oficial del core. "
            "No genera output ni trace."
        )
    )

    parser.add_argument(
        "--source",
        help=(
            "Prueba una sola fuente."
        ),
    )

    parser.add_argument(
        "--workers",
        type=int,
        default=(
            DEFAULT_WORKERS
        ),
    )

    parser.add_argument(
        "--timeout",
        type=int,
        default=(
            DEFAULT_SOURCE_TIMEOUT
        ),
        help=(
            "Timeout máximo del proceso "
            "por fuente."
        ),
    )

    parser.add_argument(
        "--child",
        help=argparse.SUPPRESS,
    )

    args = parser.parse_args()

    if args.child:

        print(
            json.dumps(
                test_one(
                    Path(
                        args.child
                    )
                ),
                ensure_ascii=False,
            )
        )

        return

    if args.source:

        configs = [
            find_config(
                args.source
            )
        ]

    else:

        configs = (
            discover_configs()
        )

        if (
            len(configs)
            != EXPECTED_SOURCES
        ):

            print(
                "ADVERTENCIA: "
                f"se esperaban "
                f"{EXPECTED_SOURCES} "
                f"configs y hay "
                f"{len(configs)}."
            )

            print()

    workers = max(
        1,
        min(
            args.workers,
            len(configs),
        ),
    )

    run_parent(
        configs,
        workers,
        max(
            1,
            args.timeout,
        ),
    )


if __name__ == "__main__":
    main()