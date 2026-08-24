from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
import threading
import time
import unicodedata
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse


# ============================================================
# CONFIGURACIÓN
# ============================================================

MAX_WORKERS = 6
MAX_PAGES = 250
MAX_DEPTH = 8
MAX_FILES = 30000

REQUEST_TIMEOUT = 12
CRAWLER_TIMEOUT = 360  # 6 minutos máximo por fuente

DELAY_SECONDS = 0.15
RANDOM_DELAY_MIN = 0.15
RANDOM_DELAY_MAX = 0.35

MAX_SITEMAP_URLS = 5000
MAX_OPENAPI_ENDPOINTS = 60
API_PAGINATION_MAX_PAGES = 10


SCRIPT_DIR = Path(__file__).resolve().parent
SOURCES_DIR = SCRIPT_DIR / "sources"
OUTPUT_DIR = SCRIPT_DIR / "output"
RETRY_MAP_DIR = OUTPUT_DIR / "retry_problematic_map"
RETRY_LOG_DIR = OUTPUT_DIR / "retry_problematic_logs"

MAIN_PATH = SCRIPT_DIR / "main.py"

PRINT_LOCK = threading.Lock()


# ============================================================
# FUENTES PROBLEMÁTICAS
# ============================================================
#
# No estamos repitiendo las fuentes que ya demostraron que el
# core navega correctamente y solo llegaron a max_pages/timeout.
#
# Aquí están los casos SIN_RECURSOS, FUENTE_DENEGADA y ERROR.
#
# Para dominios migrados se usa una URL alternativa oficial o
# un repositorio oficial relacionado con la fuente.
# ============================================================

