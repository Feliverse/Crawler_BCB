from __future__ import annotations

import json
import re

from dataclasses import asdict
from pathlib import Path
from urllib.parse import unquote, urlparse

from core.crawler import CrawlResult


# ============================================================
# NORMALIZACIÓN DE NOMBRES
# ============================================================

def normalize_key(
    value: object,
    fallback: str = "SIN_NOMBRE",
) -> str:
    """
    Normaliza un texto para utilizarlo como llave dentro
    del árbol JSON.

    Mantiene letras, números, acentos y signos útiles,
    pero reemplaza espacios y separadores por "_".
    """

    text = unquote(
        str(value or "")
    ).strip()

    if not text:
        text = fallback

    text = re.sub(
        r"[\s/\\:]+",
        "_",
        text,
    )

    text = re.sub(
        r"_+",
        "_",
        text,
    )

    text = text.strip(
        "._- "
    )

    return text or fallback


# ============================================================
# NOMBRE DEL DOCUMENTO FINAL
# ============================================================

def build_leaf_name(
    *,
    description: str,
    url: str,
    fallback: str = "RECURSO",
) -> str:
    """
    El estándar utilizado por el crawler BCB representa
    cada recurso final mediante una llave terminada en .csv,
    aunque la URL real pueda apuntar a PDF, XLSX, JSON, etc.

    La extensión .csv pertenece al identificador jerárquico,
    NO modifica la URL real del recurso.
    """

    parsed = urlparse(
        url or ""
    )

    filename = unquote(
        Path(
            parsed.path
        ).name
    ).strip()

    if filename:
        base_name = filename.rsplit(
            ".",
            1,
        )[0]

    else:
        base_name = (
            description
            or fallback
        )

    normalized = normalize_key(
        base_name,
        fallback=fallback,
    )

    return f"{normalized}.csv"


# ============================================================
# EVITAR SOBREESCRITURA DE RECURSOS
# ============================================================

def unique_leaf_name(
    container: dict,
    desired_name: str,
) -> str:
    """
    Si dos recursos terminan generando la misma llave,
    agrega un sufijo incremental para no perder ninguno.
    """

    if desired_name not in container:
        return desired_name

    if desired_name.lower().endswith(
        ".csv"
    ):
        base = desired_name[:-4]
        extension = ".csv"

    else:
        base = desired_name
        extension = ""

    counter = 2

    while True:
        candidate = (
            f"{base}_{counter}"
            f"{extension}"
        )

        if candidate not in container:
            return candidate

        counter += 1


# ============================================================
# NORMALIZAR RUTA JERÁRQUICA
# ============================================================

def normalize_route(
    route: object,
) -> list[str]:
    """
    Convierte la ruta interna del crawler en ramas válidas
    para el árbol jerárquico.

    También evita generar:

        ESTADISTICAS
            └── ESTADISTICAS
    """

    if not isinstance(
        route,
        (list, tuple),
    ):
        return []

    normalized_route: list[str] = []

    for item in route:

        value = normalize_key(
            item,
            fallback="",
        )

        if not value:
            continue

        if (
            value.upper()
            == "ESTADISTICAS"
        ):
            continue

        if (
            normalized_route
            and normalized_route[-1]
            == value
        ):
            continue

        normalized_route.append(
            value
        )

    return normalized_route


# ============================================================
# CREAR RAMAS
# ============================================================

def ensure_path(
    root: dict,
    path: list[str],
) -> dict:
    """
    Crea recursivamente una ruta dentro del árbol y devuelve
    el último nodo.
    """

    current = root

    for key in path:

        if key not in current:
            current[key] = {}

        existing = current[key]

        if not isinstance(
            existing,
            dict,
        ):
            current[key] = {}

        current = current[key]

    return current


# ============================================================
# FECHAS
# ============================================================

def normalize_date_value(
    value: object,
) -> str:
    """
    El visor BCB considera 'No disponible' como ausencia
    de fecha.
    """

    if value is None:
        return "No disponible"

    text = str(
        value
    ).strip()

    if not text:
        return "No disponible"

    return text


# ============================================================
# ARCHIVOS DESCARGABLES
# ============================================================

def add_file_to_tree(
    statistics_root: dict,
    file_record: object,
) -> None:

    data = asdict(
        file_record
    )

    description = str(
        data.get(
            "descripcion",
            "",
        )
        or ""
    ).strip()

    download_url = str(
        data.get(
            "url_descarga",
            "",
        )
        or ""
    ).strip()

    origin_url = str(
        data.get(
            "url_origen",
            "",
        )
        or ""
    ).strip()

    file_type = str(
        data.get(
            "tipo_archivo",
            "",
        )
        or ""
    ).strip()

    update_date = normalize_date_value(
        data.get(
            "fecha_actualizacion"
        )
    )

    route = normalize_route(
        data.get(
            "ruta",
            [],
        )
    )

    # --------------------------------------------------------
    # Si el crawler pudo determinar la jerarquía,
    # la respetamos.
    #
    # Si no existe ruta, utilizamos el mismo fallback
    # conceptual del crawler BCB.
    # --------------------------------------------------------

    if route:
        destination_path = route

    else:
        destination_path = [
            "OTROS",
            "DOCUMENTOS_GENERALES",
            "VARIOS",
        ]

    destination = ensure_path(
        statistics_root,
        destination_path,
    )

    leaf_name = build_leaf_name(
        description=description,
        url=download_url,
        fallback="DOCUMENTO",
    )

    leaf_name = unique_leaf_name(
        destination,
        leaf_name,
    )

    leaf = {
        "descripcion": (
            description
            or leaf_name[:-4]
        ),

        "url_descarga": download_url,

        "fecha_actualizacion": (
            update_date
        ),

        "tipo_archivo": (
            file_type.upper()
            if file_type
            else "DESCONOCIDO"
        ),

        "url_origen": (
            origin_url
            or download_url
        ),
    }

    # --------------------------------------------------------
    # ZIP
    # --------------------------------------------------------

    zip_content = data.get(
        "contenido_zip"
    )

    if zip_content:
        leaf[
            "contenido_zip"
        ] = zip_content

    destination[
        leaf_name
    ] = leaf


