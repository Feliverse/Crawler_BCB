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

El JSON generado organiza la informacion como un arbol jerarquico. La raiz suele ser `ESTADISTICAS` y debajo aparecen categorias, ramas intermedias y documentos en hojas.

```json
{
  "ESTADISTICAS": {
    "Categoria": {
      "Rama": {
        "Subrama": {
          "Documento": {
            "descripcion": "Nombre visible",
            "url_descarga": "https://..."
          }
        }
      }
    }
  }
}
```

El archivo `mapa_estadisticas_bcb.csv` aplana esa misma informacion para abrirla en Excel.

## Notas tecnicas

- El script usa un `User-Agent` de navegador para reducir bloqueos basicos.
- Incluye una pausa de 1.5 segundos entre secciones para ser mas amable con el servidor.
- Si el sitio cambia su estructura HTML, puede ser necesario ajustar los selectores del crawler.

## Archivos principales

- `crawler_BCB.py`: logica principal del crawler.
- `mapa_estadisticas_bcb.json`: salida jerarquica generada por la ejecucion.
- `mapa_estadisticas_bcb.csv`: salida plana para Excel.
- `requirements.txt`: dependencias del proyecto.

## Frontend de Revision

Se incluyo un visor web estatico en la carpeta `web/` con Tailwind CDN para explorar el JSON jerarquico.

Para abrirlo correctamente, sirvelo desde un servidor local en vez de abrir `index.html` directamente con `file://`.

Ejemplo con Python:

```bash
cd web
python -m http.server 8000
```

Luego abre `http://localhost:8000` en el navegador.

El frontend carga por defecto `../mapa_estadisticas_bcb.json` y tambien permite subir un JSON local desde la interfaz.