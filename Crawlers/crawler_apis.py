"""
Crawler de fuentes que publican via API en lugar de HTML.

Complemento de `crawler_universal.py`. La investigacion sobre las fuentes asignadas
mostro que varias no exponen sus archivos en el HTML (SPAs, visores JS, portales de
datos): el mapa real esta en un API JSON. Este modulo consume esos APIs y emite el
mismo JSON jerarquico de 5 niveles del contrato comun, un archivo por fuente.

Fuentes cubiertas y via verificada:
  fmi    DataMapper API (www.imf.org/external/datamapper/api/v1) — 132 indicadores.
         El 403 de Akamai se evita enviando el set completo de headers de navegador.
  bm     Documents & Reports API (search.worldbank.org/api/v2/wds) — ~3.400 documentos
         de Bolivia con pdfurl directo. El CDN rechaza HEAD: no se resuelve tamaño.
  dst    Statbank API (api.statbank.dk/v1/tables) — 2.315 tablas con fecha de
         actualizacion y periodicidad deducible del formato de los periodos.
  anapo  API de medios de WordPress (wp-json/wp/v2/media) — 329 archivos vivos.
         El sitio migro y dejo el HTML sin enlaces: los PDF se sirven por visor JS.
  cepal  API REST del repositorio DSpace (repositorio.cepal.org/server/api) —
         66.072 items; se indexan los mas recientes hasta un tope configurable.

Uso:
    python Crawlers/crawler_apis.py                 # todas
    python Crawlers/crawler_apis.py fmi anapo       # solo las indicadas
"""

import sys
import os
import re
import json
import time
import requests

from crawler_aps import normalizar_nombre, insertar_hoja

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

DIRECTORIO = os.path.dirname(os.path.abspath(__file__))
SALIDA = os.path.join(DIRECTORIO, "salida")

PAUSA = 0.4

# Set completo de cabeceras de navegador: con User-Agent solo, Akamai (FMI) devuelve 403
HEADERS_NAVEGADOR = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
    'Sec-Ch-Ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    'Sec-Ch-Ua-Mobile': '?0',
    'Sec-Ch-Ua-Platform': '"Windows"',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1',
    'Upgrade-Insecure-Requests': '1',
}

# Tope de items para el repositorio de CEPAL (tiene 66.072; se indexan los recientes)
CEPAL_TOPE_ITEMS = 500


def obtener_json(url, intentos=2):
    for intento in range(intentos):
        try:
            r = requests.get(url, headers=HEADERS_NAVEGADOR, timeout=60)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        time.sleep(1.5)
    return None


def hoja_base(descripcion, url_descarga, fecha, tipo, id_fuente, url_origen,
              emisor, periodicidad, tags, tamanio=None):
    hoja = {
        "descripcion": descripcion,
        "url_descarga": url_descarga,
        "fecha_actualizacion": fecha,
        "fecha_ultimo_dato": fecha,
        "tipo_archivo": tipo,
        "id_fuente": id_fuente,
        "url_origen": url_origen,
        "entidad_emisora": emisor,
        "periodicidad": periodicidad,
        "tags": sorted(tags),
    }
    if tamanio:
        hoja["tamanio_bytes"] = tamanio
    return hoja


def fecha_iso(valor):
    if not valor or not isinstance(valor, str):
        return None
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})', valor)
    if m:
        return m.group(0)
    m = re.match(r'^(\d{4})$', valor.strip())
    return f"{m.group(1)}-01-01" if m else None


# --------------------------------------------------------------------------
# FMI — DataMapper
# --------------------------------------------------------------------------

