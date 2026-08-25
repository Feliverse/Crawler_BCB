"""SQLAlchemy-based storage for more robust schema and migrations."""
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from .models import metadata, metales
import logging

logger = logging.getLogger(__name__)


class StorageSQLAlchemy:
    def __init__(self, path: str):
        # sqlite URL
        self.url = f"sqlite:///{path}"
        self.engine: Engine = create_engine(self.url, future=True)
        metadata.create_all(self.engine)

    def insert_rows(self, fecha: str, rows, moneda: str = None):
        try:
            with self.engine.begin() as conn:
                conn.execute(metales.insert().values(fecha=fecha, moneda=moneda, payload=rows))
            logger.info("Inserted %d rows for %s", len(rows) if hasattr(rows, '__len__') else 1, fecha)
        except SQLAlchemyError as exc:
            logger.error("SQLAlchemy insert failed: %s", exc)

    def query_all(self):
        with self.engine.connect() as conn:
            res = conn.execute(select(metales)).all()
            return res
