import sys
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, unquote
import time
import json
import re
from datetime import datetime

# === CONFIGURACIÓN ===
BASE_URL = "https://www.asfi.gob.bo/"
IGNORAR_URLS = ['datos-sobre-reclamos-y-consultas-atendidas']
IGNORAR_TEXTOS = ['Datos sobre Reclamos y Consultas Atendidas']
EXTENSIONES_VALIDAS = ['.pdf', '.xlsx', '.xls', '.csv', '.doc', '.docx']

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
    if any(keyword in texto.lower() for keyword in ['estadistica', 'informe', 'boletin', 'resolucion', 'circular', 'reporte', 'datos']):
        return True
    return False

def extraer_extension(href):
    nombre = href.split('/')[-1]
    if '.' in nombre:
        return nombre.split('.')[-1].lower()
    return 'pdf'

# === EXTRACCIÓN DEL MENÚ (CORREGIDA) ===
def mapear_menu_asfi_completo(soup):
    """
    Extrae el menú completo de ASFI respetando la estructura real del HTML.
    Retorna un diccionario con la jerarquía: macro → categoría → subcategorías (URLs)
    """
    menu = {}
    # 1. Obtener los ítems principales del navbar (dropdown-center)
    items_principales = soup.select('ul.navbar-nav > li.nav-item.dropdown-center')
    if not items_principales:
        # Fallback: buscar cualquier li con dropdown
        items_principales = soup.select('ul.navbar-nav > li.dropdown')
    
    for li_macro in items_principales:
        # Obtener el texto del macro (Institucional, Normativa, etc.)
        span_o_a = li_macro.find('a', class_='texto-nivel-0') or li_macro.find('span', class_='texto-nivel-0')
        if not span_o_a:
            continue
        nombre_macro = span_o_a.text.strip()
        if not nombre_macro:
            continue

        # Buscar el dropdown-menu
        dropdown = li_macro.find('ul', class_='dropdown-menu')
        if not dropdown:
            continue

        # Dentro del dropdown, buscar el div.menu-principal
        div_principal = dropdown.find('div', class_='menu-principal')
        if not div_principal:
            # Si no hay div, usar el dropdown directamente
            div_principal = dropdown

        # Recorrer los li hijos directos del div
        sub_items = div_principal.find_all('li', recursive=False)
        if not sub_items:
            continue

        menu[nombre_macro] = {}
        for li_cat in sub_items:
            # Buscar el enlace o span de la categoría (texto-nivel-1)
            enlace_cat = li_cat.find('a', class_='texto-nivel-1') or li_cat.find('span', class_='texto-nivel-1')
            if not enlace_cat:
                continue
            nombre_categoria = enlace_cat.text.strip()
            if not nombre_categoria:
                continue

            # Verificar si tiene sub-ul (collapse)
            sub_ul = li_cat.find('ul', class_='collapse')
            if sub_ul:
                # Extraer los enlaces dentro del sub-ul
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
                # Es un enlace directo (sin submenú)
                href = enlace_cat.get('href')
                if href and not href.startswith('#'):
                    menu[nombre_macro][nombre_categoria] = urljoin(BASE_URL, href)

    return menu

