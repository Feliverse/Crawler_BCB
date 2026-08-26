from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from Crawler_BCB.Old_Files.crawler_multifuente.core.navigator import NavigationResult
from Crawler_BCB.Old_Files.crawler_multifuente.core.source_config import SourceConfig


SCHEMA_VERSION = "2.0"


def _utc_iso() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def normalize_key(
    value: str,
) -> str:

    value = unquote(
        value
    ).strip()

    normalized = unicodedata.normalize(
        "NFKD",
        value,
    )

    ascii_value = normalized.encode(
        "ascii",
        "ignore",
    ).decode(
        "ascii"
    )

    ascii_value = re.sub(
        r"[\s/\\:]+",
        "_",
        ascii_value,
    )

    ascii_value = re.sub(
        r"[^a-zA-Z0-9_.\-]",
        "",
        ascii_value,
    )

    return (
        ascii_value.strip("_")
        or "GENERAL"
    )


def filename_from_url(
    url: str,
    fallback: str,
) -> str:

    parsed = urlparse(
        url
    )

    filename = Path(
        unquote(parsed.path)
    ).name

    if filename:
        return filename

    return normalize_key(
        fallback
    )


def ensure_path(
    tree: dict[str, Any],
    path: tuple[str, ...],
) -> dict[str, Any]:

    node = tree

    normalized_path = (
        path
        if path
        else ("RAIZ",)
    )

    for segment in normalized_path:

        key = normalize_key(
            segment
        )

        child = node.get(
            key
        )

        if not isinstance(
            child,
            dict,
        ):
            child = {}
            node[key] = child

        node = child

    return node


def unique_file_key(
    container: dict[str, Any],
    filename: str,
    url: str,
) -> str:

    if filename not in container:
        return filename

    existing = container[
        filename
    ]

    if (
        isinstance(existing, dict)
        and existing.get(
            "url_descarga"
        ) == url
    ):
        return filename

    stem = Path(filename).stem
    suffix = Path(filename).suffix

    counter = 2

    while True:
        candidate = (
            f"{stem}__{counter}{suffix}"
        )

        if candidate not in container:
            return candidate

        counter += 1


def build_source_map(
    config: SourceConfig,
    result: NavigationResult,
    *,
    started_at: str,
    finished_at: str,
    duration_seconds: float,
) -> dict[str, Any]:

    tree: dict[str, Any] = {}

    tree["__meta__"] = {
        "schema_version": SCHEMA_VERSION,

        "fuente": {
            "id_fuente": config.id_fuente,
            "nombre": config.nombre,
            "base_url": config.base_url,
            "allowed_domains": list(
                config.allowed_domains
            ),
            "entrypoints": list(
                config.get_entrypoints()
            ),
        },

        "ejecucion": {
            "inicio_utc": started_at,
            "fin_utc": finished_at,
            "duracion_segundos": round(
                duration_seconds,
                3,
            ),
            "motivo_parada": (
                result.stop_reason
                or "recorrido_finalizado"
            ),
            "paginas_visitadas": (
                result.total_pages
            ),
            "archivos_encontrados": (
                result.total_files
            ),
            "errores": (
                result.total_errors
            ),
        },

        "generado_utc": _utc_iso(),
    }

    # Restauramos _listados.
    for page in result.pages:

        if not page.is_listing:
            continue

        node = ensure_path(
            tree,
            page.path,
        )

        listings = node.setdefault(
            "_listados",
            [],
        )

        if page.url not in listings:
            listings.append(
                page.url
            )

    # Restauramos DOCUMENTOS -> VARIOS.
    for discovered_file in result.files:

        node = ensure_path(
            tree,
            discovered_file.path,
        )

        documentos = node.setdefault(
            "DOCUMENTOS",
            {}
        )

        varios = documentos.setdefault(
            "VARIOS",
            {}
        )

        filename = filename_from_url(
            discovered_file.url,
            discovered_file.link_text
            or "archivo",
        )

        file_key = unique_file_key(
            varios,
            filename,
            discovered_file.url,
        )

        varios[file_key] = {
            # CAMPOS DEL CRAWLER ANTERIOR
            "descripcion": (
                discovered_file.link_text
                or filename
            ),

            "url_descarga": (
                discovered_file.url
            ),

            "fecha_actualizacion": (
                discovered_file.fecha_actualizacion
            ),

            "tipo_archivo": (
                discovered_file.file_type
            ),

            "contenido_zip": list(
                discovered_file.contenido_zip
            ),

            "pagina_origen": (
                discovered_file.source_page
            ),

            # CONTRATO NUEVO
            "id_fuente": (
                config.id_fuente
            ),

            "url_origen": (
                discovered_file.source_page
            ),

            "extension": (
                discovered_file.extension
            ),

            "fecha_primer_dato": None,
            "fecha_ultimo_dato": None,
            "periodicidad": None,

            "tags_auto": [],
            "tags_manual": [],

            "procesado": False,

            "metodo_deteccion": (
                discovered_file.detected_by
            ),
        }

    if result.errors:
        tree["__meta__"][
            "errores_detalle"
        ] = list(
            result.errors
        )

    return tree


def export_source_map(
    config: SourceConfig,
    result: NavigationResult,
    *,
    output_dir: str | Path,
    started_at: str,
    finished_at: str,
    duration_seconds: float,
) -> Path:

    directory = Path(
        output_dir
    )

    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = (
        directory
        / f"{config.id_fuente}.json"
    )

    temporary_path = (
        directory
        / f".{config.id_fuente}.json.tmp"
    )

    payload = build_source_map(
        config,
        result,
        started_at=started_at,
        finished_at=finished_at,
        duration_seconds=duration_seconds,
    )

    try:
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

            file.write("\n")

        os.replace(
            temporary_path,
            output_path,
        )

    finally:
        if temporary_path.exists():
            temporary_path.unlink()

    return output_path