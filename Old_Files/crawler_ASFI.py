import sys
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, unquote
import time
import json
import re
from datetime import datetime
import os
import zipfile
import io

# === CONFIGURACIÓN ===
BASE_URL = "https://www.asfi.gob.bo/"
IGNORAR_URLS = ['datos-sobre-reclamos-y-consultas-atendidas']
IGNORAR_TEXTOS = ['Datos sobre Reclamos y Consultas Atendidas']
EXTENSIONES_VALIDAS = ['.pdf', '.xlsx', '.xls', '.csv', '.doc', '.docx', '.zip']
PROFUNDIDAD_MAXIMA = 3
PAUSA_ENTRE_PETICIONES = 1.2
INSPECCIONAR_ZIPS = True  # Flag para activar/desactivar la inspección de zips

# === FUNCIONES AUXILIARES ===
def obtener_headers():
    return {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

def normalizar_nombre(texto):
    texto = unquote(texto).strip()
    texto = re.sub(r'[\s/\\:]+', '_', texto)
    texto = re.sub(r'[^a-zA-Z0-9_\-]', '', texto)
    return texto

def extraer_fecha_de_ruta(ruta):
    patron = r'/(\d{4}-\d{2})/'
    match = re.search(patron, ruta)
    if match:
        try:
            fecha_obj = datetime.strptime(match.group(1), '%Y-%m')
            return fecha_obj.strftime('%Y-%m')
        except:
            pass
    return "No disponible"

def es_archivo_descargable(href, texto):
    if any(href.lower().endswith(ext) for ext in EXTENSIONES_VALIDAS):
        return True
    if '/sites/default/files/' in href:
        return True
    if any(keyword in texto.lower() for keyword in ['estadistica', 'informe', 'boletin', 'resolucion', 'circular', 'reporte', 'datos', 'zip']):
        return True
    return False

def extraer_extension_y_tipo(href):
    nombre = href.split('/')[-1]
    if '.' in nombre:
        ext = nombre.split('.')[-1].lower()
        return ext, ext
    if '/zip' in href or '.zip' in href:
        return 'zip', 'zip'
    return 'pdf', 'pdf'

def inspeccionar_zip(url_zip):
    """Descarga un .zip en memoria y devuelve lista de nombres de archivos internos."""
    if not INSPECCIONAR_ZIPS:
        return []
    try:
        response = requests.get(url_zip, headers=obtener_headers(), timeout=30)
        if response.status_code != 200:
            return []
        # Si el archivo es muy grande, podrías limitar el tamaño (ej. 50 MB)
        # if len(response.content) > 50 * 1024 * 1024:
        #     return ["Archivo demasiado grande para inspeccionar"]
        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            # Obtener solo nombres de archivos (ignorar directorios)
            nombres = [name for name in zf.namelist() if not name.endswith('/')]
            return nombres
    except Exception as e:
        print(f"  ⚠️ Error al inspeccionar zip {url_zip}: {e}")
        return []

def es_pagina_de_listado(soup):
    titulo = soup.title.string.lower() if soup.title else ''
    if any(p in titulo for p in ['memoria', 'boletín', 'informe', 'estadística', 'publicación', 'resolución', 'circular']):
        return True
    enlaces = soup.find_all('a', href=True)
    archivos_en_pagina = sum(1 for a in enlaces if es_archivo_descargable(a['href'], a.text))
    if archivos_en_pagina >= 3:
        return True
    if soup.select('ul.pager, li.pager__item, .pagination'):
        return True
    return False

def obtener_paginas_siguientes(soup, url_actual):
    paginas = []
    for a in soup.select('ul.pager li a, li.pager__item a, .pagination a'):
        href = a.get('href')
        if href and 'page=' in href:
            if href != url_actual and href not in paginas:
                paginas.append(urljoin(BASE_URL, href))
    return paginas

def obtener_enlaces_internos(soup, url_actual):
    enlaces = []
    for a in soup.find_all('a', href=True):
        href = a['href'].strip()
        if href.startswith('#') or href.startswith('javascript:'):
            continue
        url_absoluta = urljoin(BASE_URL, href)
        if url_absoluta.startswith(BASE_URL) and url_absoluta != url_actual:
            if not es_archivo_descargable(href, a.text):
                if '/pb/' in href or '/la/' in href or '/node/' in href:
                    enlaces.append(url_absoluta)
    return enlaces

# === EXTRACCIÓN DEL MENÚ ===
def mapear_menu_asfi_completo(soup):
    menu = {}
    items_principales = soup.select('ul.navbar-nav > li.nav-item.dropdown-center')
    if not items_principales:
        items_principales = soup.select('ul.navbar-nav > li.dropdown')
    
    for li_macro in items_principales:
        span_o_a = li_macro.find('a', class_='texto-nivel-0') or li_macro.find('span', class_='texto-nivel-0')
        if not span_o_a:
            continue
        nombre_macro = span_o_a.text.strip()
        if not nombre_macro:
            continue

        dropdown = li_macro.find('ul', class_='dropdown-menu')
        if not dropdown:
            continue

        div_principal = dropdown.find('div', class_='menu-principal')
        if not div_principal:
            div_principal = dropdown

        sub_items = div_principal.find_all('li', recursive=False)
        if not sub_items:
            continue

        menu[nombre_macro] = {}
        for li_cat in sub_items:
            enlace_cat = li_cat.find('a', class_='texto-nivel-1') or li_cat.find('span', class_='texto-nivel-1')
            if not enlace_cat:
                continue
            nombre_categoria = enlace_cat.text.strip()
            if not nombre_categoria:
                continue

            sub_ul = li_cat.find('ul', class_='collapse')
            if sub_ul:
                enlaces_sub = sub_ul.find_all('a', href=True)
                sub_categorias = {}
                for a in enlaces_sub:
                    texto_sub = a.text.strip()
                    href = a.get('href')
                    if texto_sub and href and not href.startswith('#'):
                        sub_categorias[texto_sub] = urljoin(BASE_URL, href)
                if sub_categorias:
                    menu[nombre_macro][nombre_categoria] = sub_categorias
            else:
                href = enlace_cat.get('href')
                if href and not href.startswith('#'):
                    menu[nombre_macro][nombre_categoria] = urljoin(BASE_URL, href)

    return menu

# === ESCANEO RECURSIVO CON PAGINACIÓN Y SEGUIMIENTO DE ENLACES ===
def escanear_pagina_con_profundidad(
    url,
    nivel_actual,
    path_actual,
    mapa_final,
    visitados,
    max_nivel=PROFUNDIDAD_MAXIMA
):
    if nivel_actual > max_nivel:
        return
    if url in visitados:
        return
    visitados.add(url)

    try:
        response = requests.get(url, headers=obtener_headers(), timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
    except Exception as e:
        print(f"  ⚠️ Error al acceder a {url}: {e}")
        return

    raiz = "ESTADISTICAS"
    if raiz not in mapa_final:
        mapa_final[raiz] = {}

    if path_actual:
        nombre_categoria = normalizar_nombre(path_actual[-1])
    else:
        nombre_categoria = "GENERAL"

    if nombre_categoria not in mapa_final[raiz]:
        mapa_final[raiz][nombre_categoria] = {}
    if "DOCUMENTOS" not in mapa_final[raiz][nombre_categoria]:
        mapa_final[raiz][nombre_categoria]["DOCUMENTOS"] = {}
    if "VARIOS" not in mapa_final[raiz][nombre_categoria]["DOCUMENTOS"]:
        mapa_final[raiz][nombre_categoria]["DOCUMENTOS"]["VARIOS"] = {}

    # 1. Extraer archivos directos
    for a in soup.find_all('a', href=True):
        href = a['href'].strip()
        texto_documento = a.text.strip() or href.split('/')[-1]

        if any(ignorar in href for ignorar in IGNORAR_URLS) or \
           any(ignorar in texto_documento for ignorar in IGNORAR_TEXTOS):
            continue

        if not es_archivo_descargable(href, texto_documento):
            continue

        url_absoluta = urljoin(BASE_URL, href)
        parsed = urlparse(url_absoluta)
        path_decoded = unquote(parsed.path)

        fecha = extraer_fecha_de_ruta(path_decoded)

        extension, tipo_archivo = extraer_extension_y_tipo(href)
        if tipo_archivo == 'pdf' and '.zip' in path_decoded:
            tipo_archivo = 'zip'
            extension = 'zip'

        # Nombre del archivo
        if '/sites/default/files/' in path_decoded:
            try:
                idx = path_decoded.index('sites/default/files/') + len('sites/default/files/')
                resto = path_decoded[idx:]
                partes_resto = [p for p in resto.split('/') if p]
                nombre_archivo = partes_resto[-1] if partes_resto else f"{normalizar_nombre(texto_documento)}.{extension}"
            except ValueError:
                nombre_archivo = f"{normalizar_nombre(texto_documento)}.{extension}"
        else:
            nombre_archivo = f"{normalizar_nombre(texto_documento)}.{extension}"

        # Si es zip, inspeccionar su contenido
        contenido_zip = []
        if tipo_archivo == 'zip':
            contenido_zip = inspeccionar_zip(url_absoluta)

        if nombre_archivo not in mapa_final[raiz][nombre_categoria]["DOCUMENTOS"]["VARIOS"]:
            mapa_final[raiz][nombre_categoria]["DOCUMENTOS"]["VARIOS"][nombre_archivo] = {
                "descripcion": texto_documento,
                "url_descarga": url_absoluta,
                "fecha_actualizacion": fecha,
                "tipo_archivo": tipo_archivo,
                "contenido_zip": contenido_zip,   # <--- Lista de archivos internos
                "pagina_origen": url
            }
            print(f"  [+] {nombre_archivo} ({fecha}) [{tipo_archivo}] - {len(contenido_zip)} archivos internos")

    # 2. Registrar esta página como listado
    if es_pagina_de_listado(soup):
        if "_listados" not in mapa_final[raiz][nombre_categoria]:
            mapa_final[raiz][nombre_categoria]["_listados"] = []
        if url not in mapa_final[raiz][nombre_categoria]["_listados"]:
            mapa_final[raiz][nombre_categoria]["_listados"].append(url)
            print(f"  📄 Página listado registrada: {url}")

    # 3. Detectar paginación y seguir enlaces
    paginas_siguientes = obtener_paginas_siguientes(soup, url)
    for pg in paginas_siguientes:
        if pg not in visitados:
            print(f"  ➡️ Siguiendo paginación: {pg}")
            escanear_pagina_con_profundidad(pg, nivel_actual, path_actual, mapa_final, visitados, max_nivel)
            time.sleep(PAUSA_ENTRE_PETICIONES)

    # 4. Seguir enlaces a páginas internas
    if es_pagina_de_listado(soup) and nivel_actual < max_nivel:
        enlaces_internos = obtener_enlaces_internos(soup, url)
        for enlace in enlaces_internos:
            if enlace not in visitados:
                nueva_categoria = normalizar_nombre(enlace.split('/')[-1]) if '/' in enlace else "GENERAL"
                nuevo_path = path_actual + [nueva_categoria]
                print(f"  🔗 Siguiendo enlace interno: {enlace}")
                escanear_pagina_con_profundidad(enlace, nivel_actual + 1, nuevo_path, mapa_final, visitados, max_nivel)
                time.sleep(PAUSA_ENTRE_PETICIONES)

# === MAIN ===
if __name__ == "__main__":
    response = requests.get(BASE_URL, headers=obtener_headers(), timeout=15)
    soup = BeautifulSoup(response.text, 'html.parser')

    estructura = mapear_menu_asfi_completo(soup)
    if not estructura:
        print("⚠️ No se pudo extraer el menú. Usando fallback manual...")
        estructura = {
            "ESTADISTICAS": {
                "Intermediacion_Financiera": urljoin(BASE_URL, "pb/estadisticas-intermediacion-financiera"),
                "Mercado_Valores": urljoin(BASE_URL, "pb/estadisticas-mercado-valores"),
            }
        }

    mapa_final = {}
    visitados = set()

    print("\n🔍 Iniciando escaneo de documentos (con recursividad, paginación e inspección de zips)...")

    def recorrer_menu(nodo, path_actual=[]):
        for clave, valor in nodo.items():
            if isinstance(valor, dict):
                if any(isinstance(v, dict) for v in valor.values()):
                    recorrer_menu(valor, path_actual + [clave])
                else:
                    macro = path_actual[0] if path_actual else "RAIZ"
                    for subclave, url in valor.items():
                        print(f"\n--- {macro} / {clave} / {subclave} ---")
                        escanear_pagina_con_profundidad(url, 1, [subclave], mapa_final, visitados)
            else:
                macro = path_actual[0] if path_actual else "RAIZ"
                print(f"\n--- {macro} / {clave} ---")
                escanear_pagina_con_profundidad(valor, 1, [clave], mapa_final, visitados)

    recorrer_menu(estructura)

    # Guardar JSON con versión incremental
    os.makedirs("Crawlers", exist_ok=True)
    version = 1
    while os.path.exists(f"Crawlers/mapa_global_asfi_v{version}.json"):
        version += 1
    archivo_salida = f"Crawlers/mapa_global_asfi_v{version}.json"
    with open(archivo_salida, "w", encoding="utf-8") as f:
        json.dump(mapa_final, f, ensure_ascii=False, indent=4)

    print("\n✅ ¡Listo! Mapa generado en", archivo_salida)
    total_docs = 0
    for macro in mapa_final.values():
        for seccion in macro.values():
            if "DOCUMENTOS" in seccion and "VARIOS" in seccion["DOCUMENTOS"]:
                total_docs += len(seccion["DOCUMENTOS"]["VARIOS"])
    print(f"📊 Total de documentos: {total_docs}")
    print(f"📊 Total de páginas visitadas: {len(visitados)}")