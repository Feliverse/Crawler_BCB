"""
Crawler externo — Fuente: APS, tabla dinamica de Resoluciones, Circulares e Instructivos.

Complemento de `crawler_aps.py`. Esa tabla no esta en el HTML estatico: la pagina de
Normativa la puebla via Angular contra el API publico de SIRECI. Este modulo consume
ese API directamente y genera su propio JSON, con la misma estructura de 5 niveles.

Salida separada a proposito: `crawler_aps.py` mapea normativa de base (leyes, decretos),
esto son actos administrativos, con volumen y ciclo de actualizacion distintos.

Uso:
    python Crawlers/crawler_aps_resoluciones.py
"""

import sys
import requests
import time
import json
import re
import os
from datetime import date

# Se reutilizan las utilidades del crawler principal: ambos modulos se entregan juntos
from crawler_aps import ID_FUENTE, normalizar_nombre, insertar_hoja, tipo_archivo_desde_url

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

API_URL = "https://sireci.aps.gob.bo/api/cartas_resoluciones/web/data"

RAIZ = "RESOLUCIONES_APS"

# Pagina publica desde la que se sirve la tabla; es el origen que se reporta en las hojas
URL_ORIGEN = {
    "PEN": "https://www.aps.gob.bo/index.php/pensiones/normativa",
    "SEG": "https://www.aps.gob.bo/index.php/seguros/normativa",
}

# mercado del API -> nivel 2
MERCADOS = {
    "PEN": "PENSIONES",
    "SEG": "SEGUROS",
}

# $scope.tipoDocumentos del controlador DocumentosController
TIPOS_DOCUMENTO = ("RA", "CC", "IN")

# La APS es la institucion que emite; el selector ofrece tambien las entidades predecesoras
INSTITUCION = "PS"

# $scope.instituciones del controlador: codigo del API -> sigla de la entidad emisora
EMISORES = {
    "PS": "APS",
    "AP": "AP",
    "IP": "IP",
    "IS": "IS",
    "IV": "IV",
}

# El API topea la respuesta en 500 filas aunque se pida mas
ITEMS_POR_PAGINA = 500

# Gestion a recorrer: la corriente
GESTION = date.today().year

NIVEL4_POR_DEFECTO = "GENERAL"


def obtener_headers():
    return {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'cache-control': 'no-cache',
    }


def consultar_api(mercado, tipo_documento, gestion, pagina):
    parametros = {
        'institucion': INSTITUCION,
        'gestion': gestion,
        'mercado': mercado,
        'tipoDocumento': tipo_documento,
        'categoria': '',
        'titulo': '',
        'numero': '',
        'itemsPerPage': ITEMS_POR_PAGINA,
        'pagenumber': pagina,
    }
    respuesta = requests.get(API_URL, params=parametros, headers=obtener_headers(), timeout=45)
    respuesta.raise_for_status()
    cuerpo = respuesta.json()

    if cuerpo.get('status') != 'Correcto':
        raise ValueError(f"el API respondio status={cuerpo.get('status')!r}")

    return int(cuerpo.get('totalRows') or 0), (cuerpo.get('data') or [])


def descargar_todo(mercado, tipo_documento, gestion, resumen):
    """Pagina el API hasta juntar todas las filas de la combinacion pedida."""
    filas = []
    pagina = 1
    total = None

    while True:
        try:
            total, lote = consultar_api(mercado, tipo_documento, gestion, pagina)
        except Exception as e:
            print(f"    Error en {tipo_documento}/{mercado} pagina {pagina}: {e}")
            resumen["errores"] += 1
            break

        if not lote:
            break

        filas.extend(lote)
        if len(filas) >= total or len(lote) < ITEMS_POR_PAGINA:
            break

        pagina += 1
        time.sleep(1.2)

    return total or 0, filas


def normalizar_fecha_iso(valor):
    """El API entrega `2025-12-31T04:00:00.000Z`; la parte de fecha ya es el dia local
    de Bolivia (UTC-4), asi que se toma tal cual para cumplir AAAA-MM-DD (US-03).
    """
    if not valor or not isinstance(valor, str):
        return None
    coincidencia = re.match(r'(\d{4}-\d{2}-\d{2})', valor)
    return coincidencia.group(1) if coincidencia else None


