"""SQLite-Speicher, der bereits verarbeitete Artikel merkt."""

from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PFAD = Path(__file__).parent / "newsletter.db"


def _verbindung(db_pfad: Path = DB_PFAD) -> sqlite3.Connection:
    conn = sqlite3.connect(db_pfad)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS gesehene_artikel (
            url TEXT PRIMARY KEY,
            titel TEXT NOT NULL,
            verarbeitet_am TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    return conn


def is_seen(url: str, db_pfad: Path = DB_PFAD) -> bool:
    with _verbindung(db_pfad) as conn:
        treffer = conn.execute(
            "SELECT 1 FROM gesehene_artikel WHERE url = ?", (url,)
        ).fetchone()
    return treffer is not None


def mark_seen(url: str, titel: str, db_pfad: Path = DB_PFAD) -> None:
    with _verbindung(db_pfad) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO gesehene_artikel (url, titel) VALUES (?, ?)",
            (url, titel),
        )


def main() -> None:
    test_url = "https://example.com/test-artikel"
    test_titel = "Test-Artikel für memory.py"

    print(f"Datenbank: {DB_PFAD}")

    print(f"is_seen('{test_url}') vor mark_seen: {is_seen(test_url)}")

    mark_seen(test_url, test_titel)
    print(f"mark_seen('{test_url}', '{test_titel}') aufgerufen.")

    print(f"is_seen('{test_url}') nach mark_seen: {is_seen(test_url)}")

    print(f"is_seen('https://example.com/unbekannt') (sollte False sein): "
          f"{is_seen('https://example.com/unbekannt')}")


if __name__ == "__main__":
    main()
