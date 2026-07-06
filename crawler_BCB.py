import sys
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import time
import json

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# Usamos la URL base del portal
BASE_URL = "https://www.bcb.gob.bo/"

def obtener_headers():
    return {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

def mapear_secciones_actuales():
    """
    Descubre dinámicamente qué secciones existen hoy bajo el menú de Estadísticas.
    Si agregan o quitan secciones, este bloque las detectará automáticamente.
    """
    print("Descubriendo secciones activas en el menu de Estadisticas...")
    try:
        response = requests.get(BASE_URL, headers=obtener_headers(), timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Apuntamos al contenedor del menú dinámico que identificaste (menu-42439)
        cat_links = soup.select('li.menu-42439 ul.bcbx-mega__cats a.bcbx-mega__catlink')
        
        secciones_vivas = {}
        for link in cat_links:
            # Extrae el texto del span (ej: "Sector Externo", "Sector Precios", etc.)
            nombre_seccion = link.find('span').text.strip() if link.find('span') else link.text.strip()
            ruta_relativa = link.get('href')
            
            if ruta_relativa:
                url_absoluta = urljoin(BASE_URL, ruta_relativa)
                secciones_vivas[nombre_seccion] = url_absoluta
                
        print(f"Se detectaron {len(secciones_vivas)} secciones activas en la plataforma.")
        return secciones_vivas
    except Exception as e:
        print(f"Error al mapear el menu principal: {e}")
        return {}

def escanear_documentos_de_pagina(url_pagina):
    """
    Entra a una sección y extrae todos los enlaces a archivos descargables (.xlsx, .xls, .csv, .sav)
    """
    archivos_encontrados = []
    try:
        response = requests.get(url_pagina, headers=obtener_headers(), timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Buscamos todos los hipervínculos en el cuerpo de la página
        enlaces = soup.find_all('a', href=True)
        
        for e in enlaces:
            href = e['href'].lower()
            # Filtro riguroso de extensiones solicitadas
            if any(ext in href for ext in ['.xlsx', '.xls', '.csv', '.sav']):
                texto_documento = e.text.strip() or "Documento sin título"
                url_descarga = urljoin(BASE_URL, e['href'])
                
                archivos_encontrados.append({
                    'descripcion': texto_documento,
                    'url_descarga': url_descarga
                })
    except Exception as e:
        print(f"Error al escanear la pagina {url_pagina}: {e}")
        
    return archivos_encontrados

# --- FLUJO PRINCIPAL AUTOMÁTICO ---
if __name__ == "__main__":
    # 1. El crawler descubre qué hay en el menú HOY
    menu_dinamico = mapear_secciones_actuales()
    
    mapa_automatizado_final = {}
    
    # 2. Recorre dinámicamente lo que haya encontrado, sin importar los nombres
    for nombre_seccion, url_seccion in menu_dinamico.items():
        print(f"Procesando de forma iterativa: [{nombre_seccion}]")
        
        # Extrae los archivos de la sección actual
        documentos = escanear_documentos_de_pagina(url_seccion)
        
        # Guardamos en nuestro diccionario estructurado
        mapa_automatizado_final[nombre_seccion] = {
            'url_origen': url_seccion,
            'archivos_totales': len(documentos),
            'items': documentos
        }
        
        # Delay de cortesía de 1.5 segundos para evitar bloqueos por rate-limiting
        time.sleep(1.5)
        
    # 3. Exportar el Mapa a un archivo JSON para que lo puedas explotar fácilmente
    with open("mapa_estadisticas_bcb.json", "w", encoding="utf-8") as f:
        json.dump(mapa_automatizado_final, f, ensure_ascii=False, indent=4)
        
    print("\nMapeo completado con exito. Se ha generado el archivo 'mapa_estadisticas_bcb.json'.")