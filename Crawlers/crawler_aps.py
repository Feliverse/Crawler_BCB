"""
Crawler externo — Fuente: APS (Autoridad de Fiscalizacion y Control de Pensiones y Seguros).

Recorre las paginas de Normativa de Pensiones y Seguros, extrae los documentos
descargables listados en las tablas estaticas y genera un JSON jerarquico de 5
niveles compatible con el modelo del prototipo CrawlerBCB (mapa_global_bcb.json).

Uso:
    python Crawlers/crawler_aps.py
"""

import sys
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, urlsplit, urlunsplit, unquote, quote
import time
import json
import re
import os

# Asegurar la correcta codificación de salida en la consola
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# URL base del portal
BASE_URL = "https://www.aps.gob.bo/"

ID_FUENTE = "aps"

# Raíz única del árbol. El visor del prototipo (web/app.js -> resolveRoot) solo
# renderiza la primera clave de nivel 1, así que todo cuelga de un único nodo.
RAIZ = "NORMATIVA_APS"

# Secciones asignadas: nivel 2 -> URL de origen
SECCIONES = {
    "PENSIONES": urljoin(BASE_URL, "index.php/pensiones/normativa"),
    "SEGUROS": urljoin(BASE_URL, "index.php/seguros/normativa"),
}

# Tabla renderizada por Angular/AJAX ({{item.tipodocumento}}): no está en el HTML
# estático. La cubre `crawler_aps_resoluciones.py`, que consume el API de SIRECI.
TABLAS_DINAMICAS_IGNORADAS = {"tabla-normativa"}

# Nivel 3 para la tabla principal de normativa (la que trae columna "Fecha")
SECCION_PRINCIPAL = "NORMATIVA_PRINCIPAL"

# Nivel 4 usado cuando la tabla no declara un tipo de documento por fila
TIPO_POR_DEFECTO = "DOCUMENTOS"

# Nivel 4 para las filas de anexo que cuelgan del documento anterior
TIPO_ANEXO = "ANEXOS"

EXTENSIONES_VALIDAS = ('.pdf', '.xlsx', '.xls', '.csv', '.doc', '.docx', '.sav')

# Texto que la fuente usa para marcar una fila sin archivo publicado
SIN_ARCHIVO = "(no disponible)"


def obtener_headers():
    return {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }


def normalizar_nombre(texto):
    """Reemplaza espacios por guiones bajos y limpia caracteres extraños para nombres de llaves JSON."""
    texto = unquote(texto).strip()
    texto = re.sub(r'[\s/\\:]+', '_', texto)
    texto = re.sub(r'_+', '_', texto)
    return texto.strip('_')


def normalizar_fecha(texto):
    """Convierte una fecha dd/mm/aaaa de la fuente al estándar AAAA-MM-DD (US-03).

    Devuelve None si la celda no contiene una fecha reconocible; la fuente tiene
    filas con año de dos dígitos o directamente sin fecha.
    """
    if not texto:
        return None

    coincidencia = re.search(r'(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})', texto)
    if not coincidencia:
        return None

    dia, mes, anio = (int(g) for g in coincidencia.groups())

    # Años de dos dígitos: la normativa publicada va de 1990 en adelante
    if anio < 100:
        anio += 1900 if anio > 50 else 2000

    if not (1 <= mes <= 12 and 1 <= dia <= 31):
        return None

    return f"{anio:04d}-{mes:02d}-{dia:02d}"


def normalizar_url(url):
    """Codifica la ruta para que `url_descarga` sea una URL valida.

    Muchos href de la fuente traen espacios y acentos literales; el servidor los
    acepta pero responde con un redirect a la version codificada. Emitirla ya
    codificada evita que el motor de conciliacion lea ese redirect como un cambio
    de URL (RF-04). Se desescapa primero para no codificar dos veces.
    """
    partes = urlsplit(url)
    ruta = quote(unquote(partes.path), safe="/()")
    return urlunsplit((partes.scheme, partes.netloc, ruta, partes.query, partes.fragment))


def tipo_archivo_desde_url(url):
    """Obtiene la extensión del archivo a partir del enlace de descarga (RF-07)."""
    nombre = os.path.basename(urlparse(unquote(url)).path)
    if '.' not in nombre:
        return "desconocido"
    return nombre.rsplit('.', 1)[-1].lower()


