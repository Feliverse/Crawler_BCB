from __future__ import annotations

from dataclasses import dataclass, field

from urllib.parse import (
    urljoin,
    urlparse,
    urlunparse,
)

from requests import Response


# ============================================================
# MODELOS
# ============================================================

@dataclass
class OpenApiEndpoint:
    url: str

    path: str

    method: str

    summary: str | None = None

    operation_id: str | None = None

    safe_to_execute: bool = False

    reason: str = ""

    requires_auth: bool = False

    required_parameters: list[str] = field(
        default_factory=list
    )


@dataclass
class OpenApiDiscoveryResult:
    version: str | None = None

    base_urls: list[str] = field(
        default_factory=list
    )

    endpoints: list[
        OpenApiEndpoint
    ] = field(
        default_factory=list
    )

    executable_endpoints: list[
        OpenApiEndpoint
    ] = field(
        default_factory=list
    )

    skipped_endpoints: int = 0


# ============================================================
# OPENAPI DISCOVERY
# ============================================================

class OpenApiDiscovery:
    """
    Analiza documentos OpenAPI / Swagger.

    Su objetivo NO es ejecutar ciegamente toda la API.

    Solamente considera automáticamente ejecutables los GET
    que:

    - no contienen parámetros de ruta {param}
    - no requieren parámetros obligatorios
    - no requieren autenticación
    - no están marcados como deprecated
    - pueden construirse sin inventar valores
    """

    HTTP_METHODS = {
        "get",
        "post",
        "put",
        "patch",
        "delete",
        "head",
        "options",
        "trace",
    }

    # ========================================================
    # JSON
    # ========================================================

    @staticmethod
    def _load_document(
        response: Response,
    ) -> dict | None:

        try:
            data = response.json()

        except ValueError:
            return None

        if not isinstance(
            data,
            dict,
        ):
            return None

        return data

    # ========================================================
    # BASE DEL DOCUMENTO
    # ========================================================

    @staticmethod
    def _document_base(
        document_url: str,
    ) -> str:

        parsed = urlparse(
            document_url
        )

        path = (
            parsed.path
            or "/"
        )

        segments = [
            segment
            for segment
            in path.split("/")
            if segment
        ]

        if segments:

            last = (
                segments[-1]
                .lower()
            )

            if (
                "openapi"
                in last
                or "swagger"
                in last
                or last
                in {
                    "api-docs",
                    "docs",
                }
            ):
                segments = (
                    segments[:-1]
                )

        if segments:

            base_path = (
                "/"
                + "/".join(
                    segments
                )
                + "/"
            )

        else:

            base_path = "/"

        return urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                base_path,
                "",
                "",
                "",
            )
        )

    # ========================================================
    # SERVERS OPENAPI 3
    # ========================================================

    @staticmethod
    def _replace_server_variables(
        server: dict,
    ) -> str | None:

        url = str(
            server.get(
                "url",
                "",
            )
        ).strip()

        if not url:
            return None

        variables = (
            server.get(
                "variables",
                {}
            )
            or {}
        )

        if not isinstance(
            variables,
            dict,
        ):
            variables = {}

        for (
            name,
            definition,
        ) in variables.items():

            marker = (
                "{"
                + str(name)
                + "}"
            )

            if marker not in url:
                continue

            if not isinstance(
                definition,
                dict,
            ):
                return None

            default = (
                definition.get(
                    "default"
                )
            )

            if default is None:
                return None

            url = url.replace(
                marker,
                str(
                    default
                ),
            )

        # Si quedaron variables sin resolver,
        # no utilizamos ese servidor.
        if (
            "{"
            in url
            or "}"
            in url
        ):
            return None

        return url

    # ========================================================
    # BASE URL
    # ========================================================

    def _base_urls(
        self,
        document: dict,
        document_url: str,
    ) -> list[str]:

        bases: list[str] = []

        document_base = (
            self._document_base(
                document_url
            )
        )

        # ----------------------------------------------------
        # OPENAPI 3.x
        # ----------------------------------------------------

        servers = (
            document.get(
                "servers"
            )
        )

        if isinstance(
            servers,
            list,
        ):

            for server in servers:

                if not isinstance(
                    server,
                    dict,
                ):
                    continue

                server_url = (
                    self
                    ._replace_server_variables(
                        server
                    )
                )

                if not server_url:
                    continue

                absolute = urljoin(
                    document_base,
                    server_url,
                )

                absolute = (
                    absolute.rstrip("/")
                )

                if (
                    absolute
                    and absolute
                    not in bases
                ):
                    bases.append(
                        absolute
                    )

        # ----------------------------------------------------
        # SWAGGER 2.x
        # ----------------------------------------------------

        host = (
            document.get(
                "host"
            )
        )

        if host:

            schemes = (
                document.get(
                    "schemes"
                )
                or []
            )

            if (
                not isinstance(
                    schemes,
                    list,
                )
                or not schemes
            ):

                schemes = [
                    urlparse(
                        document_url
                    ).scheme
                    or "https"
                ]

            base_path = str(
                document.get(
                    "basePath",
                    "",
                )
                or ""
            ).strip()

            for scheme in schemes:

                value = (
                    f"{scheme}://"
                    f"{host}"
                    f"{base_path}"
                ).rstrip("/")

                if (
                    value
                    and value
                    not in bases
                ):
                    bases.append(
                        value
                    )

        # ----------------------------------------------------
        # FALLBACK
        # ----------------------------------------------------

        if not bases:

            bases.append(
                document_base.rstrip(
                    "/"
                )
            )

        return bases

    # ========================================================
    # CONSTRUIR ENDPOINT
    # ========================================================

    @staticmethod
    def _join_endpoint(
        base_url: str,
        path: str,
    ) -> str:

        return (
            base_url.rstrip("/")
            + "/"
            + path.lstrip("/")
        )

    # ========================================================
    # SEGURIDAD
    # ========================================================

    @staticmethod
    def _requires_auth(
        document: dict,
        operation: dict,
    ) -> bool:

        # security en operación tiene prioridad.
        if "security" in operation:

            security = (
                operation.get(
                    "security"
                )
            )

        else:

            security = (
                document.get(
                    "security"
                )
            )

        # OpenAPI:
        #
        # security: []
        #
        # significa explícitamente sin autenticación.
        if security == []:
            return False

        if not security:
            return False

        if isinstance(
            security,
            list,
        ):

            return any(
                isinstance(
                    item,
                    dict,
                )
                and bool(
                    item
                )

                for item
                in security
            )

        return False

    # ========================================================
    # PARÁMETROS
    # ========================================================

    @staticmethod
    def _collect_parameters(
        path_definition: dict,
        operation: dict,
    ) -> tuple[
        list[str],
        bool,
    ]:
        """
        Devuelve:

            parámetros obligatorios,
            referencia no resoluble encontrada
        """

        parameters = []

        for source in (
            path_definition.get(
                "parameters",
                [],
            ),
            operation.get(
                "parameters",
                [],
            ),
        ):

            if isinstance(
                source,
                list,
            ):

                parameters.extend(
                    source
                )

        required: list[str] = []

        unresolved_reference = False

        for parameter in parameters:

            if not isinstance(
                parameter,
                dict,
            ):
                continue

            if "$ref" in parameter:

                # Conservador:
                # no ejecutamos automáticamente algo cuya
                # definición de parámetro no resolvimos.
                unresolved_reference = True

                continue

            if not parameter.get(
                "required",
                False,
            ):
                continue

            name = str(
                parameter.get(
                    "name",
                    "parametro",
                )
            )

            location = str(
                parameter.get(
                    "in",
                    "",
                )
            )

            required.append(
                (
                    f"{location}:"
                    f"{name}"
                )
            )

        return (
            required,
            unresolved_reference,
        )

    # ========================================================
    # VERSIÓN
    # ========================================================

    @staticmethod
    def _version(
        document: dict,
    ) -> str | None:

        if "openapi" in document:

            return str(
                document[
                    "openapi"
                ]
            )

        if "swagger" in document:

            return (
                "swagger-"
                + str(
                    document[
                        "swagger"
                    ]
                )
            )

        return None

    # ========================================================
    # DISCOVERY
    # ========================================================

    def discover(
        self,
        response: Response,
        document_url: str,
        *,
        max_endpoints: int = 50,
    ) -> OpenApiDiscoveryResult:

        document = (
            self._load_document(
                response
            )
        )

        if document is None:

            return (
                OpenApiDiscoveryResult()
            )

        result = (
            OpenApiDiscoveryResult(
                version=(
                    self._version(
                        document
                    )
                )
            )
        )

        result.base_urls = (
            self._base_urls(
                document,
                document_url,
            )
        )

        paths = (
            document.get(
                "paths"
            )
        )

        if not isinstance(
            paths,
            dict,
        ):

            return result

        executable_count = 0

        # ====================================================
        # PATHS
        # ====================================================

        for (
            path,
            path_definition,
        ) in paths.items():

            if not isinstance(
                path_definition,
                dict,
            ):
                continue

            operation = (
                path_definition.get(
                    "get"
                )
            )

            # Solo GET.
            if not isinstance(
                operation,
                dict,
            ):
                continue

            summary = str(
                operation.get(
                    "summary",
                    "",
                )
                or ""
            ).strip()

            operation_id = str(
                operation.get(
                    "operationId",
                    "",
                )
                or ""
            ).strip()

            requires_auth = (
                self._requires_auth(
                    document,
                    operation,
                )
            )

            (
                required_parameters,
                unresolved_reference,
            ) = (
                self._collect_parameters(
                    path_definition,
                    operation,
                )
            )

            deprecated = bool(
                operation.get(
                    "deprecated",
                    False,
                )
            )

            has_path_template = (
                "{"
                in str(
                    path
                )
                or "}"
                in str(
                    path
                )
            )

            request_body = (
                operation.get(
                    "requestBody"
                )
            )

            required_body = (
                isinstance(
                    request_body,
                    dict,
                )
                and bool(
                    request_body.get(
                        "required",
                        False,
                    )
                )
            )

            # =================================================
            # SEGURIDAD DE EJECUCIÓN
            # =================================================

            if deprecated:

                safe = False

                reason = (
                    "deprecated"
                )

            elif requires_auth:

                safe = False

                reason = (
                    "authentication_required"
                )

            elif has_path_template:

                safe = False

                reason = (
                    "path_parameter_required"
                )

            elif required_parameters:

                safe = False

                reason = (
                    "required_parameters"
                )

            elif unresolved_reference:

                safe = False

                reason = (
                    "unresolved_parameter_reference"
                )

            elif required_body:

                safe = False

                reason = (
                    "required_request_body"
                )

            else:

                safe = True

                reason = (
                    "safe_get_endpoint"
                )

            # =================================================
            # BASES
            # =================================================

            for base_url in result.base_urls:

                url = (
                    self._join_endpoint(
                        base_url,
                        str(
                            path
                        ),
                    )
                )

                endpoint = (
                    OpenApiEndpoint(
                        url=url,

                        path=str(
                            path
                        ),

                        method="GET",

                        summary=(
                            summary
                            or None
                        ),

                        operation_id=(
                            operation_id
                            or None
                        ),

                        safe_to_execute=(
                            safe
                        ),

                        reason=(
                            reason
                        ),

                        requires_auth=(
                            requires_auth
                        ),

                        required_parameters=(
                            required_parameters
                        ),
                    )
                )

                result.endpoints.append(
                    endpoint
                )

                if not safe:

                    result.skipped_endpoints += 1

                    continue

                if (
                    executable_count
                    >= max_endpoints
                ):

                    result.skipped_endpoints += 1

                    continue

                result.executable_endpoints.append(
                    endpoint
                )

                executable_count += 1

        return result