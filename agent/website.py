"""Erstellt aus einem Newsletter-Dict (siehe generator.py) eine statische
HTML-Ausgabenseite und pflegt den Gesamt-Index (docs/index.html, docs/index.json).

Storys werden nach Kategorie gruppiert angezeigt, in der Reihenfolge aus
generator.KATEGORIE_REIHENFOLGE (Breaking News -> Internationales ->
Deutschland -> Finanzen -> KI & Tech -> Sport -> Good News), damit Website und
Audio (tts.py) konsistent derselben Gliederung folgen. Breaking News wird nur
angezeigt, wenn Storys dafür vorhanden sind, erscheint dann aber ganz oben und
optisch hervorgehoben (roter Rahmen/Hintergrund).

audio_pfad ist optional: liefert tts.py keine MP3 (z.B. weil die Gemini-Audio-
API nicht verfügbar war), wird die Seite ohne <audio>-Element erzeugt statt auf
eine nicht existierende Datei zu verweisen.
"""

from __future__ import annotations

import html
import json
import os
from datetime import date
from pathlib import Path

from generator import KATEGORIE_LABEL, KATEGORIE_REIHENFOLGE

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
    "kurzform": "Mittwochsausgabe",
    "deep-dive": "Samstagsausgabe",
}

KATEGORIE_ICON = {
    "breaking-news": "🚨",
    "international": "🌍",
    "deutschland": "🇩🇪",
    "finanzen": "📈",
    "ki-tech": "🤖",
    "sport": "⚽",
    "good-news": "🌟",
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
    ist_einordnung = story.get("typ") == "einordnung"
    klasse = "story story--einordnung" if ist_einordnung else "story"
    titel = html.escape(story.get("titel", ""))
    zusammenfassung = html.escape(story.get("zusammenfassung", "")).replace("\n", "<br>")
    einordnung_label = '<p class="einordnung-label">Einordnung</p>' if ist_einordnung else ""
    return f"""
    <article class="{klasse}">
      {einordnung_label}
      <h3>{titel}</h3>
      <p>{zusammenfassung}</p>
      {_quelle_html(story)}
    </article>"""


def _gruppiere_nach_kategorie(storys: list[dict]) -> dict[str, list[dict]]:
    gruppen: dict[str, list[dict]] = {k: [] for k in KATEGORIE_REIHENFOLGE}
    for story in storys:
        kategorie = story.get("kategorie")
        gruppen.setdefault(kategorie, []).append(story)
    return gruppen


def _kategorie_abschnitt_html(kategorie: str, storys: list[dict]) -> str:
    label = KATEGORIE_LABEL.get(kategorie, kategorie.replace("-", " ").title())
    icon = KATEGORIE_ICON.get(kategorie, "")
    anzeige_label = f"{icon} {label}".strip()
    storys_html = "".join(_story_html(s) for s in storys)
    klasse = "kategorie kategorie--breaking-news" if kategorie == "breaking-news" else "kategorie"
    return f"""
    <section class="{klasse}">
      <h2 class="kategorie-titel">{html.escape(anzeige_label)}</h2>
      {storys_html}
    </section>"""


def _ausgabe_html(newsletter: dict, audio_relativ: str | None) -> str:
    titel = html.escape(newsletter.get("titel", ""))
    modus = newsletter.get("modus", "")
    datum = newsletter.get("datum", "")

    gruppen = _gruppiere_nach_kategorie(newsletter.get("storys", []))
    reihenfolge = KATEGORIE_REIHENFOLGE + [k for k in gruppen if k not in KATEGORIE_REIHENFOLGE]
    abschnitte_html = "".join(
        _kategorie_abschnitt_html(k, gruppen[k]) for k in reihenfolge if gruppen.get(k)
    )
    audio_html = (
        f'<audio id="player" controls preload="none" src="{html.escape(audio_relativ)}"></audio>'
        if audio_relativ
        else ""
    )
    sticky_player_html = (
        """
  <div class="sticky-player" id="stickyPlayer">
    <div class="sticky-player__inner">
      <button class="sticky-player__toggle" id="stickyToggle" type="button" aria-label="Abspielen">&#9654;</button>
      <div class="sticky-player__bar"><div class="sticky-player__progress" id="stickyProgress"></div></div>
    </div>
  </div>
  <script>
    (function () {
      var audio = document.getElementById('player');
      var sticky = document.getElementById('stickyPlayer');
      var toggle = document.getElementById('stickyToggle');
      var progress = document.getElementById('stickyProgress');
      if (!audio || !sticky || !window.IntersectionObserver) return;

      var beobachter = new IntersectionObserver(function (eintraege) {
        var sichtbar = eintraege[0].isIntersecting;
        sticky.classList.toggle('sticky-player--sichtbar', !sichtbar);
      }, { threshold: 0 });
      beobachter.observe(audio);

      toggle.addEventListener('click', function () {
        if (audio.paused) { audio.play(); } else { audio.pause(); }
      });
      audio.addEventListener('play', function () { toggle.innerHTML = '&#10074;&#10074;'; toggle.setAttribute('aria-label', 'Pause'); });
      audio.addEventListener('pause', function () { toggle.innerHTML = '&#9654;'; toggle.setAttribute('aria-label', 'Abspielen'); });
      audio.addEventListener('timeupdate', function () {
        if (!audio.duration) return;
        progress.style.width = (audio.currentTime / audio.duration * 100) + '%';
      });
    })();
  </script>"""
        if audio_relativ
        else ""
    )

    return f"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{titel}</title>
  <style>
{GRUNDSTIL}
    .kategorie {{ border-top: 2px solid #262a33; padding-top: 1.6rem; margin-top: 1.8rem; }}
    .kategorie:first-of-type {{ border-top: none; padding-top: 0; margin-top: 1.6rem; }}
    .kategorie-titel {{ font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.08em; color: #7dd3fc; margin: 0 0 0.8rem; }}
    .kategorie--breaking-news {{ border: 2px solid #ef4444 !important; background: #2a1414; border-radius: 10px; padding: 1.2rem 1.4rem !important; margin-top: 1.8rem !important; }}
    .kategorie--breaking-news:first-of-type {{ margin-top: 0 !important; }}
    .kategorie--breaking-news .kategorie-titel {{ color: #f87171; font-size: 0.95rem; }}
    .kategorie--breaking-news .story {{ border-top-color: #3f1d1d; }}
    .story {{ border-top: 1px solid #23262e; padding: 1.2rem 0; }}
    .story:first-of-type {{ border-top: none; padding-top: 0; }}
    .story h3 {{ font-size: 1.1rem; margin: 0 0 0.5rem; }}
    .story p {{ line-height: 1.55; color: #d4d4d8; margin: 0; }}
    .story--einordnung h3 {{ font-size: 1.3rem; color: #fbbf24; }}
    .einordnung-label {{ font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.06em; color: #fbbf24; margin: 0 0 0.3rem; }}
    .quelle {{ margin: 0.7rem 0 0; font-size: 0.82rem; color: #9aa0a6; }}
    audio {{ width: 100%; margin: 1.4rem 0; }}
    .zurueck {{ display: inline-block; margin-top: 2rem; font-size: 0.9rem; }}
    .zurueck--oben {{ margin-top: 0; margin-bottom: 1.2rem; }}
    .sticky-player {{ position: fixed; left: 0; right: 0; bottom: 0; background: #1c1f26; border-top: 1px solid #2a2d36; box-shadow: 0 -2px 10px rgba(0, 0, 0, 0.35); padding: 0.6rem 1rem; transform: translateY(100%); transition: transform 0.25s ease; z-index: 50; }}
    .sticky-player--sichtbar {{ transform: translateY(0); }}
    .sticky-player__inner {{ max-width: 700px; margin: 0 auto; display: flex; align-items: center; gap: 0.9rem; }}
    .sticky-player__toggle {{ flex: 0 0 auto; width: 2.3rem; height: 2.3rem; border-radius: 50%; border: none; background: #7dd3fc; color: #0f1115; font-size: 0.9rem; line-height: 1; cursor: pointer; display: flex; align-items: center; justify-content: center; }}
    .sticky-player__bar {{ flex: 1 1 auto; height: 4px; border-radius: 999px; background: #2a2d36; overflow: hidden; }}
    .sticky-player__progress {{ height: 100%; width: 0%; background: #7dd3fc; }}
  </style>
</head>
<body>
  <div class="container">
    <a class="zurueck zurueck--oben" href="../index.html">&larr; Alle Ausgaben</a>
    <p class="datum">{html.escape(_datum_lesbar(datum))}</p>
    <h1>{titel}</h1>
    {_badge_html(modus)}
    {audio_html}
    {abschnitte_html}
    <a class="zurueck" href="../index.html">&larr; Alle Ausgaben</a>
  </div>
  {sticky_player_html}
</body>
</html>
"""


def _lade_index() -> list[dict]:
    if not INDEX_JSON_PFAD.exists():
        return []
    with open(INDEX_JSON_PFAD, "r", encoding="utf-8") as f:
        return json.load(f)


def _gruppiere_nach_monat(eintraege: list[dict]) -> list[tuple[int, int, list[dict]]]:
    """Gruppiert die (absteigend nach Datum sortierten) Ausgaben in
    absteigende (Jahr, Monat, Ausgaben)-Blöcke, ohne die Sortierung
    aufzubrechen (siehe _aktualisiere_index)."""
    gruppen: list[tuple[int, int, list[dict]]] = []
    for e in eintraege:
        d = date.fromisoformat(e["datum"])
        if gruppen and gruppen[-1][0] == d.year and gruppen[-1][1] == d.month:
            gruppen[-1][2].append(e)
        else:
            gruppen.append((d.year, d.month, [e]))
    return gruppen


def _index_html(eintraege: list[dict]) -> str:
    gruppen = _gruppiere_nach_monat(eintraege)
    heute = date.today()
    index_offen = next(
        (i for i, (jahr, monat, _) in enumerate(gruppen) if jahr == heute.year and monat == heute.month),
        0 if gruppen else None,
    )

    monate_html = []
    for i, (jahr, monat, monats_eintraege) in enumerate(gruppen):
        karten = []
        for e in monats_eintraege:
            karten.append(f"""
      <a class="karte" href="{html.escape(e['html_pfad'])}">
        <p class="datum">{html.escape(_datum_lesbar(e['datum']))}</p>
        <h2>{html.escape(e['titel'])}</h2>
        {_badge_html(e['modus'])}
      </a>""")
        offen_attr = " open" if i == index_offen else ""
        monate_html.append(f"""
    <details class="monat"{offen_attr}>
      <summary class="monat-titel">{html.escape(MONATE_DE[monat - 1])} {jahr}</summary>
      <div class="monat-inhalt">{"".join(karten)}</div>
    </details>""")

    return f"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>KI-Newsletter, Archiv</title>
  <style>
{GRUNDSTIL}
    .monat {{ border-top: 1px solid #23262e; padding: 1rem 0; }}
    .monat:first-of-type {{ border-top: none; }}
    .monat-titel {{ cursor: pointer; font-size: 1.1rem; font-weight: 600; color: #e6e6e6; list-style: none; padding: 0.3rem 0; }}
    .monat-titel::-webkit-details-marker {{ display: none; }}
    .monat-titel::before {{ content: "\\25B8"; display: inline-block; margin-right: 0.5rem; color: #7dd3fc; transition: transform 0.15s ease; }}
    .monat[open] > .monat-titel::before {{ transform: rotate(90deg); }}
    .monat-inhalt {{ margin-top: 0.4rem; }}
    .karte {{ display: block; text-decoration: none; color: inherit; border-top: 1px solid #23262e; padding: 1.4rem 0; }}
    .karte:first-of-type {{ border-top: none; }}
    .karte h2 {{ font-size: 1.15rem; margin: 0.3rem 0 0.5rem; color: #e6e6e6; }}
  </style>
</head>
<body>
  <div class="container">
    <h1>KI-Newsletter</h1>
    <p class="datum">Alle Ausgaben</p>
    {"".join(monate_html) if monate_html else "<p>Noch keine Ausgaben vorhanden.</p>"}
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


def erstelle_ausgabe_seite(newsletter_dict: dict, audio_pfad: Path | str | None) -> Path:
    """Erstellt docs/ausgaben/DATUM.html und aktualisiert docs/index.html/.json.

    audio_pfad darf None sein, wenn tts.py keine MP3 erzeugen konnte - die
    Seite wird dann ohne <audio>-Element erstellt."""
    datum = newsletter_dict["datum"]
    audio_pfad = Path(audio_pfad) if audio_pfad else None

    AUSGABEN_VERZEICHNIS.mkdir(parents=True, exist_ok=True)
    html_pfad = AUSGABEN_VERZEICHNIS / f"{datum}.html"

    audio_relativ = (
        os.path.relpath(audio_pfad, html_pfad.parent).replace(os.sep, "/") if audio_pfad else None
    )
    with open(html_pfad, "w", encoding="utf-8") as f:
        f.write(_ausgabe_html(newsletter_dict, audio_relativ))

    audio_relativ_docs = (
        os.path.relpath(audio_pfad, DOCS_VERZEICHNIS).replace(os.sep, "/") if audio_pfad else None
    )
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
                "titel": "Zentralbanken greifen gemeinsam nach Marktschock ein",
                "zusammenfassung": "Testtext für eine Breaking-News-Meldung, wie sie nur an seltenen, außergewöhnlich wichtigen Tagen erscheinen würde.",
                "schlagwoerter": ["Marktschock", "Zentralbanken"],
                "typ": "kurzmeldung",
                "quelle_url": "https://example.com/zentralbanken-eingreifen",
                "quelle_name": "Reuters",
                "kategorie": "breaking-news",
            },
            {
                "titel": "G7-Gipfel einigt sich auf gemeinsame Erklärung",
                "zusammenfassung": "Testtext zu einer internationalen Meldung mit 120-180 Wörtern, wie sie in der echten Samstagsausgabe vorkommen würde.",
                "schlagwoerter": ["G7", "Diplomatie"],
                "typ": "kurzmeldung",
                "quelle_url": "https://example.com/g7-gipfel",
                "quelle_name": "AP News",
                "kategorie": "international",
            },
            {
                "titel": "Bundestag beschließt neues Digitalisierungsgesetz",
                "zusammenfassung": "Testtext zu einer Deutschland-Meldung.",
                "schlagwoerter": ["Bundestag", "Digitalisierung"],
                "typ": "kurzmeldung",
                "quelle_url": "https://example.com/bundestag-digitalisierung",
                "quelle_name": "Tagesschau.de",
                "kategorie": "deutschland",
            },
            {
                "titel": "DAX erreicht neues Rekordhoch",
                "zusammenfassung": "Testtext zu einer Finanzen-Meldung.",
                "schlagwoerter": ["DAX", "Aktienmarkt"],
                "typ": "kurzmeldung",
                "quelle_url": "https://example.com/dax-rekordhoch",
                "quelle_name": "Finanzen.net RSS",
                "kategorie": "finanzen",
            },
            {
                "titel": "Reasoning-Modelle im Unternehmenseinsatz",
                "zusammenfassung": "Dies ist ein längerer Testtext, der im echten Betrieb 150-200 Wörter umfassen würde und das dominierende KI/Tech-Thema der Woche einordnet.",
                "schlagwoerter": ["Reasoning", "Unternehmen", "KI-Agenten"],
                "typ": "einordnung",
                "quelle_url": "https://example.com/reasoning-modelle",
                "quelle_name": "OpenAI Blog",
                "kategorie": "ki-tech",
            },
            {
                "titel": "Google DeepMind zeigt Fortschritte bei Protein-Faltung",
                "zusammenfassung": "Testtext zu einer KI/Tech-Kurzmeldung.",
                "schlagwoerter": ["DeepMind", "Biotech"],
                "typ": "kurzmeldung",
                "quelle_url": "https://example.com/deepmind-protein",
                "quelle_name": "Google DeepMind Blog",
                "kategorie": "ki-tech",
            },
            {
                "titel": "Bundesliga-Rückrunde startet mit Topspiel",
                "zusammenfassung": "Testtext zu einer Sport-Meldung.",
                "schlagwoerter": ["Bundesliga", "Fußball"],
                "typ": "kurzmeldung",
                "quelle_url": "https://example.com/kicker-bundesliga-topspiel",
                "quelle_name": "Kicker Fußball",
                "kategorie": "sport",
            },
            {
                "titel": "Wiederaufforstungsprojekt übertrifft Ziel deutlich",
                "zusammenfassung": "Testtext zu einer Good-News-Meldung.",
                "schlagwoerter": ["Umwelt", "Wiederaufforstung"],
                "typ": "kurzmeldung",
                "quelle_url": "https://example.com/positive-news-wiederaufforstung",
                "quelle_name": "Positive News",
                "kategorie": "good-news",
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
