from pathlib import Path

from bs4 import BeautifulSoup

from core.http_client import HttpClient
from core.source_config import load_source_config


BASE_DIR = Path(__file__).resolve().parent
SOURCES_DIR = BASE_DIR / "sources"


def main() -> None:
    config_path = SOURCES_DIR / "asfi.json"

    config = load_source_config(config_path)

    print("=" * 72)
    print("CRAWLER MULTI-FUENTE")
    print("=" * 72)

    print(f"Fuente:             {config.nombre}")
    print(f"ID:                 {config.id_fuente}")
    print(f"URL base:           {config.base_url}")
    print(f"Profundidad máxima: {config.max_depth}")
    print(f"Pausa:              {config.delay_seconds} segundos")
    print(f"Timeout:             {config.request_timeout} segundos")
    print(f"Inspeccionar ZIP:    {config.inspect_zips}")

    print("\nProbando conexión HTTP...")

    with HttpClient(config) as client:
        response = client.get(config.base_url)

        content_type = response.headers.get(
            "Content-Type",
            "No disponible",
        )

        soup = BeautifulSoup(response.text, "html.parser")

        if soup.title:
            title = soup.title.get_text(" ", strip=True)
        else:
            title = "Sin título"

        print(f"Estado HTTP:         {response.status_code}")
        print(f"Content-Type:        {content_type}")
        print(f"Título detectado:    {title}")
        print(f"URL final:           {response.url}")

    print("\nCliente HTTP funcionando correctamente.")


if __name__ == "__main__":
    main()