def mapear_fmi(resumen):
    base = "https://www.imf.org/external/datamapper/api/v1"
    datos = obtener_json(f"{base}/indicators")
    if not datos or 'indicators' not in datos:
        raise RuntimeError("el API DataMapper no respondio (¿bloqueo Akamai?)")

    arbol = {"FMI": {}}
    for codigo, info in datos['indicators'].items():
        if not isinstance(info, dict):
            continue
        etiqueta = (info.get('label') or codigo).strip()
        dataset = normalizar_nombre(info.get('dataset') or 'DATAMAPPER')
        unidad = (info.get('unit') or '').strip()
        descripcion = etiqueta if not unidad else f"{etiqueta} ({unidad})"

        hoja = hoja_base(
            descripcion=descripcion,
            # El API ignora el filtro de pais: se descarga el indicador completo
            # y el consumidor filtra la clave 'BOL' del JSON
            url_descarga=f"{base}/{codigo}",
            fecha=fecha_iso(info.get('last-modified')),
            tipo="json",
            id_fuente="fmi",
            url_origen="https://www.imf.org/external/datamapper/datasets",
            emisor="FMI",
            periodicidad="anual",
            tags=["internacional", "indicadores", "macroeconomia"],
        )
        niveles = ["INDICADORES", dataset, "SERIES", f"{normalizar_nombre(codigo)}.json"]
        insertar_hoja(arbol["FMI"], niveles, hoja, resumen)

    return arbol


# --------------------------------------------------------------------------
# Banco Mundial — Documents & Reports
# --------------------------------------------------------------------------

def mapear_bm(resumen):
    base = ("https://search.worldbank.org/api/v2/wds?format=json&count_exact=Bolivia"
            "&rows=100&fl=id,display_title,docdt,docty,pdfurl,txturl,url")
    arbol = {"BANCO_MUNDIAL": {}}
    offset = 0
    total = None

    while total is None or offset < total:
        datos = obtener_json(f"{base}&os={offset}")
        if not datos:
            resumen["errores"] += 1
            break
        total = int(datos.get('total') or 0)
        documentos = datos.get('documents') or {}

        for clave, doc in documentos.items():
            if clave == 'facets' or not isinstance(doc, dict):
                continue
            pdf = (doc.get('pdfurl') or '').strip()
            if not pdf:
                resumen["sin_archivo"] += 1
                continue

            fecha = fecha_iso(doc.get('docdt'))
            anio = fecha[:4] if fecha else "SIN_ANIO"
            tipo_doc = normalizar_nombre(doc.get('docty') or 'DOCUMENTOS')

            hoja = hoja_base(
                descripcion=(doc.get('display_title') or '').strip() or os.path.basename(pdf),
                url_descarga=pdf,
                fecha=fecha,
                tipo="pdf",
                id_fuente="bm",
                url_origen=doc.get('url') or "https://documents.worldbank.org",
                emisor="BM",
                periodicidad=None,
                tags=["internacional", "desarrollo", "bolivia"],
            )
            # El CDN de documents1.worldbank.org rechaza HEAD: sin tamaño.
            niveles = ["DOCUMENTOS_BOLIVIA", tipo_doc, anio,
                       normalizar_nombre(os.path.basename(pdf))]
            insertar_hoja(arbol["BANCO_MUNDIAL"], niveles, hoja, resumen)

        offset += 100
        time.sleep(PAUSA)

    return arbol


# --------------------------------------------------------------------------
# Statistics Denmark — Statbank
# --------------------------------------------------------------------------

def periodicidad_statbank(periodo):
    """El formato del periodo declara la frecuencia: 2008Q1 trimestral, 2021M10 mensual."""
    if not periodo:
        return None
    if 'Q' in periodo:
        return "trimestral"
    if 'M' in periodo:
        return "mensual"
    if re.match(r'^\d{4}$', periodo.strip()):
        return "anual"
    return None


