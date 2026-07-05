"""Lädt Artikel aus allen in quellen.yaml konfigurierten RSS-Feeds."""

from __future__ import annotations

import sys
from dataclasses import dataclass, asdict
from pathlib import Path

import feedparser
import yaml

QUELLEN_PFAD = Path(__file__).parent / "quellen.yaml"


@dataclass
class Artikel:
    titel: str
    url: str
    datum: str
    zusammenfassung: str
    quelle_name: str
    kategorie: str


def lade_quellen(pfad: Path = QUELLEN_PFAD) -> list[dict]:
    with open(pfad, "r", encoding="utf-8") as f:
        daten = yaml.safe_load(f)
    quellen = daten.get("quellen", [])
    return [q for q in quellen if q.get("url")]


def hole_artikel_fuer_quelle(quelle: dict) -> list[Artikel]:
    feed = feedparser.parse(quelle["url"])

    if feed.bozo and not feed.entries:
        raise ValueError(f"Feed konnte nicht gelesen werden: {feed.bozo_exception}")

    artikel = []
    for eintrag in feed.entries:
        artikel.append(
            Artikel(
                titel=eintrag.get("title", ""),
                url=eintrag.get("link", ""),
                datum=eintrag.get("published", eintrag.get("updated", "")),
                zusammenfassung=eintrag.get("summary", ""),
                quelle_name=quelle["name"],
                kategorie=quelle["kategorie"],
            )
        )
    return artikel


def hole_alle_artikel(quellen: list[dict] | None = None) -> list[Artikel]:
    if quellen is None:
        quellen = lade_quellen()

    alle_artikel: list[Artikel] = []
    for quelle in quellen:
        try:
            alle_artikel.extend(hole_artikel_fuer_quelle(quelle))
        except Exception as e:
            print(f"[WARNUNG] Feed '{quelle['name']}' übersprungen: {e}", file=sys.stderr)

    return alle_artikel


def main() -> None:
    quellen = lade_quellen()
    print(f"Lade Artikel von {len(quellen)} Quellen...\n")

    artikel = hole_alle_artikel(quellen)

    print(f"\n{len(artikel)} Artikel insgesamt geladen.\n")
    for a in artikel[:10]:
        print(f"- [{a.quelle_name}] {a.titel} ({a.datum})")
        print(f"  {a.url}")


if __name__ == "__main__":
    main()
