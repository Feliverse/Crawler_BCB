# Crawler BCB - Metales

Este proyecto extrae cotizaciones de metales del Banco Central de Bolivia (BCB) para un rango de fechas configurable, con una interfaz web para validación y exportación.

## Objetivo

Automatizar la consulta a la página:

https://www.bcb.gob.bo/librerias/indicadores/metales/anteriores.php

sin tener que cambiar fechas manualmente en la web.

## Stack

- Python 3.12+
- requests
- BeautifulSoup + lxml
- Playwright (fallback para páginas con render JS)
- SQLite + SQLAlchemy
- Streamlit para validación visual

## Instalación

En PowerShell:

```powershell
cd "C:\Users\ELITEBOOK\Desktop\Pasantía Programas\Datax\Crawler_BCB"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r crawler\requirements.txt
python -m pip install -r requirements_streamlit.txt
playwright install
```

## Ejecutar el crawler por línea de comandos

```powershell
python cli.py 2023-01-01 2023-01-10
```

Con fallback de navegador:

```powershell
python cli.py 2023-01-01 2023-01-10 --playwright
```

Modo concurrente:

```powershell
python cli.py 2023-01-01 2023-01-31 --async --concurrency 5
```

## Ejecutar la interfaz web

```powershell
cd "C:\Users\ELITEBOOK\Desktop\Pasantía Programas\Datax\Crawler_BCB"
.\.venv\Scripts\streamlit.exe run streamlit_app.py --server.headless true --server.address 127.0.0.1 --server.port 8504
```

Luego abre:

```text
http://127.0.0.1:8504
```

## Salida

Los datos se guardan en SQLite en:

```text
crawler_data.sqlite
```

La tabla principal es:

```text
metales
```

También puedes descargar los resultados desde la UI como:
- CSV
- Excel

## Estructura del proyecto

```text
Crawler_BCB/
├── cli.py
├── streamlit_app.py
├── crawler/
│   ├── __init__.py
│   ├── async_collector.py
│   ├── collector.py
│   ├── config.py
│   ├── models.py
│   ├── parser.py
│   ├── requirements.txt
│   ├── storage.py
│   └── storage_sqlalchemy.py
├── tests/
│   └── test_parser.py
├── crawler_data.sqlite
├── README.md
├── requirements_streamlit.txt
└── web/
```

## Notas importantes

- El sitio puede requerir manipulación de formularios y render JS.
- El fallback de Playwright está pensado para esos casos.
- Si la estructura HTML del sitio cambia, es probable que necesites ajustar el parser.
- La UI es ideal para validación rápida antes de automatizar un rango grande.

## Siguiente mejora recomendada

- Hacerlo correr en automático en intervalos (por ejemplo, cada noche) y guardar historial semanal o mensual.
