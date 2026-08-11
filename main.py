import sys
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, unquote
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
BASE_URL = os.getenv("BASE_URL", "https://www.bcb.gob.bo/")

def obtener_headers():
    return {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

def normalizar_nombre(texto):
    """Reemplaza espacios por guiones bajos y limpia caracteres extraños para nombres de llaves JSON."""
    texto = unquote(texto).strip()
    texto = re.sub(r'[\s/\\:]+', '_', texto)
    return texto

def mapear_menu_recursivo():
    """
    Escanea la página principal y extrae de manera multinivel la estructura real 
    del menú desplegable del BCB (Soporta submenús dentro de submenús).
    """
    print("Mapeando la estructura multinivel del menú superior...")
    menu_completo = {}
    try:
        response = requests.get(BASE_URL, headers=obtener_headers(), timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Seleccionamos las pestañas raíz del menú principal
        items_raiz = soup.select('ul.navbar-nav > li.dropdown') or soup.select('div.region-navigation ul.menu > li.expanded')
        
        for item in items_raiz:
            enlace_padre = item.find('a')
            if not enlace_padre:
                continue
                
            nombre_macro = normalizar_nombre(enlace_padre.text.strip().upper())
            menu_completo[nombre_macro] = {}
            
            # Buscamos todos los sub-elementos de lista anidados de forma recursiva
            sub_elementos = item.find_all('li', recursive=True)
            
            for sub in sub_elementos:
                link = sub.find('a', href=True)
                if not link:
                    continue
                    
                nombre_sub = link.find('span').text.strip() if link.find('span') else link.text.strip()
                href = link.get('href')
                
                if href and not href.startswith('#'):
                    url_absoluta = urljoin(BASE_URL, href)
                    menu_completo[nombre_macro][nombre_sub] = url_absoluta
                    
    except Exception as e:
        print(f"Error al mapear el menú jerárquico: {e}")
        
    # Fallback preventivo
    if not menu_completo:
        print("Aviso: Usando fallback estructurado para asegurar la ejecución.")
        menu_completo = {
            "POLITICA_MONETARIA_Y_CAMBIARIA": {
                "Resultados y Convocatoria OMA": urljoin(BASE_URL, "?q=publicacion-omas"),
                "Reporte Diario OMA": urljoin(BASE_URL, "?q=content/reporte-diario-de-operaciones-de-mercado-abierto-y-monetario"),
                "Reporte Semanal OMA": urljoin(BASE_URL, "?q=content/reporte-semanal")
            },
            "ESTADISTICAS": {
                "Sector Externo": urljoin(BASE_URL, "?q=content/sector-externo-0"),
                "Sector Monetario y Bancario": urljoin(BASE_URL, "?q=content/sector-monetario-y-bancario")
            }
        }
    return menu_completo

def escanear_documentos_y_estructurar(nivel1_macro, nombre_pagina, url_pagina, mapa_final):
    """
    Escanea la página destino y acomoda las carpetas en su lugar correspondiente,
    forzando que el identificador final (Nivel 5) termine con la extensión .csv para Excel.
    """
    try:
        response = requests.get(url_pagina, headers=obtener_headers(), timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        enlaces = soup.find_all('a', href=True)
        
        if nivel1_macro not in mapa_final:
            mapa_final[nivel1_macro] = {}

        for e in enlaces:
            href = e['href'].lower()
            texto_documento = e.text.strip()
            
            if not texto_documento:
                continue
            
            es_valido = (
                any(ext in href for ext in ['.xlsx', '.xls', '.csv', '.sav', '.pdf', '.docx', '.doc']) or \
                'default/files' in href or \
                any(keyword in texto_documento.lower() for keyword in [
                    'dólar', 'dolar', 'referencial', 'serie', 'cambio', 'cuadro', 'cifras', 
                    'resumen', 'informe', 'memoria', 'boletin', 'convocatoria', 'reporte'
                ])
            )
                         
            if es_valido:
                url_absoluta = urljoin(BASE_URL, e['href'])
                parsed_url = urlparse(url_absoluta)
                path_decoded = unquote(parsed_url.path)
                
                # --- ASIGNACIÓN DE NIVELES INTELIGENTE ---
                if 'webdocs/' in path_decoded:
                    partes = [p for p in path_decoded.split('/') if p]
                    
                    nivel2 = partes[1] if len(partes) > 1 else normalizar_nombre(nombre_pagina)
                    nivel3 = partes[2] if len(partes) > 3 else "DOCUMENTOS_GENERALES"
                    nivel4 = partes[3] if len(partes) > 4 else "VARIOS"
                    
                    # Extraemos el nombre base removiendo cualquier extensión original (.xlsx, .pdf, etc.)
                    nombre_base = partes[-1].rsplit('.', 1)[0]
                    nivel5 = f"{normalizar_nombre(nombre_base)}.csv"
                else:
                    # Enlaces dinámicos/vistas de consulta de Drupal
                    nivel2 = normalizar_nombre(nombre_pagina)
                    nivel3 = "REPORTE_Y_CONSULTAS"
                    nivel4 = "CONTENIDO_WEB"
                    nivel5 = f"{normalizar_nombre(texto_documento)}.csv"
                
                # --- ALIMENTAR EL ÁRBOL JSON ---
                if nivel2 not in mapa_final[nivel1_macro]:
                    mapa_final[nivel1_macro][nivel2] = {}
                if nivel3 not in mapa_final[nivel1_macro][nivel2]:
                    mapa_final[nivel1_macro][nivel2][nivel3] = {}
                if nivel4 not in mapa_final[nivel1_macro][nivel2][nivel3]:
                    mapa_final[nivel1_macro][nivel2][nivel3][nivel4] = {}
                
                # Al mantener el orden natural de aparición del HTML, el primer elemento insertado
                # corresponde al último archivo disponible/más reciente de la lista.
                if nivel5 not in mapa_final[nivel1_macro][nivel2][nivel3][nivel4]:
                    mapa_final[nivel1_macro][nivel2][nivel3][nivel4][nivel5] = {
                        "descripcion": texto_documento,
                        "url_descarga": url_absoluta
                    }
                    
    except Exception as e:
        print(f"Error al procesar la página [{nombre_pagina}]: {e}")

# --- FLUJO PRINCIPAL AUTOMÁTICO ---
if __name__ == "__main__":
    estructura_menu =   ()
    mapa_jerarquizado_final = {}
    
    for macro_seccion, sub_secciones in estructura_menu.items():
        print(f"\n--- Escaneando macro-menú superior: [{macro_seccion}] ---")
        
        for nombre_pagina, url_pagina in sub_secciones.items():
            print(f"Indexando: {nombre_pagina} -> {url_pagina}")
            
            escanear_documentos_y_estructurar(macro_seccion, nombre_pagina, url_pagina, mapa_jerarquizado_final)
            time.sleep(1.2)
        
    # Exportar mapa global listo para Excel
    archivo_salida = "mapa_global.json"
    with open(archivo_salida, "w", encoding="utf-8") as f:
        json.dump(mapa_jerarquizado_final, f, ensure_ascii=False, indent=4)
        
    print(f"\n¡Listo! Todo el portal mapeado con nombres convertidos a '.csv' en '{archivo_salida}'.")
