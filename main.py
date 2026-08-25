"""
Rastreador genérico de reportes para sitios web.

Busca reportes de dos formas:
  A) Archivos descargables (pdf, xlsx, csv, docx, etc.)
  B) Contenido tabular/reportes que viven directamente en el HTML de una
     página (tablas <table> con datos reales, sin ningún archivo adjunto).

Para evitar perder tiempo en páginas institucionales sin datos (Historia,
Misión y Visión, Nómina de Personal, Contáctenos, etc.), el script filtra
por una lista de palabras clave de exclusión ANTES de visitar o registrar
una página. La lista trae valores por defecto razonables en español/inglés,
y es totalmente configurable por línea de comandos.

Uso básico:
    python main.py --url https://ejemplo.com

Uso avanzado:
    python main.py \
        --url https://ejemplo.com \
        --depth 3 \
        --extensions xlsx,xls,csv,pdf,docx,doc,zip \
        --exclude-keywords "quienes somos,trabaja con nosotros" \
        --export-tables-csv \
        --delay 1.0
"""

import argparse
import csv
import json
import os
import re
import random
import sys
import time
from urllib.parse import unquote, urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


# --------------------------------------------------------------------------
# Palabras clave por defecto
# --------------------------------------------------------------------------

# Páginas institucionales típicas que casi nunca contienen reportes/datos.
# Se comparan contra el nombre del enlace Y contra la URL.
DEFAULT_EXCLUDE_KEYWORDS = [
    'historia', 'mision', 'misión', 'vision', 'visión', 'quienes somos',
    'quiénes somos', 'sobre nosotros', 'about us', 'who we are',
    'nomina', 'nómina', 'personal', 'organigrama', 'directorio',
    'equipo directivo', 'autoridades', 'contactenos', 'contáctenos',
    'contacto', 'contact us', 'mapa del sitio', 'sitemap',
    'preguntas frecuentes', 'faq', 'aviso de privacidad', 'privacy policy',
    'terminos y condiciones', 'términos y condiciones', 'terms of service',
    'politica de cookies', 'política de cookies', 'cookie policy',
    'trabaja con nosotros', 'trabaje con nosotros', 'empleo', 'vacantes',
    'careers', 'jobs', 'marco legal', 'transparencia institucional',
    'redes sociales', 'social media', 'buzon de quejas', 'buzón de quejas',
    'iniciar sesion', 'iniciar sesión', 'login', 'registrarse',
    'Constitución Política del Estado', 'comunicaciones', 'leyes', 'manual',
    'auditoria', 'licitaciones', 'contrataciones', 'decreto', 'decretos'
]

# Señales de que una página SÍ contiene un reporte, aunque no tenga un
# archivo adjunto (usadas para marcar contenido HTML relevante).
DEFAULT_INCLUDE_KEYWORDS = [
    'informe', 'reporte', 'boletin', 'boletín', 'estadistica', 'estadística',
    'cifras', 'resultados', 'memoria', 'indicador', 'publicacion',
    'publicación', 'dataset', 'series', 'cuadro', 'anuario', 'report',
    'statistics', 'figures', 'data', 'dashboard', 'resumen ejecutivo',
]

def cargar_palabras_clave(entrada):
    """Convierte una cadena de texto o un archivo en una lista de palabras clave limpias."""
    if not entrada:
        return []

    # Si es una ruta de archivo existente, lee su contenido
    if os.path.isfile(entrada):
        palabras = []
        try:
            with open(entrada, 'r', encoding='utf-8') as f:
                for linea in f:
                    linea = linea.strip()
                    # Ignorar líneas vacías y comentarios que inicien con #
                    if linea and not linea.startswith('#'):
                        for p in linea.split(','):
                            if p.strip():
                                palabras.append(p.strip().lower())
            return palabras
        except Exception as e:
            print(f"Error al leer el archivo de palabras clave '{entrada}': {e}")
            return []

    # Si es texto directo, procesa la cadena separada por comas
    return [k.strip().lower() for k in entrada.split(',') if k.strip()]

