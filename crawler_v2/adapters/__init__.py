from __future__ import annotations

from adapters.asfi import AsfiAdapter
from adapters.asofin import AsofinAdapter
from adapters.att import AttAdapter
from adapters.bbv import BbvAdapter
from adapters.bcb import BcbAdapter
from adapters.mdryt import MdrytAdapter
from adapters.senamhi import SenamhiAdapter
from adapters.snis import SnisAdapter
from adapters.transtats import TranstatsAdapter
from adapters.generic import GenericAdapter


ADAPTERS = {
    "asfi": AsfiAdapter,
    "asofin": AsofinAdapter,
    "att": AttAdapter,
    "bbv": BbvAdapter,
    "bcb": BcbAdapter,
    "mdryt": MdrytAdapter,
    "senamhi": SenamhiAdapter,
    "snis": SnisAdapter,
    "transtats": TranstatsAdapter,
}


def build_adapter(
    config: dict,
) -> GenericAdapter:

    source_id = str(
        config.get(
            "id_fuente",
            "",
        )
    ).strip().lower()

    adapter_class = ADAPTERS.get(
        source_id,
        GenericAdapter,
    )

    return adapter_class(
        config
    )