TARGETS = [
    {
        "fuente": "BOLCEREALES",
        "institucion": "Bolsa de Cereales",
        "url_original": "https://www.bolsadecereales.com",
        "base_url": "https://www.bolsadecereales.com/datasets",
        "entrypoints": [
            "https://www.bolsadecereales.com/datasets",
            "https://www.bolsadecereales.com/estimaciones-informes",
            "https://www.bolsadecereales.com/estimaciones-monitoreo",
            "https://www.bolsadecereales.com/estudios-documentos-trabajo",
            "https://www.bolsadecereales.com/visualizacion-datos",
        ],
        "nota": "Se entra directamente por las secciones públicas de datos para evitar el 403 de la portada.",
    },
    {
        "fuente": "CADEXCO",
        "institucion": "Cámara de Exportadores de Cochabamba",
        "url_original": "https://www.cadexco.org.bo",
        "base_url": "https://cadexco.bo/",
        "entrypoints": ["https://cadexco.bo/"],
        "nota": "Dominio institucional actualizado.",
    },
    {
        "fuente": "CEPROBOL",
        "institucion": "Centro de Promoción Bolivia",
        "url_original": "https://www.ceprobol.gob.bo",
        "base_url": "https://produccion.gob.bo/",
        "entrypoints": ["https://produccion.gob.bo/"],
        "nota": "Fuente histórica/discontinuada; se prueba el ministerio sucesor como contingencia.",
    },
    {
        "fuente": "FAM",
        "institucion": "Federación de Asociaciones Municipales de Bolivia",
        "url_original": "https://www.fam.bo",
        "base_url": "https://fam.org.bo/",
        "entrypoints": [
            "https://fam.org.bo/",
            "https://fam.org.bo/marco-legal/",
        ],
        "nota": "Dominio institucional actualizado.",
    },
    {
        "fuente": "FDTA-Valles",
        "institucion": "Fundación para el Desarrollo Tecnológico Agropecuario de los Valles",
        "url_original": "https://www.icco.org",
        "base_url": "https://bibliotecavirtual.fundacionvalles.org/",
        "entrypoints": [
            "https://bibliotecavirtual.fundacionvalles.org/",
            "https://bibliotecavirtual.fundacionvalles.org/handle/123456789/4",
        ],
        "nota": "La URL del Excel apuntaba a ICCO. Se usa el repositorio oficial de Fundación Valles.",
    },
    {
        "fuente": "FEGASACRUZ",
        "institucion": "Federación de Ganaderos de Santa Cruz",
        "url_original": "https://www.fegasacruz.org.bo",
        "base_url": "https://fegasacruz.org/",
        "entrypoints": ["https://fegasacruz.org/"],
        "nota": "Dominio actual; la portada está en construcción pero se deja trabajar sitemap/enlaces históricos.",
    },
    {
        "fuente": "FIFA",
        "institucion": "Federación Internacional de Fútbol Asociación",
        "url_original": "https://www.fifa.com",
        "base_url": "https://inside.fifa.com/en/official-documents",
        "entrypoints": [
            "https://inside.fifa.com/en/official-documents",
            "https://inside.fifa.com/en/legal/documents",
            "https://inside.fifa.com/organisation/divisions/finances",
        ],
        "allowed_domains": ["fifa.com"],
        "nota": "La portada principal es muy dinámica; se entra por los repositorios oficiales de documentos.",
    },
    {
        "fuente": "FINRURAL/indicadores",
        "institucion": "FINRURAL Bolivia",
        "url_original": "https://www.finrural.bo",
        "base_url": "https://www.finrural.org.bo/",
        "entrypoints": [
            "https://www.finrural.org.bo/",
            "https://www.finrural.org.bo/reporte-financiero-mensual-instituciones-financieras-de-desarrollo/",
        ],
        "nota": "Dominio institucional actualizado y entrada directa al reporte financiero.",
    },
    {
        "fuente": "FMI",
        "institucion": "Fondo Monetario Internacional",
        "url_original": "https://www.imf.org",
        "base_url": "https://www.imf.org/external/datamapper/api/",
        "entrypoints": [
            "https://www.imf.org/external/datamapper/api/",
            "https://www.imf.org/external/datamapper/datasets",
        ],
        "api_endpoints": [
            {
                "url": "https://www.imf.org/external/datamapper/api/v1/indicators",
                "descripcion": "IMF DataMapper - Indicadores",
                "method": "GET",
                "documentation_url": "https://www.imf.org/external/datamapper/api/",
            },
            {
                "url": "https://www.imf.org/external/datamapper/api/v1/countries",
                "descripcion": "IMF DataMapper - Países",
                "method": "GET",
                "documentation_url": "https://www.imf.org/external/datamapper/api/",
            },
            {
                "url": "https://www.imf.org/external/datamapper/api/v1/regions",
                "descripcion": "IMF DataMapper - Regiones",
                "method": "GET",
                "documentation_url": "https://www.imf.org/external/datamapper/api/",
            },
            {
                "url": "https://www.imf.org/external/datamapper/api/v1/groups",
                "descripcion": "IMF DataMapper - Grupos",
                "method": "GET",
                "documentation_url": "https://www.imf.org/external/datamapper/api/",
            },
        ],
        "nota": "Se usa la API pública DataMapper en vez de la portada que respondió 403.",
    },
    {
        "fuente": "FUNDEMPRESA",
        "institucion": "Registro de Comercio de Bolivia",
        "url_original": "https://www.fundempresa.org.bo",
        "base_url": "https://www.seprec.gob.bo/",
        "entrypoints": ["https://www.seprec.gob.bo/"],
        "nota": "Fuente histórica; SEPREC se usa como contingencia/sucesor institucional.",
    },
    {
        "fuente": "IBCH",
        "institucion": "Instituto Boliviano del Cemento y el Hormigón",
        "url_original": "https://www.ibch.org.bo",
        "base_url": "https://www.ibch.com/",
        "entrypoints": [
            "https://www.ibch.com/",
            "https://www.ibch.com/about-us/",
        ],
        "nota": "Dominio institucional actualizado.",
    },
    {
        "fuente": "MEFP",
        "institucion": "Ministerio de Economía y Finanzas Públicas",
        "url_original": "https://www.economiayfinanzas.gob.bo",
        "base_url": "https://www.economiayfinanzas.gob.bo/",
        "entrypoints": ["https://www.economiayfinanzas.gob.bo/"],
        "nota": "Se reintenta con el core tolerante a errores y sitemap.",
    },
    {
        "fuente": "MHE",
        "institucion": "Ministerio de Hidrocarburos y Energías",
        "url_original": "https://www.hidrocarburos.gob.bo",
        "base_url": "https://www.mhe.gob.bo/",
        "entrypoints": [
            "https://www.mhe.gob.bo/",
            "https://www.mhe.gob.bo/marco-normativ/",
        ],
        "nota": "Se usa el dominio institucional actual.",
    },
    {
        "fuente": "SABSA",
        "institucion": "Servicios de Aeropuertos Bolivianos S.A.",
        "url_original": "https://www.sabsa.aero",
        "base_url": "https://naabol.gob.bo/",
        "entrypoints": [
            "https://naabol.gob.bo/",
            "https://naabol.gob.bo/manuales-tecnicos/",
            "https://naabol.gob.bo/psdi-y-pei/",
        ],
        "nota": "SABSA es histórica; NAABOL se usa como contingencia institucional actual.",
    },
    {
        "fuente": "SICOES",
        "institucion": "Sistema de Contrataciones Estatales",
        "url_original": "https://www.sicoes.gob.bo",
        "base_url": "https://www.sicoes.gob.bo/",
        "entrypoints": ["https://www.sicoes.gob.bo/"],
        "nota": "Se reintenta con sitemap; si sigue vacío será candidato a adapter específico.",
    },
    {
        "fuente": "SIGMA",
        "institucion": "Industria Farmacéutica Sigma",
        "url_original": "https://www.sigmacorp.com.bo",
        "base_url": "https://www.sigmacorp.com.bo/",
        "entrypoints": ["https://www.sigmacorp.com.bo/"],
        "nota": "Se reintenta con manejo de errores por URL y sitemap.",
    },
    {
        "fuente": "Statistics Denmark",
        "institucion": "Danmarks Statistik",
        "url_original": "https://www.dst.dk",
        "base_url": "https://www.dst.dk/en/Statistik/hjaelp-til-statistikbanken/api",
        "entrypoints": [
            "https://www.dst.dk/en/Statistik/hjaelp-til-statistikbanken/api",
            "https://www.dst.dk/en/Statistik/hjaelp-til-statistikbanken",
        ],
        "allowed_domains": ["dst.dk", "statbank.dk"],
        "api_endpoints": [
            {
                "url": "https://api.statbank.dk/v1/subjects?lang=en&format=JSON",
                "descripcion": "StatBank Denmark - Subjects",
                "method": "GET",
                "documentation_url": "https://www.dst.dk/en/Statistik/hjaelp-til-statistikbanken/api",
            },
            {
                "url": "https://api.statbank.dk/v1/tables?lang=en&format=JSON",
                "descripcion": "StatBank Denmark - Tables",
                "method": "GET",
                "documentation_url": "https://www.dst.dk/en/Statistik/hjaelp-til-statistikbanken/api",
            },
        ],
        "nota": "Se usa la API oficial StatBank para evitar depender del sitio HTML que dio error.",
    },
    {
        "fuente": "VIPFE",
        "institucion": "Viceministerio de Inversión Pública y Financiamiento Externo",
        "url_original": "https://www.vipfe.gob.bo",
        "base_url": "https://www.planificacion.gob.bo/institucion/vipfe/info",
        "entrypoints": [
            "https://www.planificacion.gob.bo/institucion/vipfe/info",
            "https://sisin.planificacion.gob.bo/",
        ],
        "allowed_domains": ["planificacion.gob.bo"],
        "nota": "VIPFE está integrado al portal de Planificación; se incluyen VIPFE y SISIN como entradas.",
    },
]


