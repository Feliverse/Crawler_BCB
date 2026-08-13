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
    Configuración de una fuente externa que será procesada por el crawler.

    Esta clase contiene únicamente parámetros de configuración.
    No debe contener lógica específica de ASFI, BCB ni de ninguna otra fuente.
    """

    id_fuente: str
    nombre: str
    base_url: str

    allowed_domains: tuple[str, ...] = field(default_factory=tuple)
    extensions: tuple[str, ...] = DEFAULT_EXTENSIONS

    max_depth: int = 3
    delay_seconds: float = 1.2
    request_timeout: int = 20
    inspect_zips: bool = True

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        if not self.id_fuente.strip():
            raise ValueError("id_fuente no puede estar vacío.")

        if not self.nombre.strip():
            raise ValueError("nombre no puede estar vacío.")

        parsed_url = urlparse(self.base_url)

        if parsed_url.scheme not in {"http", "https"}:
            raise ValueError(
                f"base_url debe utilizar http o https: {self.base_url}"
            )

        if not parsed_url.netloc:
            raise ValueError(
                f"base_url no contiene un dominio válido: {self.base_url}"
            )

        if self.max_depth < 0:
            raise ValueError("max_depth no puede ser negativo.")

        if self.delay_seconds < 0:
            raise ValueError("delay_seconds no puede ser negativo.")

        if self.request_timeout <= 0:
            raise ValueError("request_timeout debe ser mayor que cero.")

        if not self.extensions:
            raise ValueError("Debe existir al menos una extensión permitida.")

    def domain_is_allowed(self, url: str) -> bool:
        """
        Indica si una URL pertenece a uno de los dominios permitidos.

        Si allowed_domains está vacío, solamente se permite el dominio
        definido por base_url.
        """
        parsed = urlparse(url)
        domain = parsed.netloc.lower().split(":")[0]

        domains = self.allowed_domains or (
            urlparse(self.base_url).netloc.lower().split(":")[0],
        )

        for allowed_domain in domains:
            normalized_allowed = allowed_domain.lower().strip()

            if domain == normalized_allowed:
                return True

            if domain.endswith(f".{normalized_allowed}"):
                return True

        return False


def _normalize_extension(extension: str) -> str:
    extension = extension.strip().lower()

    if not extension:
        raise ValueError("Se encontró una extensión vacía.")

    if not extension.startswith("."):
        extension = f".{extension}"

    return extension


def source_config_from_dict(data: dict[str, Any]) -> SourceConfig:
    """
    Construye y valida SourceConfig desde un diccionario.
    """
    required_fields = ("id_fuente", "nombre", "base_url")

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

    raw_extensions = data.get("extensions", DEFAULT_EXTENSIONS)

    extensions = tuple(
        _normalize_extension(extension)
        for extension in raw_extensions
    )

    allowed_domains = tuple(
        str(domain).strip().lower()
        for domain in data.get("allowed_domains", [])
        if str(domain).strip()
    )

    return SourceConfig(
        id_fuente=str(data["id_fuente"]).strip().lower(),
        nombre=str(data["nombre"]).strip(),
        base_url=str(data["base_url"]).strip(),
        allowed_domains=allowed_domains,
        extensions=extensions,
        max_depth=int(data.get("max_depth", 3)),
        delay_seconds=float(data.get("delay_seconds", 1.2)),
        request_timeout=int(data.get("request_timeout", 20)),
        inspect_zips=bool(data.get("inspect_zips", True)),
    )


def load_source_config(config_path: str | Path) -> SourceConfig:
    """
    Lee una configuración JSON desde disco y devuelve SourceConfig.
    """
    path = Path(config_path)

    if not path.exists():
        raise FileNotFoundError(
            f"No existe el archivo de configuración: {path}"
        )

    if not path.is_file():
        raise ValueError(
            f"La ruta de configuración no corresponde a un archivo: {path}"
        )

    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"El archivo JSON no es válido: {path}"
        ) from exc

    if not isinstance(data, dict):
        raise ValueError(
            "La configuración raíz debe ser un objeto JSON."
        )

    return source_config_from_dict(data)