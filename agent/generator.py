"""Newsletter-Generator: erstellt per Gemini die Mittwochs- und Samstags-Ausgabe
aus einer Liste von Artikeln (siehe fetcher.py). Beide Ausgaben sind gleich
strukturiert (Kategorien in KATEGORIE_REIHENFOLGE: breaking-news, international,
deutschland, finanzen, ki-tech, sport, good-news) und nutzen dieselben
Mengen-Quoten pro Kategorie; einziger inhaltlicher Unterschied ist der optionale
Einordnungs-Absatz, den nur die Samstagsausgabe erhalten kann.

Hinweis: Die ursprünglich vorgesehene Bibliothek "google-generativeai" und das
Modell "gemini-1.5-flash" sind inzwischen abgeschaltet (gemini-1.5-flash liefert
HTTP 404). Verwendet wird daher das aktuelle, offiziell unterstützte SDK
"google-genai" mit dem Modell "gemini-2.5-flash".

Schutz gegen Halluzinationen: Der Prompt verbietet erfundene Informationen
explizit, jede Story muss auf einen echten Artikel (quelle_url/quelle_name)
verweisen, Storys mit unbekannter quelle_url werden nach der Antwort verworfen,
und bei weniger als MINDEST_ARTIKEL echten Artikeln wird abgebrochen statt mit
erfundenem Inhalt aufzufüllen. Das Feld "kategorie" wird NICHT von Gemini
erfragt, sondern nach der Antwort deterministisch aus dem echten Quellartikel
übernommen (_kategorien_zuweisen) - so kann Gemini auch hier nichts erfinden.

Sonderfall "breaking-news": Das ist keine Quellen-Kategorie (quellen.yaml kennt
sie nicht), sondern eine seltene Sonderauszeichnung. Gemini markiert dafür
einzelne Storys mit "ist_breaking_news": true; Python übernimmt diese Markierung
erst NACH der regulären, quellenbasierten Kategorie-Zuweisung und verschiebt nur
dann die Story nach "breaking-news" (_wende_breaking_news_an) - auch hier bleibt
die quelle_url-Prüfung vorgeschaltet, Gemini kann also keine frei erfundene
Breaking-News-Meldung einschleusen, sondern nur eine echte Story umetikettieren.

Zieldauer: ca. 15-20 Min Audio (ca. 2200-2800 Wörter) für beide Ausgabetage.
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv(Path(__file__).parent / ".env")

MODELL = "gemini-2.5-flash"

# date.weekday(): Montag=0 ... Sonntag=6
MITTWOCH = 2
SAMSTAG = 5

MINDEST_ARTIKEL = 3

# "breaking-news" ist keine echte Quellen-Kategorie (siehe Moduldocstring),
# daher wird sie in KATEGORIE_REIHENFOLGE_ECHT (Verfügbarkeits-/Quotencheck
# gegen echte Artikel) bewusst ausgeklammert, taucht aber in der Ausgabe-
# Reihenfolge (KATEGORIE_REIHENFOLGE) ganz vorne auf.
KATEGORIE_REIHENFOLGE = [
    "breaking-news", "international", "deutschland", "finanzen", "ki-tech", "sport", "good-news",
]
KATEGORIE_REIHENFOLGE_ECHT = [k for k in KATEGORIE_REIHENFOLGE if k != "breaking-news"]
KATEGORIE_LABEL = {
    "breaking-news": "Breaking News",
    "international": "Internationales",
    "deutschland": "Deutschland",
    "finanzen": "Finanzen",
    "ki-tech": "KI & Tech",
    "sport": "Sport",
    "good-news": "Good News",
}

# Mengen-Quoten pro Kategorie (gelten für Mittwoch UND Samstag gleichermaßen).
KATEGORIE_MENGE_TEXT = {
    "international": "genau 2",
    "deutschland": "genau 2",
    "finanzen": "genau 2",
    "ki-tech": "4 bis 5",
    "sport": "genau 2",
    "good-news": "1 bis 2",
}
KATEGORIE_MENGE_MAX = {
    "breaking-news": 3,
    "international": 2,
    "deutschland": 2,
    "finanzen": 2,
    "ki-tech": 5,
    "sport": 2,
    "good-news": 2,
}
_ZIEL_WOERTER_GESAMT = "2200-2800"

VERBOT_ERFINDEN = (
    "Fasse NUR die folgenden Artikel zusammen. Erfinde keine Informationen. "
    "Wenn ein Thema nicht in den Artikeln vorkommt, erwähne es nicht."
)

BREAKING_NEWS_HINWEIS = """
Zur Kategorie "breaking-news": Das ist KEINE reguläre Kategorie mit eigenen
Quellartikeln, sondern eine SEHR SELTENE Sonderauszeichnung für maximal 3 der
wichtigsten Meldungen der gesamten Ausgabe. Der Normalfall ist 0 - an den
allermeisten Tagen gibt es KEINE Breaking News, das ist ausdrücklich
erwünscht. Markiere eine Story nur dann zusätzlich mit "ist_breaking_news":
true, wenn mindestens eine Bedingung eindeutig erfüllt ist:
- mehrere UNABHÄNGIGE der obigen Artikel (auch über Kategorien hinweg)
  berichten zeitgleich über dasselbe konkrete Ereignis, ODER