def mapear_dst(resumen):
    datos = obtener_json("https://api.statbank.dk/v1/tables?lang=en")
    if not isinstance(datos, list):
        raise RuntimeError("el API de Statbank no respondio")

    arbol = {"STATISTICS_DENMARK": {}}
    for tabla in datos:
        codigo = (tabla.get('id') or '').strip()
        if not codigo:
            continue
        periodicidad = periodicidad_statbank(tabla.get('latestPeriod') or '')
        variables = tabla.get('variables') or []
        grupo = normalizar_nombre(variables[0]) if variables else "GENERAL"

        hoja = hoja_base(
            descripcion=(tabla.get('text') or codigo).strip(),
            url_descarga=f"https://api.statbank.dk/v1/data/{codigo}/CSV?lang=en&valuePresentation=Default",
            fecha=fecha_iso(tabla.get('updated')),
            tipo="csv",
            id_fuente="statistics_denmark",
            url_origen=f"https://www.statbank.dk/{codigo}",
            emisor="DST",
            periodicidad=periodicidad,
            tags=["internacional", "estadisticas", "dinamarca"],
        )
        niveles = ["STATBANK", normalizar_nombre(periodicidad or 'OTROS').upper(),
                   grupo, f"{normalizar_nombre(codigo)}.csv"]
        insertar_hoja(arbol["STATISTICS_DENMARK"], niveles, hoja, resumen)

    return arbol


# --------------------------------------------------------------------------
# ANAPO — WordPress media API
# --------------------------------------------------------------------------

def mapear_anapo(resumen):
    """El sitio migro y el HTML quedo sin enlaces (los PDF se sirven por visor JS).
    Los archivos viven en /wp-content/uploads/ y el API de medios los lista todos.
    Esto documenta ademas la nueva direccion de los 98 enlaces rotos (RF-05).
    """
    base = "https://anapobolivia.org/wp-json/wp/v2/media?media_type=application&per_page=100"
    arbol = {"ANAPO": {}}
    pagina = 1

    while True:
        datos = obtener_json(f"{base}&page={pagina}")
        if not isinstance(datos, list) or not datos:
            break

        for item in datos:
            url = (item.get('source_url') or '').strip()
            if not url:
                continue
            titulo = ((item.get('title') or {}).get('rendered') or '').strip()
            fecha = fecha_iso(item.get('date'))
            extension = url.rsplit('.', 1)[-1].lower() if '.' in url.rsplit('/', 1)[-1] else 'pdf'
            tamanio = ((item.get('media_details') or {}).get('filesize'))

            hoja = hoja_base(
                descripcion=titulo or os.path.basename(url),
                url_descarga=url,
                fecha=fecha,
                tipo=extension,
                id_fuente="anapo",
                url_origen="https://www.anapobolivia.org",
                emisor="ANAPO",
                periodicidad=None,
                tags=["agropecuario", "oleaginosas", "trigo"],
                tamanio=tamanio if isinstance(tamanio, int) else None,
            )
            anio = fecha[:4] if fecha else "SIN_ANIO"
            niveles = ["MEDIOS", anio, extension.upper(),
                       normalizar_nombre(os.path.basename(url))]
            insertar_hoja(arbol["ANAPO"], niveles, hoja, resumen)

        pagina += 1
        time.sleep(PAUSA)
        if pagina > 10:
            break

    return arbol


# --------------------------------------------------------------------------
# CEPAL — repositorio DSpace
# --------------------------------------------------------------------------

def _metadato(item, clave):
    valores = (item.get('metadata') or {}).get(clave) or []
    return (valores[0].get('value') or '').strip() if valores else ''