def nombre_hoja(fila):
    """Llave de nivel 5.

    `urlarchivo` apunta a `/descarga/<id>` y no expone nombre de archivo, pero la fila
    trae `rc_filename` con el nombre real y su extension.
    """
    nombre = (fila.get('rc_filename') or '').strip()
    if nombre:
        return normalizar_nombre(nombre)

    numero = fila.get('numero') or fila.get('id')
    return normalizar_nombre(f"{fila.get('rc_tipo', 'DOC')}_{numero}.pdf")


def emisor_de(fila):
    """Entidad que emitio el documento.

    Con `institucion=PS` son todos de la APS, pero el selector del portal admite
    tambien las entidades predecesoras, asi que se lee del dato en vez de asumirlo.
    """
    codigo = (fila.get('rc_inten') or INSTITUCION).strip()
    return EMISORES.get(codigo, codigo or 'APS')


def construir_hoja(fila, mercado):
    fecha = normalizar_fecha_iso(fila.get('fecha'))
    nombre = (fila.get('rc_filename') or '').strip()

    descripcion = (fila.get('titulo') or '').strip() or nombre or 'Documento sin titulo'
    numero = (str(fila.get('numero') or '')).strip()
    if numero:
        descripcion = f"{fila.get('tipo', '')} {numero} - {descripcion}".strip()

    hoja = {
        "descripcion": descripcion,
        "url_descarga": fila.get('urlarchivo', ''),
        "fecha_actualizacion": fecha,
        "fecha_ultimo_dato": fecha,
        "tipo_archivo": tipo_archivo_desde_url(nombre) if nombre else "pdf",
        "id_fuente": ID_FUENTE,
        "url_origen": URL_ORIGEN[mercado],
        "entidad_emisora": emisor_de(fila),
    }

    # Metadato que el API ya entrega y que el pendiente del proyecto pide para el nivel 5
    tamanio = fila.get('tamanioarchivo') or fila.get('rc_filesize')
    if isinstance(tamanio, int) and tamanio > 0:
        hoja["tamanio_bytes"] = tamanio

    return hoja


def procesar(mercado, tipo_documento, filas, mapa, resumen):
    for fila in filas:
        url = (fila.get('urlarchivo') or '').strip()
        if not url:
            # rc_publicar_web = false: la fila existe pero la APS no publico el archivo
            resumen["sin_archivo"] += 1
            continue

        # Nivel 4: el subtipo clasifica las Resoluciones Administrativas (R1..R17)
        subtipo = (fila.get('subtipo') or '').strip()
        nivel4 = normalizar_nombre(subtipo) if subtipo else NIVEL4_POR_DEFECTO

        niveles = [
            MERCADOS[mercado],
            normalizar_nombre(fila.get('tipo') or tipo_documento),
            nivel4,
            nombre_hoja(fila),
        ]
        insertar_hoja(mapa, niveles, construir_hoja(fila, mercado), resumen)


# --- FLUJO PRINCIPAL AUTOMÁTICO ---
if __name__ == "__main__":
    mapa_jerarquizado_final = {RAIZ: {}}
    resumen = {
        "documentos": 0,
        "duplicados": 0,
        "renombrados": 0,
        "sin_archivo": 0,
        "descartados": 0,
        "errores": 0,
    }

    print(f"Consultando el API de SIRECI — gestion {GESTION}")

    for mercado, etiqueta in MERCADOS.items():
        print(f"\n--- Mercado: [{etiqueta}] ---")
        for tipo_documento in TIPOS_DOCUMENTO:
            total, filas = descargar_todo(mercado, tipo_documento, GESTION, resumen)
            if not total:
                print(f"  {tipo_documento}: sin registros")
                continue

            antes = resumen["documentos"]
            procesar(mercado, tipo_documento, filas, mapa_jerarquizado_final[RAIZ], resumen)
            print(f"  {tipo_documento}: {total} filas en el API -> {resumen['documentos'] - antes} con archivo publicado")
            time.sleep(1.2)

    archivo_salida = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "mapa_global_aps_resoluciones.json"
    )
    with open(archivo_salida, "w", encoding="utf-8") as f:
        json.dump(mapa_jerarquizado_final, f, ensure_ascii=False, indent=4)

    print(f"\nResumen: {resumen['documentos']} documentos indexados")
    print(f"  - filas sin archivo publicado  : {resumen['sin_archivo']}")
    print(f"  - enlaces duplicados omitidos  : {resumen['duplicados']}")
    print(f"  - llaves renombradas por choque: {resumen['renombrados']}")
    print(f"  - errores de consulta          : {resumen['errores']}")
    print(f"\n¡Listo! Mapa de resoluciones APS generado en '{archivo_salida}'.")
