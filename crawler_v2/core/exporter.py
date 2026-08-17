from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from core.crawler import CrawlResult


def utc_now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def export_result(
    *,
    config: dict,
    result: CrawlResult,
    output_dir: Path,
) -> Path:
    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = (
        output_dir
        / f"{config['id_fuente']}.json"
    )

    payload = {
        "__meta__": {
            "schema_version": "2.2",

            "fuente": {
                "id_fuente": config[
                    "id_fuente"
                ],

                "nombre": config[
                    "nombre"
                ],

                "base_url": config[
                    "base_url"
                ],

                "entrypoints": config.get(
                    "entrypoints",
                    [],
                ),
            },

            "ejecucion": {
                "paginas_visitadas": len(
                    result.pages
                ),

                "archivos_encontrados": len(
                    result.files
                ),

                "errores": len(
                    result.errors
                ),

                "motivo_parada": (
                    result.stop_reason
                ),

                "duracion_segundos": round(
                    result.duration_seconds,
                    3,
                ),
            },

            "generado_utc": utc_now(),
        },

        "paginas": [
            asdict(page)
            for page in result.pages
        ],

        "archivos": [
            asdict(file)
            for file in result.files
        ],

        "datasets_web": [
            asdict(data_page)
            for data_page in result.data_pages
        ],

        "errores": result.errors,
    }

    temporary_path = (
        output_path.with_suffix(
            ".json.tmp"
        )
    )

    with temporary_path.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            payload,
            file,
            ensure_ascii=False,
            indent=2,
        )

    temporary_path.replace(
        output_path
    )

    return output_path