# Crawler APS

Crawler externo de la fuente **APS** (Autoridad de Fiscalizacion y Control de Pensiones y Seguros, Bolivia).
Forma parte del Equipo 1 (Subsistema de Extraccion Extensible) y cubre los requisitos RF-06 a RF-09.

## Que hace

Son dos modulos, porque la fuente publica su informacion por dos vias distintas:

| Modulo | Cubre | Salida |
|---|---|---|
| `crawler_aps.py` | Normativa de base (leyes, decretos, resoluciones ministeriales) en las tablas estaticas del HTML | `mapa_global_aps.json` |
| `crawler_aps_resoluciones.py` | Resoluciones, Circulares e Instructivos, servidos por el API de SIRECI que alimenta la tabla Angular | `mapa_global_aps_resoluciones.json` |

Ambos normalizan la fecha al estandar `AAAA-MM-DD` y generan un JSON jerarquico de 5 niveles
compatible con el modelo del prototipo CrawlerBCB.

Se mantienen separados a proposito: la normativa de base cambia pocas veces al año, mientras que
los actos administrativos suman cientos de documentos por gestion. Mezclarlos en un solo archivo
esconderia la normativa principal bajo el volumen de resoluciones.

## Uso

```bash
python Crawlers/crawler_aps.py
```

```bash
python Crawlers/crawler_aps_resoluciones.py
```

Para validar la **forma** de las salidas contra el contrato comun:

```bash
python Crawlers/validar_esquema.py Crawlers/mapa_global_aps.json Crawlers/mapa_global_aps_resoluciones.json
```

Para comprobar que los enlaces **existan de verdad** (y detectar los que cambiaron de ruta):

```bash
python Crawlers/verificar_enlaces.py Crawlers/mapa_global_aps.json
```

```bash
python Crawlers/verificar_enlaces.py Crawlers/mapa_global_aps_resoluciones.json --muestra 100
```

Ambos devuelven codigo de salida 0 si todo esta bien, asi que sirven en un pipeline.

Dependencias: las mismas del proyecto (`requests`, `beautifulsoup4`), ya listadas en `requirements.txt`.

## Fuente

| Seccion | URL |
|---|---|
| Pensiones | `https://www.aps.gob.bo/index.php/pensiones/normativa` |
| Seguros | `https://www.aps.gob.bo/index.php/seguros/normativa` |

Ambas responden HTML estatico: no hace falta navegador headless.
Los PDF conviven en dos rutas del sitio, `/files/webdocs/...` e `/images/webdocs/...`.

## Estructura del JSON

Arbol de 5 niveles, con la hoja en el nivel 5. Cada modulo emite su propia raiz unica.

`mapa_global_aps.json`:

```
NORMATIVA_APS                        N1  raiz unica
 └ PENSIONES | SEGUROS               N2  seccion del portal
    └ NORMATIVA_PRINCIPAL            N3  bloque de la pagina
      | RESOLUCIONES_MINISTERIALES
      | PRECEDENTES_ADMINISTRATIVOS ...
       └ Ley | Decreto_Supremo       N4  tipo de documento
         | ANEXOS | DOCUMENTOS
          └ Ley_065.pdf              N5  archivo con su extension real
```

`mapa_global_aps_resoluciones.json`:

```
RESOLUCIONES_APS                     N1  raiz unica
 └ PENSIONES | SEGUROS               N2  mercado (PEN | SEG en el API)
    └ Resolución_Administrativa      N3  tipo de documento
      | Carta_Circular
       └ R2_PROCEDIMIENTOS_ADMIN...  N4  subtipo (R1..R17); GENERAL si no aplica
          └ 0870-26-RAAPSDP.pdf      N5  rc_filename normalizado
```

Ejemplo de hoja:

```json
"ALP-LEY-430.pdf": {
    "descripcion": "Ley de modificación de la Ley de Pensiones...",
    "url_descarga": "https://www.aps.gob.bo/images/webdocs/DJ/normativa/pensiones/ALP-LEY-430.pdf",
    "fecha_actualizacion": "2013-11-07",
    "fecha_ultimo_dato": "2013-11-07",
    "tipo_archivo": "pdf",
    "id_fuente": "aps",
    "url_origen": "https://www.aps.gob.bo/index.php/pensiones/normativa"
}
```

## Decisiones de esquema

Se tomaron mirando el JSON modelo (`mapa_global_bcb.json`) y el visor (`web/app.js`):

1. **Raiz unica de nivel 1.** `resolveRoot` (web/app.js) solo renderiza la primera clave de N1.
   Con dos raices, la mitad del arbol queda invisible en el visor. Por eso todo cuelga de `NORMATIVA_APS`.
2. **Hoja como superconjunto.** `descripcion` y `url_descarga` son los campos que exige el modelo y
   que el visor usa para reconocer una hoja; encima se agregan los obligatorios de US-04
   (`id_fuente`, `url_origen`, `tipo_archivo`, `fecha_ultimo_dato`).
3. **Doble campo de fecha.** El visor lee `fecha_actualizacion`; US-04 pide `fecha_ultimo_dato`.
   Se emiten ambos con el mismo valor hasta que el equipo unifique el nombre.
4. **Extension real en el nivel 5.** El prototipo BCB renombra todo a `.csv` aunque los archivos sean
   xlsx o pdf. Aca se conserva la extension verdadera del recurso.
5. **Parseo acotado a `<table>`.** Un barrido global de `<a>` arrastra el menu y el pie de pagina,
   que se repiten en todas las vistas del portal.
