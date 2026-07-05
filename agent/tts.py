"""Wandelt einen generierten Newsletter (siehe generator.py) in eine MP3-Datei um.

Primär wird die Google Cloud Text-to-Speech API genutzt (kostenloses Kontingent,
Bibliothek google-cloud-texttospeech, deutsche Stimme de-DE-Standard-A). Das
erfordert Zugangsdaten (z.B. GOOGLE_APPLICATION_CREDENTIALS auf eine Service-
Account-JSON-Datei). Ist das nicht konfiguriert oder schlägt der Aufruf aus
einem anderen Grund fehl, wird automatisch auf gTTS zurückgefallen (kein
API-Key nötig, klingt aber etwas roboterhafter).

Storys werden wie auf der Website nach Kategorie gruppiert vorgelesen (siehe
generator.KATEGORIE_REIHENFOLGE), mit angesagten Kategorie-Übergängen
("Jetzt: ...", "Weiter mit: ...").
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from generator import KATEGORIE_LABEL, KATEGORIE_REIHENFOLGE

AUDIO_VERZEICHNIS = Path(__file__).parent.parent / "docs" / "audio"

GOOGLE_CLOUD_STIMME = "de-DE-Standard-A"
GOOGLE_CLOUD_SPRACHCODE = "de-DE"


def _gruppiere_nach_kategorie(storys: list[dict]) -> dict[str, list[dict]]:
    gruppen: dict[str, list[dict]] = {k: [] for k in KATEGORIE_REIHENFOLGE}
    for story in storys:
        gruppen.setdefault(story.get("kategorie"), []).append(story)
    return gruppen


def _kategorie_label(kategorie: str | None) -> str:
    if kategorie in KATEGORIE_LABEL:
        return KATEGORIE_LABEL[kategorie]
    return kategorie.replace("-", " ").title() if kategorie else "Weitere Themen"


def _text_aus_newsletter(newsletter: dict) -> str:
    """Baut aus dem Newsletter-Dict einen zusammenhängenden Vorlesetext,
    gruppiert nach Kategorie mit angesagten Übergängen."""
    titel = newsletter.get("titel") or ""
    storys = newsletter.get("storys", [])

    teile = []
    if titel:
        teile.append(f"{titel}.")

    gruppen = _gruppiere_nach_kategorie(storys)
    reihenfolge = KATEGORIE_REIHENFOLGE + [k for k in gruppen if k not in KATEGORIE_REIHENFOLGE]

    erste_kategorie = True
    for kategorie in reihenfolge:
        storys_in_kategorie = gruppen.get(kategorie) or []
        if not storys_in_kategorie:
            continue

        label = _kategorie_label(kategorie)
        teile.append(f"Jetzt: {label}." if erste_kategorie else f"Weiter mit: {label}.")
        erste_kategorie = False

        for story in storys_in_kategorie:
            if story.get("typ") == "einordnung":
                teile.append(f"Eine Einordnung: {story.get('titel', '')}.")
            else:
                teile.append(f"{story.get('titel', '')}.")
            teile.append(story.get("zusammenfassung", ""))

    return "\n\n".join(teil.strip() for teil in teile if teil and teil.strip())


def _mit_google_cloud_tts(text: str, ausgabe_pfad: Path) -> None:
    from google.cloud import texttospeech

    client = texttospeech.TextToSpeechClient()

    input_text = texttospeech.SynthesisInput(text=text)
    stimme = texttospeech.VoiceSelectionParams(
        language_code=GOOGLE_CLOUD_SPRACHCODE,
        name=GOOGLE_CLOUD_STIMME,
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3
    )

    response = client.synthesize_speech(
        input=input_text, voice=stimme, audio_config=audio_config
    )

    ausgabe_pfad.parent.mkdir(parents=True, exist_ok=True)
    with open(ausgabe_pfad, "wb") as f:
        f.write(response.audio_content)


def _mit_gtts(text: str, ausgabe_pfad: Path) -> None:
    from gtts import gTTS

    sprachausgabe = gTTS(text=text, lang="de")
    ausgabe_pfad.parent.mkdir(parents=True, exist_ok=True)
    sprachausgabe.save(str(ausgabe_pfad))


def text_zu_mp3(newsletter_dict: dict, ausgabe_pfad: Path | str) -> Path:
    """Erstellt aus newsletter_dict eine MP3-Datei unter ausgabe_pfad.

    Versucht zuerst Google Cloud TTS, fällt bei Fehlern (z.B. fehlende
    Zugangsdaten) automatisch auf gTTS zurück.
    """
    ausgabe_pfad = Path(ausgabe_pfad)
    text = _text_aus_newsletter(newsletter_dict)

    if not text:
        raise ValueError("Newsletter enthält keinen vorlesbaren Text.")

    try:
        _mit_google_cloud_tts(text, ausgabe_pfad)
        print(f"MP3 via Google Cloud TTS erzeugt: {ausgabe_pfad}")
    except Exception as e:
        print(f"[HINWEIS] Google Cloud TTS nicht verfügbar ({e!r}), nutze gTTS als Fallback.")
        _mit_gtts(text, ausgabe_pfad)
        print(f"MP3 via gTTS erzeugt: {ausgabe_pfad}")

    return ausgabe_pfad


def _test_newsletter_kurzform() -> dict:
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
                "titel": "DAX erreicht neues Rekordhoch",
                "zusammenfassung": "Der deutsche Leitindex DAX hat ein neues Rekordhoch erreicht.",
                "schlagwoerter": ["DAX", "Aktienmarkt"],
                "typ": "kurzmeldung",
                "kategorie": "finanzen",
            },
            {
                "titel": "OpenAI veröffentlicht neues Modell",
                "zusammenfassung": "OpenAI hat ein neues Sprachmodell mit deutlich verbesserten Fähigkeiten bei Code und Reasoning vorgestellt.",
                "schlagwoerter": ["OpenAI", "Sprachmodell"],
                "typ": "kurzmeldung",
                "kategorie": "ki-tech",
            },
        ],
        "schlagwoerter": ["KI", "Regulierung", "OpenAI"],
    }


def main() -> None:
    test_newsletter = _test_newsletter_kurzform()
    ausgabe_pfad = AUDIO_VERZEICHNIS / "test-tts.mp3"

    text_zu_mp3(test_newsletter, ausgabe_pfad)


if __name__ == "__main__":
    main()
