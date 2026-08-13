# Motor de crawling universal

`crawler_universal.py` es un motor generico: **agregar una fuente es agregar una
entrada en `fuentes.json`, no escribir codigo**. Todo lo que el motor sabe hacer
detecta estandares y plataformas web (WordPress, sitemaps, WAFs, certificados),
nunca sitios concretos. Lo especifico de una fuente vive en su configuracion o,
si publica por API propia, en un modulo corto de `crawler_apis.py`.

## Uso

```bash
python Crawlers/crawler_universal.py                  # todas las fuentes del config
python Crawlers/crawler_universal.py aps bcb          # solo algunas
python Crawlers/crawler_universal.py --listar         # ver que hay configurado
```

Salidas en `Crawlers/salida/`: un `mapa_<fuente>.json` por fuente (contrato de 5
niveles) y un `reporte.json` con el estado y los diagnosticos de cada corrida.

## Configuracion por fuente (`fuentes.json`)

| Campo | Que hace | Default |
|---|---|---|
| `id_fuente` | identificador; va en cada hoja y nombra la salida | obligatorio |
| `url_base` | punto de partida del recorrido | obligatorio |
| `entidad_emisora` | quien emite los documentos (puede diferir del portal) | id en mayusculas |
| `profundidad_max` | saltos de navegacion desde las semillas | 2 |
| `paginas_max` | tope de paginas; evita bucles y protege a la fuente | 80 |
| `rutas_semilla` | rutas o URLs absolutas extra por donde empezar | — |
| `dominios_permitidos` | sufijos de dominio adicionales (`repositorio.*`, `api.*`) | solo el de url_base |
| `excluir` | fragmentos de URL que no vale la pena recorrer | — |
| `verificar_ssl` | poner `false` si la fuente tiene certificado invalido | true |
| `periodicidad` | valor por defecto si la fuente no la declara | null |
| `tags` | etiquetas manuales; se suman a las inferidas | — |
| `raiz` | nombre del nivel 1 del arbol | id en mayusculas |

## Que hace el motor automaticamente

**Recorrido y extraccion**
- Descubrimiento BFS acotado por profundidad y tope de paginas, multi-dominio por sufijo.
- Extraccion de enlaces descargables (pdf, xlsx, xls, csv, doc, docx, sav, dta, zip, rar, 7z, txt, xml).
- Fecha por proximidad en el DOM (fila/item/contenedor del enlace) normalizada a AAAA-MM-DD.
- Descripcion desde la fila cuando el enlace solo dice "Ver"/"Descargar".
- Apertura de ZIP (< 25 MB) para indexar su contenido real con `contenido_en`.
- Tamaño y disponibilidad por HEAD con fallback a GET (hay CDNs que rechazan HEAD).
- URLs percent-encoded estables (evita falsos "URL modificada" en la conciliacion).

**Sondas de plataforma (antes del recorrido)**
- **WordPress**: si `/wp-json/wp/v2/media` responde, indexa todos los archivos subidos —
  incluso los que el HTML no enlaza (visores JS, migraciones con enlaces rotos).
- **Sitemaps**: lee `robots.txt` y las rutas estandar; siembra paginas que el menu
  no enlaza y suma archivos declarados directamente.

**Recuperacion ante bloqueos (por corrida, reportada)**
- 403 de un WAF: reintenta con el set completo de cabeceras de navegador y lo deja activo.
- Certificado TLS invalido: reintenta sin verificar y lo marca en el reporte.

**Diagnosticos al final de cada corrida**
- `tope_alcanzado`: hay mas contenido; subir `paginas_max`.
- `apis_detectadas`: URLs de API embebidas en el HTML (tablas Angular/AJAX) — candidatas
  a modulo especifico; el motor las señala aunque no las consuma.
- `contenido_dinamico`: hay renderizado JS; puede existir mas de lo que el HTML muestra.
- mayoria de enlaces rotos: posible migracion del sitio (escenario RF-04).
- `ssl_invalido` / `bloqueo_evitado`: que tuvo que hacer para entrar.

## Cuando una fuente necesita modulo propio

Si el diagnostico marca `apis_detectadas` o la fuente publica por un API conocido,
el mapeo profundo se hace con un modulo corto en `crawler_apis.py` (50-80 lineas)
que emite el mismo contrato. Los ya escritos sirven de plantilla:

| Modulo | Patron que resuelve |
|---|---|
| `mapear_fmi` | API JSON detras de un WAF (headers completos) |
| `mapear_bm` | API de documentos paginada por offset |
| `mapear_dst` | catalogo completo en una peticion, periodicidad por formato de periodo |
| `mapear_anapo` | WordPress media (hoy el motor ya lo cubre solo) |
| `mapear_cepal` | repositorio DSpace REST con filtro de tipo de entidad |
| `crawler_aps_resoluciones` | API descubierto en el controlador Angular embebido |

## Validacion

```bash
python Crawlers/validar_esquema.py Crawlers/salida/mapa_<fuente>.json
python Crawlers/verificar_enlaces.py Crawlers/salida/mapa_<fuente>.json --muestra 50
```

Ambos con codigo de salida 0/1, usables en pipeline.