# === ESCANEO DE DOCUMENTOS EN UNA PÁGINA ===
def escanear_documentos_y_estructurar(nivel1_macro, nombre_pagina, url_pagina, mapa_final):
    try:
        response = requests.get(url_pagina, headers=obtener_headers(), timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        enlaces = soup.find_all('a', href=True)

        if nivel1_macro not in mapa_final:
            mapa_final[nivel1_macro] = {}

        for e in enlaces:
            href = e['href'].strip()
            texto_documento = e.text.strip() or href.split('/')[-1]

            # === FILTROS ===
            if any(ignorar in href for ignorar in IGNORAR_URLS) or \
               any(ignorar in texto_documento for ignorar in IGNORAR_TEXTOS):
                continue

            if not es_archivo_descargable(href, texto_documento):
                continue

            url_absoluta = urljoin(BASE_URL, href)
            parsed = urlparse(url_absoluta)
            path_decoded = unquote(parsed.path)

            # === ORGANIZACIÓN JERÁRQUICA ===
            nivel2 = normalizar_nombre(nombre_pagina)

            # Extraer fecha de la ruta
            fecha = extraer_fecha_de_ruta(path_decoded)

            # Determinar niveles 3 y 4
            if 'sites/default/files/' in path_decoded:
                try:
                    idx = path_decoded.index('sites/default/files/') + len('sites/default/files/')
                    resto = path_decoded[idx:]
                    partes_resto = [p for p in resto.split('/') if p]
                    nivel3 = normalizar_nombre(partes_resto[0]) if len(partes_resto) > 0 else "DOCUMENTOS"
                    nivel4 = normalizar_nombre(partes_resto[1]) if len(partes_resto) > 1 else "VARIOS"
                    nombre_archivo = partes_resto[-1] if partes_resto else f"{normalizar_nombre(texto_documento)}.pdf"
                except ValueError:
                    nivel3 = "DOCUMENTOS"
                    nivel4 = "VARIOS"
                    nombre_archivo = f"{normalizar_nombre(texto_documento)}.pdf"
            else:
                nivel3 = "CONTENIDO_WEB"
                nivel4 = "GENERAL"
                nombre_archivo = f"{normalizar_nombre(texto_documento)}.{extraer_extension(href)}"

            # Construir árbol
            if nivel2 not in mapa_final[nivel1_macro]:
                mapa_final[nivel1_macro][nivel2] = {}
            if nivel3 not in mapa_final[nivel1_macro][nivel2]:
                mapa_final[nivel1_macro][nivel2][nivel3] = {}
            if nivel4 not in mapa_final[nivel1_macro][nivel2][nivel3]:
                mapa_final[nivel1_macro][nivel2][nivel3][nivel4] = {}

            if nombre_archivo not in mapa_final[nivel1_macro][nivel2][nivel3][nivel4]:
                mapa_final[nivel1_macro][nivel2][nivel3][nivel4][nombre_archivo] = {
                    "descripcion": texto_documento,
                    "url_descarga": url_absoluta,
                    "fecha_actualizacion": fecha
                }
                print(f"  [+] {nombre_archivo} ({fecha})")

    except Exception as e:
        print(f"Error al procesar {nombre_pagina}: {e}")

# === MAIN ===
if __name__ == "__main__":
    # Obtener HTML de la página principal
    response = requests.get(BASE_URL, headers=obtener_headers(), timeout=15)
    soup = BeautifulSoup(response.text, 'html.parser')

    # Extraer menú completo
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
    print("\n🔍 Iniciando escaneo de documentos...")

    # Recorrer el menú respetando la jerarquía
    def recorrer_menu(nodo, path_actual=[]):
        for clave, valor in nodo.items():
            if isinstance(valor, dict):
                # Verificar si es un submenú (tiene subclaves que también son dicts)
                # Si algún valor hijo es dict, profundizar
                if any(isinstance(v, dict) for v in valor.values()):
                    recorrer_menu(valor, path_actual + [clave])
                else:
                    # Es un nivel de hojas (categoría con enlaces directos)
                    macro = path_actual[0] if path_actual else "RAIZ"
                    for subclave, url in valor.items():
                        print(f"\n--- {macro} / {clave} / {subclave} ---")
                        escanear_documentos_y_estructurar(macro, subclave, url, mapa_final)
                        time.sleep(1.2)
            else:
                # Es una URL directa (hoja)
                macro = path_actual[0] if path_actual else "RAIZ"
                print(f"\n--- {macro} / {clave} ---")
                escanear_documentos_y_estructurar(macro, clave, valor, mapa_final)
                time.sleep(1.2)

    recorrer_menu(estructura)

    # Guardar JSON
    with open("mapa_global_asfi.json", "w", encoding="utf-8") as f:
        json.dump(mapa_final, f, ensure_ascii=False, indent=4)

    print("\n✅ ¡Listo! Mapa generado en mapa_global_asfi.json")
    total_docs = 0
    for macro in mapa_final.values():
        for seccion in macro.values():
            for nivel3 in seccion.values():
                for nivel4 in nivel3.values():
                    total_docs += len(nivel4)
    print(f"📊 Total de documentos: {total_docs}")