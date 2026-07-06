# Crawler BCB

Crawler en Python para recorrer automaticamente el portal del Banco Central de Bolivia (BCB), detectar las secciones activas del menu de estadisticas y recolectar enlaces a archivos descargables.

## Que hace

- Consulta la pagina principal del BCB.
- Descubre dinamicamente las secciones disponibles dentro del menu de Estadisticas.
- Recorre cada seccion encontrada.
- Extrae enlaces a archivos con extensiones `.xlsx`, `.xls`, `.csv` y `.sav`.
- Genera un archivo JSON con el mapa de resultados.

## Requisitos

- Python 3.9 o superior.
- Dependencias listadas en `requirements.txt`.

## Instalacion

```bash
pip install -r requirements.txt
```

## Uso

Ejecuta el crawler desde la carpeta del proyecto:

```bash
python crawler_BCB.py
```

Al finalizar, se crea o sobreescribe el archivo `mapa_estadisticas_bcb.json` en la raiz del proyecto.

## Estructura de salida

El JSON generado organiza la informacion por seccion, con esta forma general:

```json
{
  "Nombre de la seccion": {
    "url_origen": "https://...",
    "archivos_totales": 0,
    "items": [
      {
        "descripcion": "Nombre del archivo o enlace",
        "url_descarga": "https://..."
      }
    ]
  }
}
```

## Notas tecnicas

- El script usa un `User-Agent` de navegador para reducir bloqueos basicos.
- Incluye una pausa de 1.5 segundos entre secciones para ser mas amable con el servidor.
- Si el sitio cambia su estructura HTML, puede ser necesario ajustar los selectores del crawler.

## Archivos principales

- `crawler_BCB.py`: logica principal del crawler.
- `mapa_estadisticas_bcb.json`: salida generada por la ejecucion.
- `requirements.txt`: dependencias del proyecto.