# ============================================================
# UTILIDADES
# ============================================================

def clean_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def slugify(value: str) -> str:
    text = unicodedata.normalize("NFKD", value)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text or "fuente"


def domains_from_target(target: dict) -> list[str]:
    configured = target.get("allowed_domains")
    if configured:
        return sorted({str(x).lower().strip() for x in configured if str(x).strip()})

    domains = set()

    for url in [target["base_url"], *target.get("entrypoints", [])]:
        hostname = (urlparse(url).hostname or "").lower().strip()

        if hostname.startswith("www."):
            hostname = hostname[4:]

        if hostname:
            domains.add(hostname)

    for api in target.get("api_endpoints", []):
        hostname = (urlparse(api["url"]).hostname or "").lower().strip()

        if hostname.startswith("www."):
            hostname = hostname[4:]

        if hostname:
            domains.add(hostname)

    return sorted(domains)


def collect_resources(node: object, resources: list[dict]) -> None:
    if not isinstance(node, dict):
        return

    if isinstance(node.get("descripcion"), str) and isinstance(
        node.get("url_descarga"), str
    ):
        resources.append(node)
        return

    for value in node.values():
        collect_resources(value, resources)


def inspect_output_json(path: Path) -> dict:
    if not path.exists():
        return {
            "recursos_json": 0,
            "urls_unicas": 0,
            "duplicados_url": 0,
            "formatos": {},
        }

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {
            "recursos_json": 0,
            "urls_unicas": 0,
            "duplicados_url": 0,
            "formatos": {},
        }

    resources: list[dict] = []
    collect_resources(payload.get("ESTADISTICAS", {}), resources)

    urls = [
        clean_text(item.get("url_descarga"))
        for item in resources
        if clean_text(item.get("url_descarga"))
    ]

    formats: Counter[str] = Counter()

    for item in resources:
        resource_type = clean_text(item.get("tipo_archivo", "DESCONOCIDO")).upper()

        if resource_type == "API":
            api_format = clean_text(item.get("formato")).upper()
            formats[f"API:{api_format or 'DESCONOCIDO'}"] += 1
        else:
            formats[resource_type or "DESCONOCIDO"] += 1

    return {
        "recursos_json": len(resources),
        "urls_unicas": len(set(urls)),
        "duplicados_url": len(urls) - len(set(urls)),
        "formatos": dict(sorted(formats.items())),
    }


