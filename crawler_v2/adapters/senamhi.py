from __future__ import annotations

from urllib.parse import (
    unquote,
    urlparse,
)

from adapters.generic import GenericAdapter


HIGH_PRIORITY = (
    "/oapi/collections",
    "public-stations-info-export",
    "public-stations",
    "public-geoanalisys",
    "observations",
    "stations",
    "discovery-metadata",
)


LOW_PRIORITY = (
    "/admin",
    "/contact",
    "/about",
    "/noticias",
    "/news",
)


class SenamhiAdapter(GenericAdapter):

    def should_follow(
        self,
        url: str,
    ) -> bool:

        if not super().should_follow(
            url
        ):
            return False

        parsed = urlparse(
            url
        )

        hostname = (
            parsed.hostname
            or ""
        ).lower()

        if hostname not in {
            "wis.senamhi.gob.bo",
            "onsc.senamhi.gob.bo",
            "www.senamhi.gob.bo",
            "senamhi.gob.bo",
        }:
            return False

        searchable = unquote(
            url
        ).lower()

        path = (
            parsed.path
            or ""
        ).lower()

        # -----------------------------------------------------
        # MUY IMPORTANTE
        #
        # No recorrer observaciones individuales.
        #
        # Ejemplo:
        #
        # /oapi/collections/.../items/UUID
        #
        # Una colección puede tener cientos de miles de registros.
        # Nosotros queremos mapear LA COLECCIÓN, no abrir registro
        # por registro.
        # -----------------------------------------------------

        if "/oapi/collections/" in path:

            if "/items/" in path:
                return False

            # Tampoco necesitamos abrir el listado completo
            # de observaciones.
            if path.rstrip("/").endswith(
                "/items"
            ):
                return False

        if any(
            token in searchable
            for token in LOW_PRIORITY
        ):
            return False

        return True

    def priority(
        self,
        url: str,
        text: str,
    ) -> int:

        searchable = (
            unquote(url)
            + " "
            + text
        ).lower()

        if any(
            token in searchable
            for token in HIGH_PRIORITY
        ):
            return 1

        if any(
            token in searchable
            for token in LOW_PRIORITY
        ):
            return 95

        return super().priority(
            url,
            text,
        )

    def extend_path(
        self,
        current_path: tuple[str, ...],
        text: str,
        url: str,
    ) -> tuple[str, ...]:

        cleaned = " ".join(
            text.split()
        ).strip()

        lowered = cleaned.lower()

        if lowered in {
            "json",
            "jsonld",
            "html",
            "browse",
            "schema",
            "queryables",
            "next",
            "previous",
        }:
            return current_path

        return super().extend_path(
            current_path,
            text,
            url,
        )