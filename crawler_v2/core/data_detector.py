from __future__ import annotations

from dataclasses import dataclass

from urllib.parse import (
    unquote,
    urlparse,
)

from bs4 import BeautifulSoup
from bs4.element import Tag


DATA_KEYWORDS = (
    "estadistica",
    "estadística",
    "estadisticas",
    "estadísticas",
    "statistics",
    "statistical",
    "dato",
    "datos",
    "data",
    "dataset",
    "datasets",
    "database",
    "databases",
    "serie",
    "series",
    "indicador",
    "indicadores",
    "indicator",
    "indicators",
    "potencia",
    "generacion",
    "generación",
    "demanda",
    "oferta",
    "ventas",
    "consumo",
    "consumidores",
    "tarifa",
    "tarifas",
    "precio",
    "precios",
    "mercado",
    "market",
    "energy",
    "passenger",
    "freight",
    "traffic",
    "transport",
    "observation",
    "observations",
    "station",
    "stations",
    "temperature",
    "precipitation",
    "pressure",
    "humidity",
    "wind",
    "meteorological",
    "hydrological",
)


EXPORT_KEYWORDS = (
    "exportar",
    "export",
    "excel",
    "xlsx",
    "xls",
    "csv",
    "shp",
    "geojson",
    "json",
    "descargar datos",
    "download data",
    "download",
)


STRONG_DATA_PATHS = (
    "/informacion-estadistica/",
    "/informacion-estadistica",
    "/datos-y-estadisticas/",
    "/datos-y-estadisticas",
    "/estadisticas/",
    "/estadistica/",
    "/series/",
    "/serie-historica",
    "/indicadores/",
)


STRUCTURED_DATA_URL_HINTS = (
    "databaseinfo.asp",
    "fields.asp",
    "download.asp",
)


@dataclass
class DataPageDetection:
    is_data_page: bool

    has_table: bool = False

    has_export: bool = False

    has_filters: bool = False

    tables_count: int = 0

    reason: str | None = None


