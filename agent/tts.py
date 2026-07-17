"""Wandelt einen generierten Newsletter (siehe generator.py) in eine MP3-Datei um -
per Gemini Audio Generation (google-genai, Modell MODELL_AUDIO), nicht per
reinem Text-to-Speech-Vorlesen.

Der Ablauf in zwei Gemini-Aufrufen:
1. Ein Text-Modell (generator._rufe_gemini_json, dasselbe Modell wie beim
   Erzeugen des Newsletter-Inhalts) schreibt je Kategorie einen natürlich
   gesprochenen Moderationstext - kein stures Vorlesen von Titel +
   Zusammenfassung, sondern ein Moderator, der einleitet, Themen kommentiert,
   Übergänge zwischen Meldungen baut und gelegentlich kurz einordnet ("was das
   bedeutet...", "interessant dabei ist..."). Die erste Kategorie der
   Sendung bekommt zusätzlich eine kurze Begrüßung, die letzte einen kurzen
   Abschiedssatz. Ist die erste Kategorie "breaking-news", beginnt der Text
   mit einer Eilmeldungs-Anmoderation ("Heute haben wir zunächst eine wichtige
   Eilmeldung..."); ist die letzte Kategorie "good-news", beginnt deren Text
   mit einer Überleitung im Stil von "Und zum guten Schluss...".
2. Das Audio-Modell MODELL_AUDIO synthetisiert jeden Kategorie-Text einzeln zu
   Sprache (Rohaudio/PCM), die Segmente werden in der festen Reihenfolge aus
   generator.KATEGORIE_REIHENFOLGE (Breaking News zuerst, Good News zuletzt)
   mit kurzen Pausen zu einer Gesamt-MP3 zusammengesetzt.

Die Kategorie-Zuordnung selbst (welche Story in welcher Kategorie steht) kommt
unverändert aus dem Newsletter-Dict (dort bereits gegen Halluzination
abgesichert, siehe generator.py) - hier wird nur der SPRECHTEXT von Gemini neu
formuliert, niemals neue Fakten.

Der MP3-Export läuft über pydub, das für die Kodierung ein ffmpeg-Binary
braucht - statt auf eine System-Installation angewiesen zu sein, wird dafür
das von der Bibliothek imageio-ffmpeg mitgelieferte Binary verwendet
(_pydub_mit_ffmpeg), das funktioniert also auch ohne separat installiertes
ffmpeg (Windows-Entwicklungsumgebung ebenso wie GitHub-Actions-Runner).

Kein Fallback: Ist die Gemini-Audio-API nicht verfügbar (fehlender/ungültiger
GEMINI_API_KEY, API-Fehler o.ä.), wird nur eine Warnung ausgegeben und die
MP3 übersprungen - es gibt bewusst keinen Rückfall auf gTTS oder eine andere
Engine.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from google.genai import types

from generator import KATEGORIE_LABEL, KATEGORIE_REIHENFOLGE, _client, _rufe_gemini_json

AUDIO_VERZEICHNIS = Path(__file__).parent.parent / "docs" / "audio"

MODELL_AUDIO = "gemini-2.5-flash-preview-tts"
STIMME = "Kore"

PAUSE_ZWISCHEN_KATEGORIEN_MS = 700

VERBOT_ERFINDEN_SKRIPT = (
    "Bleibe dabei ausschließlich bei den unten gegebenen Fakten - erfinde "
    "keine zusätzlichen Informationen, Zahlen oder Zusammenhänge, die dort "
    "nicht stehen."
)


def _kategorie_label(kategorie: str | None) -> str:
    if kategorie in KATEGORIE_LABEL:
        return KATEGORIE_LABEL[kategorie]
    return kategorie.replace("-", " ").title() if kategorie else "Weitere Themen"


def _gruppiere_nach_kategorie(storys: list[dict]) -> dict[str, list[dict]]:
    gruppen: dict[str, list[dict]] = {}
    for story in storys:
        gruppen.setdefault(story.get("kategorie"), []).append(story)
    return gruppen


def _kategorien_mit_storys(newsletter: dict) -> list[tuple[str, list[dict]]]:
    """Liefert (kategorie, storys) in der Reihenfolge, in der die Sendung
    vorgelesen wird: KATEGORIE_REIHENFOLGE (Breaking News zuerst, Good News
    zuletzt), gefolgt von unbekannten Kategorien, jeweils nur wenn nicht leer."""
    gruppen = _gruppiere_nach_kategorie(newsletter.get("storys", []))
    reihenfolge = KATEGORIE_REIHENFOLGE + [k for k in gruppen if k not in KATEGORIE_REIHENFOLGE]
    return [(k, gruppen[k]) for k in reihenfolge if gruppen.get(k)]


def _storys_fuer_prompt(storys: list[dict]) -> str:
    zeilen = []
    for story in storys:
        praefix = "[EINORDNUNG] " if story.get("typ") == "einordnung" else ""
        zeilen.append(f"- {praefix}{story.get('titel', '')}: {story.get('zusammenfassung', '')}")
    return "\n".join(zeilen)


def _erste_kategorie_hinweis(kategorie: str) -> str:
    if kategorie == "breaking-news":
        return (
            "Beginne mit einer kurzen (ca. 1 Satz) Begrüßung zum Newsletter "
            "(nenne sinngemäß Titel und Anlass), gefolgt von einer kurzen "
            "Anmoderation im Stil von 'Heute haben wir zunächst eine wichtige "
            "Eilmeldung...' (Formulierung darf variieren, Dringlichkeit muss "
            "spürbar bleiben) - denn diese Kategorie ist Breaking News."
        )
    return (
        "Beginne mit einer kurzen (ca. 1 Satz) Begrüßung zum Newsletter "
        "(nenne sinngemäß den Titel), danach leite direkt und natürlich in "
        "das erste Thema über."
    )


def _letzte_kategorie_hinweis(kategorie: str) -> str:
    if kategorie == "good-news":
        return (
            "Beginne mit einer Überleitung im Stil von 'Und zum guten "
            "Schluss...' (Formulierung darf variieren). Schließe danach die "
            "gesamte Sendung mit einem kurzen, freundlichen Abschiedssatz ab."
        )
    return (
        "Leite wie gewohnt in das Thema über. Schließe danach die gesamte "
        "Sendung mit einem kurzen, freundlichen Abschiedssatz ab."
    )


def _erstelle_podcast_skript(newsletter: dict) -> dict[str, str]:
    """Fragt Gemini nach einem natürlich gesprochenen Moderationstext je
    Kategorie. Gibt {kategorie: sprechtext} zurück (Reihenfolge/Zuordnung der
    Kategorien bleibt dabei vollständig unter Kontrolle von Python, siehe
    _kategorien_mit_storys - Gemini liefert nur den Text je Kategorie)."""
    kategorien_storys = _kategorien_mit_storys(newsletter)
    if not kategorien_storys:
        return {}

    erste_kategorie = kategorien_storys[0][0]
    letzte_kategorie = kategorien_storys[-1][0]

    bloecke = []
    for kategorie, storys in kategorien_storys:
        label = _kategorie_label(kategorie)
        bloecke.append(f'### Kategorie "{kategorie}" ({label})\n{_storys_fuer_prompt(storys)}')

    hinweise = [f'- Text für Kategorie "{erste_kategorie}": {_erste_kategorie_hinweis(erste_kategorie)}']
    if letzte_kategorie != erste_kategorie:
        hinweise.append(
            f'- Text für Kategorie "{letzte_kategorie}": {_letzte_kategorie_hinweis(letzte_kategorie)}'
        )
    else:
        hinweise[0] += f" {_letzte_kategorie_hinweis(letzte_kategorie)}"

    prompt = f"""Du bist der Moderator eines gesprochenen Podcast-Newsletters auf Deutsch.

