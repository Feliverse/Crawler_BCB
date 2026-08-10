"""
Validador del esquema JSON comun de fuentes (US-04, criterio de aceptacion 2).

Comprueba que un mapa de fuente cumpla el contrato del prototipo CrawlerBCB:
arbol jerarquico de profundidad uniforme, hojas con los campos obligatorios y
fechas normalizadas a AAAA-MM-DD.

Uso:
    python Crawlers/validar_esquema.py Crawlers/mapa_global_aps.json
    python Crawlers/validar_esquema.py Crawlers/mapa_global_aps.json mapa_global_bcb.json
"""

import sys
import json
import re
import os

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

PROFUNDIDAD_ESPERADA = 5

# Marcan una hoja: es lo que el visor del prototipo (web/app.js -> isDocumentLeaf) exige
CAMPOS_MODELO = ("descripcion", "url_descarga")

# Campos obligatorios que agrega US-04
CAMPOS_US04 = ("id_fuente", "url_origen", "tipo_archivo", "url_descarga", "fecha_ultimo_dato")

CAMPOS_FECHA = ("fecha_actualizacion", "fecha_ultimo_dato")

PATRON_FECHA = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def es_hoja(nodo):
    return isinstance(nodo, dict) and all(
        isinstance(nodo.get(campo), str) for campo in CAMPOS_MODELO
    )


def recorrer(nodo, ruta, hojas, errores):
    if es_hoja(nodo):
        hojas.append((ruta, nodo))
        return

    if not isinstance(nodo, dict):
        errores.append(f"[estructura] {' / '.join(ruta)}: se esperaba objeto, se encontro {type(nodo).__name__}")
        return

    if not nodo:
        errores.append(f"[estructura] {' / '.join(ruta)}: rama vacia")
        return

    for llave, hijo in nodo.items():
        recorrer(hijo, ruta + [llave], hojas, errores)


def validar(ruta_archivo):
    print("=" * 72)
    print(f"Validando: {ruta_archivo}")
    print("=" * 72)

    with open(ruta_archivo, encoding="utf-8") as f:
        datos = json.load(f)

    errores = []
    avisos = []
    hojas = []

    if not isinstance(datos, dict) or not datos:
        print("  FALLA: el archivo no contiene un objeto raiz valido\n")
        return False

    raices = list(datos.keys())
    if len(raices) > 1:
        avisos.append(
            f"[visor] {len(raices)} raices de nivel 1 {raices}: web/app.js (resolveRoot) "
            f"solo renderiza la primera, el resto no se muestra"
        )

    recorrer(datos, [], hojas, errores)

    if not hojas:
        print("  FALLA: no se encontro ninguna hoja de documento\n")
        return False

    # 1. Profundidad uniforme
    profundidades = sorted({len(ruta) for ruta, _ in hojas})
    if profundidades != [PROFUNDIDAD_ESPERADA]:
        errores.append(
            f"[profundidad] se esperaba {PROFUNDIDAD_ESPERADA} niveles en todas las hojas, "
            f"se encontraron {profundidades}"
        )

    # 2 a 4. Campos, fechas y URLs por hoja
    faltantes = {}
    sin_fecha = 0
    for ruta, hoja in hojas:
        etiqueta = " / ".join(ruta)

        for campo in CAMPOS_US04:
            if campo not in hoja:
                faltantes.setdefault(campo, []).append(etiqueta)

        for campo in CAMPOS_FECHA:
            valor = hoja.get(campo)
            if valor is None:
                if campo == "fecha_ultimo_dato":
                    sin_fecha += 1
                continue
            if not (isinstance(valor, str) and PATRON_FECHA.match(valor)):
                errores.append(f"[fecha] {etiqueta}: {campo}={valor!r} no cumple AAAA-MM-DD")

        url = hoja.get("url_descarga", "")
        if not url.startswith(("http://", "https://")):
            errores.append(f"[url] {etiqueta}: url_descarga no es absoluta ({url!r})")

    for campo, rutas in faltantes.items():
        errores.append(f"[campo] falta '{campo}' en {len(rutas)} hoja(s), p.ej. {rutas[0]}")

    if sin_fecha:
        avisos.append(f"[fecha] {sin_fecha} de {len(hojas)} hojas sin fecha (la fuente no la publica)")

    # Reporte
    print(f"  Raices de nivel 1 : {len(raices)} -> {raices}")
    print(f"  Hojas encontradas : {len(hojas)}")
    print(f"  Profundidades     : {profundidades}")
    print(f"  Con fecha         : {len(hojas) - sin_fecha}/{len(hojas)}")

    for aviso in avisos:
        print(f"  AVISO  {aviso}")

    limite = 10
    for error in errores[:limite]:
        print(f"  ERROR  {error}")
    if len(errores) > limite:
        print(f"  ... y {len(errores) - limite} error(es) mas")

    ok = not errores
    print(f"\n  RESULTADO: {'VALIDO' if ok else 'NO VALIDO'} ({len(errores)} error(es), {len(avisos)} aviso(s))\n")
    return ok


if __name__ == "__main__":
    rutas = sys.argv[1:]
    if not rutas:
        base = os.path.dirname(os.path.abspath(__file__))
        rutas = [os.path.join(base, "mapa_global_aps.json")]

    resultados = [validar(ruta) for ruta in rutas]
    sys.exit(0 if all(resultados) else 1)