def obtener_headers():
    return {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
            '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
    }


SELECTORES_ACEPTAR_COOKIES = [
    '#onetrust-accept-btn-handler',
    '[id*="accept" i]',
    '[class*="accept" i]',
    'button:has-text("Aceptar")',
    'button:has-text("Accept")',
    'button:has-text("Acepto")',
    'button:has-text("I agree")',
    'button:has-text("Allow all")',
]

SELECTORES_CERRAR_MODAL = [
    '[aria-label="Cerrar" i]',
    '[aria-label="Close" i]',
    '[title="Cerrar" i]',
    '[title="Close" i]',
    'button:has-text("Cerrar")',
    'button:has-text("Close")',
    'button:has-text("×")',
    '[data-dismiss="modal"]',
    '[data-bs-dismiss="modal"]',
    '[class*="closeIcon" i]',
    '[class*="close-icon" i]',
    '[class*="close_icon" i]',
    '[class*="popup" i][class*="close" i]',
    '[class*="pop-up" i][class*="close" i]',
    '[data-testid*="close" i]',
    '[data-test*="close" i]',
]


def esperar_despues_de_click(page):
    page.wait_for_timeout(random.randint(2000, 5000))


def hacer_click_visible(page, selectores):
    for selector in selectores:
        try:
            elemento = page.locator(selector).first
            if elemento.is_visible(timeout=500):
                elemento.click(timeout=2000)
                esperar_despues_de_click(page)
                return True
        except Exception:
            continue
    return False


