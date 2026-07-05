"""Orchestriert den kompletten Newsletter-Workflow:

1. RSS-Artikel laden (fetcher.py)
2. Bereits gesehene Artikel herausfiltern (memory.py)
3. Neue Artikel als gesehen markieren (memory.py)
4. Newsletter aus den neuen Artikeln generieren (generator.py)
5. Ergebnis als JSON unter docs/ausgaben/DATUM.json speichern
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

import fetcher
import generator
import memory

AUSGABEN_VERZEICHNIS = Path(__file__).parent.parent / "docs" / "ausgaben"


def main() -> None:
    heute = date.today()

    quellen = fetcher.lade_quellen()
    alle_artikel = fetcher.hole_alle_artikel(quellen)

    neue_artikel = [a for a in alle_artikel if not memory.is_seen(a.url)]

    for artikel in neue_artikel:
        memory.mark_seen(artikel.url, artikel.titel)

    neue_artikel_dicts = [asdict(a) for a in neue_artikel]

    try:
        newsletter = generator.generate_newsletter(neue_artikel_dicts, heute=heute)
    except RuntimeError as e:
        print(f"[FEHLER] Newsletter konnte nicht generiert werden: {e}")
        return

    AUSGABEN_VERZEICHNIS.mkdir(parents=True, exist_ok=True)
    ausgabe_pfad = AUSGABEN_VERZEICHNIS / f"{heute.isoformat()}.json"
    with open(ausgabe_pfad, "w", encoding="utf-8") as f:
        json.dump(newsletter, f, indent=2, ensure_ascii=False)

    print("\n=== Zusammenfassung ===")
    print(f"Artikel geladen: {len(alle_artikel)}")
    print(f"Davon neu: {len(neue_artikel)}")
    print(f"Modus: {newsletter['modus']}")
    print(f"Titel: {newsletter['titel'] or '(kein Newsletter heute)'}")
    print(f"Gespeichert unter: {ausgabe_pfad}")


if __name__ == "__main__":
    main()
