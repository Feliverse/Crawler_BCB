from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from adapters import build_adapter
from core.crawler import Crawler
from core.exporter import export_result
from core.file_detector import FileDetector
from core.http_client import HttpClient


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

    return parser.parse_args()


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
        f"Motivo de parada:     "
        f"{result.stop_reason}"
    )

    print(
        f"Duración:             "
        f"{result.duration_seconds:.2f} s"
    )

    if result.files:
        counter = Counter(
            file.tipo_archivo
            or "desconocido"
            for file in result.files
        )

        print()
        print("Formatos:")

        for file_type, total in sorted(
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


def main() -> None:
    args = parse_args()

    config = load_config(
        args.source
    )

    if args.full:
        config["max_pages"] = None
        config["max_files"] = None
        config["max_depth"] = None

    print("=" * 80)
    print("CRAWLER V2")
    print("=" * 80)

    print(
        f"Fuente: {config['nombre']}"
    )

    print(
        f"URL:    {config['base_url']}"
    )

    print(
        f"Seeds:  "
        f"{len(config.get('entrypoints', []))}"
    )

    print()

    detector = FileDetector()

    adapter = build_adapter(
        config
    )

    with HttpClient(
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
    ) as client:

        crawler = Crawler(
            config=config,
            client=client,
            detector=detector,
            adapter=adapter,
        )

        result = crawler.crawl()

    output_path = export_result(
        config=config,
        result=result,
        output_dir=OUTPUT_DIR,
    )

    print_summary(
        config,
        result,
        output_path,
    )


if __name__ == "__main__":
    main()