import sys
import unittest
from pathlib import Path

from requests import Response


PROJECT_DIR = Path(__file__).resolve().parents[1]

if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))


from core.file_detector import FileDetector
from core.navigator import Navigator
from core.source_config import SourceConfig


class FakeHttpClient:
    """
    Cliente HTTP falso para probar Navigator sin realizar
    conexiones reales a Internet.
    """

    def __init__(self, responses):
        self.responses = responses
        self.requested_urls = []

    def get(self, url):
        self.requested_urls.append(url)

        if url not in self.responses:
            raise ValueError(
                f"No existe respuesta falsa para {url}"
            )

        config = self.responses[url]

        response = Response()

        response.status_code = config.get(
            "status_code",
            200,
        )

        response.url = config.get(
            "url",
            url,
        )

        response.headers.update(
            config.get(
                "headers",
                {
                    "Content-Type": "text/html"
                },
            )
        )

        response._content = config.get(
            "body",
            "",
        ).encode("utf-8")

        response.encoding = "utf-8"

        return response


class NavigatorTests(unittest.TestCase):

    def setUp(self):
        self.config = SourceConfig(
            id_fuente="test",
            nombre="Sitio de prueba",
            base_url="https://example.com/",
            allowed_domains=(
                "example.com",
            ),
            extensions=(
                ".pdf",
                ".xlsx",
                ".csv",
                ".zip",
            ),
            max_depth=2,
            delay_seconds=0,
        )

        self.detector = FileDetector(
            self.config
        )

    def test_normaliza_url_relativa(self):
        result = Navigator.normalize_url(
            "/documentos/informe.pdf",
            "https://example.com/seccion/",
        )

        self.assertEqual(
            result,
            "https://example.com/documentos/informe.pdf",
        )

    def test_elimina_fragmento(self):
        result = Navigator.normalize_url(
            "https://example.com/pagina#contenido"
        )

        self.assertEqual(
            result,
            "https://example.com/pagina",
        )

    def test_ignora_mailto(self):
        result = Navigator.normalize_url(
            "mailto:correo@example.com"
        )

        self.assertIsNone(result)

    def test_detecta_documento_directo(self):
        responses = {
            "https://example.com/": {
                "body": """
                    <html>
                        <head>
                            <title>Inicio</title>
                        </head>
                        <body>
                            <a href="/docs/reporte.pdf">
                                Descargar reporte
                            </a>
                        </body>
                    </html>
                """
            }
        }

        client = FakeHttpClient(responses)

        navigator = Navigator(
            self.config,
            client,
            self.detector,
        )

        result = navigator.crawl()

        self.assertEqual(
            result.total_pages,
            1,
        )

        self.assertEqual(
            result.total_files,
            1,
        )

        self.assertEqual(
            result.files[0].file_type,
            "pdf",
        )

        self.assertEqual(
            result.files[0].link_text,
            "Descargar reporte",
        )

    def test_sigue_paginas_internas(self):
        responses = {
            "https://example.com/": {
                "body": """
                    <a href="/estadisticas">
                        Estadísticas
                    </a>
                """
            },
            "https://example.com/estadisticas": {
                "body": """
                    <a href="/datos/serie.xlsx">
                        Serie estadística
                    </a>
                """
            },
        }

        client = FakeHttpClient(responses)

        navigator = Navigator(
            self.config,
            client,
            self.detector,
        )

        result = navigator.crawl()

        self.assertEqual(
            result.total_pages,
            2,
        )

        self.assertEqual(
            result.total_files,
            1,
        )

        self.assertEqual(
            result.files[0].file_type,
            "xlsx",
        )

    def test_no_sigue_dominios_externos(self):
        responses = {
            "https://example.com/": {
                "body": """
                    <a href="https://google.com/archivo.pdf">
                        Externo
                    </a>

                    <a href="/archivo.pdf">
                        Interno
                    </a>
                """
            }
        }

        client = FakeHttpClient(responses)

        navigator = Navigator(
            self.config,
            client,
            self.detector,
        )

        result = navigator.crawl()

        urls = [
            file.url
            for file in result.files
        ]

        self.assertIn(
            "https://example.com/archivo.pdf",
            urls,
        )

        self.assertNotIn(
            "https://google.com/archivo.pdf",
            urls,
        )

    def test_evitar_ciclo(self):
        responses = {
            "https://example.com/": {
                "body": """
                    <a href="/pagina-a">
                        Página A
                    </a>
                """
            },
            "https://example.com/pagina-a": {
                "body": """
                    <a href="/">
                        Volver inicio
                    </a>
                """
            },
        }

        client = FakeHttpClient(responses)

        navigator = Navigator(
            self.config,
            client,
            self.detector,
        )

        result = navigator.crawl()

        self.assertEqual(
            result.total_pages,
            2,
        )

        self.assertEqual(
            client.requested_urls.count(
                "https://example.com/"
            ),
            1,
        )

    def test_no_duplica_archivos(self):
        responses = {
            "https://example.com/": {
                "body": """
                    <a href="/reporte.pdf">
                        Reporte 1
                    </a>

                    <a href="/reporte.pdf">
                        Reporte repetido
                    </a>
                """
            }
        }

        client = FakeHttpClient(responses)

        navigator = Navigator(
            self.config,
            client,
            self.detector,
        )

        result = navigator.crawl()

        self.assertEqual(
            result.total_files,
            1,
        )

    def test_respeta_profundidad_maxima(self):
        responses = {
            "https://example.com/": {
                "body": """
                    <a href="/nivel1">
                        Nivel 1
                    </a>
                """
            },
            "https://example.com/nivel1": {
                "body": """
                    <a href="/nivel2">
                        Nivel 2
                    </a>
                """
            },
            "https://example.com/nivel2": {
                "body": """
                    <a href="/nivel3">
                        Nivel 3
                    </a>
                """
            },
        }

        client = FakeHttpClient(responses)

        navigator = Navigator(
            self.config,
            client,
            self.detector,
        )

        result = navigator.crawl()

        visited_urls = [
            page.url
            for page in result.pages
        ]

        self.assertIn(
            "https://example.com/nivel2",
            visited_urls,
        )

        self.assertNotIn(
            "https://example.com/nivel3",
            visited_urls,
        )


if __name__ == "__main__":
    unittest.main()