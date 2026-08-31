from __future__ import annotations

import argparse
import csv
import json
import os
import re
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
OUTPUT_DIR = BASE_DIR / "output"
LOG_DIR = OUTPUT_DIR / "batch_logs"
MAIN_PATH = BASE_DIR / "main.py"

EXPECTED_SOURCES = 52

DEFAULT_WORKERS = 4
DEFAULT_SOURCE_TIMEOUT = 1800

TEMP_PREFIXES = (
    "full_",
    "retry_",
    "batch_",
    "temp_",
    "test_",
)

PRINT_LOCK = threading.Lock()
DOMAIN_LOCKS_LOCK = threading.Lock()
DOMAIN_LOCKS: dict[str, threading.Lock] = {}


# ============================================================
# CONFIGS
# ============================================================

def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8-sig") as file:
        return json.load(file)


def is_temporary_config(path: Path) -> bool:
    return path.stem.lower().startswith(TEMP_PREFIXES)


def discover_configs() -> list[Path]:
    configs: list[Path] = []

    for path in sorted(SOURCES_DIR.glob("*.json")):
        if is_temporary_config(path):
            continue

        try:
            config = load_config(path)
        except Exception:
            continue

        if not config.get("id_fuente"):
            continue

        if not config.get("base_url"):
            continue

        configs.append(path)

    return configs


def config_identity(path: Path) -> tuple[str, str]:
    config = load_config(path)

    return (
        path.stem.lower(),
        str(config.get("id_fuente", "")).strip().lower(),
    )


def find_config(source: str) -> Path:
    wanted = source.strip().lower()

    for path in discover_configs():
        stem, source_id = config_identity(path)

        if wanted in {stem, source_id}:
            return path

    raise SystemExit(
        f"No existe configuración permanente para '{source}'."
    )


def primary_domain(path: Path) -> str:
    try:
        config = load_config(path)
    except Exception:
        return path.stem.lower()

    urls = [
        str(config.get("base_url", "")).strip(),
        *[
            str(url).strip()
            for url in (config.get("entrypoints") or [])
            if url
        ],
    ]

    for url in urls:
        host = (urlparse(url).hostname or "").lower()

        if host.startswith("www."):
            host = host[4:]

        if host:
            return host

    return path.stem.lower()


def get_domain_lock(path: Path) -> threading.Lock:
    key = primary_domain(path)

    with DOMAIN_LOCKS_LOCK:
        lock = DOMAIN_LOCKS.get(key)

        if lock is None:
            lock = threading.Lock()
            DOMAIN_LOCKS[key] = lock

        return lock


# ============================================================
# MÉTRICAS JSON
# ============================================================

def collect_resources(node: object, resources: list[dict]) -> None:
    if not isinstance(node, dict):
        return

    if (
        isinstance(node.get("descripcion"), str)
        and isinstance(node.get("url_descarga"), str)
    ):
        resources.append(node)
        return

    for value in node.values():
        collect_resources(value, resources)


