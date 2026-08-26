from __future__ import annotations

from Crawler_BCB.Old_Files.crawler_multifuente.core.site_adapter import SiteAdapter
from Crawler_BCB.Old_Files.crawler_multifuente.core.source_config import SourceConfig

from Crawler_BCB.Old_Files.crawler_multifuente.adapters.asfi import AsfiAdapter


ADAPTERS = {
    "asfi": AsfiAdapter,
}


def build_adapter(
    config: SourceConfig,
) -> SiteAdapter:
    """
    Devuelve un adapter especializado cuando existe.

    Si una fuente no necesita comportamiento particular,
    utiliza automáticamente el adapter genérico.
    """

    adapter_class = ADAPTERS.get(
        config.id_fuente,
        SiteAdapter,
    )

    return adapter_class(
        config
    )