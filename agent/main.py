"""Orchestriert den kompletten Newsletter-Workflow:

1. RSS-Artikel laden (fetcher.py)
2. Bereits gesehene Artikel herausfiltern (memory.py)
3. Neue Artikel als gesehen markieren (memory.py)
4. Newsletter aus den neuen Artikeln generieren (generator.py)
5. Ergebnis als JSON unter docs/ausgaben/DATUM.json speichern
6. Newsletter als MP3 vorlesen lassen (tts.py) - nur an Newsletter-Tagen. Ist
   die Gemini-Audio-API nicht verfügbar, liefert tts.py None (kein Fallback),
   die Seite wird dann ohne Audio erstellt.
7. Ausgabenseite + Index erstellen (website.py) - nur an Newsletter-Tagen

Mit --test-mittwoch / --test-samstag lässt sich die Pipeline an jedem
Wochentag testen, ohne auf den echten Mittwoch/Samstag warten zu müssen.
Das echte Tagesdatum bleibt dabei für Dateinamen/Anzeige erhalten (nur der
Modus wird erzwungen) - so überschreibt ein Testlauf nie versehentlich die
echte Ausgabe eines vergangenen oder kommenden Mittwochs/Samstags.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

import emailer
import fetcher
import generator
import memory
import tts
import website

AUSGABEN_VERZEICHNIS = Path(__file__).parent.parent / "docs" / "ausgaben"
AUDIO_VERZEICHNIS = Path(__file__).parent.parent / "docs" / "audio"
WEBSITE_BASIS_URL = "https://scheiblenicolas.github.io/ki-newsletter/ausgaben"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="KI-Newsletter Pipeline")
    gruppe = parser.add_mutually_exclusive_group()
    gruppe.add_argument(
        "--test-mittwoch",
        action="store_true",
        help="Pipeline wie an einem Mittwoch (Kurzform) ausführen, unabhängig vom echten Wochentag.",
    )
    gruppe.add_argument(
        "--test-samstag",
        action="store_true",
        help="Pipeline wie an einem Samstag (Deep-Dive) ausführen, unabhängig vom echten Wochentag.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    heute = date.today()

    modus_erzwingen = None
    if args.test_mittwoch:
        modus_erzwingen = "kurzform"
        print(f"[TEST-MODUS] Wochentag wird als Mittwoch (Kurzform) behandelt, echtes Datum {heute.isoformat()} bleibt für Dateinamen erhalten.\n")
    elif args.test_samstag:
        modus_erzwingen = "deep-dive"
        print(f"[TEST-MODUS] Wochentag wird als Samstag (Deep-Dive) behandelt, echtes Datum {heute.isoformat()} bleibt für Dateinamen erhalten.\n")

    quellen = fetcher.lade_quellen()
    alle_artikel = fetcher.hole_alle_artikel(quellen)

    neue_artikel = [a for a in alle_artikel if not memory.is_seen(a.url)]

    for artikel in neue_artikel:
        memory.mark_seen(artikel.url, artikel.titel)

    neue_artikel_dicts = [asdict(a) for a in neue_artikel]

    try:
        newsletter = generator.generate_newsletter(
            neue_artikel_dicts, heute=heute, modus_erzwingen=modus_erzwingen
        )
    except RuntimeError as e:
        print(f"[FEHLER] Newsletter konnte nicht generiert werden: {e}")
        return

    AUSGABEN_VERZEICHNIS.mkdir(parents=True, exist_ok=True)
    ausgabe_pfad = AUSGABEN_VERZEICHNIS / f"{heute.isoformat()}.json"
    with open(ausgabe_pfad, "w", encoding="utf-8") as f:
        json.dump(newsletter, f, indent=2, ensure_ascii=False)

    html_pfad = None
    audio_pfad = None
    if newsletter["modus"] != "kein-newsletter-tag":
        audio_pfad = tts.text_zu_mp3(newsletter, AUDIO_VERZEICHNIS / f"{heute.isoformat()}.mp3")
        html_pfad = website.erstelle_ausgabe_seite(newsletter, audio_pfad)
        website_url = f"{WEBSITE_BASIS_URL}/{heute.isoformat()}.html"
        emailer.sende_benachrichtigung(newsletter, website_url)

    print("\n=== Zusammenfassung ===")
    print(f"Artikel geladen: {len(alle_artikel)}")
    print(f"Davon neu: {len(neue_artikel)}")
    modus_anzeige = website.MODUS_LABEL.get(newsletter["modus"], newsletter["modus"])
    print(f"Modus: {modus_anzeige}")
    print(f"Titel: {newsletter['titel'] or '(kein Newsletter heute)'}")
    print(f"Gespeichert unter: {ausgabe_pfad}")
    if html_pfad:
        print(f"Website: {html_pfad}")
    if audio_pfad:
        print(f"Audio: {audio_pfad}")


if __name__ == "__main__":
    main()
