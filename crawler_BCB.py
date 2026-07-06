import sys
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import time
import json
import re

# Asegurar la correcta codificación de salida en la consola
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# URL base del portal institucional
BASE_URL = "https://www.bcb.gob.bo/"

def obtener_headers():
    return {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'es-ES,es;q=0.9'
    }

def mapear_secciones_actuales():
    """
    Descubre dinámicamente qué secciones existen hoy bajo el menú de Estadísticas.
    Si el menú cambia por completo o requiere JS, aplica un fallback estable.
    """
    print("Descubriendo secciones activas en el menú de Estadísticas...")
    secciones_vivas = {}
    try:
        response = requests.get(BASE_URL, headers=obtener_headers(), timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Selector del menú dinámico de categorías
        cat_links = soup.select('li.menu-42439 ul.bcbx-mega__cats a.bcbx-mega__catlink')
        
        for link in cat_links:
            nombre_seccion = link.find('span').text.strip() if link.find('span') else link.text.strip()
            ruta_relativa = link.get('href')
            
            if ruta_relativa:
                url_absoluta = urljoin(BASE_URL, ruta_relativa)
                secciones_vivas[nombre_seccion] = url_absoluta
    except Exception as e:
        print(f"Error al mapear el menú dinámico: {e}")

    # Fallback de seguridad con las rutas conocidas si el menú principal no responde
    if not secciones_vivas:
        print("Aviso: No se detectó el menú dinámico. Usando fallback de secciones conocidas.")
        secciones_vivas = {
            "Sector Externo": urljoin(BASE_URL, "?q=content/sector-externo-0"),
            "Sector Monetario y Bancario": urljoin(BASE_URL, "?q=content/sector-monetario-y-bancario"),
            "Sector Fiscal": urljoin(BASE_URL, "?q=content/sector-fiscal"),
            "Sector Real": urljoin(BASE_URL, "?q=content/sector-real")
        }
                
    print(f"Se detectaron {len(secciones_vivas)} macro-categorías para procesar.")
    return secciones_vivas

def escanear_estructura_pagina(url_pagina):
    """
    Analiza la página de un sector y extrae de forma ordenada las Secciones (H3),
    Subsecciones (A, B, C...) e ítems junto con sus fechas de actualización.
    """
    estructura_secciones = {}
    try:
        response = requests.get(url_pagina, headers=obtener_headers(), timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        seccion_actual = "GENERAL"
        subseccion_actual = "General"
        
        estructura_secciones[seccion_actual] = {subseccion_actual: []}
        cuerpo = soup.find('body') or soup
        
        # Escaneo secuencial del árbol para mantener la jerarquía exacta del diseño del sitio
        for elemento in cuerpo.find_all(['h3', 'em', 'span', 'a']):
            
            # 1. Captura de Secciones Principales (ej: BALANZA DE PAGOS, TIPO DE CAMBIO)
            if elemento.name == 'h3':
                seccion_actual = elemento.text.strip().upper()
                subseccion_actual = "General"
                if seccion_actual not in estructura_secciones:
                    estructura_secciones[seccion_actual] = {}
                if subseccion_actual not in estructura_secciones[seccion_actual]:
                    estructura_secciones[seccion_actual][subseccion_actual] = []
                    
            # 2. Captura de Subsecciones con viñetas de letras (ej: A. Comercio Internacional..., B. ...)
            elif elemento.name in ['em', 'span'] and elemento.text:
                texto = elemento.text.strip()
                if any(texto.startswith(f"{letra}.") for letra in "ABCDEFGH"):
                    subseccion_actual = texto
                    if subseccion_actual not in estructura_secciones[seccion_actual]:
                        estructura_secciones[seccion_actual][subseccion_actual] = []

            # 3. Procesamiento y filtrado inteligente de hipervínculos
            elif elemento.name == 'a' and elemento.has_attr('href'):
                href = elemento['href'].lower()
                texto_documento = elemento.text.strip()
                
                if not texto_documento:
                    continue
                
                # Filtro de validación expansivo (archivos físicos + palabras clave de resúmenes o visualizadores internos)
                es_valido = (
                    any(ext in href for ext in ['.xlsx', '.xls', '.csv', '.sav']) or \
                    'default/files' in href or \
                    any(keyword in texto_documento.lower() for keyword in [
                        'dólar', 'dolar', 'referencial', 'serie', 'cambio', 'cuadro', 
                        'cifras', 'resumen', 'balance', 'posición', 'deuda', 'reservas'
                    ])
                )
                
                if es_valido:
                    url_descarga = urljoin(BASE_URL, elemento['href'])
                    
                    # Validación para no duplicar enlaces exactos dentro de la misma subcategoría
                    if url_descarga not in [item['url_descarga'] for item in estructura_secciones[seccion_actual][subseccion_actual]]:
                        
                        # --- DETERMINACIÓN DE LA FECHA DE ACTUALIZACIÓN ---
                        fecha_actualizacion = "No disponible"
                        
                        # Estrategia A: Búsqueda de patrones de años o rangos de meses en el texto
                        patron_fecha = re.search(r'\b(19|20)\d{2}\b', texto_documento)
                        if patron_fecha:
                            fecha_actualizacion = f"Ref. Texto: {patron_fecha.group(0)}"
                        
                        # Estrategia B: Si apunta a un archivo estático, consultamos los metadatos del servidor
                        elif any(ext in href for ext in ['.xlsx', '.xls', '.csv', '.sav']):
                            try:
                                res_file = requests.head(url_descarga, headers=obtener_headers(), timeout=5)
                                if 'Last-Modified' in res_file.headers:
                                    fecha_actualizacion = res_file.headers['Last-Modified']
                            except Exception:
                                pass # En caso de rechazo del HEAD request, preserva "No disponible"
                        
                        estructura_secciones[seccion_actual][subseccion_actual].append({
                            'descripcion': texto_documento,
                            'url_descarga': url_descarga,
                            'fecha_actualizacion': fecha_actualizacion
                        })

        # Limpieza higiénica del diccionario: eliminamos ramas vacías o auxiliares creadas sin ítems
        for sec in list(estructura_secciones.keys()):
            for subsec in list(estructura_secciones[sec].keys()):
                if not estructura_secciones[sec][subsec]:
                    del estructura_secciones[sec][subsec]
            if not estructura_secciones[sec]:
                del estructura_secciones[sec]

    except Exception as e:
        print(f"Error al estructurar la página {url_pagina}: {e}")
        
    return estructura_secciones

# --- FLUJO PRINCIPAL DE EJECUCIÓN ---
if __name__ == "__main__":
    menu_dinamico = mapear_secciones_actuales()
    mapa_automatizado_final = {}
    
    for nombre_macro, url_seccion in menu_dinamico.items():
        print(f"Procesando de forma jerárquica: [{nombre_macro}]")
        
        # Extraemos las capas de subsecciones e indicadores ordenadamente
        estructura_interna = escanear_estructura_pagina(url_seccion)
        
        mapa_automatizado_final[nombre_macro] = {
            'url_origen': url_seccion,
            'secciones': estructura_interna
        }
        
        # Delay de seguridad prudencial para no saturar las peticiones concurrentes
        time.sleep(1.5)
        
    # Guardar los resultados en formato JSON estructurado
    archivo_salida = "mapa_estadisticas_bcb.json"
    with open(archivo_salida, "w", encoding="utf-8") as f:
        json.dump(mapa_automatizado_final, f, ensure_ascii=False, indent=4)
        
    print(f"\nMapeo estructurado completado con éxito. Se ha generado '{archivo_salida}'.")