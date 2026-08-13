from __future__ import annotations

import argparse
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from adapters import build_adapter
from core.archive_inspector import ArchiveInspector
from core.exporter import export_source_map
from core.file_detector import FileDetector
from core.http_client import HttpClient
from core.navigator import NavigationResult, Navigator
from core.source_config import SourceConfig, load_source_config


BASE_DIR = Path(__file__).resolve().parent
SOURCES_DIR = BASE_DIR / "sources"
OUTPUT_DIR = BASE_DIR / "output"


def utc_iso() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Crawler genérico multi-fuente."
    )

    parser.add_argument(
        "source",
        nargs="?",
        help=(
            "ID de una fuente configurada. "
            "Ejemplos: asfi, aetn, bcb."
        ),
    )

    parser.add_argument(
        "--all",
        action="store_true",
        help="Ejecuta todas las fuentes configuradas.",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help=(
            "Muestra al finalizar todas las páginas "
            "y archivos encontrados."
        ),
    )

    parser.add_argument(
        "--fast-scan",
        action="store_true",
        help=(
            "Realiza una prueba rápida de descubrimiento. "
            "Detecta ZIP pero no los descarga ni inspecciona."
        ),
    )

    return parser.parse_args()


def available_sources() -> list[str]:
    return sorted(
        path.stem
        for path in SOURCES_DIR.glob(
            "*.json"
        )
    )


def resolve_config_path(
    source_id: str,
) -> Path:
    normalized = (
        source_id
        .strip()
        .lower()
    )

    if not normalized:
        raise ValueError(
            "El identificador de la fuente "
            "no puede estar vacío."
        )

    valid = all(
        character.isalnum()
        or character in {
            "_",
            "-",
        }
        for character in normalized
    )

    if not valid:
        raise ValueError(
            "Identificador de fuente inválido: "
            f"{source_id}"
        )

    config_path = (
        SOURCES_DIR
        / f"{normalized}.json"
    )

    if not config_path.exists():
        sources = ", ".join(
            available_sources()
        )

        raise FileNotFoundError(
            f"No existe configuración para "
            f"'{normalized}'. "
            f"Fuentes disponibles: {sources}"
        )

    return config_path


def print_configuration(
    config: SourceConfig,
    *,
    fast_scan: bool,
) -> None:
    print("=" * 80)
    print("CRAWLER MULTI-FUENTE")
    print("=" * 80)

    print(
        f"Fuente:             "
        f"{config.nombre}"
    )

    print(
        f"ID:                 "
        f"{config.id_fuente}"
    )

    print(
        f"URL base:           "
        f"{config.base_url}"
    )

    print(
        f"Entry points:       "
        f"{len(config.get_entrypoints())}"
    )

    print(
        f"Profundidad máxima: "
        f"{config.max_depth}"
    )

    print(
        f"Máximo páginas:     "
        f"{config.max_pages}"
    )

    print(
        f"Máximo archivos:    "
        f"{config.max_files}"
    )

    if fast_scan:
        print(
            "Modo:               FAST SCAN"
        )

        print(
            "Inspección ZIP:     NO "
            "(se detectan, no se descargan)"
        )

    else:
        print(
            "Modo:               COMPLETO"
        )

        print(
            f"Inspección ZIP:     "
            f"{config.inspect_zips}"
        )

    print()


def print_pages(
    result: NavigationResult,
) -> None:
    print()
    print("-" * 80)
    print("PÁGINAS VISITADAS")
    print("-" * 80)

    for index, page in enumerate(
        result.pages,
        start=1,
    ):
        print(
            f"[{index:04}] "
            f"d={page.depth} | "
            f"{page.url}"
        )


def print_files(
    result: NavigationResult,
) -> None:
    print()
    print("-" * 80)
    print("ARCHIVOS ENCONTRADOS")
    print("-" * 80)

    for index, item in enumerate(
        result.files,
        start=1,
    ):
        file_type = (
            item.file_type
            or "desconocido"
        )

        print(
            f"[{index:04}] "
            f"{file_type.upper():7} | "
            f"{item.url}"
        )


def count_zip_information(
    result: NavigationResult,
) -> tuple[int, int]:
    zip_count = 0
    zip_entries = 0

    for item in result.files:
        if item.file_type != "zip":
            continue

        zip_count += 1

        zip_entries += len(
            item.contenido_zip
        )

    return (
        zip_count,
        zip_entries,
    )


