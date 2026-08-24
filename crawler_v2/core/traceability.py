from __future__ import annotations

import sqlite3

from datetime import (
    datetime,
    timezone,
)

from pathlib import Path


# ============================================================
# ESTADOS
# ============================================================

STATUS_PENDING = "PENDING"

STATUS_IN_PROCESS = "IN_PROCESS"

STATUS_PROCESSED = "PROCESSED"

STATUS_ERROR = "ERROR"


# ============================================================
# TRACEABILITY
# ============================================================

class Traceability:
    """
    Mantiene un historial local de las ejecuciones del crawler.

    La información de trazabilidad queda separada del JSON
    contractual generado para cada fuente.

    Base:

        trace/crawler_trace.sqlite
    """

    def __init__(
        self,
        database_path: str | Path,
    ) -> None:

        self.database_path = Path(
            database_path
        )

        self.database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._initialize()

    # ========================================================
    # CONEXIÓN
    # ========================================================

    def _connect(
        self,
    ) -> sqlite3.Connection:

        connection = sqlite3.connect(
            self.database_path
        )

        connection.row_factory = (
            sqlite3.Row
        )

        connection.execute(
            "PRAGMA foreign_keys = ON"
        )

        return connection

    # ========================================================
    # FECHA
    # ========================================================

    @staticmethod
    def _now(
    ) -> str:

        return (
            datetime.now(
                timezone.utc
            )
            .isoformat(
                timespec="seconds"
            )
        )

    # ========================================================
    # ESTRUCTURA
    # ========================================================

    def _initialize(
        self,
    ) -> None:

        with self._connect() as connection:

            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS ejecuciones (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,

                    fuente TEXT NOT NULL,

                    fecha_inicio TEXT NOT NULL,

                    fecha_fin TEXT,

                    url_configurada TEXT,

                    url_utilizada TEXT,

                    uso_fallback INTEGER NOT NULL DEFAULT 0,

                    estado TEXT NOT NULL,

                    paginas INTEGER NOT NULL DEFAULT 0,

                    archivos INTEGER NOT NULL DEFAULT 0,

                    datasets INTEGER NOT NULL DEFAULT 0,

                    errores INTEGER NOT NULL DEFAULT 0,

                    motivo_parada TEXT,

                    duracion REAL NOT NULL DEFAULT 0,

                    mensaje_error TEXT
                )
                """
            )

            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_ejecuciones_fuente

                ON ejecuciones (
                    fuente
                )
                """
            )

            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_ejecuciones_estado

                ON ejecuciones (
                    estado
                )
                """
            )

            connection.commit()

    # ========================================================
    # CREAR EJECUCIÓN
    # ========================================================

    def create_execution(
        self,
        *,
        source_id: str,
        configured_url: str | None,
    ) -> int:

        with self._connect() as connection:

            cursor = connection.execute(
                """
                INSERT INTO ejecuciones (
                    fuente,
                    fecha_inicio,
                    url_configurada,
                    estado
                )
                VALUES (
                    ?,
                    ?,
                    ?,
                    ?
                )
                """,
                (
                    source_id,
                    self._now(),
                    configured_url,
                    STATUS_PENDING,
                ),
            )

            connection.commit()

            execution_id = (
                cursor.lastrowid
            )

        if execution_id is None:

            raise RuntimeError(
                "No se pudo crear la ejecución "
                "de trazabilidad."
            )

        return int(
            execution_id
        )

    # ========================================================
    # INICIO
    # ========================================================

    def mark_in_process(
        self,
        execution_id: int,
        *,
        used_url: str | None,
        used_fallback: bool,
    ) -> None:

        with self._connect() as connection:

            connection.execute(
                """
                UPDATE ejecuciones

                SET
                    estado = ?,
                    url_utilizada = ?,
                    uso_fallback = ?

                WHERE id = ?
                """,
                (
                    STATUS_IN_PROCESS,
                    used_url,
                    int(
                        bool(
                            used_fallback
                        )
                    ),
                    execution_id,
                ),
            )

            connection.commit()

    # ========================================================
    # PROCESSED
    # ========================================================

    def mark_processed(
        self,
        execution_id: int,
        *,
        pages: int,
        files: int,
        datasets: int,
        errors: int,
        stop_reason: str | None,
        duration: float,
    ) -> None:

        with self._connect() as connection:

            connection.execute(
                """
                UPDATE ejecuciones

                SET
                    fecha_fin = ?,
                    estado = ?,
                    paginas = ?,
                    archivos = ?,
                    datasets = ?,
                    errores = ?,
                    motivo_parada = ?,
                    duracion = ?,
                    mensaje_error = NULL

                WHERE id = ?
                """,
                (
                    self._now(),
                    STATUS_PROCESSED,
                    int(
                        pages
                    ),
                    int(
                        files
                    ),
                    int(
                        datasets
                    ),
                    int(
                        errors
                    ),
                    stop_reason,
                    float(
                        duration
                    ),
                    execution_id,
                ),
            )

            connection.commit()

    # ========================================================
    # ERROR
    # ========================================================

    def mark_error(
        self,
        execution_id: int,
        *,
        message: str,
        duration: float = 0.0,
    ) -> None:

        with self._connect() as connection:

            connection.execute(
                """
                UPDATE ejecuciones

                SET
                    fecha_fin = ?,
                    estado = ?,
                    duracion = ?,
                    mensaje_error = ?

                WHERE id = ?
                """,
                (
                    self._now(),
                    STATUS_ERROR,
                    float(
                        duration
                    ),
                    str(
                        message
                    ),
                    execution_id,
                ),
            )

            connection.commit()

    # ========================================================
    # ÚLTIMA EJECUCIÓN
    # ========================================================

    def get_last_execution(
        self,
        source_id: str,
    ) -> dict | None:

        with self._connect() as connection:

            row = connection.execute(
                """
                SELECT *
                FROM ejecuciones

                WHERE fuente = ?

                ORDER BY id DESC

                LIMIT 1
                """,
                (
                    source_id,
                ),
            ).fetchone()

        if row is None:

            return None

        return dict(
            row
        )