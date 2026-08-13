# Reporte semanal — Fuentes asignadas a Alex

Plan B ejecutado en dos pasadas sobre las 14 fuentes de la planilla "Fuentes de Datasets":
una primera pasada de crawling HTML generico, y una segunda de **mapeo profundo** que
investigo cada fuente fallida o rasa hasta encontrar donde publica realmente sus archivos.

Herramientas propias (todas en `Crawlers/`):
- `crawler_universal.py` + `fuentes.json` — motor generico configurable (una entrada
  por fuente: semillas, profundidad, dominios permitidos, SSL, tags).
- `crawler_apis.py` — fuentes que publican via API y no via HTML (FMI, BM, DST, ANAPO, CEPAL).
- `crawler_aps.py` + `crawler_aps_resoluciones.py` — modulos especificos de la fuente asignada APS.
- `validar_esquema.py` / `verificar_enlaces.py` — control de calidad del contrato y de los enlaces.

**No se descarga ningun archivo**: se indexa URL, fecha, tipo, tamaño, periodicidad y
tags. Los unicos que se bajan son los comprimidos (< 25 MB) para listar su contenido.

## Resultado global

```
Resueltas          : 13 / 14  (93%)  — la restante es inviable por la fuente, no por el crawler
Documentos         : 14.079  (+723 del modulo APS/SIRECI = 14.802)
Con fecha          : 85%
Peso declarado     : 17,1 GB  (sin descargar; via content-length y APIs)
Validacion         : los 14 mapas pasan el validador (profundidad 5, 0 errores)
```

## Tabla final por fuente

| # | Fuente | Via | Docs | Con fecha | Peso | Observaciones |
|---|--------|-----|-----:|----------:|-----:|---------------|
| 1 | BCB | HTML prof.3 | 3.484 | 56% | 3,9 GB | Semillas de estadisticas; **138 ZIP abiertos** (133 archivos internos). 2,5x la pasada inicial. |
| 2 | BM | **API** | 3.080 | 100% | n/d | Documents & Reports API con filtro Bolivia (3.418 fichas, 3.080 con PDF directo). El CDN rechaza HEAD: descargar con GET stream. |
| 3 | Statistics Denmark | **API** | 2.315 | 100% | n/d | Catalogo completo de Statbank en 1 peticion. **Periodicidad real por tabla** deducida del formato del periodo (Q=trimestral, M=mensual). |
| 4 | ASFI-Valores | HTML prof.3 | 2.096 | 99% | 3,1 GB | 193 comprimidos -> 385 archivos internos. 3,4x la pasada inicial. |
| 5 | MEFP | HTML prof.3 | 1.136 | 100% | 2,5 GB | Certificado TLS invalido del ministerio, manejado con flag documentado. |
| 6 | CEPAL (repositorio) | **API** | 500 | 91% | 5,0 GB | DSpace REST: 500 mas recientes de **49.969 publicaciones** (ampliable por config). Filtrado entityType=Publication (el repositorio tambien indexa autores y eventos como items). |
| 7 | OMC | HTML prof.3 | 462 | 8% | 267 MB | 7 ZIP -> 314 internos. La fuente casi no publica fechas visibles. |
| 8 | ANAPO | **API** | 268 | 100% | 345 MB | WordPress media API. El HTML tiene 98 enlaces rotos (migracion); **la nueva direccion es /wp-content/uploads/ — RF-05 cumplido**. |
| 9 | MMYM | HTML | 156 | 100% | 941 MB | Servidor muy lento. |
| 10 | APS | HTML + API | 154 (+723) | 74%/100% | 0,8+5 GB | 41 secciones + modulo SIRECI. Fuente asignada: detalle completo en README_APS.md. |
| 11 | FMI | **API** | 132 | 100% | n/d | DataMapper API. El 403 de Akamai se evita con el set completo de headers de navegador. SDMX nuevo (api.imf.org) tambien verificado para CSV. |
| 12 | CEPAL (portal) | HTML multi-dominio | 130 | 78% | 172 MB | Complementa al repositorio. |
| 13 | FINRURAL | HTML prof.3 | 129 | 98% | 4 MB | **URL de la planilla desactualizada**: el dominio vigente es finrural.org.bo. |
| 14 | VIPFE | HTML (via MEFP) | 37 | 100% | 30 MB | Su sitio esta caido (DNS/timeout); los datos de inversion publica 2006-2023 viven en el portal del MEFP. `entidad_emisora: VIPFE`. |
| 15 | FEGASACRUZ | — | 0 | — | — | **NO VIABLE**: dominio de la planilla muerto; el vigente solo sirve una pagina "en construccion" con bucles de redireccion. Reevaluar a futuro. |

## Hallazgos clave del mapeo profundo

1. **5 de las 14 fuentes no publican por HTML sino por API** (FMI, BM, DST, ANAPO, CEPAL).
   Un crawler solo-HTML las ve vacias o rasas aunque tengan miles de documentos.
   El patron correcto: motor universal para lo comun + modulo API por fuente.
2. **2 URLs de la planilla oficial estan muertas** (FINRURAL y FEGASACRUZ cambiaron de
   dominio) — el escenario RF-04 detectado en la practica.
3. **ANAPO es el caso RF-05 completo**: 98 enlaces rotos en el HTML y la nueva direccion
   de los archivos encontrada y documentada via su API de WordPress.
4. **Los comprimidos multiplican**: 338 ZIP en total escondian 832 archivos reales.
5. **VIPFE demuestra fuente absorbida**: institucion con sitio propio muerto cuyos datos
   migraron al portal de su ministerio — separar `id_fuente` de `entidad_emisora` lo resuelve.
6. **MEFP con TLS invalido** — reportable como hallazgo de infraestructura.
7. Trucos tecnicos que quedaron codificados: headers completos anti-Akamai (FMI),
   GET-stream porque el CDN rechaza HEAD (BM), paginas de 25 items porque el DSpace
   se ahoga con 100 (CEPAL), fallback HEAD->GET y `verificar_ssl` por fuente (motor).

## Metadatos emitidos por hoja

`descripcion, url_descarga, fecha_actualizacion, fecha_ultimo_dato, tipo_archivo,
id_fuente, url_origen, entidad_emisora, periodicidad, tags [, tamanio_bytes, contenido_en]`

- `periodicidad`: en Statistics Denmark sale **real por tabla** desde el API; en el resto
  se infiere del texto o queda `null`. Pendiente de acuerdo de equipo el default obligatorio.
- `tags`: automaticos por vocabulario (19 categorias) + manuales por fuente.
- `contenido_en`: ruta interna cuando el archivo vive dentro de un comprimido.

## Pendientes

- Ampliar CEPAL mas alla de los 500 recientes (es subir `CEPAL_TOPE_ITEMS`; total 49.969).
- BCB y ASFI siguen tocando su tope de paginas (300): hay mas contenido si se amplia.
- FMI: el modulo indexa el catalogo DataMapper; las series completas por pais salen
  del SDMX nuevo (api.imf.org) ya verificado.
- Reintentar VIPFE directo y FEGASACRUZ en unas semanas.
