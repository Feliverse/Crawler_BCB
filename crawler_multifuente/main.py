from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from core.file_detector import FileDetector
from core.http_client import HttpClient
from core.navigator import NavigationResult, Navigator
from core.source_config import SourceConfig, load_source_config


BASE_DIR = Path(__file__).resolve().parent
SOURCES_DIR = BASE_DIR / "sources"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Crawler genérico multi-fuente."
    )

    parser.add_argument(
        "source",
        nargs="?",
        default="asfi",
        help=(
            "Identificador de la fuente configurada en sources/. "
            "Ejemplos: asfi, aetn."
        ),
    )

    return parser.parse_args()


def resolve_config_path(source_id: str) -> Path:
    """
    Resuelve de forma segura el archivo JSON correspondiente
    a una fuente configurada.
    """
    normalized = source_id.strip().lower()

    if not normalized:
        raise ValueError(
            "El identificador de la fuente no puede estar vacío."
        )

    valid = all(
        character.isalnum() or character in {"_", "-"}
        for character in normalized
    )

    if not valid:
        raise ValueError(
            f"Identificador de fuente inválido: {source_id}"
        )

    config_path = SOURCES_DIR / f"{normalized}.json"

    if not config_path.exists():
        available_sources = sorted(
            path.stem
            for path in SOURCES_DIR.glob("*.json")
        )

        available_text = ", ".join(available_sources)

        raise FileNotFoundError(
            f"No existe configuración para '{normalized}'. "
            f"Fuentes disponibles: {available_text}"
        )

    return config_path


def print_configuration(config: SourceConfig) -> None:
    print("=" * 80)
    print("CRAWLER MULTI-FUENTE")
    print("=" * 80)

    print(f"Fuente:             {config.nombre}")
    print(f"ID:                 {config.id_fuente}")
    print(f"URL base:           {config.base_url}")
    print(f"Profundidad máxima: {config.max_depth}")
    print(f"Máximo páginas:     {config.max_pages}")
    print(f"Máximo archivos:    {config.max_files}")
    print(f"Pausa:              {config.delay_seconds} segundos")
    print(f"Timeout:             {config.request_timeout} segundos")
    print(f"Inspeccionar ZIP:    {config.inspect_zips}")

    print()


def print_pages(result: NavigationResult) -> None:
    print("-" * 80)
    print("PÁGINAS VISITADAS")
    print("-" * 80)

    if not result.pages:
        print("No se visitaron páginas HTML.")
        return

    for index, page in enumerate(
        result.pages,
        start=1,
    ):
        print(
            f"[{index:03}] "
            f"profundidad={page.depth} | "
            f"{page.url}"
        )

        if page.title:
            print(
                f"      título: {page.title}"
            )


def print_files(result: NavigationResult) -> None:
    print()
    print("-" * 80)
    print("ARCHIVOS ENCONTRADOS")
    print("-" * 80)

    if not result.files:
        print("No se encontraron archivos descargables.")
        return

    for index, file in enumerate(
        result.files,
        start=1,
    ):
        print(
            f"[{index:03}] "
            f"{(file.file_type or 'desconocido').upper():6} | "
            f"{file.url}"
        )

        if file.link_text:
            print(
                f"      texto: {file.link_text}"
            )

        if file.source_page:
            print(
                f"      origen: {file.source_page}"
            )

        print(
            f"      detección: {file.detected_by}"
        )


def print_summary(
    config: SourceConfig,
    result: NavigationResult,
) -> None:
    print()
    print("=" * 80)
    print("RESUMEN DE EJECUCIÓN")
    print("=" * 80)

    print(f"Fuente:              {config.id_fuente}")
    print(f"Páginas visitadas:   {result.total_pages}")
    print(f"Archivos encontrados:{result.total_files:>4}")
    print(f"Errores:              {result.total_errors}")
    print(
        f"Motivo de parada:     "
        f"{result.stop_reason or 'recorrido finalizado'}"
    )

    if result.files:
        type_counter = Counter(
            file.file_type or "desconocido"
            for file in result.files
        )

        print()
        print("Archivos por tipo:")

        for file_type, quantity in sorted(
            type_counter.items()
        ):
            print(
                f"  - {file_type.upper():6}: {quantity}"
            )

    if result.errors:
        print()
        print("Errores encontrados:")

        for index, error in enumerate(
            result.errors,
            start=1,
        ):
            print(
                f"  [{index}] {error}"
            )


def run_crawler(
    config: SourceConfig,
) -> NavigationResult:
    detector = FileDetector(
        config
    )

    with HttpClient(config) as client:
        navigator = Navigator(
            config=config,
            client=client,
            file_detector=detector,
        )

        return navigator.crawl()


def main() -> None:
    args = parse_arguments()

    config_path = resolve_config_path(
        args.source
    )

    config = load_source_config(
        config_path
    )

    print_configuration(
        config
    )

    print("Iniciando recorrido real...\n")

    result = run_crawler(
        config
    )

    print_pages(
        result
    )

    print_files(
        result
    )

    print_summary(
        config,
        result,
    )


if __name__ == "__main__":
    main()