def inspect_output_json(output_path: Path) -> dict:
    empty = {
        "recursos_json": 0,
        "urls_unicas": 0,
        "duplicados_url": 0,
        "formatos": {},
        "apis_detectadas": 0,
        "api_urls_unicas": 0,
        "api_formatos": {},
        "sitio_con_api": False,
    }

    if not output_path.exists():
        return empty

    try:
        with output_path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except Exception:
        return empty

    resources: list[dict] = []
    collect_resources(
        payload.get("ESTADISTICAS", {}),
        resources,
    )

    urls = [
        str(item.get("url_descarga", "")).strip()
        for item in resources
        if str(item.get("url_descarga", "")).strip()
    ]

    counter: Counter[str] = Counter()
    api_counter: Counter[str] = Counter()
    api_urls: list[str] = []

    for item in resources:
        resource_type = str(
            item.get(
                "tipo_archivo",
                "DESCONOCIDO",
            )
            or "DESCONOCIDO"
        ).strip().upper()

        resource_kind = str(
            item.get(
                "tipo_recurso",
                "",
            )
            or ""
        ).strip().lower()

        is_api = (
            resource_type == "API"
            or resource_kind == "api"
        )

        if is_api:
            api_format = str(
                item.get(
                    "formato",
                    "",
                )
                or "DESCONOCIDO"
            ).strip().upper()

            resource_type = (
                f"API:{api_format}"
            )

            api_counter[
                api_format
            ] += 1

            api_url = str(
                item.get(
                    "url_descarga",
                    "",
                )
                or ""
            ).strip()

            if api_url:
                api_urls.append(
                    api_url
                )

        counter[resource_type] += 1

    return {
        "recursos_json": len(resources),
        "urls_unicas": len(set(urls)),
        "duplicados_url": len(urls) - len(set(urls)),
        "formatos": dict(sorted(counter.items())),
        "apis_detectadas": sum(api_counter.values()),
        "api_urls_unicas": len(set(api_urls)),
        "api_formatos": dict(sorted(api_counter.items())),
        "sitio_con_api": bool(api_counter),
    }


# ============================================================
# EXTRAER RESUMEN DE MAIN
# ============================================================

def extract_number(output: str, pattern: str) -> int:
    match = re.search(
        pattern,
        output,
        flags=re.IGNORECASE,
    )

    if not match:
        return 0

    try:
        return int(match.group(1))
    except ValueError:
        return 0


def extract_float(output: str, pattern: str) -> float:
    match = re.search(
        pattern,
        output,
        flags=re.IGNORECASE,
    )

    if not match:
        return 0.0

    try:
        return float(match.group(1))
    except ValueError:
        return 0.0


def extract_text(output: str, pattern: str) -> str:
    match = re.search(
        pattern,
        output,
        flags=re.IGNORECASE,
    )

    if not match:
        return ""

    return " ".join(
        match.group(1).split()
    ).strip()


# ============================================================
# CLASIFICAR
# ============================================================

def classify(
    *,
    timed_out: bool,
    returncode: int | None,
    stop_reason: str,
    crawler_errors: int,
    resources: int,
    console_output: str,
) -> tuple[str, str]:

    if timed_out:
        return "TIMEOUT", "La fuente excedió el timeout del batch."

    if returncode not in (0, None):
        return "ERROR", f"main.py terminó con código {returncode}."

    lowered = console_output.lower()

    if resources == 0 and (
        "http=403" in lowered
        or "forbidden" in lowered
    ):
        return "FUENTE_DENEGADA", "La fuente respondió HTTP 403."

    stop = stop_reason.lower().strip()

    if stop in {
        "max_pages",
        "max_files",
    }:
        return (
            "INCOMPLETO_LIMITE",
            f"Se alcanzó {stop_reason}.",
        )

    if resources == 0:
        return (
            "SIN_RECURSOS",
            "La ejecución terminó sin recursos catalogados.",
        )

    if crawler_errors > 0:
        return (
            "MAPEADO_CON_ERRORES",
            "Hay recursos, pero también errores parciales.",
        )

    if stop == "frontier_exhausted":
        return (
            "MAPEADO",
            "La frontera alcanzable se agotó sin errores.",
        )

    return (
        "REVISAR",
        "La fuente generó recursos, pero el motivo de parada requiere revisión.",
    )


# ============================================================
# EJECUCIÓN
# ============================================================

def should_echo(line: str, last_progress: list[float]) -> bool:
    text = line.strip()

    if not text:
        return False

    important = (
        "DATASETS=",
        "DATASET ACTUALIZADO",
        "OPENAPI",
        "API PAGINACION",
        "SITEMAP |",
        "Páginas visitadas:",
        "Archivos encontrados:",
        "Datasets web:",
        "Errores:",
        "Motivo de parada:",
        "JSON:",
        "Estado:",
        "Utilizada:",
        "Fallback:",
    )

    if any(token in text for token in important):
        return True

    if " t=" in text and " | pag=" in text and " | cola=" in text:
        now = time.monotonic()

        if now - last_progress[0] >= 5.0:
            last_progress[0] = now
            return True

    return False


