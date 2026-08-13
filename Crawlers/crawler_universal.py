"""
Crawler universal configurable por fuente.

Un solo motor para todas las fuentes: se le cambia la entrada en `fuentes.json` y
mapea el sitio sin tocar el codigo. Cubre RF-06 a RF-09 y US-01 del proyecto.

Que hace por cada fuente:
  1. Descubre las paginas internas recorriendo el sitio en anchura (BFS acotado).
  2. Recolecta los enlaces a archivos descargables de cada pagina.
  3. Extrae la fecha visible mas cercana al enlace y la normaliza a AAAA-MM-DD.
  4. Resuelve tipo y tamaño del archivo, e indexa el contenido de los comprimidos.
  5. Infiere periodicidad y etiquetas de busqueda (tags).
  6. Emite el JSON jerarquico de 5 niveles del contrato comun.

No descarga los archivos: solo los indexa. La unica excepcion son los comprimidos,
que se bajan para poder listar lo que traen adentro.

Uso:
    python Crawlers/crawler_universal.py                  # todas las fuentes del config
    python Crawlers/crawler_universal.py aps bcb          # solo las indicadas
    python Crawlers/crawler_universal.py --listar         # ver que fuentes hay
"""

import sys
import json
import re
import os
import time
import argparse
import zipfile
import io
import requests
import urllib3
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlsplit, urlunsplit, unquote, quote
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from functools import partial

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

DIRECTORIO = os.path.dirname(os.path.abspath(__file__))
CONFIG_POR_DEFECTO = os.path.join(DIRECTORIO, "fuentes.json")

EXTENSIONES_DESCARGABLES = (
    '.pdf', '.xlsx', '.xls', '.csv', '.doc', '.docx',
    '.sav', '.dta', '.zip', '.rar', '.7z', '.txt', '.xml',
)

EXTENSIONES_COMPRIMIDAS = ('.zip',)

# Paginas que no vale la pena recorrer: buscadores, vistas de impresion, sesiones
PATRONES_EXCLUIDOS = (
    'component/finder', 'tmpl=component', 'task=suggestions',
    'format=opensearch', 'format=feed', '/login', 'logout',
    'mailto:', 'javascript:', 'whatsapp.com', 'facebook.com',
    'twitter.com', 'youtube.com', 'instagram.com', 'linkedin.com',
)

TIEMPO_ESPERA = 25
PAUSA_ENTRE_PAGINAS = 0.4
HILOS_METADATOS = 6

# Tamaño maximo que se baja para abrir un comprimido; por encima solo se indexa el .zip
LIMITE_COMPRIMIDO_BYTES = 25 * 1024 * 1024

NIVEL_POR_DEFECTO_2 = "GENERAL"
NIVEL_POR_DEFECTO_3 = "DOCUMENTOS"
NIVEL_POR_DEFECTO_4 = "ARCHIVOS"

# Periodicidad declarada por la fuente en el texto del enlace o en la ruta (US-03 ampliado)
PATRONES_PERIODICIDAD = (
    ("diaria", r'\bdiari[ao]s?\b|\bdaily\b|\bpor d[ií]a\b'),
    ("semanal", r'\bsemanal(es)?\b|\bweekly\b'),
    ("quincenal", r'\bquincenal(es)?\b'),
    ("mensual", r'\bmensual(es)?\b|\bmonthly\b|\bpor mes\b'),
    ("bimestral", r'\bbimestral(es)?\b'),
    ("trimestral", r'\btrimestral(es)?\b|\bquarterly\b|\btrimestre\b'),
    ("semestral", r'\bsemestral(es)?\b|\bsemestre\b'),
    ("anual", r'\banual(es)?\b|\byearly\b|\bannual\b|\bgesti[óo]n\b'),
)