6. **Fechas ausentes como `null`.** Los bloques agrupados no publican fecha; se deja `null` antes que
   inventar un valor. El visor trata `null` como "sin fecha" sin romperse.
7. **Anexos.** Las filas de anexo (`ANEXO1`, `ANEXO2`) no traen fecha propia: heredan la del decreto
   que las aprueba, porque se publican junto con el.
8. **URLs percent-encoded.** Muchos href de la fuente traen espacios y acentos literales. El servidor
   los acepta pero responde con un redirect a la version codificada, y el motor de conciliacion podria
   leer ese redirect como "URL modificada" (RF-04). Se emite la URL ya codificada: verificados los 120
   enlaces, la correccion baja las redirecciones de 53 a 0.

## Modulo de Resoluciones (API de SIRECI)

La tabla "Resoluciones, Circulares e Instructivos" (`id=tabla-normativa`) no esta en el HTML:
la pagina solo trae los placeholders `{{item.tipodocumento}}` y Angular la puebla en tiempo de
ejecucion. Leyendo el controlador `DocumentosController` embebido en la pagina se identifico el
endpoint que la alimenta, que resulta ser publico y sin autenticacion:

```
GET https://sireci.aps.gob.bo/api/cartas_resoluciones/web/data
    ?institucion=PS&gestion=<AAAA>&mercado=PEN|SEG
    &tipoDocumento=RA|CC|IN&categoria=&titulo=&numero=
    &itemsPerPage=<n>&pagenumber=<n>
```

Responde `application/json` con `{status, data[], totalRows}`. Cada fila trae `tipo`, `subtipo`,
`gestion`, `numero`, `fecha` (ISO 8601), `titulo`, `tamanioarchivo` (bytes) y `urlarchivo`.

`crawler_aps_resoluciones.py` consume ese API en lugar de raspar HTML. Detalles de la implementacion:

- **Paginacion obligatoria**: `itemsPerPage` topea en 500 filas por respuesta, sin importar lo que se pida.
- **Filas sin archivo**: muchas traen `urlarchivo` vacio (`rc_publicar_web: false`). Se descartan y se cuentan.
- **Nivel 5**: `urlarchivo` apunta a `/descarga/<id>` y no expone nombre de archivo; se usa `rc_filename`,
  que si trae el nombre real con su extension.
- **Alcance actual**: la gestion corriente. El parametro `gestion` permite ampliarlo; medido sobre
  2024-2026 da 4945 filas, 2403 con enlace descargable.
- **Metadato de tamaño**: se emite `tamanio_bytes` en la hoja, cubriendo parte del pendiente de
  metadatos definido a nivel de proyecto.

## Resultado de la ultima corrida

`crawler_aps.py`:

```
PENSIONES : 36 documentos (normativa principal) + 28 (bloques agrupados)
SEGUROS   : 34 documentos (normativa principal) + 22 (bloques agrupados)

120 documentos indexados
  - enlaces duplicados omitidos : 1
  - filas sin archivo publicado : 2
  - tablas dinamicas pendientes : 2   (las cubre el otro modulo)
```

`crawler_aps_resoluciones.py` (gestion 2026):

```
PENSIONES : RA 390 filas ->  84 con archivo | CC  15 filas -> 15
SEGUROS   : RA 448 filas -> 447 con archivo | CC 177 filas -> 177

723 documentos indexados
  - filas sin archivo publicado : 307
```

Validacion de esquema de ambos: **profundidad 5 uniforme, 0 errores**.
`mapa_global_aps.json` 120 hojas (69 con fecha); `mapa_global_aps_resoluciones.json` 723 hojas
(723 con fecha, 4996 MB de archivos declarados). Cargados en el visor `web/` renderizan completos
y el filtro por fecha responde.

Verificacion de enlaces: **120/120 y 100/100 (muestra) responden HTTP 200 con `content-type` PDF**,
sin redirecciones ni fallos.

## Pendientes (fuera del alcance de esta version)

- **Seccion "Estadisticas"**: son graficas y tablas generadas por JS, sin archivo descargable asociado.
- **Gestiones historicas** del API de SIRECI: hoy se recorre solo la gestion corriente.
- **Metadatos ampliados** (fecha del primer dato, datos georreferenciales): pendiente definido a
  nivel de proyecto para el nivel 5. El tamaño de archivo ya se emite en el modulo de resoluciones.

## Observaciones sobre la fuente

- La fila `Ley 3791` apunta al PDF `Ley_1732.pdf`: es un error del sitio APS, no del crawler.
  Al ser exactamente el mismo enlace ya indexado, se omite y se reporta como duplicado.
- Dos filas de Resoluciones Supremas figuran como `(no disponible)`, sin enlace. Se descartan.
- Una fila trae la fecha `19/03/19` con año de dos digitos; se normaliza a `2019-03-19`.

## Hallazgos sobre el prototipo CrawlerBCB

Detectados al levantar el proyecto, se reportan para el equipo:

1. `mapear_menu_recursivo()` nunca encuentra el menu y cae siempre al fallback hardcodeado
   (`Aviso: Usando fallback estructurado`), por lo que solo se crawlean 5 URLs fijas. RF-06 queda sin cumplir.
2. `web/app.js` pide `../mapa_estadisticas_bcb.json`, archivo que ya no existe en el repo
   (ahora es `mapa_global_bcb.json`): el visor arranca en 404.
3. `resolveRoot` solo renderiza la primera raiz de N1, por lo que el visor muestra 197 de los
   347 documentos del modelo.
4. El modelo no emite fechas en ninguna hoja, aunque el visor tiene filtro por fecha y US-04 las exige.