Verwandle die folgenden, bereits recherchierten Meldungen JE KATEGORIE in
einen natürlich gesprochenen Moderationstext. Das ist kein stures Vorlesen
von Stichpunkten, sondern eine lockere, lebendige Moderation, wie ein
Mensch sie tatsächlich spricht - kein reines Vorlesen von Titel und
Zusammenfassung:
- Baue eigene Übergänge zwischen den Meldungen einer Kategorie und
  kommentiere kurz statt Fakten nur aneinanderzureihen.
- Baue gelegentlich (nicht bei jeder Meldung) eine kurze eigene Einordnung
  ein ("was das bedeutet...", "interessant dabei ist...", "spannend daran
  ist...").
- Baue an mindestens einer Stelle pro Kategorie eine echte Überraschung oder
  Betonung ein, z.B. "Das ist wirklich bemerkenswert...", "Damit hätte kaum
  jemand gerechnet...", "Und jetzt kommt der spannende Teil...".
- Setze gelegentlich kurze, lockere Einwürfe ("Kurz gesagt: ...", "Man stelle
  sich das mal vor...", "Ehrlich gesagt...").
- Erlaube gelegentlich einen leichten, dezenten Humor, wenn es zur Meldung
  passt - nie auf Kosten von Betroffenen und nie bei ernsten Themen.
- Gestalte den Übergang am ENDE eines Kategorie-Textes so, dass er neugierig
  auf das nächste Thema macht (leichter Cliffhanger oder Ausblick), statt nur
  neutral abzuschließen.
Insgesamt soll es klingen wie ein Moderator, der die Themen selbst spannend
findet - nicht wie eine vorgelesene Zusammenfassung. {VERBOT_ERFINDEN_SKRIPT}

Newsletter-Titel: "{newsletter.get('titel') or 'KI-Newsletter'}"
Datum: {newsletter.get('datum', '')}

Bei jedem Kategorie-Wechsel innerhalb der Sendung baut der jeweilige Text
eine kurze, natürlich klingende Überleitung zur eigenen Kategorie ein (nicht
immer dieselbe Formulierung verwenden). Zusätzlich gilt:
{chr(10).join(hinweise)}

Antworte NUR mit JSON in diesem Format, mit GENAU einem Eintrag je unten
aufgeführter Kategorie (Schlüssel exakt wie angegeben, z.B. "{erste_kategorie}"):

{{
  "segmente": {{
    "<kategorie-schluessel>": "gesprochener Moderationstext für diese Kategorie"
  }}
}}

Kategorien und ihre Meldungen:
{chr(10).join(bloecke)}
"""
    daten = _rufe_gemini_json(prompt)
    return daten.get("segmente", {})


def _abtastrate_aus_mime(mime_type: str | None) -> int:
    if mime_type:
        treffer = re.search(r"rate=(\d+)", mime_type)
        if treffer:
            return int(treffer.group(1))
    return 24000


def _pydub_mit_ffmpeg():
    """Importiert pydub und zeigt es auf das per imageio-ffmpeg mitgelieferte
    ffmpeg-Binary, statt auf eine eventuell fehlende System-Installation
    angewiesen zu sein (Windows-Entwicklungsumgebung ebenso wie
    GitHub-Actions-Runner)."""
    import imageio_ffmpeg
    from pydub import AudioSegment

    AudioSegment.converter = imageio_ffmpeg.get_ffmpeg_exe()
    return AudioSegment


def _segment_zu_audio(text: str):
    AudioSegment = _pydub_mit_ffmpeg()

    client = _client()
    response = client.models.generate_content(
        model=MODELL_AUDIO,
        contents=text,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=STIMME)
                )
            ),
        ),
    )
    inline = response.candidates[0].content.parts[0].inline_data
    abtastrate = _abtastrate_aus_mime(inline.mime_type)
    return AudioSegment(data=inline.data, sample_width=2, frame_rate=abtastrate, channels=1)


def _skript_zu_audio(segmente_text: dict[str, str], kategorien_storys: list[tuple[str, list[dict]]]):
    AudioSegment = _pydub_mit_ffmpeg()

    gesamt = AudioSegment.silent(duration=PAUSE_ZWISCHEN_KATEGORIEN_MS)
    pause = AudioSegment.silent(duration=PAUSE_ZWISCHEN_KATEGORIEN_MS)
    segmente_erzeugt = 0

    for kategorie, _ in kategorien_storys:
        text = segmente_text.get(kategorie)
        if not text:
            print(f"[WARNUNG] Kein Sprechtext für Kategorie '{kategorie}' erhalten, wird übersprungen.")
            continue
        gesamt += _segment_zu_audio(text) + pause
        segmente_erzeugt += 1

    if segmente_erzeugt == 0:
        raise RuntimeError("Für keine Kategorie konnte Audio erzeugt werden.")

    return gesamt


def text_zu_mp3(newsletter_dict: dict, ausgabe_pfad: Path | str) -> Path | None:
    """Erstellt aus newsletter_dict eine MP3-Datei unter ausgabe_pfad via
    Gemini Audio Generation. Gibt bei Erfolg ausgabe_pfad zurück, sonst None
    (Warnung wird ausgegeben, es gibt keinen Fallback auf eine andere Engine)."""
    ausgabe_pfad = Path(ausgabe_pfad)
    kategorien_storys = _kategorien_mit_storys(newsletter_dict)

    if not kategorien_storys:
        print("[HINWEIS] Newsletter enthält keine Storys, MP3 wird übersprungen.")
        return None

    try:
        segmente_text = _erstelle_podcast_skript(newsletter_dict)
        if not segmente_text:
            raise RuntimeError("Gemini hat kein Podcast-Skript geliefert.")
        audio = _skript_zu_audio(segmente_text, kategorien_storys)
        ausgabe_pfad.parent.mkdir(parents=True, exist_ok=True)
        audio.export(str(ausgabe_pfad), format="mp3", bitrate="128k")
    except Exception as e:
        print(f"[WARNUNG] Gemini Audio-Generierung nicht verfügbar ({e!r}), MP3 wird übersprungen.")
        return None

    print(f"MP3 via Gemini Audio erzeugt: {ausgabe_pfad}")
    return ausgabe_pfad


def _test_newsletter() -> dict:
    return {
        "modus": "kurzform",
        "datum": date.today().isoformat(),
        "titel": "KI-Newsletter Kurzform, Testausgabe",
        "storys": [
            {
                "titel": "G7-Gipfel einigt sich auf gemeinsame Erklärung",
                "zusammenfassung": "Die G7-Staaten haben sich auf eine gemeinsame Erklärung zu Handelsfragen geeinigt.",
                "schlagwoerter": ["G7", "Diplomatie"],
                "typ": "kurzmeldung",
                "kategorie": "international",
            },
            {
                "titel": "Bundestag beschließt neues Digitalisierungsgesetz",
                "zusammenfassung": "Der Bundestag hat ein Gesetz zur Beschleunigung der Verwaltungsdigitalisierung verabschiedet.",
                "schlagwoerter": ["Bundestag", "Digitalisierung"],
                "typ": "kurzmeldung",
                "kategorie": "deutschland",
            },
            {
                "titel": "OpenAI veröffentlicht neues Modell",
                "zusammenfassung": "OpenAI hat ein neues Sprachmodell mit deutlich verbesserten Fähigkeiten bei Code und Reasoning vorgestellt.",
                "schlagwoerter": ["OpenAI", "Sprachmodell"],
                "typ": "kurzmeldung",
                "kategorie": "ki-tech",
            },
            {
                "titel": "Wiederaufforstungsprojekt übertrifft Ziel deutlich",
                "zusammenfassung": "Ein Wiederaufforstungsprojekt hat sein Jahresziel bereits nach wenigen Monaten weit übertroffen.",
                "schlagwoerter": ["Umwelt", "Wiederaufforstung"],
                "typ": "kurzmeldung",
                "kategorie": "good-news",
            },
        ],
        "schlagwoerter": ["KI", "Regulierung", "OpenAI"],
    }


def main() -> None:
    test_newsletter = _test_newsletter()
    ausgabe_pfad = AUDIO_VERZEICHNIS / "test-tts.mp3"

    text_zu_mp3(test_newsletter, ausgabe_pfad)


if __name__ == "__main__":
    main()