# Vocabulario para las etiquetas automaticas. La parte manual se agrega por fuente
# en `fuentes.json` (clave `tags`), que es lo acordado: una parte se infiere y otra
# se carga a mano.
VOCABULARIO_TAGS = {
    "pensiones": r'\bpensi[oó]n(es)?\b|\bjubilaci[oó]n\b|\brenta dignidad\b|\bafp\b',
    "seguros": r'\bseguros?\b|\bp[oó]liza(s)?\b|\breaseguro\b|\bsoat\b',
    "normativa": r'\bley(es)?\b|\bdecreto\b|\bresoluci[oó]n\b|\breglamento\b|\bcircular\b|\bnormativa\b',
    "estadisticas": r'\bestad[ií]stica(s)?\b|\bindicador(es)?\b|\bserie(s)?\b|\bboletin\b',
    "tasas-de-interes": r'\btasa(s)? de inter[eé]s\b|\btasa(s)? activa\b|\btasa(s)? pasiva\b|\btre\b',
    "tipo-de-cambio": r'\btipo de cambio\b|\bd[oó]lar\b|\bcambiari[ao]\b|\bufv\b',
    "inflacion": r'\binflaci[oó]n\b|\bipc\b|\b[íi]ndice de precios\b',
    "comercio-exterior": r'\bexportaci[oó]n(es)?\b|\bimportaci[oó]n(es)?\b|\bcomercio exterior\b|\baranc',
    "monetario": r'\bmonetari[ao]\b|\boma\b|\bmercado abierto\b|\breservas internacionales\b',
    "fiscal": r'\bfiscal\b|\bpresupuesto\b|\bdeuda p[uú]blica\b|\brecaudaci[oó]n\b',
    "financiero": r'\bfinancier[ao]s?\b|\bbanc[ao]s?\b|\bcr[eé]dito\b|\bdep[oó]sito(s)?\b|\bcartera\b',
    "transparencia": r'\btransparencia\b|\brendici[oó]n de cuentas\b|\bauditor[ií]a\b|\bpoa\b',
    "agropecuario": r'\bagr[ií]cola\b|\bagropecuari[ao]\b|\bganader[ií]a\b|\bcultivo\b|\bsoya\b|\btrigo\b',
    "energia": r'\bhidrocarburo(s)?\b|\benerg[ií]a\b|\bel[eé]ctric[ao]\b|\bgas\b|\bpetr[oó]leo\b',
    "mineria": r'\bminer[ií]a\b|\bmineral(es)?\b|\bmetal[uú]rgic[ao]\b',
    "empleo": r'\bempleo\b|\bdesempleo\b|\blaboral\b|\bsalario\b',
    "demografia": r'\bpoblaci[oó]n\b|\bcenso\b|\bdemogr[aá]fic[ao]\b|\bvivienda\b',
    "salud": r'\bsalud\b|\bepidemiol[oó]gic[ao]\b|\bhospital\b',
    "educacion": r'\beducaci[oó]n\b|\bescolar\b|\bestudiantes?\b',
}

PATRON_FECHA_LATINA = re.compile(r'(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})')
PATRON_FECHA_ISO = re.compile(r'(\d{4})-(\d{2})-(\d{2})')
PATRON_ANIO = re.compile(r'\b(19[5-9]\d|20[0-4]\d)\b')

MESES = {
    'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4, 'mayo': 5, 'junio': 6,
    'julio': 7, 'agosto': 8, 'septiembre': 9, 'setiembre': 9, 'octubre': 10,
    'noviembre': 11, 'diciembre': 12,
}
PATRON_FECHA_TEXTO = re.compile(
    r'(\d{1,2})\s+de\s+(' + '|'.join(MESES) + r')\s+de\s+(\d{4})', re.IGNORECASE
)


def obtener_headers():
    return {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
    }