# ============================================================
# DATASETS / TABLAS / APIs / CONSULTAS WEB
# ============================================================

def add_dataset_to_tree(
    statistics_root: dict,
    data_record: object,
) -> None:

    data = asdict(
        data_record
    )

    description = str(
        data.get(
            "descripcion",
            "",
        )
        or ""
    ).strip()

    dataset_url = str(
        data.get(
            "url",
            "",
        )
        or data.get(
            "url_descarga",
            "",
        )
        or ""
    ).strip()

    origin_url = str(
        data.get(
            "url_origen",
            "",
        )
        or ""
    ).strip()

    reference_date = (
        data.get(
            "fecha_referencia"
        )
    )

    if reference_date is None:
        reference_date = data.get(
            "fecha_actualizacion"
        )

    update_date = normalize_date_value(
        reference_date
    )

    route = normalize_route(
        data.get(
            "ruta",
            [],
        )
    )

    # --------------------------------------------------------
    # Los datasets web siguen la misma idea del BCB:
    #
    # REPORTE_Y_CONSULTAS
    #     └── CONTENIDO_WEB
    # --------------------------------------------------------

    if route:
        destination_path = [
            *route,
            "REPORTE_Y_CONSULTAS",
            "CONTENIDO_WEB",
        ]

    else:
        destination_path = [
            "OTROS",
            "REPORTE_Y_CONSULTAS",
            "CONTENIDO_WEB",
        ]

    destination = ensure_path(
        statistics_root,
        destination_path,
    )

    leaf_name = build_leaf_name(
        description=description,
        url="",
        fallback="DATASET_WEB",
    )

    leaf_name = unique_leaf_name(
        destination,
        leaf_name,
    )

    leaf = {
        "descripcion": (
            description
            or leaf_name[:-4]
        ),

        # ----------------------------------------------------
        # IMPORTANTE:
        #
        # El frontend existente exige url_descarga,
        # aunque sea una página HTML/API.
        # ----------------------------------------------------

        "url_descarga": dataset_url,

        "fecha_actualizacion": (
            update_date
        ),

        "tipo_archivo": "WEB",

        "url_origen": (
            origin_url
            or dataset_url
        ),
    }

    # --------------------------------------------------------
    # Metadata adicional.
    # El visor BCB la ignorará si no la necesita,
    # pero otros robots podrán utilizarla.
    # --------------------------------------------------------

    optional_fields = (
        "metodo_deteccion",
        "tiene_tabla_html",
        "tablas_detectadas",
        "permite_exportar",
        "tiene_filtros",
    )

    for field_name in optional_fields:

        value = data.get(
            field_name
        )

        if value is not None:
            leaf[
                field_name
            ] = value

    destination[
        leaf_name
    ] = leaf


# ============================================================
# EXPORTADOR PRINCIPAL
# ============================================================

def export_result(
    *,
    config: dict,
    result: CrawlResult,
    output_dir: Path,
) -> Path:
    """
    Exporta el resultado utilizando el estándar jerárquico
    definido por el crawler BCB de referencia.

    SALIDA:

    {
        "ESTADISTICAS": {
            "...": {
                "...": {
                    "Documento.csv": {
                        "descripcion": "...",
                        "url_descarga": "..."
                    }
                }
            }
        }
    }

    Ya no se exportan como raíz:

        __meta__
        paginas
        archivos
        datasets_web
        errores

    Esa información sigue existiendo durante la ejecución
    del crawler y continúa mostrándose en consola.
    """

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = (
        output_dir
        / f"{config['id_fuente']}.json"
    )

    # ========================================================
    # RAÍZ ESTÁNDAR
    # ========================================================

    payload: dict = {
        "ESTADISTICAS": {}
    }

    statistics_root = payload[
        "ESTADISTICAS"
    ]

    # ========================================================
    # ARCHIVOS
    # ========================================================

    for file_record in result.files:

        add_file_to_tree(
            statistics_root,
            file_record,
        )

    # ========================================================
    # DATASETS WEB
    # ========================================================

    for data_record in result.data_pages:

        add_dataset_to_tree(
            statistics_root,
            data_record,
        )

    # ========================================================
    # ESCRITURA ATÓMICA
    # ========================================================

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
            indent=4,
        )

    temporary_path.replace(
        output_path
    )

    return output_path