def crawl_one(
    config_path: Path,
    position: int,
    total: int,
    source_timeout: int,
    full_mode: bool,
    max_pages: int | None,
    max_files: int | None,
    max_depth: int | None,
) -> dict:

    config = load_config(config_path)

    source_id = str(
        config.get(
            "id_fuente",
            config_path.stem,
        )
    )

    source_name = str(
        config.get(
            "nombre",
            source_id,
        )
    )

    domain = primary_domain(config_path)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    canonical_output = OUTPUT_DIR / f"{source_id}.json"
    log_path = LOG_DIR / f"{source_id}.log"

    # Nunca reutilizamos silenciosamente un JSON anterior.
    try:
        if canonical_output.exists():
            canonical_output.unlink()
    except OSError:
        pass

    with PRINT_LOCK:
        print()
        print("=" * 90)
        print(
            f"[{position}/{total}] INICIO "
            f"{source_id} | {domain}"
        )
        print("=" * 90)

    started = time.monotonic()

    timed_out = False
    returncode: int | None = None

    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["PYTHONUNBUFFERED"] = "1"

    command = [
        sys.executable,
        str(MAIN_PATH),
        source_id,
    ]

    if full_mode:
        command.append("--full")
    else:
        if max_pages is not None:
            command.extend(["--max-pages", str(max_pages)])

        if max_files is not None:
            command.extend(["--max-files", str(max_files)])

        if max_depth is not None:
            command.extend(["--max-depth", str(max_depth)])

    last_progress = [0.0]

    # Un solo crawler activo por sitio principal.
    with get_domain_lock(config_path):

        process: subprocess.Popen | None = None
        reader_thread: threading.Thread | None = None

        with log_path.open(
            "w",
            encoding="utf-8",
        ) as log_file:

            process = subprocess.Popen(
                command,
                cwd=str(BASE_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=environment,
            )

            def reader() -> None:
                assert process is not None
                assert process.stdout is not None

                for line in process.stdout:
                    log_file.write(line)
                    log_file.flush()

                    if should_echo(
                        line,
                        last_progress,
                    ):
                        with PRINT_LOCK:
                            print(
                                f"[{source_id}] "
                                f"{line.rstrip()}",
                                flush=True,
                            )

            reader_thread = threading.Thread(
                target=reader,
                daemon=True,
                name=f"reader-{source_id}",
            )

            reader_thread.start()

            try:
                returncode = process.wait(
                    timeout=source_timeout
                )

            except subprocess.TimeoutExpired:
                timed_out = True

                with PRINT_LOCK:
                    print(
                        f"[{source_id}] TIMEOUT "
                        f">{source_timeout}s",
                        flush=True,
                    )

                process.kill()
                returncode = process.wait(
                    timeout=30
                )

                log_file.write(
                    "\n[BATCH] TIMEOUT DE FUENTE\n"
                )
                log_file.flush()

            finally:
                reader_thread.join(
                    timeout=10
                )

    total_duration = (
        time.monotonic()
        - started
    )

    try:
        console_output = log_path.read_text(
            encoding="utf-8",
            errors="replace",
        )
    except Exception:
        console_output = ""

    pages = extract_number(
        console_output,
        r"Páginas visitadas:\s*(\d+)",
    )

    files = extract_number(
        console_output,
        r"Archivos encontrados:\s*(\d+)",
    )

    datasets = extract_number(
        console_output,
        r"Datasets web:\s*(\d+)",
    )

    errors = extract_number(
        console_output,
        r"Errores:\s*(\d+)",
    )

    crawler_duration = extract_float(
        console_output,
        r"Duración:\s*([\d.]+)",
    )

    stop_reason = extract_text(
        console_output,
        r"Motivo de parada:\s*([^\r\n]+)",
    )

    api_probe_errors = extract_number(
        console_output,
        r"API SONDEOS FALLIDOS\s*\|\s*total=(\d+)",
    )

    used_url = (
        extract_text(
            console_output,
            r"Utilizada:\s*([^\r\n]+)",
        )
        or extract_text(
            console_output,
            r"URL de trabajo:\s*([^\r\n]+)",
        )
    )

    fallback_text = extract_text(
        console_output,
        r"Fallback:\s*([^\r\n]+)",
    ).lower()

    metrics = inspect_output_json(
        canonical_output
    )

    status, detail = classify(
        timed_out=timed_out,
        returncode=returncode,
        stop_reason=stop_reason,
        crawler_errors=errors,
        resources=metrics["recursos_json"],
        console_output=console_output,
    )

    result = {
        "fuente": source_id,
        "nombre": source_name,
        "dominio": domain,
        "url_configurada": str(
            config.get(
                "base_url",
                "",
            )
        ),
        "url_utilizada": used_url,
        "uso_fallback": fallback_text in {
            "sí",
            "si",
            "yes",
            "true",
        },
        "paginas": pages,
        "archivos": files,
        "datasets": datasets,
        "recursos_json": metrics["recursos_json"],
        "urls_unicas": metrics["urls_unicas"],
        "duplicados_url": metrics["duplicados_url"],
        "formatos": metrics["formatos"],
        "apis_detectadas": metrics["apis_detectadas"],
        "api_urls_unicas": metrics["api_urls_unicas"],
        "api_formatos": metrics["api_formatos"],
        "sitio_con_api": metrics["sitio_con_api"],
        "api_sondeos_fallidos": api_probe_errors,
        "errores": errors,
        "motivo_parada": stop_reason,
        "duracion_crawler": crawler_duration,
        "duracion_total": round(
            total_duration,
            2,
        ),
        "returncode": returncode,
        "resultado": status,
        "detalle": detail,
        "json_output": (
            str(canonical_output)
            if canonical_output.exists()
            else ""
        ),
        "log_output": str(log_path),
    }

    with PRINT_LOCK:
        print(
            f"[{position}/{total}] FIN {source_id} | "
            f"{status} | pag={pages} | "
            f"files={files} | data={datasets} | "
            f"json={metrics['recursos_json']} | "
            f"api={metrics['apis_detectadas']} | "
            f"probe={api_probe_errors} | "
            f"err={errors} | "
            f"{total_duration:.1f}s",
            flush=True,
        )

    return result


# ============================================================
# RESUMEN
# ============================================================

def save_results(results: list[dict]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    json_path = (
        OUTPUT_DIR
        / "batch_resultados.json"
    )

    csv_path = (
        OUTPUT_DIR
        / "batch_resultados.csv"
    )

    with json_path.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            results,
            file,
            ensure_ascii=False,
            indent=2,
        )

    fieldnames = [
        "fuente",
        "nombre",
        "dominio",
        "url_configurada",
        "url_utilizada",
        "uso_fallback",
        "paginas",
        "archivos",
        "datasets",
        "recursos_json",
        "urls_unicas",
        "duplicados_url",
        "formatos",
        "apis_detectadas",
        "api_urls_unicas",
        "api_formatos",
        "sitio_con_api",
        "api_sondeos_fallidos",
        "errores",
        "motivo_parada",
        "duracion_crawler",
        "duracion_total",
        "returncode",
        "resultado",
        "detalle",
        "json_output",
        "log_output",
    ]

    with csv_path.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
            delimiter=";",
        )

        writer.writeheader()

        for item in results:
            row = dict(item)

            row["formatos"] = json.dumps(
                row.get(
                    "formatos",
                    {},
                ),
                ensure_ascii=False,
                sort_keys=True,
            )

            row["api_formatos"] = json.dumps(
                row.get(
                    "api_formatos",
                    {},
                ),
                ensure_ascii=False,
                sort_keys=True,
            )

            writer.writerow(row)