# Set completo de cabeceras de navegador. Algunos WAF (Akamai en el FMI, por ejemplo)
# devuelven 403 si falta cualquiera de estas; con el set completo responden normal.
HEADERS_COMPLETOS = {
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


def normalizar_nombre(texto):
    texto = unquote(texto).strip()
    texto = re.sub(r'[\s/\\:]+', '_', texto)
    texto = re.sub(r'_+', '_', texto)
    return texto.strip('_') or "SIN_NOMBRE"


def normalizar_url(url):
    """Codifica la ruta para que la URL sea valida y estable entre corridas.

    Evita que el motor de conciliacion lea como 'URL modificada' lo que en realidad
    es el servidor normalizando espacios (RF-04).
    """
    partes = urlsplit(url)
    return urlunsplit((
        partes.scheme, partes.netloc,
        quote(unquote(partes.path), safe="/()"),
        partes.query, '',
    ))


def normalizar_fecha(texto):
    """Devuelve la primera fecha reconocible del texto en formato AAAA-MM-DD."""
    if not texto:
        return None

    coincidencia = PATRON_FECHA_ISO.search(texto)
    if coincidencia:
        anio, mes, dia = (int(g) for g in coincidencia.groups())
        if 1 <= mes <= 12 and 1 <= dia <= 31:
            return f"{anio:04d}-{mes:02d}-{dia:02d}"

    coincidencia = PATRON_FECHA_TEXTO.search(texto)
    if coincidencia:
        dia, mes, anio = coincidencia.groups()
        return f"{int(anio):04d}-{MESES[mes.lower()]:02d}-{int(dia):02d}"

    coincidencia = PATRON_FECHA_LATINA.search(texto)
    if coincidencia:
        dia, mes, anio = (int(g) for g in coincidencia.groups())
        if anio < 100:
            anio += 1900 if anio > 50 else 2000
        if 1 <= mes <= 12 and 1 <= dia <= 31:
            return f"{anio:04d}-{mes:02d}-{dia:02d}"

    return None


def fecha_cercana(enlace):
    """Busca la fecha visible mas proxima al enlace.

    Se sube por el arbol desde el <a>: primero su fila o item, despues el
    contenedor. Es la unica forma agnostica de asociar la fecha a un archivo
    cuando cada fuente la maqueta distinto.
    """
    nodo = enlace
    for _ in range(4):
        nodo = nodo.parent
        if nodo is None:
            break
        fecha = normalizar_fecha(nodo.get_text(' ', strip=True))
        if fecha:
            return fecha
    return None


def anio_de_respaldo(texto):
    """Si no hay fecha completa, un año suelto en el nombre ya ubica el dato."""
    coincidencia = PATRON_ANIO.search(texto or '')
    return f"{coincidencia.group(1)}-01-01" if coincidencia else None


def inferir_periodicidad(*textos):
    blob = ' '.join(t for t in textos if t).lower()
    for nombre, patron in PATRONES_PERIODICIDAD:
        if re.search(patron, blob):
            return nombre
    return None


def generar_tags(textos, tags_manuales):
    """Etiquetas de busqueda: las que se infieren del texto mas las cargadas a mano."""
    blob = ' '.join(t for t in textos if t).lower()
    tags = {t for t, patron in VOCABULARIO_TAGS.items() if re.search(patron, blob)}
    tags.update(tags_manuales)
    return sorted(tags)


def tipo_archivo_desde_url(url):
    nombre = os.path.basename(unquote(urlsplit(url).path))
    return nombre.rsplit('.', 1)[-1].lower() if '.' in nombre else "desconocido"


def nombre_archivo_desde_url(url):
    nombre = os.path.basename(unquote(urlsplit(url).path))
    return normalizar_nombre(nombre) if nombre else "documento"


def es_descargable(url):
    return unquote(urlsplit(url).path).lower().endswith(EXTENSIONES_DESCARGABLES)


def es_comprimido(url):
    return unquote(urlsplit(url).path).lower().endswith(EXTENSIONES_COMPRIMIDAS)


def excluido(url):
    minuscula = url.lower()
    return any(patron in minuscula for patron in PATRONES_EXCLUIDOS)


# Carpetas del repositorio de archivos, no secciones del sitio: no deben dar nombre a un nivel
SEGMENTOS_TECNICOS = {
    'index.php', 'index.html', 'images', 'img', 'files', 'file', 'webdocs',
    'media', 'sites', 'default', 'uploads', 'upload', 'assets', 'docs',
    'documentos', 'attachments', 'adjuntos', 'storage', 'download', 'descargas',
    'wp-content', 'content', 'public', 'static', 'data',
}


def segmentos_de(url, filtrar_tecnicos=True):
    """Segmentos utiles de la ruta, que son los que dan estructura al arbol."""
    ruta = unquote(urlsplit(url).path)
    partes = [p for p in ruta.split('/') if p]
    if partes and '.' in partes[-1]:
        partes = partes[:-1]
    if filtrar_tecnicos:
        partes = [p for p in partes if p.lower() not in SEGMENTOS_TECNICOS]
    return partes


# --------------------------------------------------------------------------
# Sondas de plataforma (estandares web, agnosticas de la fuente)
# --------------------------------------------------------------------------

# Señales de que la pagina arma su contenido por JavaScript contra un API:
# si aparecen, el HTML estatico no cuenta la historia completa.
PATRON_API_EMBEBIDA = re.compile(r'https?://[^"\'\s<>]{4,150}/api/[^"\'\s<>]{2,100}')
PATRON_CONTENIDO_DINAMICO = re.compile(r'\{\{[^}]{1,80}\}\}|ng-app|ng-controller|__NEXT_DATA__|v-for=')


def sondear_wordpress(base, sesion, estado, resumen):
    """Si el sitio es WordPress, su API de medios lista TODOS los archivos subidos,
    incluso los que el HTML no enlaza (visores JS, migraciones que rompieron enlaces).
    Es un estandar de la plataforma, no algo propio de una fuente.
    """
    archivos = {}
    for pagina in range(1, 6):
        url = f"{base}/wp-json/wp/v2/media?media_type=application&per_page=100&page={pagina}"
        try:
            r = sesion.get(url, headers=estado['headers'], timeout=TIEMPO_ESPERA,
                           verify=estado['ssl'])
            if r.status_code != 200 or 'json' not in (r.headers.get('content-type') or ''):
                break
            items = r.json()
            if not isinstance(items, list) or not items:
                break
        except Exception:
            break

        for item in items:
            url_archivo = (item.get('source_url') or '').strip()
            if not url_archivo or not es_descargable(url_archivo):
                continue
            titulo = ((item.get('title') or {}).get('rendered') or '').strip()
            fecha = normalizar_fecha(item.get('date') or '')
            archivos[normalizar_url(url_archivo)] = {
                "descripcion": titulo or nombre_archivo_desde_url(url_archivo),
                "fecha": fecha,
                "url_pagina": base,
            }
        time.sleep(PAUSA_ENTRE_PAGINAS)

    if archivos:
        resumen["plataforma"] = "wordpress"
        print(f"  Sonda WordPress: {len(archivos)} archivos en el API de medios")
    return archivos


def sondear_sitemaps(base, sesion, estado, dominio_valido):
    """Los sitemaps declaran paginas que el menu no enlaza. Se leen robots.txt y las
    rutas estandar; devuelve paginas para sembrar el recorrido y archivos directos.
    """
    candidatas = [f"{base}/sitemap.xml", f"{base}/sitemap_index.xml", f"{base}/wp-sitemap.xml"]
    try:
        r = sesion.get(f"{base}/robots.txt", headers=estado['headers'], timeout=15,
                       verify=estado['ssl'])
        if r.status_code == 200:
            candidatas = re.findall(r'(?im)^sitemap:\s*(\S+)', r.text) + candidatas
    except Exception:
        pass

    urls, pendientes, leidos = [], list(dict.fromkeys(candidatas)), 0
    while pendientes and leidos < 6:
        sm = pendientes.pop(0)
        try:
            r = sesion.get(sm, headers=estado['headers'], timeout=20, verify=estado['ssl'])
            if r.status_code != 200:
                continue
            leidos += 1
            encontradas = re.findall(r'<loc>\s*([^<\s]+)\s*</loc>', r.text)
            if '<sitemapindex' in r.text:
                pendientes = encontradas[:5] + pendientes
            else:
                urls.extend(encontradas)
        except Exception:
            continue

    semillas, archivos = [], []
    for u in urls[:500]:
        if not dominio_valido(urlsplit(u).netloc):
            continue
        (archivos if es_descargable(u) else semillas).append(u)
    return semillas[:40], archivos


def detectar_apis(paginas, resumen):
    """Busca URLs de API embebidas en el HTML (el patron de las tablas Angular/AJAX):
    no las consume, pero las reporta como candidatas a modulo especifico.
    """
    apis = set()
    dinamico = False
    for html in paginas.values():
        if not dinamico and PATRON_CONTENIDO_DINAMICO.search(html):
            dinamico = True
        for m in PATRON_API_EMBEBIDA.findall(html):
            apis.add(m.split('?')[0])
            if len(apis) >= 8:
                break
    if dinamico:
        resumen["contenido_dinamico"] = True
    if apis:
        resumen["apis_detectadas"] = sorted(apis)


# --------------------------------------------------------------------------
# Descubrimiento del sitio
# --------------------------------------------------------------------------

def descargar_pagina(url, sesion, estado, resumen):
    """Descarga una pagina HTML recuperandose de los bloqueos tipicos.

    - SSLError con certificado invalido: reintenta sin verificar y lo deja
      registrado en el resumen (no inventamos seguridad que la fuente no tiene).
    - 403 de un WAF: reintenta una vez con el set completo de cabeceras de
      navegador; si funciona, ese set queda activo para el resto del recorrido.
    Ambas decisiones son por corrida y quedan reportadas.
    """
    def pedir():
        return sesion.get(url, headers=estado['headers'], timeout=TIEMPO_ESPERA,
                          verify=estado['ssl'])

    try:
        try:
            respuesta = pedir()
        except requests.exceptions.SSLError:
            if not estado['ssl']:
                return None
            estado['ssl'] = False
            resumen['ssl_invalido'] = True
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            respuesta = pedir()

        if respuesta.status_code == 403 and not estado['headers_completos']:
            estado['headers'] = dict(HEADERS_COMPLETOS)
            estado['headers_completos'] = True
            respuesta = pedir()
            if respuesta.status_code == 200:
                resumen['bloqueo_evitado'] = True

        tipo = (respuesta.headers.get('content-type') or '').lower()
        if respuesta.status_code != 200 or 'html' not in tipo:
            return None
        return respuesta.text
    except Exception:
        return None


def crear_validador_dominio(config):
    """Muchas fuentes sirven los archivos desde otro subdominio (repositorio.*, api.*).
    `dominios_permitidos` amplia el recorrido a esos sufijos sin abrir la puerta a
    cualquier sitio enlazado.
    """
    dominio = urlsplit(config['url_base'].rstrip('/')).netloc.lower()
    permitidos = tuple(d.lower().lstrip('.') for d in config.get('dominios_permitidos', []))

    def dominio_valido(netloc):
        netloc = netloc.lower()
        if netloc == dominio:
            return True
        for sufijo in permitidos:
            if netloc == sufijo or netloc.endswith('.' + sufijo):
                return True
        return False

    return dominio_valido


def descubrir(config, sesion, estado, resumen, semillas_extra=()):
    """Recorrido en anchura del sitio, acotado por profundidad y cantidad de paginas.

    Devuelve {url_pagina: html}. El limite de paginas es lo que evita el bucle
    infinito que menciona US-01 y protege a la fuente de un barrido desmedido.
    """
    base = config['url_base'].rstrip('/')
    profundidad_max = config.get('profundidad_max', 2)
    paginas_max = config.get('paginas_max', 80)
    extra_excluir = tuple(p.lower() for p in config.get('excluir', []))
    dominio_valido = crear_validador_dominio(config)

    semillas = [base] + [urljoin(base + '/', r) for r in config.get('rutas_semilla', [])]
    semillas += [u for u in semillas_extra if u not in semillas]
    pendientes = deque((u, 0) for u in semillas)
    vistas = set(semillas)
    paginas = {}

    while pendientes and len(paginas) < paginas_max:
        url, profundidad = pendientes.popleft()
        html = descargar_pagina(url, sesion, estado, resumen)
        time.sleep(PAUSA_ENTRE_PAGINAS)
        if html is None:
            resumen["paginas_fallidas"] += 1
            continue

        paginas[url] = html

        if profundidad >= profundidad_max:
            continue

        for enlace in BeautifulSoup(html, 'html.parser').find_all('a', href=True):
            destino = urljoin(url, enlace['href']).split('#')[0].rstrip('/')
            if not dominio_valido(urlsplit(destino).netloc):
                continue
            if destino in vistas or excluido(destino):
                continue
            if any(p in destino.lower() for p in extra_excluir):
                continue
            if es_descargable(destino):
                continue
            vistas.add(destino)
            pendientes.append((destino, profundidad + 1))

    resumen["paginas_visitadas"] = len(paginas)
    return paginas


# --------------------------------------------------------------------------
# Extraccion de archivos
# --------------------------------------------------------------------------

def extraer_de_pagina(url_pagina, html, base):
    """Enlaces descargables de una pagina, con su texto y la fecha mas cercana."""
    encontrados = {}
    for enlace in BeautifulSoup(html, 'html.parser').find_all('a', href=True):
        destino = normalizar_url(urljoin(url_pagina, enlace['href']).split('#')[0])
        if not es_descargable(destino) or excluido(destino):
            continue

        texto = enlace.get_text(' ', strip=True)
        # "Ver", "Descargar" y similares no describen nada: se usa la fila completa
        if len(texto) < 6:
            contenedor = enlace.find_parent(['tr', 'li', 'p', 'div'])
            if contenedor is not None:
                texto = contenedor.get_text(' ', strip=True)[:220] or texto

        encontrados[destino] = {
            "descripcion": texto or nombre_archivo_desde_url(destino),
            "fecha": fecha_cercana(enlace),
            "url_pagina": url_pagina,
        }
    return encontrados


def resolver_metadatos(item, verificar_ssl=True):
    """Tamaño y disponibilidad reales, por HEAD. No descarga el archivo.

    Algunos servidores rechazan HEAD pero sirven GET: se reintenta con GET en
    streaming (solo cabeceras, la conexion se cierra sin leer el cuerpo).
    """
    url, datos = item
    try:
        respuesta = requests.head(url, headers=obtener_headers(), timeout=TIEMPO_ESPERA,
                                  allow_redirects=True, verify=verificar_ssl)
        if respuesta.status_code in (403, 405, 501):
            respuesta = requests.get(url, headers=obtener_headers(), timeout=TIEMPO_ESPERA,
                                     stream=True, verify=verificar_ssl)
            respuesta.close()
        longitud = respuesta.headers.get('content-length')
        datos["http"] = respuesta.status_code
        datos["tamanio"] = int(longitud) if longitud and longitud.isdigit() else None
    except Exception:
        datos["http"] = None
        datos["tamanio"] = None
    return url, datos


def listar_comprimido(url, tamanio, verificar_ssl=True):
    """Lista lo que trae un comprimido.

    Es el unico caso en que se baja el archivo: sin abrirlo, el mapa diria
    "un .zip" y esconderia los documentos reales que la fuente publica adentro.
    """
    if tamanio and tamanio > LIMITE_COMPRIMIDO_BYTES:
        return []
    try:
        respuesta = requests.get(url, headers=obtener_headers(), timeout=90, verify=verificar_ssl)
        if respuesta.status_code != 200:
            return []
        with zipfile.ZipFile(io.BytesIO(respuesta.content)) as comprimido:
            return [
                (info.filename, info.file_size)
                for info in comprimido.infolist()
                if not info.is_dir()
            ]
    except Exception:
        return []


# --------------------------------------------------------------------------
# Construccion del arbol
# --------------------------------------------------------------------------

def insertar(nodo_raiz, niveles, hoja, resumen):
    nodo = nodo_raiz
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


def niveles_para(url_archivo, url_pagina):
    """Los niveles 2 a 4 salen de la navegacion del sitio, no de la ruta del archivo.

    Reflejan como la fuente organiza su contenido, que es mas legible que los
    segmentos crudos del repositorio de archivos.
    """
    segmentos = segmentos_de(url_pagina) or segmentos_de(url_archivo)
    nivel2 = normalizar_nombre(segmentos[0]).upper() if len(segmentos) > 0 else NIVEL_POR_DEFECTO_2
    nivel3 = normalizar_nombre(segmentos[1]) if len(segmentos) > 1 else NIVEL_POR_DEFECTO_3
    nivel4 = normalizar_nombre(segmentos[2]) if len(segmentos) > 2 else NIVEL_POR_DEFECTO_4
    return [nivel2, nivel3, nivel4]


def construir_hoja(config, url, datos, tags_manuales, dentro_de=None):
    descripcion = datos["descripcion"]
    fecha = datos.get("fecha") or anio_de_respaldo(descripcion) or anio_de_respaldo(url)
    textos = (descripcion, unquote(url), datos.get("url_pagina", ''))

    # Para un archivo que viene dentro de un comprimido, el tipo es el suyo, no el del .zip
    tipo = tipo_archivo_desde_url(dentro_de) if dentro_de else tipo_archivo_desde_url(url)

    hoja = {
        "descripcion": descripcion,
        "url_descarga": url,
        "fecha_actualizacion": fecha,
        "fecha_ultimo_dato": fecha,
        "tipo_archivo": tipo,
        "id_fuente": config["id_fuente"],
        "url_origen": datos.get("url_pagina", config["url_base"]),
        "entidad_emisora": config.get("entidad_emisora", config["id_fuente"].upper()),
        "periodicidad": inferir_periodicidad(*textos) or config.get("periodicidad"),
        "tags": generar_tags(textos, tags_manuales),
    }
    if datos.get("tamanio"):
        hoja["tamanio_bytes"] = datos["tamanio"]
    if dentro_de:
        # Permite al descargador saber que el archivo no se pide suelto sino dentro del comprimido
        hoja["contenido_en"] = dentro_de
    return hoja


# --------------------------------------------------------------------------
# Motor por fuente
# --------------------------------------------------------------------------

def mapear_fuente(config):
    resumen = {
        "documentos": 0, "duplicados": 0, "renombrados": 0,
        "paginas_visitadas": 0, "paginas_fallidas": 0,
        "enlaces_rotos": 0, "comprimidos": 0, "dentro_de_comprimidos": 0,
        "bytes": 0,
    }

    raiz = config.get("raiz") or f"{config['id_fuente'].upper()}"
    arbol = {raiz: {}}
    base = config['url_base'].rstrip('/')
    tags_manuales = config.get("tags", [])
    dominio_valido = crear_validador_dominio(config)

    # Estado HTTP mutable de la corrida: si un WAF exige headers completos o el
    # certificado es invalido, el ajuste se hace una vez y persiste el resto.
    estado = {
        "headers": obtener_headers(),
        "headers_completos": False,
        "ssl": config.get("verificar_ssl", True),
    }
    if not estado["ssl"]:
        resumen['ssl_invalido'] = True
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    sesion = requests.Session()

    # Sondas de plataforma antes del recorrido: sitemaps para sembrar paginas que el
    # menu no enlaza, y el API de medios si el sitio es WordPress.
    archivos_wp = sondear_wordpress(base, sesion, estado, resumen)
    semillas_sitemap, archivos_sitemap = sondear_sitemaps(base, sesion, estado, dominio_valido)
    if semillas_sitemap:
        print(f"  Sonda sitemap: {len(semillas_sitemap)} paginas y {len(archivos_sitemap)} archivos declarados")

    print(f"  Descubriendo paginas (profundidad {config.get('profundidad_max', 2)}, "
          f"tope {config.get('paginas_max', 80)})...")
    paginas = descubrir(config, sesion, estado, resumen, semillas_extra=semillas_sitemap)
    print(f"  Paginas visitadas: {resumen['paginas_visitadas']}")
    if resumen['paginas_visitadas'] >= config.get('paginas_max', 80):
        resumen["tope_alcanzado"] = True

    detectar_apis(paginas, resumen)

    candidatos = dict(archivos_wp)
    for u in archivos_sitemap:
        candidatos.setdefault(normalizar_url(u), {
            "descripcion": nombre_archivo_desde_url(u),
            "fecha": None,
            "url_pagina": base,
        })
    for url_pagina, html in paginas.items():
        for url, datos in extraer_de_pagina(url_pagina, html, config['url_base']).items():
            # El HTML gana sobre las sondas: trae descripcion y fecha visibles
            candidatos[url] = datos if url not in archivos_wp else {**candidatos[url], **{
                k: v for k, v in datos.items() if v}}
    print(f"  Archivos descargables detectados: {len(candidatos)}")

    if not candidatos:
        return arbol, resumen

    with ThreadPoolExecutor(HILOS_METADATOS) as ejecutor:
        resueltos = dict(ejecutor.map(
            partial(resolver_metadatos, verificar_ssl=estado['ssl']),
            candidatos.items(),
        ))

    for url, datos in resueltos.items():
        if datos.get("http") != 200:
            resumen["enlaces_rotos"] += 1
            continue

        resumen["bytes"] += datos.get("tamanio") or 0
        base_niveles = niveles_para(url, datos["url_pagina"])
        nombre = nombre_archivo_desde_url(url)
        insertar(arbol[raiz], base_niveles + [nombre],
                 construir_hoja(config, url, datos, tags_manuales), resumen)

        if es_comprimido(url):
            resumen["comprimidos"] += 1
            interiores = listar_comprimido(url, datos.get("tamanio"), estado['ssl'])
            grupo = normalizar_nombre(nombre.rsplit('.', 1)[0])
            for ruta_interna, tamanio in interiores:
                hijo = {
                    "descripcion": f"{os.path.basename(ruta_interna)} (dentro de {nombre})",
                    "fecha": datos.get("fecha"),
                    "url_pagina": datos["url_pagina"],
                    "tamanio": tamanio,
                }
                # Se referencia el comprimido: el archivo interno no tiene URL propia
                niveles_hijo = base_niveles[:2] + [grupo, normalizar_nombre(os.path.basename(ruta_interna))]
                insertar(
                    arbol[raiz],
                    niveles_hijo,
                    construir_hoja(config, url, hijo, tags_manuales, dentro_de=ruta_interna),
                    resumen,
                )
                resumen["dentro_de_comprimidos"] += 1

    return arbol, resumen


def cargar_configuracion(ruta):
    with open(ruta, encoding='utf-8') as f:
        datos = json.load(f)
    return datos["fuentes"]


def main():
    parser = argparse.ArgumentParser(description="Crawler universal configurable por fuente.")
    parser.add_argument('fuentes', nargs='*', help="ids a procesar (por defecto: todas)")
    parser.add_argument('--config', default=CONFIG_POR_DEFECTO)
    parser.add_argument('--salida', default=os.path.join(DIRECTORIO, 'salida'))
    parser.add_argument('--listar', action='store_true', help="listar las fuentes configuradas y salir")
    args = parser.parse_args()

    configuradas = cargar_configuracion(args.config)

    if args.listar:
        print(f"{len(configuradas)} fuentes configuradas:\n")
        for c in configuradas:
            print(f"  {c['id_fuente']:22} {c.get('nombre', ''):46} {c['url_base']}")
        return 0

    seleccion = [c for c in configuradas if not args.fuentes or c['id_fuente'] in args.fuentes]
    if not seleccion:
        print("Ninguna fuente coincide con lo pedido.")
        return 1

    os.makedirs(args.salida, exist_ok=True)
    reporte = []

    for config in seleccion:
        print(f"\n{'=' * 70}\n{config['id_fuente'].upper()} — {config.get('nombre', '')}\n{'=' * 70}")
        inicio = time.time()
        try:
            arbol, resumen = mapear_fuente(config)
        except Exception as e:
            print(f"  ERROR: {type(e).__name__}: {e}")
            reporte.append({"id_fuente": config['id_fuente'], "estado": "ERROR",
                            "detalle": f"{type(e).__name__}: {e}", "documentos": 0})
            continue

        archivo = os.path.join(args.salida, f"mapa_{config['id_fuente']}.json")
        with open(archivo, "w", encoding="utf-8") as f:
            json.dump(arbol, f, ensure_ascii=False, indent=4)

        segundos = time.time() - inicio
        estado = "OK" if resumen["documentos"] else "SIN_ARCHIVOS"
        print(f"  Documentos indexados : {resumen['documentos']}")
        print(f"  Dentro de comprimidos: {resumen['dentro_de_comprimidos']} "
              f"(de {resumen['comprimidos']} comprimidos)")
        print(f"  Enlaces rotos        : {resumen['enlaces_rotos']}")
        print(f"  Peso declarado       : {resumen['bytes'] / 1048576:.0f} MB")
        print(f"  Tiempo               : {segundos:.0f}s  ->  {archivo}")

        # Diagnosticos que orientan el paso siguiente sobre la fuente
        if resumen.get("tope_alcanzado"):
            print("  DIAGNOSTICO: se alcanzo el tope de paginas — hay mas contenido, subir paginas_max")
        if resumen.get("ssl_invalido"):
            print("  DIAGNOSTICO: certificado TLS invalido en la fuente (se continuo sin verificar)")
        if resumen.get("bloqueo_evitado"):
            print("  DIAGNOSTICO: la fuente devolvio 403 y se recupero con headers completos de navegador")
        if resumen["enlaces_rotos"] > 10 and resumen["enlaces_rotos"] > resumen["documentos"]:
            print("  DIAGNOSTICO: la mayoria de los enlaces estan rotos — posible migracion del sitio (RF-04)")
        if resumen.get("apis_detectadas"):
            print("  DIAGNOSTICO: APIs embebidas en el HTML (candidatas a modulo especifico):")
            for api in resumen["apis_detectadas"]:
                print(f"    - {api}")
        elif resumen.get("contenido_dinamico"):
            print("  DIAGNOSTICO: hay contenido renderizado por JS — puede existir mas de lo que el HTML muestra")

        reporte.append({
            "id_fuente": config['id_fuente'],
            "nombre": config.get('nombre', ''),
            "estado": estado,
            "documentos": resumen["documentos"],
            "paginas_visitadas": resumen["paginas_visitadas"],
            "enlaces_rotos": resumen["enlaces_rotos"],
            "comprimidos": resumen["comprimidos"],
            "archivos_en_comprimidos": resumen["dentro_de_comprimidos"],
            "megabytes": round(resumen["bytes"] / 1048576, 1),
            "segundos": round(segundos),
            "plataforma": resumen.get("plataforma"),
            "tope_alcanzado": resumen.get("tope_alcanzado", False),
            "ssl_invalido": resumen.get("ssl_invalido", False),
            "bloqueo_evitado": resumen.get("bloqueo_evitado", False),
            "contenido_dinamico": resumen.get("contenido_dinamico", False),
            "apis_detectadas": resumen.get("apis_detectadas", []),
        })

    ruta_reporte = os.path.join(args.salida, "reporte.json")
    with open(ruta_reporte, "w", encoding="utf-8") as f:
        json.dump(reporte, f, ensure_ascii=False, indent=4)

    print(f"\n{'=' * 70}\nRESUMEN\n{'=' * 70}")
    print(f"{'fuente':16} {'estado':13} {'docs':>6} {'pags':>5} {'rotos':>6} {'MB':>8}")
    for r in reporte:
        print(f"{r['id_fuente']:16} {r['estado']:13} {r.get('documentos', 0):6} "
              f"{r.get('paginas_visitadas', 0):5} {r.get('enlaces_rotos', 0):6} "
              f"{r.get('megabytes', 0):8}")
    resueltas = sum(1 for r in reporte if r['estado'] == 'OK')
    print(f"\nResueltas: {resueltas}/{len(reporte)}   ->   {ruta_reporte}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
