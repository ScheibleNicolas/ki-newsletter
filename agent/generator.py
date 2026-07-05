"""Newsletter-Generator: erstellt per Gemini die Mittwochs-Kurzform oder den
Samstags-Deep-Dive aus einer Liste von Artikeln (siehe fetcher.py).

Hinweis: Die ursprünglich vorgesehene Bibliothek "google-generativeai" und das
Modell "gemini-1.5-flash" sind inzwischen abgeschaltet (gemini-1.5-flash liefert
HTTP 404). Verwendet wird daher das aktuelle, offiziell unterstützte SDK
"google-genai" mit dem Modell "gemini-2.5-flash".

Schutz gegen Halluzinationen: Der Prompt verbietet erfundene Informationen
explizit, jede Story muss auf einen echten Artikel (quelle_url/quelle_name)
verweisen, Storys mit unbekannter quelle_url werden nach der Antwort verworfen,
und bei weniger als MINDEST_ARTIKEL echten Artikeln wird abgebrochen statt mit
erfundenem Inhalt aufzufüllen.
"""

from __future__ import annotations

import json
import os
from datetime import date

from google import genai
from google.genai import types

MODELL = "gemini-2.5-flash"

# date.weekday(): Montag=0 ... Sonntag=6
MITTWOCH = 2
SAMSTAG = 5

MINDEST_ARTIKEL = 3

VERBOT_ERFINDEN = (
    "Fasse NUR die folgenden Artikel zusammen. Erfinde keine Informationen. "
    "Wenn ein Thema nicht in den Artikeln vorkommt, erwähne es nicht."
)


class ZuWenigArtikelFehler(RuntimeError):
    """Wird ausgelöst, wenn zu wenige echte Artikel für einen Newsletter vorliegen."""


def _client() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Umgebungsvariable GEMINI_API_KEY ist nicht gesetzt. "
            "API-Key niemals hardcoden, sondern z.B. per "
            "'export GEMINI_API_KEY=...' setzen."
        )
    return genai.Client(api_key=api_key)


def _artikel_fuer_prompt(artikel_liste: list[dict]) -> str:
    bloecke = []
    for i, a in enumerate(artikel_liste, start=1):
        bloecke.append(
            f"{i}. Titel: {a.get('titel', '')}\n"
            f"   URL: {a.get('url', '')}\n"
            f"   Quelle: {a.get('quelle_name', '')}\n"
            f"   Kategorie: {a.get('kategorie', '')}\n"
            f"   Beschreibung: {a.get('zusammenfassung', '')}"
        )
    return "\n".join(bloecke)


