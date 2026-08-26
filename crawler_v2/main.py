from __future__ import annotations

import argparse
import json
import time

from collections import Counter
from pathlib import Path

from adapters import build_adapter

from core.crawler import Crawler
from core.exporter import export_result
from core.file_detector import FileDetector
from core.http_client import HttpClient

from core.source_resolver import (
    SourceResolver,
    apply_source_resolution,
)

from core.traceability import (
    STATUS_PROCESSED,
    STATUS_ERROR,
    Traceability,
)


BASE_DIR = Path(
    __file__
).resolve().parent

SOURCES_DIR = (
    BASE_DIR
    / "sources"
)

OUTPUT_DIR = (
    BASE_DIR
    / "output"
)

TRACE_DIR = (
    BASE_DIR
    / "trace"
)

TRACE_DATABASE = (
    TRACE_DIR
    / "crawler_trace.sqlite"
)


# ============================================================
# ARGUMENTOS
# ============================================================

def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description=(
            "Crawler V2 orientado a datos "
            "y documentos públicos."
        )
    )

    parser.add_argument(
        "source",
        help=(
            "Fuente a ejecutar. "
            "Ejemplo: asfi, bcb, att"
        ),
    )

    parser.add_argument(
        "--full",
        action="store_true",
        help=(
            "Elimina límites de páginas, "
            "archivos y profundidad."
        ),
    )

    parser.add_argument(
        "--max-pages",
        type=int,
        help="Límite temporal de páginas para esta ejecución.",
    )

    parser.add_argument(
        "--max-files",
        type=int,
        help="Límite temporal de archivos para esta ejecución.",
    )

    parser.add_argument(
        "--max-depth",
        type=int,
        help="Límite temporal de profundidad para esta ejecución.",
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

    return args


# ============================================================
# CONFIG
# ============================================================

def load_config(
    source_id: str,
) -> dict:

    source_id = (
        source_id
        .strip()
        .lower()
    )

    path = (
        SOURCES_DIR
        / f"{source_id}.json"
    )

    if not path.exists():

        raise FileNotFoundError(
            "No existe configuración para "
            f"'{source_id}': {path}"
        )

    with path.open(
        "r",
        encoding="utf-8-sig",
    ) as file:

        data = json.load(
            file
        )

    return data


def optional_float(
    value,
) -> float | None:

    if value is None:
        return None

    return float(
        value
    )


def optional_bool(
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


# ============================================================
# HTTP
# ============================================================

def build_http_client(
    config: dict,
) -> HttpClient:

    ca_bundle = str(
        config.get(
            "ca_bundle",
            "",
        )
        or ""
    ).strip()

    return HttpClient(
        timeout=int(
            config.get(
                "request_timeout",
                10,
            )
        ),

        delay_seconds=float(
            config.get(
                "delay_seconds",
                0.3,
            )
        ),

        random_delay_min=(
            optional_float(
                config.get(
                    "random_delay_min"
                )
            )
        ),

        random_delay_max=(
            optional_float(
                config.get(
                    "random_delay_max"
                )
            )
        ),

        verify_ssl=(
            optional_bool(
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
    )

def get_delay_range(
    config: dict,
) -> tuple[
    float,
    float,
]:

    delay = float(
        config.get(
            "delay_seconds",
            0.3,
        )
    )

    minimum = optional_float(
        config.get(
            "random_delay_min"
        )
    )

    maximum = optional_float(
        config.get(
            "random_delay_max"
        )
    )

    if minimum is None:

        minimum = max(
            0.0,
            delay,
        )

    if maximum is None:

        if delay > 0:

            maximum = (
                delay
                * 3
            )

        else:

            maximum = 0.0

    return (
        minimum,
        maximum,
    )


# ============================================================
# RESOLUCIÓN DE FUENTE
# ============================================================

def print_resolution(
    result,
) -> None:

    print()
    print(
        "Resolución de fuente:"
    )

    if not result.final_url:

        print(
            "  Estado: "
            "no se encontró URL alternativa utilizable"
        )

    else:

        print(
            f"  Original: "
            f"{result.original_url}"
        )

        print(
            f"  Utilizada: "
            f"{result.final_url}"
        )

        print(
            f"  Fallback: "
            f"{'sí' if result.used_fallback else 'no'}"
        )

    print(
        f"  Intentos: "
        f"{len(result.attempts)}"
    )

    for attempt in result.attempts:

        status_code = (
            attempt.status_code
            if attempt.status_code
            is not None
            else "-"
        )

        print(
            "    - "
            f"{attempt.status:14} | "
            f"HTTP={status_code} | "
            f"{attempt.url}"
        )


# ============================================================
# RESUMEN
# ============================================================

def print_summary(
    config: dict,
    result,
    output_path: Path,
) -> None:

    print()
    print("=" * 80)
    print("RESULTADO")
    print("=" * 80)

    print(
        f"Fuente:              "
        f"{config['id_fuente']}"
    )

    print(
        f"Páginas visitadas:   "
        f"{len(result.pages)}"
    )

    print(
        f"Archivos encontrados:"
        f"{len(result.files):>5}"
    )

    print(
        f"Datasets web:         "
        f"{len(result.data_pages)}"
    )

    print(
        f"Errores:              "
        f"{len(result.errors)}"
    )

    print(
        f"Sondeos API fallidos: "
        f"{len(getattr(result, 'api_probe_errors', []) or [])}"
    )

    print(
        f"Motivo de parada:     "
        f"{result.stop_reason}"
    )

    print(
        f"Duración:             "
        f"{result.duration_seconds:.2f} s"
    )

    print(
        f"Sitemaps procesados:  "
        f"{getattr(result, 'sitemap_documents', 0)}"
    )

    print(
        f"URLs por sitemap:     "
        f"{getattr(result, 'sitemap_urls_discovered', 0)}"
    )

    print(
        f"URLs sitemap en cola: "
        f"{getattr(result, 'sitemap_urls_queued', 0)}"
    )

    if result.errors:

        print()
        print(
            "Detalle de errores:"
        )

        max_error_details = 20

        for error in result.errors[
            :max_error_details
        ]:

            print(
                f"  - {error}"
            )

        remaining_errors = (
            len(result.errors)
            - max_error_details
        )

        if remaining_errors > 0:

            print(
                "  - "
                f"... {remaining_errors} "
                "errores adicionales "
                "no mostrados."
            )

    api_probe_errors = (
        getattr(
            result,
            "api_probe_errors",
            [],
        )
        or []
    )

    if api_probe_errors:

        print()
        print(
            "Sondeos API fallidos "
            "(diagnóstico, no error de fuente):"
        )

        max_probe_details = 10

        for error in api_probe_errors[
            :max_probe_details
        ]:

            print(
                f"  - {error}"
            )

        remaining_probes = (
            len(api_probe_errors)
            - max_probe_details
        )

        if remaining_probes > 0:

            print(
                "  - "
                f"... {remaining_probes} "
                "sondeos adicionales "
                "no mostrados."
            )

    if result.files:

        counter = Counter(
            file.tipo_archivo
            or "desconocido"

            for file
            in result.files
        )

        print()
        print(
            "Formatos:"
        )

        for (
            file_type,
            total,
        ) in sorted(
            counter.items()
        ):

            print(
                f"  - "
                f"{file_type.upper():7}: "
                f"{total}"
            )

    print()

    print(
        f"JSON: {output_path}"
    )


# ============================================================
# TRAZABILIDAD
# ============================================================

def print_traceability(
    execution_id: int,
    status: str,
) -> None:

    print()
    print(
        "Trazabilidad:"
    )

    print(
        f"  Ejecución: "
        f"{execution_id}"
    )

    print(
        f"  Estado:    "
        f"{status}"
    )

    print(
        f"  Base:      "
        f"{TRACE_DATABASE}"
    )


# ============================================================
# MAIN
# ============================================================

def main() -> None:

    args = parse_args()

    # ========================================================
    # CONFIGURACIÓN
    # ========================================================

    config = load_config(
        args.source
    )

    if args.full:

        config[
            "max_pages"
        ] = None

        config[
            "max_files"
        ] = None

        config[
            "max_depth"
        ] = None

    else:

        if args.max_pages is not None:
            config["max_pages"] = args.max_pages

        if args.max_files is not None:
            config["max_files"] = args.max_files

        if args.max_depth is not None:
            config["max_depth"] = args.max_depth

    # ========================================================
    # TRAZABILIDAD
    # ========================================================

    traceability = Traceability(
        TRACE_DATABASE
    )

    execution_id = (
        traceability
        .create_execution(
            source_id=str(
                config[
                    "id_fuente"
                ]
            ),

            configured_url=str(
                config.get(
                    "base_url",
                    "",
                )
            )
            or None,
        )
    )

    execution_started = (
        time.monotonic()
    )

    # Si todavía no ocurrió resolución,
    # mantenemos la configuración original.
    resolved_config = dict(
        config
    )

    # ========================================================
    # EJECUCIÓN
    # ========================================================

    try:

        minimum_delay, maximum_delay = (
            get_delay_range(
                config
            )
        )

        print("=" * 80)
        print("CRAWLER V2")
        print("=" * 80)

        print(
            f"Fuente: "
            f"{config['nombre']}"
        )

        print(
            f"URL configurada: "
            f"{config['base_url']}"
        )

        print(
            f"Timeout HTTP: "
            f"{config.get('request_timeout', 10)} s"
        )

        print(
            "Pausa HTTP:   "
            f"aleatoria "
            f"{minimum_delay:.2f}s - "
            f"{maximum_delay:.2f}s"
        )

        ca_bundle = str(
            config.get(
                "ca_bundle",
                "",
            )
            or ""
        ).strip()

        if ca_bundle:
            tls_text = (
                f"CA personalizada: "
                f"{ca_bundle}"
            )
        elif optional_bool(
            config.get(
                "verify_ssl"
            ),
            True,
        ):
            tls_text = "activa"
        else:
            tls_text = (
                "desactivada por configuración "
                "de la fuente"
            )

        print(
            f"Verificación TLS: "
            f"{tls_text}"
        )

        print()

        detector = (
            FileDetector()
        )

        # ====================================================
        # CLIENTE HTTP
        # ====================================================

        with build_http_client(
            config
        ) as client:

            # ================================================
            # RESOLVER URL
            # ================================================

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

            print_resolution(
                resolution
            )

            resolved_config = (
                apply_source_resolution(
                    config,
                    resolution,
                )
            )

            # ================================================
            # IN PROCESS
            # ================================================

            used_url = (
                resolution.final_url
                or resolved_config.get(
                    "base_url"
                )
            )

            traceability.mark_in_process(
                execution_id,

                used_url=(
                    str(
                        used_url
                    )
                    if used_url
                    else None
                ),

                used_fallback=bool(
                    resolution.used_fallback
                ),
            )

            print()

            print(
                f"URL de trabajo: "
                f"{resolved_config['base_url']}"
            )

            print(
                f"Seeds: "
                f"{len(resolved_config.get('entrypoints', []))}"
            )

            if args.full:

                print(
                    "Modo: FULL"
                )

                print(
                    "ADVERTENCIA: FULL elimina "
                    "max_pages, max_files y max_depth."
                )

            else:

                print(
                    f"Máx páginas: "
                    f"{resolved_config.get('max_pages')}"
                )

                print(
                    f"Máx archivos: "
                    f"{resolved_config.get('max_files')}"
                )

                print(
                    f"Máx profundidad: "
                    f"{resolved_config.get('max_depth')}"
                )

            print(
                "Sitemaps: "
                f"{'activo' if resolved_config.get('discover_sitemaps', True) else 'inactivo'}"
            )

            if resolved_config.get(
                "discover_sitemaps",
                True,
            ):
                print(
                    f"Máx URLs sitemap: "
                    f"{resolved_config.get('max_sitemap_urls', 10000)}"
                )

            print()

            # ================================================
            # ADAPTER
            # ================================================

            adapter = (
                build_adapter(
                    resolved_config
                )
            )

            # ================================================
            # CRAWLER
            # ================================================

            crawler = Crawler(
                config=resolved_config,
                client=client,
                detector=detector,
                adapter=adapter,
            )

            result = (
                crawler.crawl()
            )

        # ====================================================
        # EXPORT
        # ====================================================

        output_path = (
            export_result(
                config=resolved_config,
                result=result,
                output_dir=OUTPUT_DIR,
            )
        )

        # ====================================================
        # PROCESSED
        # ====================================================

        execution_duration = (
            time.monotonic()
            - execution_started
        )

        traceability.mark_processed(
            execution_id,

            pages=len(
                result.pages
            ),

            files=len(
                result.files
            ),

            datasets=len(
                result.data_pages
            ),

            errors=len(
                result.errors
            ),

            stop_reason=(
                result.stop_reason
            ),

            duration=(
                execution_duration
            ),
        )

        # ====================================================
        # RESUMEN
        # ====================================================

        print_summary(
            resolved_config,
            result,
            output_path,
        )

        print_traceability(
            execution_id,
            STATUS_PROCESSED,
        )

    # ========================================================
    # ERROR FATAL
    # ========================================================

    except Exception as exc:

        execution_duration = (
            time.monotonic()
            - execution_started
        )

        # Intentamos registrar el error sin ocultar
        # la excepción original si la propia BD fallara.
        try:

            traceability.mark_error(
                execution_id,

                message=(
                    f"{type(exc).__name__}: "
                    f"{exc}"
                ),

                duration=(
                    execution_duration
                ),
            )

        except Exception as trace_error:

            print()
            print(
                "ADVERTENCIA: "
                "no se pudo actualizar la trazabilidad:"
            )

            print(
                f"  {type(trace_error).__name__}: "
                f"{trace_error}"
            )

        print_traceability(
            execution_id,
            STATUS_ERROR,
        )

        # Conservamos el traceback real para poder
        # diagnosticar el problema.
        raise


if __name__ == "__main__":
    main()