class DataDetector:

    # ========================================================
    # CONTENIDO PRINCIPAL
    # ========================================================

    @staticmethod
    def _main_content(
        soup: BeautifulSoup,
    ) -> Tag | BeautifulSoup:

        selectors = (
            "main",
            "article",
            ".entry-content",
            ".site-main",
            ".page-content",
            ".post-content",
            "#main",
            "#content",
        )

        for selector in selectors:

            element = soup.select_one(
                selector
            )

            if element is not None:
                return element

        if soup.body is not None:
            return soup.body

        return soup

    # ========================================================
    # TEXTO
    # ========================================================

    @staticmethod
    def _context_text(
        main: Tag | BeautifulSoup,
        title: str,
        url: str,
    ) -> str:

        headings = []

        for heading in main.find_all(
            [
                "h1",
                "h2",
                "h3",
            ],
            limit=15,
        ):

            text = heading.get_text(
                " ",
                strip=True,
            )

            if text:
                headings.append(
                    text
                )

        return (
            url
            + " "
            + title
            + " "
            + " ".join(
                headings
            )
        ).lower()

    # ========================================================
    # TABLAS
    # ========================================================

    @staticmethod
    def _is_data_table(
        table: Tag,
    ) -> bool:

        rows = table.find_all(
            "tr"
        )

        if len(rows) < 2:
            return False

        total_cells = 0

        max_columns = 0

        for row in rows:

            cells = row.find_all(
                [
                    "th",
                    "td",
                ]
            )

            total_cells += len(
                cells
            )

            max_columns = max(
                max_columns,
                len(cells),
            )

        if max_columns < 2:
            return False

        if total_cells < 6:
            return False

        return True

    def _find_data_tables(
        self,
        main: Tag | BeautifulSoup,
    ) -> list[Tag]:

        valid_tables = []

        for table in main.find_all(
            "table"
        ):

            if self._is_data_table(
                table
            ):
                valid_tables.append(
                    table
                )

        return valid_tables

    # ========================================================
    # EXPORTACIÓN
    # ========================================================

    @staticmethod
    def _has_export_control(
        main: Tag | BeautifulSoup,
    ) -> bool:

        for element in main.find_all(
            [
                "a",
                "button",
                "input",
            ]
        ):

            text = element.get_text(
                " ",
                strip=True,
            ).lower()

            href = str(
                element.get(
                    "href",
                    "",
                )
            ).lower()

            value = str(
                element.get(
                    "value",
                    "",
                )
            ).lower()

            classes = " ".join(
                element.get(
                    "class",
                    [],
                )
            ).lower()

            identifier = str(
                element.get(
                    "id",
                    "",
                )
            ).lower()

            searchable = (
                text
                + " "
                + href
                + " "
                + value
                + " "
                + classes
                + " "
                + identifier
            )

            if any(
                keyword in searchable
                for keyword in EXPORT_KEYWORDS
            ):
                return True

        return False

    # ========================================================
    # FILTROS
    # ========================================================

    @staticmethod
    def _has_filters(
        main: Tag | BeautifulSoup,
    ) -> bool:

        if main.find(
            "select"
        ) is not None:
            return True

        for input_element in main.find_all(
            "input"
        ):

            input_type = str(
                input_element.get(
                    "type",
                    "",
                )
            ).lower()

            if input_type in {
                "date",
                "month",
                "number",
                "range",
            }:
                return True

        return False

    # ========================================================
    # GRÁFICOS
    # ========================================================

    @staticmethod
    def _has_chart(
        main: Tag | BeautifulSoup,
    ) -> bool:

        if main.find(
            "canvas"
        ) is not None:
            return True

        for element in main.find_all(
            True
        ):

            classes = " ".join(
                element.get(
                    "class",
                    [],
                )
            ).lower()

            identifier = str(
                element.get(
                    "id",
                    "",
                )
            ).lower()

            searchable = (
                classes
                + " "
                + identifier
            )

            if any(
                keyword in searchable
                for keyword in (
                    "chart",
                    "highchart",
                    "plotly",
                    "grafico",
                    "grafica",
                    "graph",
                )
            ):
                return True

        return False

    # ========================================================
    # OGC / PYGeoAPI
    # ========================================================

    @staticmethod
    def _ogc_collection_reason(
        url: str,
    ) -> str | None:
        """
        Reconoce colecciones OGC API Features / pygeoapi.

        Registra la colección como dataset, pero NO cada item
        individual de la colección.
        """

        parsed = urlparse(
            unquote(url)
        )

        path = (
            parsed.path
            or ""
        ).lower().rstrip("/")

        marker = "/oapi/collections"

        if marker not in path:
            return None

        # Catálogo general.
        if path.endswith(
            marker
        ):
            return "ogc_collection_catalog"

        remainder = path.split(
            marker + "/",
            1,
        )

        if len(remainder) != 2:
            return None

        tail = (
            remainder[1]
            .strip("/")
        )

        if not tail:
            return "ogc_collection_catalog"

        # No registrar observaciones individuales.
        if "/items/" in tail:
            return None

        if tail.endswith(
            "/items"
        ):
            return None

        # queryables/schema son metadatos auxiliares,
        # no un dataset independiente.
        if (
            tail.endswith(
                "/queryables"
            )
            or tail.endswith(
                "/schema"
            )
        ):
            return None

        # Una única sección después de /collections/
        # representa una colección.
        if "/" not in tail:
            return "ogc_api_collection"

        return None

    # ========================================================
    # DETECCIÓN
    # ========================================================

    def detect(
        self,
        soup: BeautifulSoup,
        title: str,
        url: str,
    ) -> DataPageDetection:

        main = self._main_content(
            soup
        )

        context = self._context_text(
            main,
            title,
            url,
        )

        lowered_url = (
            url.lower()
        )

        keyword_found = any(
            keyword in context
            for keyword in DATA_KEYWORDS
        )

        strong_path = any(
            path in lowered_url
            for path in STRONG_DATA_PATHS
        )

        structured_data_page = any(
            marker in lowered_url
            for marker in STRUCTURED_DATA_URL_HINTS
        )

        ogc_reason = (
            self._ogc_collection_reason(
                url
            )
        )

        data_tables = (
            self._find_data_tables(
                main
            )
        )

        tables_count = len(
            data_tables
        )

        has_table = (
            tables_count > 0
        )

        has_export = (
            self._has_export_control(
                main
            )
        )

        has_filters = (
            self._has_filters(
                main
            )
        )

        has_chart = (
            self._has_chart(
                main
            )
        )

        # ====================================================
        # CASO 0 - OGC / PYGeoAPI
        # ====================================================

        if ogc_reason is not None:

            return DataPageDetection(
                is_data_page=True,

                has_table=has_table,

                has_export=True,

                has_filters=has_filters,

                tables_count=tables_count,

                reason=ogc_reason,
            )

        # ====================================================
        # CASO 1 - PORTALES LEGACY
        # TranStats
        # ====================================================

        if structured_data_page:

            if (
                "download.asp"
                in lowered_url
            ):

                reason = (
                    "interactive_download"
                )

                has_export = True

            elif (
                "fields.asp"
                in lowered_url
            ):

                reason = (
                    "data_table_definition"
                )

            elif (
                "databaseinfo.asp"
                in lowered_url
            ):

                reason = (
                    "database_dataset"
                )

            else:

                reason = (
                    "structured_data_page"
                )

            return DataPageDetection(
                is_data_page=True,

                has_table=has_table,

                has_export=has_export,

                has_filters=has_filters,

                tables_count=tables_count,

                reason=reason,
            )

        # ====================================================
        # CASO 2 - RUTA ESTADÍSTICA
        # ====================================================

        if (
            strong_path
            and (
                has_table
                or has_export
                or has_chart
                or has_filters
            )
        ):

            if has_table:

                reason = (
                    "statistical_html_table"
                )

            elif has_export:

                reason = (
                    "exportable_data_page"
                )

            elif has_chart:

                reason = (
                    "statistical_chart"
                )

            else:

                reason = (
                    "interactive_data_page"
                )

            return DataPageDetection(
                is_data_page=True,

                has_table=has_table,

                has_export=has_export,

                has_filters=has_filters,

                tables_count=tables_count,

                reason=reason,
            )

        # ====================================================
        # CASO 3 - CONTEXTO + TABLA
        # ====================================================

        if (
            keyword_found
            and has_table
        ):

            return DataPageDetection(
                is_data_page=True,

                has_table=True,

                has_export=has_export,

                has_filters=has_filters,

                tables_count=tables_count,

                reason="data_html_table",
            )

        # ====================================================
        # CASO 4 - CONTEXTO + EXPORT
        # ====================================================

        if (
            keyword_found
            and has_export
        ):

            return DataPageDetection(
                is_data_page=True,

                has_table=has_table,

                has_export=True,

                has_filters=has_filters,

                tables_count=tables_count,

                reason="exportable_data_page",
            )

        # ====================================================
        # CASO 5 - CONTEXTO + GRÁFICO
        # ====================================================

        if (
            keyword_found
            and has_chart
        ):

            return DataPageDetection(
                is_data_page=True,

                has_table=has_table,

                has_export=has_export,

                has_filters=has_filters,

                tables_count=tables_count,

                reason="data_chart",
            )

        return DataPageDetection(
            is_data_page=False,

            has_table=False,

            has_export=False,

            has_filters=False,

            tables_count=0,

            reason=None,
        )