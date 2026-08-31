from __future__ import annotations

from datetime import date
from urllib.parse import urlparse

from adapters.asfi import AsfiAdapter
from adapters.generic import (
    AdapterFileCandidate,
    AdapterFileCandidateGroup,
)


IFD_PAGE_PATH = (
    "/pb/instituciones-financieras-desarrollo"
)

IFD_SCRIPT_MARKER = (
    "/sites/default/files/js_/ifd-bol.js"
)

IFD_FILES_ROOT = (
    "/sites/default/files/estadisticaif/int_fin_des"
)

MONTHLY_RESOURCES = (
    (
        "ESTADOS FINANCIEROS",
        "Estados Financieros",
        "IFD_EstadosFinancieros.zip",
    ),
    (
        "ESTADOS FINANCIEROS",
        "Estados Financieros por monedas",
        "IFD_EstadosFinancierosMoneda.zip",
    ),
    (
        "INDICADORES FINANCIEROS",
        "Calificación de Cartera",
        "IFD_CalificacionCartera.zip",
    ),
    (
        "INDICADORES FINANCIEROS",
        "Indicadores Financieros",
        "IFD_IndicadoresFinancieros.zip",
    ),
    (
        "INDICADORES FINANCIEROS",
        "Ponderación de Activos y CAP.",
        "IFD_PonderacionActivos.zip",
    ),
    (
        "CAPTACIONES",
        "Encaje Legal",
        "SNB_EncajeLegal.zip",
    ),
    (
        "CAPTACIONES",
        "Estratificación de depósitos",
        "IFD_EstratificacionDepTotal.zip",
    ),
    (
        "CAPTACIONES",
        "Obligaciones, cartera y contingente por departamento",
        "IFD_ObligCarteraContingenteTotal.zip",
    ),
    (
        "ESTADOS FINANCIEROS EVOLUTIVOS",
        "Estados Financieros evolutivos",
        "IFD_EstadosFinancieros_Evolutivo.zip",
    ),
    (
        "INDICADORES FINANCIEROS EVOLUTIVOS",
        "Indicadores Financieros evolutivos",
        "IFD_IndicadoresFinancieros_Evolutivo.zip",
    ),
    (
        "ESTADOS FINANCIEROS DESAGREGADOS",
        "Estados financieros desagregados",
        "IFD_EstadosFinancierosDesagregados.zip",
    ),
    (
        "AGENCIAS, SUCURSALES Y NRO. DE EMPLEADOS",
        "Puntos de atención financiera por departamento",
        "IFD_PAFs_x_Depto.zip",
    ),
)

QUARTERLY_RESOURCES = (
    (
        "COLOCACIONES",
        (
            "Trimestral - Clasificación de cartera por actividad "
            "económica del deudor"
        ),
        "IFD_ClasifCarteraActividadEconomica.zip",
    ),
    (
        "COLOCACIONES",
        (
            "Trimestral - Clasificación de cartera por tipo "
            "de crédito"
        ),
        "IFD_ClasifCarteraTipoCredito.zip",
    ),
    (
        "COLOCACIONES",
        (
            "Trimestral - Clasificación de cartera y contingente "
            "por departamento, estado y destino del crédito"
        ),
        "IFD_ClasifCarContDeptoEstadoDestino.zip",
    ),
    (
        "COLOCACIONES",
        (
            "Trimestral - Clasificación de cartera y contingente "
            "por entidad, estado y destino del crédito"
        ),
        "IFD_ClasifCarContEntidadEstadoDestino.zip",
    ),
    (
        "COLOCACIONES",
        (
            "Trimestral - Clasificación de cartera y contingente "
            "por entidad, estado y tipo de crédito"
        ),
        "IFD_ClasifCarContEntidadEstadoTipo.zip",
    ),
    (
        "COLOCACIONES",
        (
            "Trimestral - Clasificación de cartera y contingente "
            "por tipo de garantía"
        ),
        "IFD_ClasifCarContTipoGarantia.zip",
    ),
    (
        "COLOCACIONES",
        (
            "Trimestral - Clasificación de cartera y contingente "
            "por tipo y objeto del crédito"
        ),
        "IFD_ClasifCarContTipoObjCredito.zip",
    ),
    (
        "COLOCACIONES",
        (
            "Trimestral - Clasificación del contingente por "
            "actividad económica del deudor"
        ),
        "IFD_ClasifContingActividadEconomica.zip",
    ),
    (
        "COLOCACIONES",
        (
            "Trimestral - Estratificación de cartera y contingente "
            "por entidad y estado de crédito"
        ),
        "IFD_EstratifCarContEntidadEstado.zip",
    ),
    (
        "COLOCACIONES",
        (
            "Trimestral - Estratificación de cartera por monto "
            "y número de prestatarios"
        ),
        "IFD_EstratifCarContMontoNumeroPrestatarios.zip",
    ),
    (
        "AGENCIAS, SUCURSALES Y NRO. DE EMPLEADOS",
        "Trimestral - Agencias, Sucursales y Nro. de Empleados",
        "IFD_Agencias.zip",
    ),
)

