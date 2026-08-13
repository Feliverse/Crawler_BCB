from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


DEFAULT_EXTENSIONS = (
    ".pdf",
    ".xlsx",
    ".xls",
    ".csv",
    ".doc",
    ".docx",
    ".zip",
    ".ods",
    ".txt",
)


@dataclass(frozen=True)
class SourceConfig:
    """
    Configuración declarativa de una fuente externa.

    El core no debe conocer ASFI, AETN, BCB ni ninguna otra
    institución. Todas las diferencias configurables deben vivir aquí.
    """

    id_fuente: str
    nombre: str
    base_url: str

    allowed_domains: tuple[str, ...] = field(
        default_factory=tuple
    )

    entrypoints: tuple[str, ...] = field(
        default_factory=tuple
    )

    extensions: tuple[str, ...] = DEFAULT_EXTENSIONS

    max_depth: int = 3
    max_pages: int | None = None
    max_files: int | None = None

    delay_seconds: float = 1.2
    request_timeout: int = 20
    inspect_zips: bool = True

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        if not self.id_fuente.strip():
            raise ValueError(
                "id_fuente no puede estar vacío."
            )

        if not self.nombre.strip():
            raise ValueError(
                "nombre no puede estar vacío."
            )

        self._validate_http_url(
            self.base_url,
            "base_url",
        )

        if self.max_depth < 0:
            raise ValueError(
                "max_depth no puede ser negativo."
            )

        if (
            self.max_pages is not None
            and self.max_pages <= 0
        ):
            raise ValueError(
                "max_pages debe ser mayor que cero."
            )

        if (
            self.max_files is not None
            and self.max_files <= 0
        ):
            raise ValueError(
                "max_files debe ser mayor que cero."
            )

        if self.delay_seconds < 0:
            raise ValueError(
                "delay_seconds no puede ser negativo."
            )

        if self.request_timeout <= 0:
            raise ValueError(
                "request_timeout debe ser mayor que cero."
            )

        if not self.extensions:
            raise ValueError(
                "Debe existir al menos una extensión permitida."
            )

        for entrypoint in self.entrypoints:
            self._validate_http_url(
                entrypoint,
                "entrypoint",
            )

            if not self.domain_is_allowed(
                entrypoint
            ):
                raise ValueError(
                    "El entrypoint pertenece a un dominio "
                    f"no permitido: {entrypoint}"
                )

    @staticmethod
    def _validate_http_url(
        url: str,
        field_name: str,
    ) -> None:
        parsed = urlparse(url)

        if parsed.scheme not in {
            "http",
            "https",
        }:
            raise ValueError(
                f"{field_name} debe utilizar http o https: "
                f"{url}"
            )

        if not parsed.netloc:
            raise ValueError(
                f"{field_name} no contiene un dominio válido: "
                f"{url}"
            )

    def domain_is_allowed(
        self,
        url: str,
    ) -> bool:
        parsed = urlparse(url)

        domain = (
            parsed.hostname or ""
        ).lower()

        if not domain:
            return False

        if self.allowed_domains:
            domains = self.allowed_domains
        else:
            base_domain = (
                urlparse(self.base_url).hostname
                or ""
            ).lower()

            domains = (
                base_domain,
            )

        for allowed_domain in domains:
            normalized_allowed = (
                allowed_domain
                .lower()
                .strip()
            )

            if domain == normalized_allowed:
                return True

            if domain.endswith(
                f".{normalized_allowed}"
            ):
                return True

        return False

    def get_entrypoints(self) -> tuple[str, ...]:
        """
        Devuelve las URLs desde las cuales debe comenzar el crawler.

        Si una fuente no configura entrypoints específicos,
        se utiliza automáticamente base_url.
        """

        if self.entrypoints:
            return self.entrypoints

        return (
            self.base_url,
        )


def _normalize_extension(
    extension: str,
) -> str:
    extension = (
        extension
        .strip()
        .lower()
    )

    if not extension:
        raise ValueError(
            "Se encontró una extensión vacía."
        )

    if not extension.startswith("."):
        extension = f".{extension}"

    return extension


def _optional_positive_int(
    value: Any,
    field_name: str,
) -> int | None:
    if value is None:
        return None

    parsed = int(value)

    if parsed <= 0:
        raise ValueError(
            f"{field_name} debe ser mayor que cero."
        )

    return parsed


def source_config_from_dict(
    data: dict[str, Any],
) -> SourceConfig:
    required_fields = (
        "id_fuente",
        "nombre",
        "base_url",
    )

    missing_fields = [
        field_name
        for field_name in required_fields
        if not data.get(field_name)
    ]

    if missing_fields:
        raise ValueError(
            "Faltan campos obligatorios en la configuración: "
            + ", ".join(missing_fields)
        )

    raw_extensions = data.get(
        "extensions",
        DEFAULT_EXTENSIONS,
    )

    extensions = tuple(
        _normalize_extension(extension)
        for extension in raw_extensions
    )

    allowed_domains = tuple(
        str(domain)
        .strip()
        .lower()
        for domain in data.get(
            "allowed_domains",
            [],
        )
        if str(domain).strip()
    )

    entrypoints = tuple(
        str(url).strip()
        for url in data.get(
            "entrypoints",
            [],
        )
        if str(url).strip()
    )

    return SourceConfig(
        id_fuente=str(
            data["id_fuente"]
        ).strip().lower(),

        nombre=str(
            data["nombre"]
        ).strip(),

        base_url=str(
            data["base_url"]
        ).strip(),

        allowed_domains=allowed_domains,

        entrypoints=entrypoints,

        extensions=extensions,

        max_depth=int(
            data.get(
                "max_depth",
                3,
            )
        ),

        max_pages=_optional_positive_int(
            data.get("max_pages"),
            "max_pages",
        ),

        max_files=_optional_positive_int(
            data.get("max_files"),
            "max_files",
        ),

        delay_seconds=float(
            data.get(
                "delay_seconds",
                1.2,
            )
        ),

        request_timeout=int(
            data.get(
                "request_timeout",
                20,
            )
        ),

        inspect_zips=bool(
            data.get(
                "inspect_zips",
                True,
            )
        ),
    )


def load_source_config(
    config_path: str | Path,
) -> SourceConfig:
    path = Path(config_path)

    if not path.exists():
        raise FileNotFoundError(
            f"No existe el archivo de configuración: {path}"
        )

    if not path.is_file():
        raise ValueError(
            "La ruta de configuración no corresponde "
            f"a un archivo: {path}"
        )

    try:
        with path.open(
            "r",
            encoding="utf-8-sig",
        ) as file:
            data = json.load(file)

    except json.JSONDecodeError as exc:
        raise ValueError(
            f"El archivo JSON no es válido: {path}"
        ) from exc

    if not isinstance(
        data,
        dict,
    ):
        raise ValueError(
            "La configuración raíz debe ser un objeto JSON."
        )

    return source_config_from_dict(
        data
    )