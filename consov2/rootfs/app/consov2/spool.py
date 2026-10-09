"""File d'attente des lots à envoyer, dans SQLite (/data survit aux redémarrages).

Chaque lot reçoit une clé d'idempotence à sa création : s'il est renvoyé après une
coupure, le site le reconnaît et ne compte rien deux fois.
"""
import json
import sqlite3
import threading
import time
import uuid
from typing import List, Optional, Tuple

from .model import Measurement


class Spool:
    def __init__(self, path: str, max_batches: int = 30000):
        self.max_batches = max_batches
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS batch ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT, created INTEGER NOT NULL, idem TEXT NOT NULL,"
            " body TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, next_try INTEGER NOT NULL DEFAULT 0)")

    def push(self, measurements: List[Measurement]) -> Optional[str]:
        if not measurements:
            return None
        idem = "consov2-" + uuid.uuid4().hex
        body = json.dumps({"measurements": [m.to_api() for m in measurements]}, ensure_ascii=False)
        with self._lock:
            self._db.execute("INSERT INTO batch (created, idem, body) VALUES (?, ?, ?)",
                             (int(time.time()), idem, body))
            # Au-delà de la limite, on oublie les lots les plus anciens.
            self._db.execute("DELETE FROM batch WHERE id <= (SELECT MAX(id) FROM batch) - ?", (self.max_batches,))
        return idem

    def next_due(self, now: int) -> Optional[Tuple[int, str, str, int]]:
        """Le plus ancien lot, s'il est à envoyer maintenant (jamais un récent avant un ancien)."""
        with self._lock:
            row = self._db.execute(
                "SELECT id, idem, body, attempts, next_try FROM batch ORDER BY id LIMIT 1").fetchone()
        if row is None or row[4] > now:
            return None
        return row[:4]

    def done(self, batch_id: int):
        with self._lock:
            self._db.execute("DELETE FROM batch WHERE id = ?", (batch_id,))

    def retry_later(self, batch_id: int, at: int):
        with self._lock:
            self._db.execute("UPDATE batch SET attempts = attempts + 1, next_try = ? WHERE id = ?", (at, batch_id))

    def pending(self) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM batch").fetchone()[0]

    def oldest_age(self, now: int) -> int:
        with self._lock:
            row = self._db.execute("SELECT MIN(created) FROM batch").fetchone()
        return 0 if row[0] is None else now - row[0]
