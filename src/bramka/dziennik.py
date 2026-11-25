"""Dziennik operacji bramki w SQLite. Każde wywołanie narzędzia, także odmowy, z powodem."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

SCHEMAT = """
CREATE TABLE IF NOT EXISTS operacje (
    nr INTEGER PRIMARY KEY AUTOINCREMENT,
    czas TEXT NOT NULL,
    przebieg TEXT NOT NULL,
    narzedzie TEXT NOT NULL,
    mail_id INTEGER,
    parametry TEXT NOT NULL,
    wynik TEXT NOT NULL,      -- ok | odmowa | blad
    powod TEXT
);
CREATE INDEX IF NOT EXISTS operacje_przebieg ON operacje (przebieg);
"""


class Dziennik:
    def __init__(self, sciezka: str):
        self._sciezka = sciezka
        self._blokada = threading.Lock()
        with self._polacz() as b:
            b.executescript(SCHEMAT)

    @contextmanager
    def _polacz(self):
        b = sqlite3.connect(self._sciezka)
        try:
            with b:  # zatwierdza albo wycofuje transakcję
                yield b
        finally:
            b.close()

    def zapisz(self, przebieg: str, narzedzie: str, parametry: dict, wynik: str = "ok",
               mail_id: int | None = None, powod: str | None = None) -> None:
        czas = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._blokada, self._polacz() as b:
            b.execute(
                "INSERT INTO operacje (czas, przebieg, narzedzie, mail_id, parametry, wynik, powod) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (czas, przebieg, narzedzie, mail_id, json.dumps(parametry, ensure_ascii=False), wynik, powod),
            )

    def operacje(self, przebieg: str, narzedzia: tuple[str, ...], wynik: str = "ok") -> list[dict]:
        """Operacje przebiegu w kolejności wykonania."""
        znaki = ",".join("?" * len(narzedzia))
        with self._polacz() as b:
            wiersze = b.execute(
                f"SELECT nr, narzedzie, mail_id, parametry FROM operacje "
                f"WHERE przebieg = ? AND wynik = ? AND narzedzie IN ({znaki}) ORDER BY nr",
                (przebieg, wynik, *narzedzia),
            ).fetchall()
        return [{"nr": nr, "narzedzie": n, "mail_id": m, "parametry": json.loads(p)} for nr, n, m, p in wiersze]

    def licz(self, przebieg: str, narzedzie: str, wynik: str = "ok") -> int:
        with self._polacz() as b:
            return b.execute(
                "SELECT COUNT(*) FROM operacje WHERE przebieg = ? AND narzedzie = ? AND wynik = ?",
                (przebieg, narzedzie, wynik),
            ).fetchone()[0]

    def przebiegi(self, ile: int = 20) -> list[dict]:
        with self._polacz() as b:
            wiersze = b.execute(
                "SELECT przebieg, MIN(czas), MAX(czas), COUNT(*), "
                "SUM(narzedzie IN ('etykietuj', 'oznacz_przeczytane') AND wynik = 'ok'), SUM(wynik = 'odmowa') "
                "FROM operacje GROUP BY przebieg ORDER BY MIN(nr) DESC LIMIT ?",
                (ile,),
            ).fetchall()
        return [
            {"przebieg": p, "od": a, "do": z, "operacji": n, "zmian": zm or 0, "odmow": o or 0}
            for p, a, z, n, zm, o in wiersze
        ]