QUARTER_MONTHS = {
    3,
    6,
    9,
    12,
}

PROBE_SUFFIXES = (
    "IFD_EstadosFinancieros.zip",
    "IFD_IndicadoresFinancieros.zip",
)


class AsfiFinruralAdapter(AsfiAdapter):
    """
    Adapter específico para la sección de Instituciones Financieras
    de Desarrollo (IFD) publicada por ASFI.

    La página no expone los ZIP en el HTML inicial. El JavaScript
    `ifd-bol.js` construye sus URLs con una regla año/mes. Este adapter
    reproduce únicamente esa semántica pública y deja al core la
    comprobación HTTP, relevancia, registro y deduplicación.
    """

    def generated_file_groups(
        self,
        *,
        page_url: str,
        html: str,
        title: str,
    ) -> tuple[
        AdapterFileCandidateGroup,
        ...,
    ]:
        parsed = urlparse(
            str(
                page_url
                or ""
            )
        )

        path = (
            parsed.path
            or ""
        ).rstrip("/").lower()

        if path != IFD_PAGE_PATH:
            return ()

        if (
            IFD_SCRIPT_MARKER
            not in str(
                html
                or ""
            )
        ):
            return ()

        today = date.today()

        try:
            start_year = int(
                self.config.get(
                    "ifd_generated_start_year",
                    2005,
                )
            )
        except (
            TypeError,
            ValueError,
        ):
            start_year = 2005

        try:
            end_year = int(
                self.config.get(
                    "ifd_generated_end_year",
                    today.year,
                )
            )
        except (
            TypeError,
            ValueError,
        ):
            end_year = today.year

        start_year = max(
            2000,
            start_year,
        )

        end_year = min(
            today.year,
            max(
                start_year,
                end_year,
            ),
        )

        base_url = (
            f"{parsed.scheme or 'https'}://"
            f"{parsed.netloc or 'www.asfi.gob.bo'}"
        )

        groups: list[
            AdapterFileCandidateGroup
        ] = []

        # Más reciente primero: da valor rápido y facilita observar
        # si el sitio deja de publicar periodos nuevos.
        for year in range(
            end_year,
            start_year - 1,
            -1,
        ):
            max_month = (
                today.month
                if year == today.year
                else 12
            )

            for month in range(
                max_month,
                0,
                -1,
            ):
                period = (
                    f"{year:04d}-"
                    f"{month:02d}"
                )

                prefix = (
                    f"{year:04d}"
                    f"{month:02d}_"
                )

                root = (
                    f"{base_url}"
                    f"{IFD_FILES_ROOT}/"
                    f"{year:04d}/"
                    f"{month:02d}/"
                )

                resource_specs = list(
                    MONTHLY_RESOURCES
                )

                if month in QUARTER_MONTHS:
                    resource_specs.extend(
                        QUARTERLY_RESOURCES
                    )

                candidates: list[
                    AdapterFileCandidate
                ] = []

                by_suffix: dict[
                    str,
                    AdapterFileCandidate,
                ] = {}

                for (
                    category,
                    description,
                    suffix,
                ) in resource_specs:
                    candidate = (
                        AdapterFileCandidate(
                            url=(
                                f"{root}"
                                f"{prefix}"
                                f"{suffix}"
                            ),
                            description=description,
                            path=(
                                "Intermediación Financiera",
                                (
                                    "Instituciones Financieras "
                                    "de Desarrollo"
                                ),
                                period,
                                category,
                            ),
                        )
                    )

                    # La fuente repite algunos nombres en su JS.
                    # El dict evita duplicar candidatos por URL/sufijo.
                    if suffix not in by_suffix:
                        by_suffix[
                            suffix
                        ] = candidate

                        candidates.append(
                            candidate
                        )

                probes = tuple(
                    by_suffix[
                        suffix
                    ]
                    for suffix in PROBE_SUFFIXES
                    if suffix in by_suffix
                )

                groups.append(
                    AdapterFileCandidateGroup(
                        key=period,
                        probes=probes,
                        candidates=tuple(
                            candidates
                        ),
                    )
                )

        return tuple(
            groups
        )

    def relevance_adjustment(
        self,
        *,
        url: str,
        description: str = "",
        origin_url: str = "",
        path: tuple[str, ...] | list[str] = (),
        resource_type: str = "",
    ) -> int:
        adjustment = super().relevance_adjustment(
            url=url,
            description=description,
            origin_url=origin_url,
            path=path,
            resource_type=resource_type,
        )

        searchable = " ".join(
            (
                str(
                    url
                    or ""
                ),
                str(
                    origin_url
                    or ""
                ),
                str(
                    description
                    or ""
                ),
                " ".join(
                    str(
                        item
                        or ""
                    )
                    for item in path
                ),
            )
        ).lower()

        if (
            "/estadisticaif/int_fin_des/"
            in searchable
        ):
            adjustment += 80

        return adjustment
