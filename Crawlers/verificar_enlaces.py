"""
Verificador de enlaces de descarga de un mapa de fuente.

El validador de esquema comprueba la forma del JSON; esto comprueba que los enlaces
existan de verdad. Sirve de control de calidad del crawler y, corrido periodicamente,
alimenta el diagnostico de URLs caidas o modificadas (RF-04, RF-05).

Uso:
    python Crawlers/verificar_enlaces.py Crawlers/mapa_global_aps.json
    python Crawlers/verificar_enlaces.py Crawlers/mapa_global_aps_resoluciones.json --muestra 100
"""

import sys
import json
import argparse
import requests
from concurrent.futures import ThreadPoolExecutor
from random import Random
from urllib.parse import unquote

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

# Algunos servidores rechazan HEAD pero responden GET
CODIGOS_REINTENTO_GET = (403, 405, 501)

TIEMPO_ESPERA = 30


def recolectar_hojas(nodo, ruta, acumulado):
    if isinstance(nodo, dict) and 'url_descarga' in nodo:
        acumulado.append((ruta, nodo))
        return
    if not isinstance(nodo, dict):
        return
    for llave, hijo in nodo.items():
        recolectar_hojas(hijo, ruta + [llave], acumulado)


def es_misma_url(original, final):
    """Un servidor puede responder con la version percent-encoded de la misma ruta.

    Eso no es una relocalizacion: comparar desescapado evita reportar un cambio de
    URL donde solo hubo normalizacion de espacios o acentos.
    """
    return unquote(original) == unquote(final)


def verificar(entrada):
    ruta, hoja = entrada
    url = hoja.get('url_descarga', '')
    try:
        respuesta = requests.head(url, headers=HEADERS, timeout=TIEMPO_ESPERA, allow_redirects=True)
        if respuesta.status_code in CODIGOS_REINTENTO_GET:
            respuesta = requests.get(url, headers=HEADERS, timeout=TIEMPO_ESPERA, stream=True)
            respuesta.close()
        tipo = (respuesta.headers.get('content-type') or '').split(';')[0]
        destino = None if es_misma_url(url, respuesta.url) else respuesta.url
        return ruta, url, respuesta.status_code, tipo, destino
    except Exception as e:
        return ruta, url, 'ERROR', type(e).__name__, None


def main():
    parser = argparse.ArgumentParser(description="Verifica que los enlaces de un mapa de fuente respondan.")
    parser.add_argument('archivo', help="JSON del mapa a verificar")
    parser.add_argument('--muestra', type=int, default=0,
                        help="verificar solo N enlaces al azar (0 = todos)")
    parser.add_argument('--hilos', type=int, default=6, help="peticiones en paralelo")
    parser.add_argument('--semilla', type=int, default=11, help="semilla para que la muestra sea reproducible")
    args = parser.parse_args()

    with open(args.archivo, encoding='utf-8') as f:
        datos = json.load(f)

    hojas = []
    recolectar_hojas(datos, [], hojas)
    if not hojas:
        print("No se encontraron hojas con url_descarga")
        return 1

    objetivo = hojas
    if args.muestra and args.muestra < len(hojas):
        objetivo = Random(args.semilla).sample(hojas, args.muestra)

    print(f"Verificando {len(objetivo)} de {len(hojas)} enlaces de {args.archivo}\n")

    with ThreadPoolExecutor(args.hilos) as ejecutor:
        resultados = list(ejecutor.map(verificar, objetivo))

    correctos = [r for r in resultados if r[2] == 200]
    pdfs = [r for r in correctos if 'pdf' in r[3].lower()]
    redirigidos = [r for r in correctos if r[4]]
    fallidos = [r for r in resultados if r[2] != 200]

    for ruta, url, codigo, detalle, _ in fallidos:
        print(f"  FALLA [{codigo}] {detalle}")
        print(f"         {' / '.join(ruta)}")
        print(f"         {url}")

    # Una redireccion es la pista tipica de que la fuente movio el archivo (RF-04/RF-05)
    for ruta, url, _, _, destino in redirigidos:
        print(f"  REDIRIGE {' / '.join(ruta)}")
        print(f"           {url}")
        print(f"        -> {destino}")

    print(f"\n  Responden 200      : {len(correctos)}/{len(resultados)}")
    print(f"  Content-Type PDF   : {len(pdfs)}/{len(resultados)}")
    print(f"  Con redireccion    : {len(redirigidos)}")
    print(f"  Fallidos           : {len(fallidos)}")

    return 0 if not fallidos else 1


if __name__ == "__main__":
    sys.exit(main())
