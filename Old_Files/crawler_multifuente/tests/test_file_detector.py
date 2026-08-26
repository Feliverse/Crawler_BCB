import sys
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]

if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))


from Crawler_BCB.Old_Files.crawler_multifuente.core.file_detector import FileDetector
from Crawler_BCB.Old_Files.crawler_multifuente.core.source_config import SourceConfig


class FileDetectorTests(unittest.TestCase):

    def setUp(self):
        self.config = SourceConfig(
            id_fuente="test",
            nombre="Fuente de prueba",
            base_url="https://example.com/",
            extensions=(
                ".pdf",
                ".xlsx",
                ".xls",
                ".csv",
                ".doc",
                ".docx",
                ".zip",
                ".ods",
                ".txt",
            ),
        )

        self.detector = FileDetector(self.config)

    def test_detecta_pdf_por_extension(self):
        result = self.detector.detect(
            "https://example.com/documentos/informe.pdf"
        )

        self.assertTrue(result.is_downloadable)
        self.assertEqual(result.file_type, "pdf")
        self.assertEqual(result.extension, ".pdf")
        self.assertEqual(result.detected_by, "url_extension")

    def test_detecta_xlsx_por_extension(self):
        result = self.detector.detect(
            "https://example.com/datos/serie.xlsx"
        )

        self.assertTrue(result.is_downloadable)
        self.assertEqual(result.file_type, "xlsx")

    def test_detecta_zip_por_extension(self):
        result = self.detector.detect(
            "https://example.com/descargas/archivo.zip"
        )

        self.assertTrue(result.is_downloadable)
        self.assertEqual(result.file_type, "zip")

    def test_query_string_no_rompe_extension(self):
        result = self.detector.detect(
            "https://example.com/archivo.pdf?download=1&id=20"
        )

        self.assertTrue(result.is_downloadable)
        self.assertEqual(result.file_type, "pdf")

    def test_detecta_pdf_por_content_type_sin_extension(self):
        result = self.detector.detect(
            "https://example.com/download?id=123",
            {
                "Content-Type": "application/pdf"
            },
        )

        self.assertTrue(result.is_downloadable)
        self.assertEqual(result.file_type, "pdf")
        self.assertEqual(result.detected_by, "content_type")

    def test_detecta_xlsx_por_content_type(self):
        result = self.detector.detect(
            "https://example.com/download?id=456",
            {
                "Content-Type": (
                    "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet"
                )
            },
        )

        self.assertTrue(result.is_downloadable)
        self.assertEqual(result.file_type, "xlsx")

    def test_html_no_es_documento(self):
        result = self.detector.detect(
            "https://example.com/informe",
            {
                "Content-Type": "text/html; charset=UTF-8"
            },
        )

        self.assertFalse(result.is_downloadable)
        self.assertEqual(result.file_type, "html")

    def test_texto_informe_no_convierte_html_en_pdf(self):
        result = self.detector.detect(
            "https://example.com/node/123",
            {
                "Content-Type": "text/html"
            },
        )

        self.assertFalse(result.is_downloadable)
        self.assertNotEqual(result.file_type, "pdf")

    def test_extension_no_permitida(self):
        result = self.detector.detect(
            "https://example.com/video.mp4"
        )

        self.assertFalse(result.is_downloadable)

    def test_content_type_tiene_prioridad_sobre_url_enganosa(self):
        result = self.detector.detect(
            "https://example.com/documento.pdf",
            {
                "Content-Type": "text/html; charset=UTF-8"
            },
        )

        self.assertFalse(result.is_downloadable)
        self.assertEqual(result.file_type, "html")


if __name__ == "__main__":
    unittest.main()