def _rufe_gemini_json(prompt: str) -> dict:
    client = _client()
    response = client.models.generate_content(
        model=MODELL,
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    return json.loads(response.text)


def _pruefe_mindestanzahl(artikel_liste: list[dict]) -> None:
    if len(artikel_liste) < MINDEST_ARTIKEL:
        raise ZuWenigArtikelFehler(
            f"Nur {len(artikel_liste)} echte Artikel vorhanden, mindestens "
            f"{MINDEST_ARTIKEL} werden für einen Newsletter benötigt. Abbruch, "
            "um keine Ausgabe mit erfundenem Inhalt zu erzeugen."
        )


def _validiere_quellen(storys: list[dict], artikel_liste: list[dict]) -> list[dict]:
    """Verwirft Storys, deren quelle_url nicht zu einem echten Artikel gehört."""
    echte_urls = {a.get("url") for a in artikel_liste}
    gueltige_storys = []
    for story in storys:
        quelle_url = story.get("quelle_url")
        if quelle_url not in echte_urls:
            print(
                f"[WARNUNG] Story '{story.get('titel', '')}' verweist auf keine "
                f"echte Artikel-URL ({quelle_url!r}) und wird verworfen "
                "(mögliche Halluzination)."
            )
            continue
        gueltige_storys.append(story)
    return gueltige_storys


def _erstelle_kurzform(artikel_liste: list[dict], heute: date) -> dict:
    _pruefe_mindestanzahl(artikel_liste)

    prompt = f"""Du bist Redakteur eines KI/Tech/Wirtschaft-Newsletters auf Deutsch.

{VERBOT_ERFINDEN}
Du darfst ausschließlich Inhalte aus der unten stehenden nummerierten
Artikelliste verwenden. Wähle daraus die 5 relevantesten Artikel aus.
Jede Story MUSS "quelle_url" und "quelle_name" enthalten - übernimm dafür
exakt die URL und den Quellennamen aus der Artikelliste, erfinde niemals
eine URL.

Antworte NUR mit JSON in exakt diesem Format (keine weiteren Felder):

{{
  "titel": "Newsletter-Titel für diese Kurzform-Ausgabe",
  "storys": [
    {{
      "titel": "Artikeltitel",
      "zusammenfassung": "2-3 Sätze Zusammenfassung auf Deutsch",
      "schlagwoerter": ["Schlagwort1", "Schlagwort2"],
      "quelle_url": "exakte URL aus der Artikelliste",
      "quelle_name": "exakter Quellenname aus der Artikelliste"
    }}
  ],
  "schlagwoerter": ["übergreifende Schlagwörter der gesamten Ausgabe"]
}}

Artikelliste:
{_artikel_fuer_prompt(artikel_liste)}
"""
    daten = _rufe_gemini_json(prompt)
    return {
        "modus": "kurzform",
        "datum": heute.isoformat(),
        "titel": daten.get("titel", ""),
        "storys": _validiere_quellen(daten.get("storys", []), artikel_liste),
        "schlagwoerter": daten.get("schlagwoerter", []),
    }


def _erstelle_deep_dive(artikel_liste: list[dict], heute: date) -> dict:
    _pruefe_mindestanzahl(artikel_liste)

    prompt = f"""Du bist Redakteur eines KI/Tech/Wirtschaft-Newsletters auf Deutsch.

{VERBOT_ERFINDEN}
Du darfst ausschließlich Inhalte aus der unten stehenden nummerierten
Artikelliste verwenden. Identifiziere daraus das wichtigste Thema der Woche
und erkläre es ausführlich in 400-500 Wörtern (Feld "zusammenfassung" der
ersten Story, "typ": "deep-dive"). Ergänze danach 3-4 weitere kurze Meldungen
(je 2-3 Sätze, "typ": "kurzmeldung").
Jede Story MUSS "quelle_url" und "quelle_name" enthalten - übernimm dafür
exakt die URL und den Quellennamen aus der Artikelliste, erfinde niemals
eine URL. Falls das Hauptthema auf mehreren Artikeln basiert, nutze die URL
des Artikels, der das Thema am zentralsten behandelt.

Antworte NUR mit JSON in exakt diesem Format (keine weiteren Felder):

{{
  "titel": "Newsletter-Titel für diese Deep-Dive-Ausgabe",
  "storys": [
    {{
      "titel": "Titel des Hauptthemas",
      "zusammenfassung": "400-500 Wörter Fließtext auf Deutsch",
      "schlagwoerter": ["Schlagwort1", "Schlagwort2"],
      "typ": "deep-dive",
      "quelle_url": "exakte URL aus der Artikelliste",
      "quelle_name": "exakter Quellenname aus der Artikelliste"
    }},
    {{
      "titel": "Titel der Kurzmeldung",
      "zusammenfassung": "2-3 Sätze",
      "schlagwoerter": ["Schlagwort1"],
      "typ": "kurzmeldung",
      "quelle_url": "exakte URL aus der Artikelliste",
      "quelle_name": "exakter Quellenname aus der Artikelliste"
    }}
  ],
  "schlagwoerter": ["übergreifende Schlagwörter der gesamten Ausgabe"]
}}

Artikelliste:
{_artikel_fuer_prompt(artikel_liste)}
"""
    daten = _rufe_gemini_json(prompt)
    return {
        "modus": "deep-dive",
        "datum": heute.isoformat(),
        "titel": daten.get("titel", ""),
        "storys": _validiere_quellen(daten.get("storys", []), artikel_liste),
        "schlagwoerter": daten.get("schlagwoerter", []),
    }


def generate_newsletter(artikel_liste: list[dict], heute: date | None = None) -> dict:
    """Erstellt den Newsletter-Inhalt für den aktuellen (oder übergebenen) Tag.

    Mittwoch -> Kurzform, Samstag -> Deep-Dive, sonst kein Newsletter.

    Wirft ZuWenigArtikelFehler, wenn an einem Newsletter-Tag weniger als
    MINDEST_ARTIKEL echte Artikel übergeben werden.
    """
    heute = heute or date.today()
    wochentag = heute.weekday()

    if wochentag == MITTWOCH:
        return _erstelle_kurzform(artikel_liste, heute)
    elif wochentag == SAMSTAG:
        return _erstelle_deep_dive(artikel_liste, heute)
    else:
        return {
            "modus": "kein-newsletter-tag",
            "datum": heute.isoformat(),
            "titel": "",
            "storys": [],
            "schlagwoerter": [],
        }


def _test_artikel() -> list[dict]:
    return [
        {
            "titel": "OpenAI veröffentlicht neues Flaggschiff-Modell",
            "url": "https://example.com/openai-neues-modell",
            "datum": "2026-07-01",
            "zusammenfassung": "OpenAI hat ein neues Sprachmodell mit deutlich verbesserten Fähigkeiten bei Code und Reasoning vorgestellt.",
            "quelle_name": "OpenAI Blog",
            "kategorie": "ki-international",
        },
        {
            "titel": "Anthropic erweitert Claude um neue Agenten-Fähigkeiten",
            "url": "https://example.com/anthropic-agenten",
            "datum": "2026-07-01",
            "zusammenfassung": "Anthropic hat Claude um Funktionen erweitert, die autonomes mehrstufiges Arbeiten in Entwicklerumgebungen verbessern.",
            "quelle_name": "Anthropic Blog",
            "kategorie": "ki-international",
        },
        {
            "titel": "EU einigt sich auf neue KI-Regularien",
            "url": "https://example.com/eu-ki-regeln",
            "datum": "2026-06-30",
            "zusammenfassung": "Die EU-Staaten haben sich auf verschärfte Transparenzpflichten für KI-Anbieter geeinigt.",
            "quelle_name": "Tagesschau.de",
            "kategorie": "wirtschaft-politik",
        },
        {
            "titel": "Deutsche Industrie investiert massiv in KI-Infrastruktur",
            "url": "https://example.com/industrie-ki-investition",
            "datum": "2026-06-29",
            "zusammenfassung": "Mehrere deutsche Großkonzerne kündigen Milliarden-Investitionen in eigene KI-Rechenzentren an.",
            "quelle_name": "Heise.de",
            "kategorie": "ki-deutsch",
        },
        {
            "titel": "Google DeepMind zeigt Fortschritte bei Protein-Faltung",
            "url": "https://example.com/deepmind-protein",
            "datum": "2026-06-28",
            "zusammenfassung": "Ein neues Modell von DeepMind verbessert die Vorhersage von Proteinstrukturen erneut deutlich.",
            "quelle_name": "Google DeepMind Blog",
            "kategorie": "ki-international",
        },
        {
            "titel": "Hacker News diskutiert neuen Open-Source-Inferenz-Server",
            "url": "https://example.com/hn-inferenz-server",
            "datum": "2026-06-27",
            "zusammenfassung": "Ein neues Open-Source-Projekt zur schnellen lokalen Modell-Inferenz sorgt für rege Diskussion.",
            "quelle_name": "Hacker News",
            "kategorie": "ki-international",
        },
        {
            "titel": "Reuters: Chipmangel entspannt sich laut Branchenverband",
            "url": "https://example.com/reuters-chipmangel",
            "datum": "2026-06-26",
            "zusammenfassung": "Der weltweite Halbleitermangel geht laut aktuellen Zahlen spürbar zurück.",
            "quelle_name": "Reuters",
            "kategorie": "wirtschaft-politik",
        },
        {
            "titel": "t3n: Deutsche Startups setzen verstärkt auf KI-Agenten",
            "url": "https://example.com/t3n-startups-agenten",
            "datum": "2026-06-25",
            "zusammenfassung": "Immer mehr deutsche Startups bauen ihr Produkt um autonome KI-Agenten herum.",
            "quelle_name": "t3n.de",
            "kategorie": "ki-deutsch",
        },
    ]


def main() -> None:
    artikel = _test_artikel()

    testfaelle = [
        (date(2026, 7, 8), "Mittwoch -> Kurzform", artikel),
        (date(2026, 7, 11), "Samstag -> Deep-Dive", artikel),
        (date(2026, 7, 5), "Sonntag -> kein Newsletter-Tag", artikel),
        (date(2026, 7, 8), "Mittwoch, aber nur 2 Artikel -> Abbruch", artikel[:2]),
    ]

    for tag, label, artikel_fuer_test in testfaelle:
        print(f"\n=== {label} ({tag.isoformat()}) ===")
        try:
            ergebnis = generate_newsletter(artikel_fuer_test, heute=tag)
        except RuntimeError as e:
            print(f"[FEHLER] {e}")
            continue
        print(json.dumps(ergebnis, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