def obtener_html(url):
    """Carga una página con JavaScript, acepta cookies y cierra modales visibles."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise RuntimeError(
            "Playwright no está instalado. Ejecute: "
            "python -m pip install -r requirements.txt"
        ) from error

    with sync_playwright() as playwright:
        navegador = playwright.chromium.launch(headless=True)
        try:
            pagina = navegador.new_page(user_agent=obtener_headers()['User-Agent'])
            pagina.on('dialog', lambda dialogo: dialogo.dismiss())
            pagina.goto(url, wait_until='domcontentloaded', timeout=15000)
            hacer_click_visible(pagina, SELECTORES_ACEPTAR_COOKIES)
            hacer_click_visible(pagina, SELECTORES_CERRAR_MODAL)
            return pagina.content()
        finally:
            navegador.close()


def normalizar_nombre(texto):
    texto = unquote(texto).strip()
    texto = re.sub(r'[\s/\\:?*"<>|]+', '_', texto)
    return texto.strip('_') or "SIN_NOMBRE"


def mismo_dominio(url, base_netloc):
    try:
        return urlparse(url).netloc == base_netloc
    except Exception:
        return False


def contiene_alguna(texto, palabras):
    texto_l = texto.lower()
    return any(p in texto_l for p in palabras)


def cerrar_modales(soup):
    """Retira del DOM los contenedores que representan modales o overlays."""
    selectores = [
        'dialog',
        '[role="dialog"]',
        '[role="alertdialog"]',
        '[aria-modal="true"]',
        '[class~="modal"]',
        '[class~="dialog"]',
        '[class~="popup"]',
        '[class~="overlay"]',
        '[class*="popup" i]',
        '[class*="pop-up" i]',
        '[class*="modal" i]',
        '[id~="modal"]',
        '[id~="dialog"]',
        '[id~="popup"]',
        '[id~="overlay"]',
    ]
    eliminados = set()
    for selector in selectores:
        for elemento in soup.select(selector):
            identificador = id(elemento)
            if identificador not in eliminados:
                elemento.decompose()
                eliminados.add(identificador)
    return len(eliminados)


def es_excluida(nombre, url, exclude_keywords):
    """True si el nombre del enlace o la URL matchean una palabra de exclusión."""
    if not exclude_keywords:
        return False
    return contiene_alguna(nombre, exclude_keywords) or contiene_alguna(url, exclude_keywords)


def puede_rastrear(url, robot_parser, ignorar_robots):
    if ignorar_robots or robot_parser is None:
        return True
    try:
        return robot_parser.can_fetch("*", url)
    except Exception:
        return True


def cargar_robots(base_url):
    parsed = urlparse(base_url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    rp = RobotFileParser()
    try:
        rp.set_url(robots_url)
        rp.read()
        return rp
    except Exception:
        return None


# --------------------------------------------------------------------------
# Descubrimiento de navegación
# --------------------------------------------------------------------------

SELECTORES_MENU = [
    'nav a[href]',
    'header nav a[href]',
    '[role="navigation"] a[href]',
    'ul.navbar-nav a[href]',
    'ul.nav a[href]',
    'ul.menu a[href]',
    '.main-menu a[href]',
    '.main-nav a[href]',
    '#main-menu a[href]',
    '#nav a[href]',
    '.dropdown a[href]',
    '.navigation a[href]',
]


def descubrir_enlaces_menu(base_url, exclude_keywords):
    print("Buscando el menú de navegación principal...")
    enlaces = {}
    base_netloc = urlparse(base_url).netloc

    try:
        soup = BeautifulSoup(obtener_html(base_url), 'html.parser')
        cerrar_modales(soup)
    except Exception as e:
        print(f"No se pudo descargar la página base: {e}")
        return enlaces

    def registrar(a):
        href = a.get('href')
        if not href or href.startswith('#') or href.startswith('javascript:'):
            return
        url_abs = urljoin(base_url, href)
        if not mismo_dominio(url_abs, base_netloc):
            return
        nombre = a.get_text(strip=True) or href
        if es_excluida(nombre, url_abs, exclude_keywords):
            return
        enlaces[normalizar_nombre(nombre)] = url_abs

    for selector in SELECTORES_MENU:
        for a in soup.select(selector):
            registrar(a)
        if len(enlaces) >= 3:
            print(f"Menú detectado usando el selector: {selector} ({len(enlaces)} enlaces)")
            return enlaces

    print("No se detectó un menú reconocible; usando todos los enlaces internos de la página de inicio.")
    for a in soup.find_all('a', href=True):
        nombre = a.get_text(strip=True)
        if not nombre or not (2 < len(nombre) < 80):
            continue
        registrar(a)

    if not enlaces:
        enlaces = {"HOME": base_url}

    return enlaces


# --------------------------------------------------------------------------
# Extracción de tablas HTML (reportes embebidos, sin archivo adjunto)
# --------------------------------------------------------------------------

def extraer_tablas(soup, max_filas=100, max_celdas_texto=200):
    """Extrae tablas <table> con datos reales (>=2 filas). Recorta tablas
    enormes para no inflar el JSON de salida."""
    tablas = []
    for tabla in soup.find_all('table'):
        filas = []
        for tr in tabla.find_all('tr'):
            celdas = [c.get_text(strip=True)[:max_celdas_texto] for c in tr.find_all(['td', 'th'])]
            if celdas:
                filas.append(celdas)
        if len(filas) >= 2:
            truncada = len(filas) > max_filas
            tablas.append({
                "filas": filas[:max_filas],
                "truncada": truncada,
                "total_filas_original": len(filas),
            })
    return tablas


def extraer_bloques_elementor(soup, max_filas=100, max_celdas_texto=200):
    """Extrae filas de datos que Elementor representa como contenedores."""
    bloques = []
    for fila in soup.select('.e-con-boxed'):
        celdas = []
        for encabezado in fila.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
            texto = encabezado.get_text(' ', strip=True)
            if texto and texto not in celdas:
                celdas.append(texto[:max_celdas_texto])
        if len(celdas) >= 3:
            bloques.append(celdas)

    if not bloques:
        return []
    return [{
        "filas": bloques[:max_filas],
        "truncada": len(bloques) > max_filas,
        "total_filas_original": len(bloques),
        "tipo": "contenedores_elementor",
    }]


def extraer_contadores_elementor(soup, max_filas=100, max_celdas_texto=200):
    """Extrae contadores Elementor junto con su etiqueta descriptiva."""
    filas = []
    vistos = set()
    for columna in soup.select('.elementor-column'):
        contador = columna.select_one('.elementor-counter-number')
        titulo = columna.select_one(
            '.elementor-heading-title, .elementor-counter-number-wrapper + *'
        )
        if not contador or not titulo:
            continue

        valor = contador.get('data-to-value') or contador.get_text(' ', strip=True)
        nombre = titulo.get_text(' ', strip=True)
        if not valor or not nombre:
            continue
        fila = (nombre[:max_celdas_texto], valor[:max_celdas_texto])
        if fila not in vistos:
            filas.append(list(fila))
            vistos.add(fila)

    if not filas:
        return []
    return [{
        "filas": filas[:max_filas],
        "truncada": len(filas) > max_filas,
        "total_filas_original": len(filas),
        "tipo": "contadores_elementor",
    }]


def extraer_bloques_estadisticos(soup, max_filas=100, max_celdas_texto=200):
    """Extrae indicadores visuales de sitios como BBV."""
    filas = []
    vistos = set()

    for bloque in soup.select('.stadistic-item'):
        titulo = bloque.select_one('.stadistic-item__title')
        numero = bloque.select_one('.stadistic-item__number')
        unidad = bloque.select_one('.stadistic-item__unity')
        tabla = bloque.select_one('table')
        fila = tuple(
            texto[:max_celdas_texto]
            for texto in (
                titulo.get_text(' ', strip=True) if titulo else '',
                numero.get_text(' ', strip=True) if numero else '',
                unidad.get_text(' ', strip=True) if unidad else '',
            )
            if texto
        )
        if len(fila) >= 2 and fila not in vistos and tabla is None:
            filas.append(list(fila))
            vistos.add(fila)

    for bloque in soup.select('.dailyInfo-box'):
        indicadores = bloque.select('.circleBox')
        if not indicadores:
            indicadores = bloque.select('.dailyInfo-circleBox, .dailyInfo-state')
        for indicador in indicadores:
            textos = []
            for elemento in indicador.select(
                    '.circleBox__text, .circleBox__data, '
                    '.dailyInfo-state__date, .dailyInfo-state__text, '
                    '.dailyInfo-state__status'):
                texto = elemento.get_text(' ', strip=True)
                if texto and texto not in textos:
                    textos.append(texto[:max_celdas_texto])
            fila = tuple(textos)
            if len(fila) >= 2 and fila not in vistos:
                filas.append(list(fila))
                vistos.add(fila)

    if not filas:
        return []
    return [{
        "filas": filas[:max_filas],
        "truncada": len(filas) > max_filas,
        "total_filas_original": len(filas),
        "tipo": "indicadores_estadisticos",
    }]


def extraer_iframes(soup, url_pagina):
    """Devuelve URLs de documentos o visores embebidos en iframes."""
    iframes = []
    vistos = set()
    for iframe in soup.find_all('iframe', src=True):
        url_iframe = urljoin(url_pagina, iframe['src'].strip())
        if url_iframe in vistos:
            continue
        vistos.add(url_iframe)
        if url_iframe.startswith(('http://', 'https://')):
            iframes.append({
                "url": url_iframe,
                "titulo": iframe.get('title', '').strip() or "Documento embebido",
            })
    return iframes


def guardar_tablas_csv(tablas, nombre_pagina, tables_dir, contador_global):
    import os
    os.makedirs(tables_dir, exist_ok=True)
    rutas = []
    for i, tabla in enumerate(tablas):
        contador_global[0] += 1
        nombre_archivo = f"{normalizar_nombre(nombre_pagina)}_tabla{i + 1}_{contador_global[0]}.csv"
        ruta = f"{tables_dir}/{nombre_archivo}"
        try:
            with open(ruta, "w", newline='', encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerows(tabla["filas"])
            rutas.append(ruta)
        except Exception as e:
            print(f"  No se pudo guardar la tabla como CSV: {e}")
    return rutas


# --------------------------------------------------------------------------
# Rastreo recursivo
# --------------------------------------------------------------------------

def es_documento_valido(href_lower, texto, extensiones, palabras_clave):
    if any(href_lower.endswith('.' + ext) or f'.{ext}?' in href_lower or f'.{ext}#' in href_lower
           for ext in extensiones):
        return True
    if palabras_clave and contiene_alguna(texto, palabras_clave):
        return True
    return False


def construir_ruta_jerarquica(url_absoluta, nombre_pagina):
    path_decoded = unquote(urlparse(url_absoluta).path)
    partes = [p for p in path_decoded.split('/') if p]

    if len(partes) >= 2:
        intermedios = partes[:-1][-3:]
        while len(intermedios) < 3:
            intermedios = [normalizar_nombre(nombre_pagina)] + intermedios
        nivel2, nivel3, nivel4 = [normalizar_nombre(p) for p in intermedios]
        nombre_archivo = partes[-1]
    else:
        nivel2 = normalizar_nombre(nombre_pagina)
        nivel3 = "DOCUMENTOS"
        nivel4 = "VARIOS"
        nombre_archivo = partes[-1] if partes else normalizar_nombre(url_absoluta)

    return nivel2, nivel3, nivel4, nombre_archivo


def escanear_pagina(macro_seccion, nombre_pagina, url_pagina, mapa_documentos,
                     paginas_relevantes, extensiones, palabras_clave_doc,
                     include_keywords, exclude_keywords, keep_extension,
                     forced_extension, export_tables_csv, tables_dir,
                     contador_tablas):
    try:
        soup = BeautifulSoup(obtener_html(url_pagina), 'html.parser')
        cerrar_modales(soup)
    except Exception as e:
        print(f"Error al procesar la página [{nombre_pagina}]: {e}")
        return []

    enlaces_para_seguir = []
    base_netloc = urlparse(url_pagina).netloc
    mapa_documentos.setdefault(macro_seccion, {})

    # --- A) Documentos descargables ---
    for e in soup.find_all('a', href=True):
        href_original = e['href']
        href_lower = href_original.lower()
        texto_documento = e.get_text(strip=True)
        url_absoluta = urljoin(url_pagina, href_original)

        if href_lower.startswith('#') or href_lower.startswith('javascript:'):
            continue
        if not texto_documento:
            texto_documento = href_original.rsplit('/', 1)[-1]
        if es_excluida(texto_documento, url_absoluta, exclude_keywords):
            continue

        if es_documento_valido(href_lower, texto_documento, extensiones, palabras_clave_doc):
            nivel2, nivel3, nivel4, nombre_archivo = construir_ruta_jerarquica(url_absoluta, nombre_pagina)
            nombre_base, ext_original = (nombre_archivo.rsplit('.', 1) + [''])[:2] \
                if '.' in nombre_archivo else (nombre_archivo, '')

            if forced_extension:
                nivel5 = f"{normalizar_nombre(nombre_base)}.{forced_extension}"
            elif keep_extension and ext_original:
                nivel5 = f"{normalizar_nombre(nombre_base)}.{ext_original}"
            else:
                nivel5 = normalizar_nombre(nombre_base) or normalizar_nombre(nombre_archivo)

            mapa_documentos[macro_seccion].setdefault(nivel2, {})
            mapa_documentos[macro_seccion][nivel2].setdefault(nivel3, {})
            mapa_documentos[macro_seccion][nivel2][nivel3].setdefault(nivel4, {})
            mapa_documentos[macro_seccion][nivel2][nivel3][nivel4].setdefault(nivel5, {
                "descripcion": texto_documento,
                "url_descarga": url_absoluta,
            })
        elif mismo_dominio(url_absoluta, base_netloc):
            enlaces_para_seguir.append((texto_documento or nombre_pagina, url_absoluta))

    # --- B) Documentos o visores embebidos ---
    for iframe in extraer_iframes(soup, url_pagina):
        url_iframe = iframe["url"]
        nivel2, nivel3, nivel4, nombre_archivo = construir_ruta_jerarquica(url_iframe, nombre_pagina)
        nombre_base = normalizar_nombre(nombre_archivo or "documento_embebido")
        mapa_documentos[macro_seccion].setdefault(nivel2, {})
        mapa_documentos[macro_seccion][nivel2].setdefault(nivel3, {})
        mapa_documentos[macro_seccion][nivel2][nivel3].setdefault(nivel4, {})
        mapa_documentos[macro_seccion][nivel2][nivel3][nivel4].setdefault(nombre_base, {
            "descripcion": iframe["titulo"],
            "url_descarga": url_iframe,
            "tipo": "iframe",
        })

    # --- C) Reportes embebidos directamente en el HTML ---
    tablas = extraer_tablas(soup)
    tablas += extraer_bloques_elementor(soup)
    tablas += extraer_contadores_elementor(soup)
    tablas += extraer_bloques_estadisticos(soup)
    titulo_pagina = soup.title.get_text(strip=True) if soup.title else nombre_pagina
    parece_reporte = contiene_alguna(nombre_pagina, include_keywords) or \
        contiene_alguna(titulo_pagina, include_keywords)

    if tablas or parece_reporte:
        entrada = {
            "pagina": nombre_pagina,
            "titulo": titulo_pagina,
            "url": url_pagina,
            "coincide_palabra_clave": parece_reporte,
            "num_tablas_detectadas": len(tablas),
        }
        if tablas:
            if export_tables_csv:
                rutas = guardar_tablas_csv(tablas, nombre_pagina, tables_dir, contador_tablas)
                entrada["tablas_csv"] = rutas
            else:
                entrada["tablas"] = tablas
        # Solo se registra si tiene tablas reales o si coincide claramente
        # con una palabra clave de reporte (evita ruido de páginas vacías).
        if tablas or parece_reporte:
            paginas_relevantes.append(entrada)

    return enlaces_para_seguir


def rastrear(base_url, max_depth, extensiones, palabras_clave_doc,
             include_keywords, exclude_keywords, delay, keep_extension,
             forced_extension, ignorar_robots, max_paginas,
             export_tables_csv, tables_dir):
    robot_parser = cargar_robots(base_url)
    visitadas = set()
    mapa_documentos = {}
    paginas_relevantes = []
    contador_tablas = [0]

    menu = descubrir_enlaces_menu(base_url, exclude_keywords)
    cola = [(nombre, nombre, url, 1) for nombre, url in menu.items()]
    paginas_procesadas = 0

    while cola:
        macro_seccion, nombre_pagina, url_pagina, profundidad = cola.pop(0)

        if url_pagina in visitadas:
            continue
        if max_paginas and paginas_procesadas >= max_paginas:
            print(f"Límite de {max_paginas} páginas alcanzado; deteniendo el rastreo.")
            break
        if not puede_rastrear(url_pagina, robot_parser, ignorar_robots):
            print(f"robots.txt prohíbe rastrear: {url_pagina}")
            continue
        if es_excluida(nombre_pagina, url_pagina, exclude_keywords):
            print(f"Omitida por palabra clave de exclusión: {nombre_pagina}")
            continue

        visitadas.add(url_pagina)
        paginas_procesadas += 1
        print(f"[prof. {profundidad}] Indexando: {nombre_pagina} -> {url_pagina}")

        enlaces_para_seguir = escanear_pagina(
            macro_seccion, nombre_pagina, url_pagina, mapa_documentos,
            paginas_relevantes, extensiones, palabras_clave_doc,
            include_keywords, exclude_keywords, keep_extension,
            forced_extension, export_tables_csv, tables_dir, contador_tablas,
        )

        if profundidad < max_depth:
            for nombre_enlace, url_enlace in enlaces_para_seguir:
                if url_enlace not in visitadas and not es_excluida(nombre_enlace, url_enlace, exclude_keywords):
                    cola.append((macro_seccion, nombre_enlace, url_enlace, profundidad + 1))

        time.sleep(delay)

    return mapa_documentos, paginas_relevantes


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(description="Rastreador genérico de reportes para sitios web.")
    parser.add_argument('--url', default='https://www.bcb.gob.bo/')
    parser.add_argument('--depth', type=int, default=2)
    parser.add_argument('--extensions', default='xlsx,xls,csv,sav,pdf,docx,doc,zip,pptx,ppt')
    parser.add_argument('--keywords', default='',
                         help='Palabras clave extra para detectar documentos sin extensión reconocible')
    parser.add_argument('--exclude-keywords', default='',
                            help='Palabras clave a excluir (cadena separada por comas o ruta a un archivo .txt)',)
    parser.add_argument('--include-keywords', default='',
                         help='Palabras clave extra que marcan una página como reporte, '
                              'además de la lista por defecto')
    parser.add_argument('--no-default-excludes', action='store_true',
                         help='No usar la lista de exclusión por defecto, solo --exclude-keywords')
    parser.add_argument('--no-default-includes', action='store_true',
                         help='No usar la lista de inclusión por defecto, solo --include-keywords')
    parser.add_argument('--delay', type=float, default=1.0)
    parser.add_argument('--output', default='mapa_global.json')
    parser.add_argument('--keep-extension', action='store_true')
    parser.add_argument('--force-extension', default='')
    parser.add_argument('--ignore-robots', action='store_true')
    parser.add_argument('--max-pages', type=int, default=300)
    parser.add_argument('--export-tables-csv', action='store_true',
                         help='Guarda cada tabla HTML detectada como un .csv aparte '
                              'en vez de incrustarla en el JSON de salida')
    parser.add_argument('--tables-dir', default='tablas_extraidas')
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    extensiones = [e.strip().lower().lstrip('.') for e in args.extensions.split(',') if e.strip()]
    palabras_clave_doc = [k.strip().lower() for k in args.keywords.split(',') if k.strip()]

    exclude_keywords = [] if args.no_default_excludes else list(DEFAULT_EXCLUDE_KEYWORDS)
    exclude_keywords += cargar_palabras_clave(args.exclude_keywords)
    include_keywords = [] if args.no_default_includes else list(DEFAULT_INCLUDE_KEYWORDS)
    include_keywords += cargar_palabras_clave(args.include_keywords)

    print(f"Sitio base: {args.url}")
    print(f"Profundidad máxima: {args.depth}")
    print(f"Extensiones consideradas: {extensiones}")
    print(f"Palabras de exclusión activas: {len(exclude_keywords)}")
    print(f"Palabras de inclusión (reportes) activas: {len(include_keywords)}")

    mapa_documentos, paginas_relevantes = rastrear(
        base_url=args.url,
        max_depth=args.depth,
        extensiones=extensiones,
        palabras_clave_doc=palabras_clave_doc,
        include_keywords=include_keywords,
        exclude_keywords=exclude_keywords,
        delay=args.delay,
        keep_extension=args.keep_extension,
        forced_extension=args.force_extension.strip().lstrip('.').lower(),
        ignorar_robots=args.ignore_robots,
        max_paginas=args.max_pages,
        export_tables_csv=args.export_tables_csv,
        tables_dir=args.tables_dir,
    )

    resultado_final = {
        "documentos": mapa_documentos,
        "paginas_con_contenido_relevante": paginas_relevantes,
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(resultado_final, f, ensure_ascii=False, indent=4)

    print(f"\n¡Listo! {len(paginas_relevantes)} páginas con contenido HTML relevante detectadas.")
    print(f"Resultado guardado en '{args.output}'.")