def extract_number(output: str, pattern: str) -> int | None:
    match = re.search(pattern, output, re.IGNORECASE)

    if not match:
        return None

    try:
        return int(match.group(1))
    except ValueError:
        return None


def extract_float(output: str, pattern: str) -> float | None:
    match = re.search(pattern, output, re.IGNORECASE)

    if not match:
        return None

    try:
        return float(match.group(1))
    except ValueError:
        return None


def extract_text(output: str, pattern: str) -> str:
    match = re.search(pattern, output, re.IGNORECASE)
    return clean_text(match.group(1)) if match else ""


# ============================================================
# CONFIG TEMPORAL
# ============================================================

def create_config(target: dict, index: int) -> tuple[str, Path]:
    source_id = f"retry_{index:02d}_{slugify(target['fuente'])}"

    path = SOURCES_DIR / f"{source_id}.json"

    config = {
        "id_fuente": source_id,
        "nombre": target["institucion"],
        "base_url": target["base_url"],
        "allowed_domains": domains_from_target(target),
        "entrypoints": target.get("entrypoints", [target["base_url"]]),
        "auto_url_variants": True,

        "max_depth": MAX_DEPTH,
        "max_pages": MAX_PAGES,
        "max_files": MAX_FILES,

        "request_timeout": REQUEST_TIMEOUT,
        "delay_seconds": DELAY_SECONDS,
        "random_delay_min": RANDOM_DELAY_MIN,
        "random_delay_max": RANDOM_DELAY_MAX,

        "discover_sitemaps": True,
        "max_sitemap_urls": MAX_SITEMAP_URLS,

        "discover_openapi_endpoints": True,
        "crawl_api_documentation": True,
        "max_openapi_endpoints": MAX_OPENAPI_ENDPOINTS,

        "api_pagination": {
            "enabled": True,
            "max_pages": API_PAGINATION_MAX_PAGES,
        },
    }

    if target.get("api_endpoints"):
        config["api_endpoints"] = target["api_endpoints"]

    path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return source_id, path


# ============================================================
# CLASIFICAR
# ============================================================

