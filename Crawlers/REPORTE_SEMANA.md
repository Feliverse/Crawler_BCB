# Reporte semanal — Fuentes asignadas a Alex

Experimento del Plan B: pasar el crawler por las 14 fuentes asignadas (planilla
"Fuentes de Datasets") y reportar cuales resuelve, cuales no y por que.
Motor utilizado: `crawler_universal.py` + `fuentes.json` (una entrada por fuente,
sin codigo especifico). Los mapas generados estan en `Crawlers/salida/`.

**Nota**: no se descargo ningun archivo; se indexan URL, fecha, tipo, tamaño
(`content-length`), periodicidad y tags. Los unicos que se bajan son los
comprimidos (< 25 MB) para listar su contenido interno.

## Resultado global

```
Resueltas       : 10 / 14  (71%)
Documentos      : 3.808
Peso declarado  : ~7,1 GB (sin descargar)
Validacion      : los 10 mapas generados pasan el validador (profundidad 5, 0 errores)
```

## Tabla por fuente

| # | Fuente | Estado | Docs | Peso | Observaciones |
|---|--------|--------|-----:|-----:|---------------|
| 1 | BCB | OK | 1.400 | 1,66 GB | 4x mas documentos que el prototipo original (347). Alcanzo el tope de 120 paginas: hay mas contenido si se amplia `paginas_max`. 526 sin fecha visible. |
| 2 | MEFP | OK | 819 | 2,21 GB | **El servidor del ministerio tiene certificado TLS invalido**; se accede con `verificar_ssl: false` documentado en el config. 819/819 con fecha. |
| 3 | ASFI-Valores | OK | 615 | 1,49 GB | 2 ZIP abiertos (4 archivos internos). Tambien toco el tope de paginas. |
| 4 | OMC | OK | 326 | 29 MB | Caso extremo de comprimidos: 13 enlaces visibles -> **314 archivos dentro de 6 ZIP**. Sin la inspeccion de comprimidos se subcontaria 25 a 1. Fechas no visibles en el HTML. |
| 5 | APS | OK | 154 | 811 MB | 41 secciones recorridas (vs 2 del primer intento). 3 ZIP -> 9 internos. 13 enlaces rotos publicados por la fuente. Ademas: modulo especifico para el API SIRECI (+723 docs, 5 GB — ver README_APS). |
| 6 | MMYM | OK | 144 | 896 MB | Servidor muy lento (6 min la corrida). |
| 7 | BM | OK | 140 | n/d | El CDN no expone `content-length`. 15 ZIP -> 27 internos. Sitio enorme: esto es solo la porcion enlazada desde la home; la via correcta a futuro es su API de datos. |
| 8 | FINRURAL | OK | 129 | 4 MB | **La URL de la planilla esta desactualizada**: `finrural.bo` no resuelve; el dominio vigente es `finrural.org.bo`. Corregido en el config. |
| 9 | Statistics Denmark | OK | 63 | 47 MB | Portal principalmente JS; lo estatico son informes PDF. Su API (api.statbank.dk) seria el camino para las series. |
| 10 | CEPAL | OK | 18 | 18 MB | Solo publicaciones sueltas: las estadisticas viven en statistics.cepal.org (JS + API). Candidata a adaptador especifico. |
| 11 | ANAPO | NO — fuente rota | 0 | — | El sitio publica **98 enlaces a archivos y los 98 dan 404**: apuntan a un WordPress viejo (`/nuevo/wp-content/uploads/...`) eliminado en la migracion del sitio. Se probaron rutas alternativas: los archivos ya no existen en el servidor. Estado US-11: "fuente interrumpio la emision". |
| 12 | FMI | NO — anti-bot | 0 | — | 403 (Akamai) ante cualquier peticion automatizada. El camino correcto no es scraping sino su API de datos (SDMX/dataservices). Requiere adaptador especifico. |
| 13 | VIPFE | NO — caido | 0 | — | `www.vipfe.gob.bo` no resuelve DNS; `vipfe.gob.bo` resuelve pero el servidor no responde (timeout). Reintentar en dias posteriores. |
| 14 | FEGASACRUZ | NO — sitio vacio | 0 | — | **URL de la planilla desactualizada** (`fegasacruz.org.bo` no resuelve; el vigente es `fegasacruz.org`), y el sitio nuevo es una pagina placeholder de 3 KB sin contenido descargable. |

## Lista para el grupo (fuentes no resueltas, con causa)

1. **ANAPO** — enlaces muertos en la propia fuente (404 masivo tras migracion). No es problema del crawler: ningun crawler los va a resolver. Decidir si se reporta a la institucion.
2. **FMI** — bloqueo anti-bot; proponer adaptador via API SDMX.
3. **VIPFE** — servidor caido al momento de las pruebas; reintentar.
4. **FEGASACRUZ** — sitio actual sin contenido; confirmar si la institucion publica en otro canal.

## Hallazgos transversales

- **2 URLs de la planilla oficial estan desactualizadas** (FINRURAL, FEGASACRUZ). Es
  exactamente el escenario RF-04/RF-05 que el sistema busca detectar.
- **MEFP opera con TLS invalido** — reportable como dato de infraestructura.
- **Los comprimidos importan**: 26 ZIP en total escondian 354 archivos reales.
- Las fuentes internacionales grandes (BM, FMI, CEPAL, DST) publican lo importante
  via APIs, no HTML: el patron "motor universal para lo comun + modulo especifico
  por API" (como el de SIRECI en APS) es el camino natural para crecer.

## Metadatos emitidos por hoja

`descripcion, url_descarga, fecha_actualizacion, fecha_ultimo_dato, tipo_archivo,
id_fuente, url_origen, entidad_emisora, periodicidad, tags [, tamanio_bytes,
contenido_en]`

- `periodicidad`: inferida del texto cuando la fuente la declara; queda `null` si no.
  Pendiente de acuerdo de equipo: valor por defecto por fuente para que sea obligatoria.
- `tags`: automaticos por vocabulario (19 categorias) + manuales por fuente en el config.
- `contenido_en`: ruta interna cuando el archivo vive dentro de un comprimido.