- das Ereignis ist von historischer/außergewöhnlicher Tragweite auf
  gesamtgesellschaftlicher oder globaler Ebene (z.B. Kriegsausbruch,
  Regierungssturz, Naturkatastrophe mit vielen Opfern, Börsencrash,
  Jahrhundert-KI-Durchbruch, den selbst Nicht-Fachpublikum sofort als
  Schlagzeile erkennen würde).
Das ist eine SEHR hohe Hürde. Ausdrücklich KEINE Breaking News sind: ein neues
Produkt oder Modell-Update (auch nicht von großen Firmen wie OpenAI, Google
oder Anthropic), ein Quartalsbericht, ein Rekordhoch/-tief an der Börse ohne
Schock-Charakter, eine Forschungsmeldung, ein Gipfeltreffen mit erwartbarem
Ergebnis, ein Sportresultat - auch wenn die Formulierung im Artikel
("bahnbrechend", "historisch" o.ä.) das nahelegt. Im Zweifel IMMER gegen
Breaking News entscheiden. Markiere niemals mehr als 1-2 Storys als Breaking
News, außer die Beweislage ist überwältigend eindeutig. Wird eine Story als
Breaking News markiert, zähle sie NICHT zusätzlich zur Quote ihrer
ursprünglichen Kategorie - sie erscheint dann ausschließlich unter Breaking
News.
"""


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
    """Gruppiert die Artikel nach Kategorie und nummeriert sie durchgehend,
    damit Gemini die Mengen-Quote pro Kategorie einhalten kann."""
    bloecke = []
    zaehler = 1

    kategorien_mit_sonstigen = KATEGORIE_REIHENFOLGE_ECHT + ["sonstige"]
    for kategorie in kategorien_mit_sonstigen:
        if kategorie == "sonstige":
            artikel_in_kategorie = [
                a for a in artikel_liste if a.get("kategorie") not in KATEGORIE_REIHENFOLGE_ECHT
            ]
        else:
            artikel_in_kategorie = [a for a in artikel_liste if a.get("kategorie") == kategorie]

        if not artikel_in_kategorie:
            continue

        bloecke.append(f"### Kategorie: {kategorie}")
        for a in artikel_in_kategorie:
            bloecke.append(
                f"{zaehler}. Titel: {a.get('titel', '')}\n"
                f"   URL: {a.get('url', '')}\n"
                f"   Quelle: {a.get('quelle_name', '')}\n"
                f"   Beschreibung: {a.get('zusammenfassung', '')}"
            )
            zaehler += 1

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


def _kategorien_zuweisen(storys: list[dict], artikel_liste: list[dict]) -> list[dict]:
    """Setzt "kategorie" je Story auf die echte Kategorie ihres Quellartikels
    (nie von Gemini erfragt, damit hier nichts erfunden werden kann)."""
    kategorie_je_url = {a.get("url"): a.get("kategorie") for a in artikel_liste}
    for story in storys:
        story["kategorie"] = kategorie_je_url.get(story.get("quelle_url"), "sonstige")
    return storys


def _wende_breaking_news_an(storys: list[dict]) -> list[dict]:
    """Verschiebt Storys, die Gemini mit "ist_breaking_news": true markiert
    hat, nachträglich in die Kategorie "breaking-news" - erst NACH der
    quellenbasierten Kategorie-Zuweisung, damit weiterhin jede Story auf einen
    echten Artikel zurückgeht (siehe Moduldocstring)."""
    for story in storys:
        if story.get("typ") != "einordnung" and story.get("ist_breaking_news"):
            story["kategorie"] = "breaking-news"
    return storys


def _begrenze_pro_kategorie(storys: list[dict], max_je_kategorie: dict[str, int]) -> list[dict]:
    """Erzwingt die Mengen-Quote hart im Code, falls Gemini die Vorgabe im
    Prompt nicht einhält (z.B. zu viele Meldungen in einer Kategorie).
    Die Einordnungs-Story zählt nicht zur Quote und bleibt immer erhalten."""
    gezaehlt: dict[str, int] = {}
    begrenzt = []
    for story in storys:
        if story.get("typ") == "einordnung":
            begrenzt.append(story)
            continue
        kategorie = story.get("kategorie")
        max_anzahl = max_je_kategorie.get(kategorie, 0)
        anzahl = gezaehlt.get(kategorie, 0)
        if anzahl >= max_anzahl:
            print(
                f"[HINWEIS] Story '{story.get('titel', '')}' überschreitet die "
                f"Quote von {max_anzahl} für Kategorie '{kategorie}' und wird "
                "nicht übernommen."
            )
            continue
        gezaehlt[kategorie] = anzahl + 1
        begrenzt.append(story)
    return begrenzt


def _kategorie_verfuegbarkeit_text(artikel_liste: list[dict]) -> str:
    zeilen = []
    for kategorie in KATEGORIE_REIHENFOLGE_ECHT:
        anzahl = sum(1 for a in artikel_liste if a.get("kategorie") == kategorie)
        zeilen.append(f"- {kategorie}: {anzahl} Artikel verfügbar")
    return "\n".join(zeilen)


def _kategorie_quoten_text() -> str:
    zeilen = [
        f"- {kategorie}: {KATEGORIE_MENGE_TEXT[kategorie]} Meldungen"
        for kategorie in KATEGORIE_REIHENFOLGE_ECHT
    ]
    return "\n".join(zeilen)


def _erstelle_ausgabe(artikel_liste: list[dict], heute: date, modus: str) -> dict:
    _pruefe_mindestanzahl(artikel_liste)

    laenge_hinweis = "ca. 120-180 Wörter Zusammenfassung je Meldung"
    typ_hinweis = '"typ" ist immer "kurzmeldung".'
    einordnung_hinweis = ""
    if modus == "deep-dive":
        typ_hinweis = (
            '"typ" ist "kurzmeldung" für normale Meldungen, oder "einordnung" '
            "für den optionalen Einordnungs-Absatz."
        )
        einordnung_hinweis = """