def classify(
    *,
    timed_out: bool,
    returncode: int | None,
    stop_reason: str,
    errors: int,
    resources: int,
    console: str,
) -> tuple[str, str]:

    if timed_out:
        return "TIMEOUT", "Excedió el tiempo máximo del retry."

    if returncode not in (0, None):
        return "ERROR", f"main.py terminó con código {returncode}."

    if resources == 0 and (
        "HTTP=403" in console
        or "forbidden" in console.lower()
    ):
        return "FUENTE_DENEGADA", "La URL utilizada respondió 403."

    stop = stop_reason.lower().strip()

    if stop in {"max_pages", "max_files"}:
        return "FUNCIONA_LIMITE", f"Encontró recursos pero llegó a {stop_reason}."

    if resources == 0:
        return "SIGUE_SIN_RECURSOS", "Terminó sin recursos; requiere revisión específica."

    if errors > 0:
        return "FUNCIONA_CON_ERRORES", "Generó recursos pero tuvo errores parciales."

    if stop == "frontier_exhausted":
        return "RESUELTO", "Agotó la frontera alcanzable y generó recursos."

    return "FUNCIONA_REVISAR", "Generó recursos; revisar motivo de parada."


# ============================================================
# EJECUTAR
# ============================================================

def run_target(target: dict, index: int, total: int) -> dict:
    source_id = ""
    config_path: Path | None = None

    RETRY_MAP_DIR.mkdir(parents=True, exist_ok=True)
    RETRY_LOG_DIR.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()

    with PRINT_LOCK:
        print()
        print("=" * 80)
        print(f"[{index}/{total}] {target['fuente']}")
        print(f"Original: {target['url_original']}")
        print(f"Trabajo : {target['base_url']}")
        print(f"Motivo  : {target['nota']}")
        print("=" * 80)

    try:
        source_id, config_path = create_config(target, index)

        generated_output = OUTPUT_DIR / f"{source_id}.json"
        retry_output = RETRY_MAP_DIR / f"{index:02d}_{slugify(target['fuente'])}.json"
        log_path = RETRY_LOG_DIR / f"{index:02d}_{slugify(target['fuente'])}.log"

        if generated_output.exists():
            generated_output.unlink()

        timed_out = False
        returncode: int | None = None
        console = ""

        try:
            process = subprocess.run(
                [
                    sys.executable,
                    str(MAIN_PATH),
                    source_id,
                ],
                cwd=str(SCRIPT_DIR),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=CRAWLER_TIMEOUT,
            )

            returncode = process.returncode
            console = process.stdout + "\n" + process.stderr

        except subprocess.TimeoutExpired as exc:
            timed_out = True

            stdout = exc.stdout or ""
            stderr = exc.stderr or ""

            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", errors="replace")

            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", errors="replace")

            console = stdout + "\n" + stderr

        log_path.write_text(console, encoding="utf-8")

        if generated_output.exists():
            retry_output.write_bytes(generated_output.read_bytes())

        metrics = inspect_output_json(retry_output)

        pages = extract_number(console, r"Páginas visitadas:\s*(\d+)") or 0
        files = extract_number(console, r"Archivos encontrados:\s*(\d+)") or 0
        datasets = extract_number(console, r"Datasets web:\s*(\d+)") or 0
        errors = extract_number(console, r"Errores:\s*(\d+)") or 0
        duration = extract_float(console, r"Duración:\s*([\d.]+)") or 0.0
        stop_reason = extract_text(console, r"Motivo de parada:\s*([^\r\n]+)")

        sitemap_docs = extract_number(console, r"Sitemaps procesados:\s*(\d+)") or 0
        sitemap_urls = extract_number(console, r"URLs por sitemap:\s*(\d+)") or 0
        sitemap_queued = extract_number(console, r"URLs sitemap en cola:\s*(\d+)") or 0

        status, detail = classify(
            timed_out=timed_out,
            returncode=returncode,
            stop_reason=stop_reason,
            errors=errors,
            resources=metrics["recursos_json"],
            console=console,
        )

        result = {
            "fuente": target["fuente"],
            "institucion": target["institucion"],
            "url_original": target["url_original"],
            "url_prueba": target["base_url"],
            "nota": target["nota"],

            "paginas": pages,
            "archivos": files,
            "datasets": datasets,

            **metrics,

            "errores": errors,
            "motivo_parada": stop_reason,
            "duracion_crawler": duration,
            "duracion_total": round(time.monotonic() - started, 2),

            "sitemaps": sitemap_docs,
            "urls_sitemap": sitemap_urls,
            "urls_sitemap_en_cola": sitemap_queued,

            "resultado": status,
            "detalle": detail,

            "json_output": str(retry_output) if retry_output.exists() else "",
            "log_output": str(log_path),
        }

        with PRINT_LOCK:
            print(
                f"[{status}] {target['fuente']} | "
                f"pag={pages} | files={files} | data={datasets} | "
                f"json={metrics['recursos_json']} | err={errors} | "
                f"sitemap={sitemap_urls}"
            )

        return result

    except Exception as exc:
        return {
            "fuente": target["fuente"],
            "institucion": target["institucion"],
            "url_original": target["url_original"],
            "url_prueba": target["base_url"],
            "nota": target["nota"],
            "paginas": 0,
            "archivos": 0,
            "datasets": 0,
            "recursos_json": 0,
            "urls_unicas": 0,
            "duplicados_url": 0,
            "formatos": {},
            "errores": 0,
            "motivo_parada": "",
            "duracion_crawler": 0.0,
            "duracion_total": round(time.monotonic() - started, 2),
            "sitemaps": 0,
            "urls_sitemap": 0,
            "urls_sitemap_en_cola": 0,
            "resultado": "ERROR_RETRY",
            "detalle": f"{type(exc).__name__}: {exc}",
            "json_output": "",
            "log_output": "",
        }

    finally:
        if config_path and config_path.exists():
            try:
                config_path.unlink()
            except OSError:
                pass