def print_summary(
    config: SourceConfig,
    result: NavigationResult,
    output_path: Path,
    duration_seconds: float,
    *,
    fast_scan: bool,
) -> None:
    print()
    print("=" * 80)
    print("RESUMEN")
    print("=" * 80)

    print(
        f"Fuente:              "
        f"{config.id_fuente}"
    )

    print(
        f"Páginas visitadas:   "
        f"{result.total_pages}"
    )

    print(
        f"Archivos encontrados:"
        f"{result.total_files:>5}"
    )

    print(
        f"Errores:              "
        f"{result.total_errors}"
    )

    print(
        f"Motivo de parada:     "
        f"{result.stop_reason or 'recorrido_finalizado'}"
    )

    print(
        f"Duración:             "
        f"{duration_seconds:.2f} s"
    )

    if result.files:
        counter = Counter(
            item.file_type
            or "desconocido"
            for item in result.files
        )

        print()
        print("Tipos encontrados:")

        for file_type, quantity in sorted(
            counter.items()
        ):
            print(
                f"  - "
                f"{file_type.upper():7}: "
                f"{quantity}"
            )

    zip_count, zip_entries = (
        count_zip_information(
            result
        )
    )

    if zip_count:
        print()
        print("ZIP:")

        print(
            f"  - ZIP detectados:       "
            f"{zip_count}"
        )

        if fast_scan:
            print(
                "  - Inspección interna:    "
                "omitida por FAST SCAN"
            )

        else:
            print(
                f"  - Archivos internos:    "
                f"{zip_entries}"
            )

    if result.errors:
        print()
        print(
            "Primeros errores:"
        )

        for error in result.errors[:10]:
            print(
                f"  - {error}"
            )

        if len(result.errors) > 10:
            print(
                f"  ... y "
                f"{len(result.errors) - 10} "
                "más."
            )

    print()

    print(
        f"JSON generado: "
        f"{output_path}"
    )


def run_source(
    source_id: str,
    *,
    verbose: bool,
    fast_scan: bool,
) -> tuple[
    SourceConfig,
    NavigationResult,
]:
    config_path = resolve_config_path(
        source_id
    )

    config = load_source_config(
        config_path
    )

    print_configuration(
        config,
        fast_scan=fast_scan,
    )

    print(
        "Iniciando recorrido real...",
        flush=True,
    )

    started_at = utc_iso()

    started_monotonic = (
        time.monotonic()
    )

    detector = FileDetector(
        config
    )

    adapter = build_adapter(
        config
    )

    with HttpClient(
        config
    ) as client:

        # FAST SCAN:
        # los ZIP se descubren pero no se descargan.
        if (
            config.inspect_zips
            and not fast_scan
        ):
            archive_inspector = (
                ArchiveInspector(
                    client
                )
            )

        else:
            archive_inspector = None

        navigator = Navigator(
            config=config,
            client=client,
            file_detector=detector,
            adapter=adapter,
            archive_inspector=archive_inspector,
        )

        result = navigator.crawl()

    duration_seconds = (
        time.monotonic()
        - started_monotonic
    )

    finished_at = utc_iso()

    output_path = export_source_map(
        config,
        result,
        output_dir=OUTPUT_DIR,
        started_at=started_at,
        finished_at=finished_at,
        duration_seconds=duration_seconds,
    )

    if verbose:
        print_pages(
            result
        )

        print_files(
            result
        )

    print_summary(
        config,
        result,
        output_path,
        duration_seconds,
        fast_scan=fast_scan,
    )

    return (
        config,
        result,
    )


def run_all_sources(
    *,
    verbose: bool,
    fast_scan: bool,
) -> None:
    sources = available_sources()

    if not sources:
        raise RuntimeError(
            "No existen fuentes configuradas."
        )

    print(
        f"Ejecutando {len(sources)} "
        "fuente(s)..."
    )

    successful = 0
    failed = 0

    results: list[
        dict[str, object]
    ] = []

    for index, source_id in enumerate(
        sources,
        start=1,
    ):
        print()
        print("#" * 80)

        print(
            f"[{index}/{len(sources)}] "
            f"{source_id.upper()}"
        )

        print("#" * 80)

        try:
            config, result = run_source(
                source_id,
                verbose=verbose,
                fast_scan=fast_scan,
            )

            successful += 1

            results.append(
                {
                    "fuente": config.id_fuente,
                    "paginas": result.total_pages,
                    "archivos": result.total_files,
                    "errores": result.total_errors,
                    "estado": "OK",
                }
            )

        except Exception as exc:
            failed += 1

            results.append(
                {
                    "fuente": source_id,
                    "paginas": 0,
                    "archivos": 0,
                    "errores": 1,
                    "estado": "ERROR",
                    "detalle": str(exc),
                }
            )

            print(
                f"ERROR EN {source_id}: "
                f"{exc}",
                flush=True,
            )

    print()
    print("=" * 80)
    print("RESULTADO GLOBAL")
    print("=" * 80)

    for row in results:
        print(
            f"{str(row['fuente']):<15} "
            f"| {str(row['estado']):<5} "
            f"| páginas={str(row['paginas']):<6} "
            f"| archivos={str(row['archivos']):<6} "
            f"| errores={row['errores']}"
        )

    print()

    print(
        f"Correctas: {successful}"
    )

    print(
        f"Con error: {failed}"
    )


def main() -> None:
    args = parse_arguments()

    if args.all:
        run_all_sources(
            verbose=args.verbose,
            fast_scan=args.fast_scan,
        )

        return

    source_id = (
        args.source
        or "asfi"
    )

    run_source(
        source_id,
        verbose=args.verbose,
        fast_scan=args.fast_scan,
    )


if __name__ == "__main__":
    main()