Zusätzlich NUR für diese Ausgabe (Samstag): Falls ein einzelnes KI/Tech-Thema
aus der Kategorie "ki-tech" die Woche klar dominiert hat, füge GENAU EINE
zusätzliche Story mit "typ": "einordnung" hinzu, die dieses Thema in 150-200
Wörtern einordnet und erklärt (Feld "kategorie" dieser Story ist "ki-tech").
Falls kein Thema klar dominiert hat, füge KEINE Einordnung hinzu."""

    prompt = f"""Du bist Redakteur eines KI/Tech/Wirtschaft-Newsletters auf Deutsch.

{VERBOT_ERFINDEN}
Du darfst ausschließlich Inhalte aus der unten stehenden, nach Kategorie
gruppierten Artikelliste verwenden.

Verfügbare Artikel pro Kategorie:
{_kategorie_verfuegbarkeit_text(artikel_liste)}

Wähle pro Kategorie die folgende Anzahl der relevantesten Meldungen aus
({laenge_hinweis}). Das ist eine harte Vorgabe: wähle für JEDE Kategorie mit
mindestens einem verfügbaren Artikel (siehe Liste oben) auch mindestens eine
Meldung aus, und wähle NIE mehr Meldungen als die obere Grenze der jeweiligen
Spanne aus, selbst wenn eine andere Kategorie mehr interessante Artikel
bietet. Überspringe eine Kategorie nur, wenn für sie laut obiger Liste 0
Artikel vorhanden sind - erfinde niemals zusätzliche Meldungen, um eine leere
Kategorie zu füllen.