# ============================================================
# GUARDAR
# ============================================================

def save_results(results: list[dict]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    json_path = OUTPUT_DIR / "retry_problematic_resultados.json"
    csv_path = OUTPUT_DIR / "retry_problematic_resultados.csv"

    json_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    fields = [
        "fuente",
        "institucion",
        "url_original",
        "url_prueba",
        "nota",
        "paginas",
        "archivos",
        "datasets",
        "recursos_json",
        "urls_unicas",
        "duplicados_url",
        "formatos",
        "errores",
        "motivo_parada",
        "duracion_crawler",
        "duracion_total",
        "sitemaps",
        "urls_sitemap",
        "urls_sitemap_en_cola",
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
        writer = csv.DictWriter(file, fieldnames=fields, delimiter=";")
        writer.writeheader()

        for row in results:
            output = dict(row)
            output["formatos"] = json.dumps(
                output.get("formatos", {}),
                ensure_ascii=False,
            )
            writer.writerow(output)

    print()
    print(f"JSON: {json_path}")
    print(f"CSV : {csv_path}")


# ============================================================
# MAIN
# ============================================================

def main() -> None:
    print("=" * 80)
    print("RETRY RÁPIDO - FUENTES PROBLEMÁTICAS")
    print("=" * 80)
    print(f"Fuentes: {len(TARGETS)}")
    print(f"Paralelismo: {MAX_WORKERS}")
    print(f"Máx páginas: {MAX_PAGES}")
    print(f"Máx profundidad: {MAX_DEPTH}")
    print(f"Timeout por fuente: {CRAWLER_TIMEOUT}s")
    print()

    results: list[dict] = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_map = {
            executor.submit(
                run_target,
                target,
                index,
                len(TARGETS),
            ): target
            for index, target in enumerate(TARGETS, start=1)
        }

        for future in as_completed(future_map):
            results.append(future.result())

    order = {
        target["fuente"]: index
        for index, target in enumerate(TARGETS)
    }

    results.sort(
        key=lambda item: order.get(item["fuente"], 9999)
    )

    save_results(results)

    counts = Counter(item["resultado"] for item in results)

    print()
    print("=" * 80)
    print("RESUMEN")
    print("=" * 80)

    for status, total in sorted(counts.items()):
        print(f"{status:<25} {total}")

    print()
    print("Siguiente paso:")
    print("  pásame output/retry_problematic_resultados.json")
    print("  y solo hacemos adapters para los que SIGAN vacíos.")


if __name__ == "__main__":
    main()