def print_summary(results: list[dict]) -> None:
    statuses = Counter(
        item["resultado"]
        for item in results
    )

    resources = sum(
        int(item.get("recursos_json", 0))
        for item in results
    )

    api_sources = sum(
        1
        for item in results
        if bool(
            item.get(
                "sitio_con_api",
                False,
            )
        )
    )

    api_endpoints = sum(
        int(
            item.get(
                "api_urls_unicas",
                0,
            )
        )
        for item in results
    )

    api_resources = sum(
        int(
            item.get(
                "apis_detectadas",
                0,
            )
        )
        for item in results
    )

    api_probe_errors = sum(
        int(
            item.get(
                "api_sondeos_fallidos",
                0,
            )
        )
        for item in results
    )

    print()
    print("=" * 90)
    print("RESUMEN FINAL")
    print("=" * 90)
    print(f"Fuentes:             {len(results)}")
    print(f"Recursos JSON:       {resources}")
    print(f"Fuentes con API:     {api_sources}")
    print(f"Endpoints API únicos:{api_endpoints:>7}")
    print(f"Recursos API:        {api_resources}")
    print(f"Sondeos API fallidos:{api_probe_errors:>7}")
    print()

    for status, total in sorted(statuses.items()):
        print(f"{status:<24} {total}")

    print()
    print("APIs detectadas por fuente:")

    api_items = [
        item
        for item in results
        if int(
            item.get(
                "apis_detectadas",
                0,
            )
        ) > 0
    ]

    if not api_items:
        print("  Ninguna.")
    else:
        for item in api_items:
            print(
                f"  {item['fuente']:<30} "
                f"endpoints={item.get('api_urls_unicas', 0):<4} "
                f"recursos={item.get('apis_detectadas', 0):<4} "
                f"formatos={item.get('api_formatos', {})}"
            )

    print()
    print("Sondeos API fallidos por fuente:")

    probe_items = [
        item
        for item in results
        if int(
            item.get(
                "api_sondeos_fallidos",
                0,
            )
        ) > 0
    ]

    if not probe_items:
        print("  Ninguno.")
    else:
        for item in probe_items:
            print(
                f"  {item['fuente']:<30} "
                f"sondeos_fallidos="
                f"{item.get('api_sondeos_fallidos', 0)}"
            )

    print()
    print("Fuentes no cerradas:")

    pending = [
        item
        for item in results
        if item["resultado"] != "MAPEADO"
    ]

    if not pending:
        print("  Ninguna.")
    else:
        for item in pending:
            print(
                f"  {item['fuente']:<30} "
                f"{item['resultado']:<22} "
                f"recursos={item['recursos_json']}"
            )


