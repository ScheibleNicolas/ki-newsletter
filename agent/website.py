"""Erstellt aus einem Newsletter-Dict (siehe generator.py) eine statische
HTML-Ausgabenseite und pflegt den Gesamt-Index (docs/index.html, docs/index.json).
"""

from __future__ import annotations

import html
import json
import os
from datetime import date
from pathlib import Path

DOCS_VERZEICHNIS = Path(__file__).parent.parent / "docs"
AUSGABEN_VERZEICHNIS = DOCS_VERZEICHNIS / "ausgaben"
INDEX_HTML_PFAD = DOCS_VERZEICHNIS / "index.html"
INDEX_JSON_PFAD = DOCS_VERZEICHNIS / "index.json"

WOCHENTAGE_DE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MONATE_DE = [
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
]

MODUS_LABEL = {
    "kurzform": "Kurzform",
    "deep-dive": "Deep-Dive",
}

GRUNDSTIL = """
    body { background: #0f1115; color: #e6e6e6; font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; margin: 0; padding: 0 1rem; }
    .container { max-width: 700px; margin: 0 auto; padding: 2rem 0 4rem; }
    a { color: #7dd3fc; }
    h1 { font-size: 1.6rem; line-height: 1.3; margin: 0 0 0.5rem; }
    .datum { color: #9aa0a6; font-size: 0.95rem; margin: 0 0 1rem; }
    .badge { display: inline-block; padding: 0.2rem 0.7rem; border-radius: 999px; font-size: 0.8rem; font-weight: 600; letter-spacing: 0.02em; }
    .badge--kurzform { background: #14342e; color: #6ee7b7; }
    .badge--deep-dive { background: #33281a; color: #fbbf24; }
    .badge--sonstiges { background: #2a2a33; color: #c7c7d1; }
    .tags { margin: 0.6rem 0 0; }
    .tag { display: inline-block; background: #1c1f26; color: #9aa0a6; border-radius: 6px; padding: 0.15rem 0.55rem; font-size: 0.78rem; margin: 0 0.4rem 0.4rem 0; }
"""


def _datum_lesbar(datum_str: str) -> str:
    d = date.fromisoformat(datum_str)
    return f"{WOCHENTAGE_DE[d.weekday()]}, {d.day:02d}. {MONATE_DE[d.month - 1]} {d.year}"


def _badge_html(modus: str) -> str:
    label = MODUS_LABEL.get(modus, modus.replace("-", " ").title())
    css_klasse = {"kurzform": "badge--kurzform", "deep-dive": "badge--deep-dive"}.get(
        modus, "badge--sonstiges"
    )
    return f'<span class="badge {css_klasse}">{html.escape(label)}</span>'

def _tags_html(schlagwoerter: list[str]) -> str:
    if not schlagwoerter:
        return ""
    pills = "".join(f'<span class="tag">{html.escape(s)}</span>' for s in schlagwoerter)
    return f'<div class="tags">{pills}</div>'


def _quelle_html(story: dict) -> str:
    quelle_url = story.get("quelle_url")
    if not quelle_url:
        return ""
    label = story.get("quelle_name") or quelle_url
    return (
        f'<p class="quelle">Quelle: '
        f'<a href="{html.escape(quelle_url)}" target="_blank" rel="noopener noreferrer">'
        f'{html.escape(label)}</a></p>'
    )


def _story_html(story: dict) -> str:
    ist_hauptartikel = story.get("typ") == "deep-dive"
    klasse = "story story--haupt" if ist_hauptartikel else "story"
    titel = html.escape(story.get("titel", ""))
    zusammenfassung = html.escape(story.get("zusammenfassung", "")).replace("\n", "<br>")
    return f"""
    <article class="{klasse}">
      <h2>{titel}</h2>
      <p>{zusammenfassung}</p>
      {_tags_html(story.get("schlagwoerter", []))}
      {_quelle_html(story)}
    </article>"""