{_kategorie_quoten_text()}
{BREAKING_NEWS_HINWEIS}
{einordnung_hinweis}

Zielumfang der gesamten Ausgabe: ca. {_ZIEL_WOERTER_GESAMT} Wörter (entspricht
bei natürlicher Moderation ca. 15-20 Minuten Vorlesezeit).

Jede Story MUSS "quelle_url" und "quelle_name" enthalten - übernimm dafür
exakt die URL und den Quellennamen aus der Artikelliste, erfinde niemals eine
URL. {typ_hinweis} Optionales Feld "ist_breaking_news" (true/false, siehe oben).

Antworte NUR mit JSON in exakt diesem Format (keine weiteren Felder):

{{
  "titel": "Newsletter-Titel für diese Ausgabe",
  "storys": [
    {{
      "titel": "Artikeltitel",
      "zusammenfassung": "Zusammenfassung auf Deutsch",
      "schlagwoerter": ["Schlagwort1", "Schlagwort2"],
      "typ": "kurzmeldung",
      "ist_breaking_news": false,
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
    storys = _validiere_quellen(daten.get("storys", []), artikel_liste)
    storys = _kategorien_zuweisen(storys, artikel_liste)
    storys = _wende_breaking_news_an(storys)
    storys = _begrenze_pro_kategorie(storys, KATEGORIE_MENGE_MAX)

    return {
        "modus": modus,
        "datum": heute.isoformat(),
        "titel": daten.get("titel", ""),
        "storys": storys,
        "schlagwoerter": daten.get("schlagwoerter", []),
    }


def generate_newsletter(
    artikel_liste: list[dict],
    heute: date | None = None,
    modus_erzwingen: str | None = None,
) -> dict:
    """Erstellt den Newsletter-Inhalt für den aktuellen (oder übergebenen) Tag.

    Mittwoch -> Kurzform, Samstag -> Deep-Dive, sonst kein Newsletter. Beide
    Ausgaben sind gleich strukturiert (Storys mit "kategorie" in
    KATEGORIE_REIHENFOLGE) und nutzen dieselben Mengen-Quoten pro Kategorie;
    nur Samstag kann zusätzlich eine Einordnungs-Story enthalten.

    modus_erzwingen ("kurzform" oder "deep-dive") überschreibt die
    Wochentagsermittlung, z.B. für Testläufe an einem beliebigen Tag - "heute"
    bleibt dabei unverändert das echte Datum (für Dateinamen/Anzeige), nur der
    Modus wird erzwungen.

    Wirft ZuWenigArtikelFehler, wenn an einem Newsletter-Tag weniger als
    MINDEST_ARTIKEL echte Artikel übergeben werden.
    """
    heute = heute or date.today()

    if modus_erzwingen is not None:
        modus = modus_erzwingen
    elif heute.weekday() == MITTWOCH:
        modus = "kurzform"
    elif heute.weekday() == SAMSTAG:
        modus = "deep-dive"
    else:
        modus = "kein-newsletter-tag"

    if modus in ("kurzform", "deep-dive"):
        return _erstelle_ausgabe(artikel_liste, heute, modus)

    return {
        "modus": "kein-newsletter-tag",
        "datum": heute.isoformat(),
        "titel": "",
        "storys": [],
        "schlagwoerter": [],
    }


def _test_artikel() -> list[dict]:
    return [
        # international
        {
            "titel": "BBC: UN-Sicherheitsrat berät über neue Nahost-Initiative",
            "url": "https://example.com/un-sicherheitsrat-nahost",
            "datum": "2026-07-01",
            "zusammenfassung": "Der UN-Sicherheitsrat hat eine Dringlichkeitssitzung zu einer neuen diplomatischen Initiative im Nahen Osten abgehalten.",
            "quelle_name": "BBC World News",
            "kategorie": "international",
        },
        {
            "titel": "AP News: G7-Gipfel einigt sich auf gemeinsame Erklärung",
            "url": "https://example.com/g7-gipfel-erklaerung",
            "datum": "2026-06-30",
            "zusammenfassung": "Die G7-Staaten haben sich auf eine gemeinsame Erklärung zu Handelsfragen und Klimapolitik geeinigt.",
            "quelle_name": "AP News",
            "kategorie": "international",
        },
        {
            "titel": "Reuters: Chipmangel entspannt sich laut Branchenverband",
            "url": "https://example.com/reuters-chipmangel",
            "datum": "2026-06-26",
            "zusammenfassung": "Der weltweite Halbleitermangel geht laut aktuellen Zahlen spürbar zurück.",
            "quelle_name": "Reuters",
            "kategorie": "international",
        },
        # deutschland
        {
            "titel": "Tagesschau: Bundestag beschließt neues Digitalisierungsgesetz",
            "url": "https://example.com/bundestag-digitalisierung",
            "datum": "2026-07-01",
            "zusammenfassung": "Der Bundestag hat ein Gesetz zur Beschleunigung der Verwaltungsdigitalisierung verabschiedet.",
            "quelle_name": "Tagesschau.de",
            "kategorie": "deutschland",
        },
        {
            "titel": "Tagesschau Wirtschaft: Deutsche Wirtschaft wächst leicht im zweiten Quartal",
            "url": "https://example.com/deutsche-wirtschaft-q2",
            "datum": "2026-06-29",
            "zusammenfassung": "Das deutsche Bruttoinlandsprodukt ist im zweiten Quartal leicht gewachsen, getragen von Exporten.",
            "quelle_name": "Tagesschau Wirtschaft",
            "kategorie": "deutschland",
        },
        {
            "titel": "Deutsche Industrie investiert massiv in KI-Infrastruktur",
            "url": "https://example.com/industrie-ki-investition",
            "datum": "2026-06-29",
            "zusammenfassung": "Mehrere deutsche Großkonzerne kündigen Milliarden-Investitionen in eigene KI-Rechenzentren an.",
            "quelle_name": "Heise.de",
            "kategorie": "deutschland",
        },
        # finanzen
        {
            "titel": "Yahoo Finance: Aktienmärkte schließen im Plus nach Zinssignal der Fed",
            "url": "https://example.com/aktienmaerkte-fed-signal",
            "datum": "2026-07-02",
            "zusammenfassung": "Die US-Notenbank hat Signale für stabile Zinsen gesendet, woraufhin die Aktienmärkte deutlich zulegten.",
            "quelle_name": "Yahoo Finance RSS",
            "kategorie": "finanzen",
        },
        {
            "titel": "DAX erreicht neues Rekordhoch",
            "url": "https://example.com/dax-rekordhoch",
            "datum": "2026-07-01",
            "zusammenfassung": "Der deutsche Leitindex DAX hat ein neues Rekordhoch erreicht, getrieben von starken Quartalszahlen.",
            "quelle_name": "Finanzen.net RSS",
            "kategorie": "finanzen",
        },
        # ki-tech
        {
            "titel": "OpenAI veröffentlicht neues Flaggschiff-Modell",
            "url": "https://example.com/openai-neues-modell",
            "datum": "2026-07-01",
            "zusammenfassung": "OpenAI hat ein neues Sprachmodell mit deutlich verbesserten Fähigkeiten bei Code und Reasoning vorgestellt.",
            "quelle_name": "OpenAI Blog",
            "kategorie": "ki-tech",
        },
        {
            "titel": "Anthropic erweitert Claude um neue Agenten-Fähigkeiten",
            "url": "https://example.com/anthropic-agenten",
            "datum": "2026-07-01",
            "zusammenfassung": "Anthropic hat Claude um Funktionen erweitert, die autonomes mehrstufiges Arbeiten in Entwicklerumgebungen verbessern.",
            "quelle_name": "Anthropic Blog",
            "kategorie": "ki-tech",
        },
        {
            "titel": "Google DeepMind zeigt Fortschritte bei Protein-Faltung",
            "url": "https://example.com/deepmind-protein",
            "datum": "2026-06-28",
            "zusammenfassung": "Ein neues Modell von DeepMind verbessert die Vorhersage von Proteinstrukturen erneut deutlich.",
            "quelle_name": "Google DeepMind Blog",
            "kategorie": "ki-tech",
        },
        {
            "titel": "Hacker News diskutiert neuen Open-Source-Inferenz-Server",
            "url": "https://example.com/hn-inferenz-server",
            "datum": "2026-06-27",
            "zusammenfassung": "Ein neues Open-Source-Projekt zur schnellen lokalen Modell-Inferenz sorgt für rege Diskussion.",
            "quelle_name": "Hacker News",
            "kategorie": "ki-tech",
        },
        {
            "titel": "t3n: Deutsche Startups setzen verstärkt auf KI-Agenten",
            "url": "https://example.com/t3n-startups-agenten",
            "datum": "2026-06-25",
            "zusammenfassung": "Immer mehr deutsche Startups bauen ihr Produkt um autonome KI-Agenten herum.",
            "quelle_name": "t3n.de",
            "kategorie": "ki-tech",
        },
        # sport
        {
            "titel": "Kicker: Bundesliga-Rückrunde startet mit Topspiel",
            "url": "https://example.com/kicker-bundesliga-topspiel",
            "datum": "2026-07-01",
            "zusammenfassung": "Die zweite Hälfte der Bundesliga-Saison beginnt mit einem direkten Duell um die Tabellenführung.",
            "quelle_name": "Kicker Fußball",
            "kategorie": "sport",
        },
        {
            "titel": "Cyclingnews: Radprofi gewinnt überraschend Bergetappe",
            "url": "https://example.com/cyclingnews-bergetappe",
            "datum": "2026-06-30",
            "zusammenfassung": "Ein bislang wenig beachteter Fahrer hat die schwerste Bergetappe der Rundfahrt für sich entschieden.",
            "quelle_name": "Cyclingnews",
            "kategorie": "sport",
        },
        # good-news
        {
            "titel": "Positive News: Wiederaufforstungsprojekt übertrifft Ziel deutlich",
            "url": "https://example.com/positive-news-wiederaufforstung",
            "datum": "2026-06-29",
            "zusammenfassung": "Ein Wiederaufforstungsprojekt hat sein Jahresziel bereits nach wenigen Monaten weit übertroffen.",
            "quelle_name": "Positive News",
            "kategorie": "good-news",
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
