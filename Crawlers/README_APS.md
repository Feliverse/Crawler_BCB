# Crawler APS

Crawler externo de la fuente **APS** (Autoridad de Fiscalizacion y Control de Pensiones y Seguros, Bolivia).
Forma parte del Equipo 1 (Subsistema de Extraccion Extensible) y cubre los requisitos RF-06 a RF-09.

## Que hace

- Recorre las dos paginas de Normativa asignadas: Pensiones y Seguros.
- Extrae los documentos descargables listados en las tablas estaticas del HTML.
- Normaliza la fecha publicada por la fuente (`dd/mm/aaaa`) al estandar `AAAA-MM-DD`.
- Genera un JSON jerarquico de 5 niveles compatible con el modelo del prototipo CrawlerBCB.

## Uso

```bash
python Crawlers/crawler_aps.py
```

Genera o sobreescribe `Crawlers/mapa_global_aps.json`.

Para validar la salida contra el contrato comun:

```bash
python Crawlers/validar_esquema.py Crawlers/mapa_global_aps.json
```

Dependencias: las mismas del proyecto (`requests`, `beautifulsoup4`), ya listadas en `requirements.txt`.

## Fuente

| Seccion | URL |
|---|---|
| Pensiones | `https://www.aps.gob.bo/index.php/pensiones/normativa` |
| Seguros | `https://www.aps.gob.bo/index.php/seguros/normativa` |

Ambas responden HTML estatico: no hace falta navegador headless.
Los PDF conviven en dos rutas del sitio, `/files/webdocs/...` e `/images/webdocs/...`.

## Estructura del JSON

Arbol de 5 niveles, con la hoja en el nivel 5:

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

## Resultado de la ultima corrida

```
PENSIONES : 36 documentos (normativa principal) + 28 (bloques agrupados)
SEGUROS   : 34 documentos (normativa principal) + 22 (bloques agrupados)

120 documentos indexados
  - enlaces duplicados omitidos : 1
  - filas sin archivo publicado : 2
  - tablas dinamicas pendientes : 2
```

Validacion: **120 hojas, profundidad 5 uniforme, 0 errores**, 69 hojas con fecha.
Cargado en el visor `web/` renderiza los 120 documentos y el filtro por fecha responde.

## Pendientes (fuera del alcance de esta version)

- **Tabla "Resoluciones, Circulares e Instructivos"** (`id=tabla-normativa`): se renderiza via
  Angular/AJAX, en el HTML estatico solo aparecen los placeholders `{{item.tipodocumento}}`.
  Requiere identificar el endpoint del API en la pestaña Network. El crawler la detecta por su `id`
  y la omite explicitamente, dejando constancia en el log.
- **Seccion "Estadisticas"**: son graficas y tablas generadas por JS, sin archivo descargable asociado.
- **Metadatos ampliados** (tamaño de archivo, fecha del primer dato, datos georreferenciales):
  pendiente definido a nivel de proyecto para el nivel 5.

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
