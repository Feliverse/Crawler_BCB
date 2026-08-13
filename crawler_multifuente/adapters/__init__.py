from __future__ import annotations

from core.site_adapter import SiteAdapter
from core.source_config import SourceConfig

from adapters.asfi import AsfiAdapter


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