def _ausgabe_html(newsletter: dict, audio_relativ: str) -> str:
    titel = html.escape(newsletter.get("titel", ""))
    modus = newsletter.get("modus", "")
    datum = newsletter.get("datum", "")
    storys_html = "".join(_story_html(s) for s in newsletter.get("storys", []))

    return f"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{titel}</title>
  <style>
{GRUNDSTIL}
    .story {{ border-top: 1px solid #23262e; padding: 1.4rem 0; }}
    .story:first-of-type {{ border-top: none; }}
    .story h2 {{ font-size: 1.15rem; margin: 0 0 0.5rem; }}
    .story p {{ line-height: 1.55; color: #d4d4d8; margin: 0; }}
    .story--haupt h2 {{ font-size: 1.35rem; color: #fbbf24; }}
    .quelle {{ margin: 0.7rem 0 0; font-size: 0.82rem; color: #9aa0a6; }}
    audio {{ width: 100%; margin: 1.4rem 0; }}
    .zurueck {{ display: inline-block; margin-top: 2rem; font-size: 0.9rem; }}
  </style>
</head>
<body>
  <div class="container">
    <p class="datum">{html.escape(_datum_lesbar(datum))}</p>
    <h1>{titel}</h1>
    {_badge_html(modus)}
    <audio controls preload="none" src="{html.escape(audio_relativ)}"></audio>
    {storys_html}
    <a class="zurueck" href="../index.html">&larr; Alle Ausgaben</a>
  </div>
</body>
</html>
"""


def _lade_index() -> list[dict]:
    if not INDEX_JSON_PFAD.exists():
        return []
    with open(INDEX_JSON_PFAD, "r", encoding="utf-8") as f:
        return json.load(f)


def _index_html(eintraege: list[dict]) -> str:
    karten = []
    for e in eintraege:
        karten.append(f"""
    <a class="karte" href="{html.escape(e['html_pfad'])}">
      <p class="datum">{html.escape(_datum_lesbar(e['datum']))}</p>
      <h2>{html.escape(e['titel'])}</h2>
      {_badge_html(e['modus'])}
      {_tags_html(e.get('schlagwoerter', []))}
    </a>""")

    return f"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>KI-Newsletter, Archiv</title>
  <style>
{GRUNDSTIL}
    .karte {{ display: block; text-decoration: none; color: inherit; border-top: 1px solid #23262e; padding: 1.4rem 0; }}
    .karte:first-of-type {{ border-top: none; }}
    .karte h2 {{ font-size: 1.15rem; margin: 0.3rem 0 0.5rem; color: #e6e6e6; }}
  </style>
</head>
<body>
  <div class="container">
    <h1>KI-Newsletter</h1>
    <p class="datum">Alle Ausgaben</p>
    {"".join(karten) if karten else "<p>Noch keine Ausgaben vorhanden.</p>"}
  </div>
</body>
</html>
"""


def _aktualisiere_index(neuer_eintrag: dict) -> None:
    eintraege = [e for e in _lade_index() if e["datum"] != neuer_eintrag["datum"]]
    eintraege.append(neuer_eintrag)
    eintraege.sort(key=lambda e: e["datum"], reverse=True)

    DOCS_VERZEICHNIS.mkdir(parents=True, exist_ok=True)
    with open(INDEX_JSON_PFAD, "w", encoding="utf-8") as f:
        json.dump(eintraege, f, indent=2, ensure_ascii=False)

    with open(INDEX_HTML_PFAD, "w", encoding="utf-8") as f:
        f.write(_index_html(eintraege))


def erstelle_ausgabe_seite(newsletter_dict: dict, audio_pfad: Path | str) -> Path:
    """Erstellt docs/ausgaben/DATUM.html und aktualisiert docs/index.html/.json."""
    datum = newsletter_dict["datum"]
    audio_pfad = Path(audio_pfad)

    AUSGABEN_VERZEICHNIS.mkdir(parents=True, exist_ok=True)
    html_pfad = AUSGABEN_VERZEICHNIS / f"{datum}.html"

    audio_relativ = os.path.relpath(audio_pfad, html_pfad.parent).replace(os.sep, "/")
    with open(html_pfad, "w", encoding="utf-8") as f:
        f.write(_ausgabe_html(newsletter_dict, audio_relativ))

    audio_relativ_docs = os.path.relpath(audio_pfad, DOCS_VERZEICHNIS).replace(os.sep, "/")
    html_relativ_docs = os.path.relpath(html_pfad, DOCS_VERZEICHNIS).replace(os.sep, "/")
    _aktualisiere_index({
        "datum": datum,
        "titel": newsletter_dict.get("titel", ""),
        "modus": newsletter_dict.get("modus", ""),
        "schlagwoerter": newsletter_dict.get("schlagwoerter", []),
        "audio_pfad": audio_relativ_docs,
        "html_pfad": html_relativ_docs,
    })

    return html_pfad


def _test_newsletter() -> dict:
    return {
        "modus": "deep-dive",
        "datum": date.today().isoformat(),
        "titel": "KI-Newsletter Deep-Dive, Testausgabe",
        "storys": [
            {
                "titel": "Hauptthema der Woche: Reasoning-Modelle im Unternehmenseinsatz",
                "zusammenfassung": "Dies ist ein längerer Testtext, der im echten Betrieb 400-500 Wörter umfassen würde und das wichtigste Thema der Woche ausführlich erklärt.",
                "schlagwoerter": ["Reasoning", "Unternehmen", "KI-Agenten"],
                "typ": "deep-dive",
                "quelle_url": "https://example.com/reasoning-modelle",
                "quelle_name": "OpenAI Blog",
            },
            {
                "titel": "EU einigt sich auf neue KI-Regularien",
                "zusammenfassung": "Kurzmeldung zu neuen Transparenzpflichten für KI-Anbieter in der EU.",
                "schlagwoerter": ["EU", "Regulierung"],
                "typ": "kurzmeldung",
                "quelle_url": "https://example.com/eu-ki-regeln",
                "quelle_name": "Tagesschau.de",
            },
            {
                "titel": "Google DeepMind zeigt Fortschritte bei Protein-Faltung",
                "zusammenfassung": "Kurzmeldung zu einem verbesserten Modell für Proteinstruktur-Vorhersagen.",
                "schlagwoerter": ["DeepMind", "Biotech"],
                "typ": "kurzmeldung",
                "quelle_url": "https://example.com/deepmind-protein",
                "quelle_name": "Google DeepMind Blog",
            },
        ],
        "schlagwoerter": ["Reasoning", "KI-Agenten", "Regulierung"],
    }


def main() -> None:
    newsletter = _test_newsletter()
    audio_pfad = DOCS_VERZEICHNIS / "audio" / f"{newsletter['datum']}.mp3"

    html_pfad = erstelle_ausgabe_seite(newsletter, audio_pfad)

    print(f"Ausgabenseite erstellt: {html_pfad}")
    print(f"Index aktualisiert: {INDEX_HTML_PFAD}")
    print(f"Index-JSON aktualisiert: {INDEX_JSON_PFAD}")


if __name__ == "__main__":
    main()