def nombre_archivo_desde_url(url):
    """Nombre de archivo normalizado, conservando la extensión real del recurso."""
    nombre = os.path.basename(urlparse(unquote(url)).path)
    return normalizar_nombre(nombre) if nombre else "documento"


def es_descargable(url):
    ruta = urlparse(unquote(url)).path.lower()
    return ruta.endswith(EXTENSIONES_VALIDAS)


def celdas_de(fila):
    return [celda.get_text(' ', strip=True) for celda in fila.find_all(['td', 'th'])]


def insertar_hoja(mapa, niveles, hoja, resumen):
    """Ubica una hoja en el árbol creando los niveles intermedios que falten.

    Si la llave de nivel 5 ya existe se distingue con un sufijo, salvo que se
    trate exactamente del mismo enlace (la fuente repite algunos PDF).
    """
    nodo = mapa
    for nivel in niveles[:-1]:
        nodo = nodo.setdefault(nivel, {})

    llave = niveles[-1]
    if llave in nodo:
        if nodo[llave].get("url_descarga") == hoja["url_descarga"]:
            resumen["duplicados"] += 1
            return
        sufijo = 2
        while f"{llave}__{sufijo}" in nodo:
            sufijo += 1
        llave = f"{llave}__{sufijo}"
        resumen["renombrados"] += 1

    nodo[llave] = hoja
    resumen["documentos"] += 1


def construir_hoja(descripcion, url_absoluta, fecha, url_origen):
    """Hoja de nivel 5.

    Mantiene `descripcion` y `url_descarga` (contrato del modelo CrawlerBCB) y
    `fecha_actualizacion` (lo que consume el visor web), y agrega los campos
    obligatorios de US-04: id_fuente, url_origen, tipo_archivo y fecha_ultimo_dato.
    """
    return {
        "descripcion": descripcion,
        "url_descarga": url_absoluta,
        "fecha_actualizacion": fecha,
        "fecha_ultimo_dato": fecha,
        "tipo_archivo": tipo_archivo_desde_url(url_absoluta),
        "id_fuente": ID_FUENTE,
        "url_origen": url_origen,
    }


def procesar_tabla_principal(tabla, seccion, url_origen, mapa, resumen):
    """Tabla con columnas `Tipo | N° | Fecha | Descripción | Ver`.

    El nivel 4 sale de la columna "Tipo". Las filas cortas que solo traen
    descripción y enlace son anexos del documento anterior: heredan su fecha,
    porque se publican junto a la norma que los aprueba.
    """
    ultima_fecha = None

    for fila in tabla.find_all('tr'):
        celdas = celdas_de(fila)
        if not celdas or not any(celdas):
            continue

        enlace = fila.find('a', href=True)
        if enlace is None:
            # Cabecera, o fila marcada por la fuente como "(no disponible)"
            if SIN_ARCHIVO in ' '.join(celdas).lower():
                resumen["sin_archivo"] += 1
            continue

        url_absoluta = normalizar_url(urljoin(BASE_URL, enlace['href']))
        if not es_descargable(url_absoluta):
            resumen["descartados"] += 1
            continue

        if len(celdas) >= 4:
            tipo = celdas[0].strip()
            fecha = normalizar_fecha(celdas[2])
            descripcion = celdas[3].strip()
            if fecha:
                ultima_fecha = fecha
            nivel4 = normalizar_nombre(tipo) if tipo not in ('', '-') else TIPO_POR_DEFECTO
        else:
            # Fila de anexo: hereda la vigencia del documento que la precede
            tipo = TIPO_ANEXO
            fecha = ultima_fecha
            descripcion = celdas[0].strip()
            nivel4 = TIPO_ANEXO

        if not descripcion:
            descripcion = nombre_archivo_desde_url(url_absoluta)

        niveles = [
            seccion,
            SECCION_PRINCIPAL,
            nivel4,
            nombre_archivo_desde_url(url_absoluta),
        ]
        insertar_hoja(mapa, niveles, construir_hoja(descripcion, url_absoluta, fecha, url_origen), resumen)


