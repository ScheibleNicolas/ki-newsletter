"""Wandelt einen generierten Newsletter (siehe generator.py) in eine MP3-Datei um.

Primär wird die Google Cloud Text-to-Speech API genutzt (kostenloses Kontingent,
Bibliothek google-cloud-texttospeech, deutsche Stimme de-DE-Standard-A). Das
erfordert Zugangsdaten (z.B. GOOGLE_APPLICATION_CREDENTIALS auf eine Service-
Account-JSON-Datei). Ist das nicht konfiguriert oder schlägt der Aufruf aus
einem anderen Grund fehl, wird automatisch auf gTTS zurückgefallen (kein
API-Key nötig, klingt aber etwas roboterhafter).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

AUDIO_VERZEICHNIS = Path(__file__).parent.parent / "docs" / "audio"

GOOGLE_CLOUD_STIMME = "de-DE-Standard-A"
GOOGLE_CLOUD_SPRACHCODE = "de-DE"


def _text_aus_newsletter(newsletter: dict) -> str:
    """Baut aus dem Newsletter-Dict einen zusammenhängenden Vorlesetext."""
    modus = newsletter.get("modus")
    titel = newsletter.get("titel") or ""
    storys = newsletter.get("storys", [])

    teile = []
    if titel:
        teile.append(f"{titel}.")

    if modus == "deep-dive":
        hauptartikel = [s for s in storys if s.get("typ") == "deep-dive"]
        kurzmeldungen = [s for s in storys if s.get("typ") != "deep-dive"]
        if not hauptartikel and storys:
            # Falls "typ" fehlt: erste Story als Hauptartikel behandeln.
            hauptartikel, kurzmeldungen = [storys[0]], storys[1:]

        for story in hauptartikel:
            teile.append(f"{story.get('titel', '')}.")
            teile.append(story.get("zusammenfassung", ""))

        if kurzmeldungen:
            teile.append("Außerdem in Kürze:")
            for story in kurzmeldungen:
                teile.append(
                    f"{story.get('titel', '')}. {story.get('zusammenfassung', '')}"
                )
    else:
        # Kurzform (oder unbekannter Modus): jede Story mit Titel + Zusammenfassung.
        for story in storys:
            teile.append(f"{story.get('titel', '')}. {story.get('zusammenfassung', '')}")

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
                "titel": "OpenAI veröffentlicht neues Modell",
                "zusammenfassung": "OpenAI hat ein neues Sprachmodell mit deutlich verbesserten Fähigkeiten bei Code und Reasoning vorgestellt.",
                "schlagwoerter": ["OpenAI", "Sprachmodell"],
            },
            {
                "titel": "EU einigt sich auf neue KI-Regularien",
                "zusammenfassung": "Die EU-Staaten haben sich auf verschärfte Transparenzpflichten für KI-Anbieter geeinigt.",
                "schlagwoerter": ["EU", "Regulierung"],
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