# ============================================================
# MAIN
# ============================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Batch oficial para ejecutar las "
            "configuraciones permanentes del crawler."
        )
    )

    parser.add_argument(
        "--source",
        help=(
            "Ejecuta una sola fuente por nombre "
            "de config o id_fuente."
        ),
    )

    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
    )

    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_SOURCE_TIMEOUT,
        help="Timeout máximo por fuente en segundos.",
    )

    parser.add_argument(
        "--full",
        action="store_true",
        help=(
            "Ejecuta main.py --full. Úsalo solo "
            "cuando realmente quieras eliminar "
            "max_pages/max_files/max_depth."
        ),
    )

    parser.add_argument(
        "--max-pages",
        type=int,
        help="Límite temporal de páginas por fuente.",
    )

    parser.add_argument(
        "--max-files",
        type=int,
        help="Límite temporal de archivos por fuente.",
    )

    parser.add_argument(
        "--max-depth",
        type=int,
        help="Límite temporal de profundidad por fuente.",
    )

    args = parser.parse_args()

    if args.max_pages is not None and args.max_pages < 1:
        parser.error("--max-pages debe ser >= 1")

    if args.max_files is not None and args.max_files < 1:
        parser.error("--max-files debe ser >= 1")

    if args.max_depth is not None and args.max_depth < 0:
        parser.error("--max-depth debe ser >= 0")

    if (
        args.full
        and (
            args.max_pages is not None
            or args.max_files is not None
            or args.max_depth is not None
        )
    ):
        parser.error(
            "--full no puede combinarse con límites temporales."
        )

    if args.source:
        configs = [
            find_config(
                args.source
            )
        ]
    else:
        configs = discover_configs()

        if len(configs) != EXPECTED_SOURCES:
            print(
                f"ADVERTENCIA: se esperaban "
                f"{EXPECTED_SOURCES} configuraciones "
                f"permanentes y hay {len(configs)}."
            )
            print()

    workers = max(
        1,
        min(
            int(args.workers),
            len(configs),
        ),
    )

    print("=" * 90)
    print("BATCH OFICIAL - CRAWLER")
    print("=" * 90)
    print(f"Fuentes:          {len(configs)}")
    print(f"Workers:          {workers}")
    print("Mismo dominio:    SECUENCIAL")
    print(f"Timeout/fuente:   {args.timeout}s")
    print(
        f"Modo:             "
        f"{'FULL' if args.full else 'CONFIGURADO'}"
    )
    print(f"Output:           {OUTPUT_DIR}")
    print()

    results: list[dict] = []

    with ThreadPoolExecutor(
        max_workers=workers
    ) as executor:

        future_map = {
            executor.submit(
                crawl_one,
                config_path,
                position,
                len(configs),
                args.timeout,
                args.full,
                args.max_pages,
                args.max_files,
                args.max_depth,
            ): config_path
            for position, config_path
            in enumerate(
                configs,
                start=1,
            )
        }

        for future in as_completed(
            future_map
        ):
            config_path = future_map[future]

            try:
                result = future.result()

            except Exception as exc:
                config = load_config(
                    config_path
                )

                source_id = str(
                    config.get(
                        "id_fuente",
                        config_path.stem,
                    )
                )

                result = {
                    "fuente": source_id,
                    "nombre": str(
                        config.get(
                            "nombre",
                            source_id,
                        )
                    ),
                    "dominio": primary_domain(
                        config_path
                    ),
                    "url_configurada": str(
                        config.get(
                            "base_url",
                            "",
                        )
                    ),
                    "url_utilizada": "",
                    "uso_fallback": False,
                    "paginas": 0,
                    "archivos": 0,
                    "datasets": 0,
                    "recursos_json": 0,
                    "urls_unicas": 0,
                    "duplicados_url": 0,
                    "formatos": {},
                    "apis_detectadas": 0,
                    "api_urls_unicas": 0,
                    "api_formatos": {},
                    "sitio_con_api": False,
                    "api_sondeos_fallidos": 0,
                    "errores": 1,
                    "motivo_parada": "batch_exception",
                    "duracion_crawler": 0.0,
                    "duracion_total": 0.0,
                    "returncode": None,
                    "resultado": "ERROR",
                    "detalle": (
                        f"{type(exc).__name__}: "
                        f"{exc}"
                    ),
                    "json_output": "",
                    "log_output": "",
                }

            results.append(result)

            results.sort(
                key=lambda item: item["fuente"]
            )

            # Guardado incremental.
            save_results(results)

    results.sort(
        key=lambda item: item["fuente"]
    )

    save_results(results)
    print_summary(results)

    print()
    print(
        f"Resumen JSON: "
        f"{OUTPUT_DIR / 'batch_resultados.json'}"
    )
    print(
        f"Resumen CSV : "
        f"{OUTPUT_DIR / 'batch_resultados.csv'}"
    )
    print(
        f"Logs        : "
        f"{LOG_DIR}"
    )


if __name__ == "__main__":
    main()