def mapear_cepal(resumen):
    """Repositorio con 66.072 items: se indexan los mas recientes hasta el tope.
    El total queda documentado; ampliar es subir CEPAL_TOPE_ITEMS.
    """
    # size=25: con 100 el servidor DSpace excede el timeout (verificado: 75s sin responder
    # vs 13s con 25). Mas paginas chicas es mas lento pero confiable.
    # f.entityType=Publication: el repositorio tambien indexa autores (Person) y
    # eventos (Event) como items; sin el filtro, la mitad del resultado no es documento.
    # Publicaciones reales: 49.969 de los 66.072 items.
    base = ("https://repositorio.cepal.org/server/api/discover/search/objects"
            "?dsoType=item&size=25&sort=dc.date.accessioned,DESC"
            "&f.entityType=Publication,equals&embed=bundles/bitstreams")
    arbol = {"CEPAL_REPOSITORIO": {}}

    for pagina in range(max(1, CEPAL_TOPE_ITEMS // 25)):
        datos = obtener_json(f"{base}&page={pagina}")
        try:
            objetos = datos['_embedded']['searchResult']['_embedded']['objects']
        except (TypeError, KeyError):
            resumen["errores"] += 1
            break

        for envoltura in objetos:
            item = (envoltura.get('_embedded') or {}).get('indexableObject') or {}
            titulo = (item.get('name') or '').strip()
            fecha = fecha_iso(_metadato(item, 'dc.date.issued'))

            # Primer bitstream del bundle ORIGINAL: el archivo publicado
            url = None
            tamanio = None
            nombre_archivo = None
            try:
                for bundle in item['_embedded']['bundles']['_embedded']['bundles']:
                    if (bundle.get('name') or '').upper() != 'ORIGINAL':
                        continue
                    flujos = bundle['_embedded']['bitstreams']['_embedded']['bitstreams']
                    if flujos:
                        primero = flujos[0]
                        url = f"https://repositorio.cepal.org/server/api/core/bitstreams/{primero['uuid']}/content"
                        tamanio = primero.get('sizeBytes')
                        nombre_archivo = primero.get('name')
                    break
            except (TypeError, KeyError):
                pass

            if not url:
                resumen["sin_archivo"] += 1
                continue

            extension = (nombre_archivo or 'documento.pdf').rsplit('.', 1)[-1].lower()
            anio = fecha[:4] if fecha else "SIN_ANIO"

            hoja = hoja_base(
                descripcion=titulo or nombre_archivo,
                url_descarga=url,
                fecha=fecha,
                tipo=extension,
                id_fuente="cepal",
                url_origen=f"https://repositorio.cepal.org/items/{item.get('uuid', '')}",
                emisor="CEPAL",
                periodicidad=None,
                tags=["internacional", "estadisticas", "publicaciones"],
                tamanio=tamanio if isinstance(tamanio, int) else None,
            )
            niveles = ["PUBLICACIONES_RECIENTES", anio, extension.upper(),
                       normalizar_nombre(nombre_archivo or item.get('uuid', 'doc'))]
            insertar_hoja(arbol["CEPAL_REPOSITORIO"], niveles, hoja, resumen)

        time.sleep(PAUSA)

    return arbol


# --------------------------------------------------------------------------

FUENTES = {
    "fmi": ("mapa_fmi.json", mapear_fmi),
    "bm": ("mapa_bm.json", mapear_bm),
    "statistics_denmark": ("mapa_statistics_denmark.json", mapear_dst),
    "anapo": ("mapa_anapo.json", mapear_anapo),
    "cepal": ("mapa_cepal_repositorio.json", mapear_cepal),
}

if __name__ == "__main__":
    pedidas = [f.lower() for f in sys.argv[1:]] or list(FUENTES)
    os.makedirs(SALIDA, exist_ok=True)

    for nombre in pedidas:
        if nombre not in FUENTES:
            print(f"Fuente desconocida: {nombre} (disponibles: {', '.join(FUENTES)})")
            continue

        archivo, funcion = FUENTES[nombre]
        resumen = {"documentos": 0, "duplicados": 0, "renombrados": 0,
                   "sin_archivo": 0, "errores": 0}
        print(f"\n{'=' * 70}\n{nombre.upper()} (via API)\n{'=' * 70}")

        try:
            inicio = time.time()
            arbol = funcion(resumen)
        except Exception as e:
            print(f"  ERROR: {type(e).__name__}: {e}")
            continue

        ruta = os.path.join(SALIDA, archivo)
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(arbol, f, ensure_ascii=False, indent=4)

        print(f"  Documentos indexados : {resumen['documentos']}")
        print(f"  Sin archivo publicado: {resumen['sin_archivo']}")
        print(f"  Errores              : {resumen['errores']}")
        print(f"  Tiempo               : {time.time() - inicio:.0f}s  ->  {ruta}")
