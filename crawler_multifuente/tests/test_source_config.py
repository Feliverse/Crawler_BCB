import sys
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]

if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(
        0,
        str(PROJECT_DIR),
    )


from core.source_config import (
    SourceConfig,
    source_config_from_dict,
)


class SourceConfigTests(unittest.TestCase):

    def test_limites_son_opcionales(self):
        config = SourceConfig(
            id_fuente="test",
            nombre="Fuente",
            base_url="https://example.com/",
        )

        self.assertIsNone(
            config.max_pages
        )

        self.assertIsNone(
            config.max_files
        )

    def test_carga_limites_desde_diccionario(self):
        config = source_config_from_dict(
            {
                "id_fuente": "test",
                "nombre": "Fuente",
                "base_url": "https://example.com/",
                "max_pages": 50,
                "max_files": 500,
            }
        )

        self.assertEqual(
            config.max_pages,
            50,
        )

        self.assertEqual(
            config.max_files,
            500,
        )

    def test_rechaza_max_pages_cero(self):
        with self.assertRaises(
            ValueError
        ):
            SourceConfig(
                id_fuente="test",
                nombre="Fuente",
                base_url="https://example.com/",
                max_pages=0,
            )

    def test_rechaza_max_files_negativo(self):
        with self.assertRaises(
            ValueError
        ):
            SourceConfig(
                id_fuente="test",
                nombre="Fuente",
                base_url="https://example.com/",
                max_files=-1,
            )


if __name__ == "__main__":
    unittest.main()