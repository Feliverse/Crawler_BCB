"""Simple SQLite storage for extracted rows."""
import sqlite3
from typing import List, Dict
import json
import logging

logger = logging.getLogger(__name__)


class Storage:
    def __init__(self, path: str):
        self.path = path
        self._conn = sqlite3.connect(self.path)
        self._ensure()

    def _ensure(self):
        cur = self._conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS metales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha TEXT NOT NULL,
                payload JSON NOT NULL
            )
            """
        )
        self._conn.commit()

    def insert_rows(self, fecha: str, rows: List[Dict[str, str]]):
        cur = self._conn.cursor()
        payload = json.dumps(rows, ensure_ascii=False)
        cur.execute("INSERT INTO metales (fecha, payload) VALUES (?, ?)", (fecha, payload))
        self._conn.commit()
        logger.info("Inserted %d rows for %s", len(rows), fecha)

    def close(self):
        self._conn.close()