def procesar_tabla_por_bloques(tabla, seccion, url_origen, mapa, resumen):
    """Tabla agrupada por bloques: una fila de una sola celda abre el grupo
    (`PRINCIPIOS DEL DERECHO ADMINISTRATIVO`, `RESOLUCIONES MINISTERIALES`, ...)
    y las siguientes traen `Descripción | Archivo`. No publica fechas.
    """
    grupo_actual = "GENERAL"

    for fila in tabla.find_all('tr'):
        columnas = fila.find_all(['td', 'th'])
        celdas = celdas_de(fila)
        if not celdas or not any(celdas):
            continue

        # Fila de una sola celda sin enlace: es el encabezado del bloque
        if len(columnas) == 1 and not fila.find('a', href=True):
            grupo_actual = normalizar_nombre(celdas[0])
            continue

        enlace = fila.find('a', href=True)
        if enlace is None:
            continue

        url_absoluta = normalizar_url(urljoin(BASE_URL, enlace['href']))
        if not es_descargable(url_absoluta):
            resumen["descartados"] += 1
            continue

        descripcion = celdas[0].strip() or nombre_archivo_desde_url(url_absoluta)

        niveles = [
            seccion,
            grupo_actual,
            TIPO_POR_DEFECTO,
            nombre_archivo_desde_url(url_absoluta),
        ]
        # La fuente no publica fecha en estos bloques: se deja en null antes que inventarla
        insertar_hoja(mapa, niveles, construir_hoja(descripcion, url_absoluta, None, url_origen), resumen)


def es_tabla_principal(tabla):
    """Distingue la tabla de normativa (trae columna Fecha) de las agrupadas por bloques."""
    primera = tabla.find('tr')
    if primera is None:
        return False
    encabezados = [c.lower() for c in celdas_de(primera)]
    return 'fecha' in encabezados and 'tipo' in encabezados


def escanear_seccion(seccion, url_pagina, mapa, resumen):
    """Descarga una página de normativa y vuelca sus tablas en el árbol.

    Se recorre únicamente el contenido de las tablas: un barrido global de <a>
    arrastraría el menú y el pie de página, que se repiten en todas las vistas.
    """
    try:
        respuesta = requests.get(url_pagina, headers=obtener_headers(), timeout=25)
        respuesta.raise_for_status()
    except Exception as e:
        print(f"Error al descargar [{seccion}]: {e}")
        resumen["errores"] += 1
        return

    soup = BeautifulSoup(respuesta.text, 'html.parser')
    tablas = soup.find_all('table')
    print(f"  Tablas encontradas: {len(tablas)}")

    for indice, tabla in enumerate(tablas):
        if tabla.get('id') in TABLAS_DINAMICAS_IGNORADAS:
            print(f"  - tabla {indice}: omitida (Angular/AJAX, la cubre crawler_aps_resoluciones.py)")
            resumen["tablas_dinamicas"] += 1
            continue

        antes = resumen["documentos"]
        if es_tabla_principal(tabla):
            procesar_tabla_principal(tabla, seccion, url_pagina, mapa, resumen)
            etiqueta = "normativa principal"
        else:
            procesar_tabla_por_bloques(tabla, seccion, url_pagina, mapa, resumen)
            etiqueta = "bloques agrupados"
        print(f"  - tabla {indice} ({etiqueta}): {resumen['documentos'] - antes} documentos")


# --- FLUJO PRINCIPAL AUTOMÁTICO ---
if __name__ == "__main__":
    mapa_jerarquizado_final = {RAIZ: {}}
    resumen = {
        "documentos": 0,
        "duplicados": 0,
        "renombrados": 0,
        "sin_archivo": 0,
        "descartados": 0,
        "tablas_dinamicas": 0,
        "errores": 0,
    }

    for seccion, url_pagina in SECCIONES.items():
        print(f"\n--- Escaneando sección: [{seccion}] ---")
        print(f"Indexando: {url_pagina}")
        escanear_seccion(seccion, url_pagina, mapa_jerarquizado_final[RAIZ], resumen)
        time.sleep(1.2)

    archivo_salida = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mapa_global_aps.json")
    with open(archivo_salida, "w", encoding="utf-8") as f:
        json.dump(mapa_jerarquizado_final, f, ensure_ascii=False, indent=4)

    print(f"\nResumen: {resumen['documentos']} documentos indexados")
    print(f"  - enlaces duplicados omitidos : {resumen['duplicados']}")
    print(f"  - llaves renombradas por choque: {resumen['renombrados']}")
    print(f"  - filas sin archivo publicado  : {resumen['sin_archivo']}")
    print(f"  - enlaces no descargables      : {resumen['descartados']}")
    print(f"  - tablas dinámicas pendientes  : {resumen['tablas_dinamicas']}")
    print(f"\n¡Listo! Mapa de la fuente APS generado en '{archivo_salida}'.")
