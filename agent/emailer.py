"""Verschickt eine Benachrichtigungs-E-Mail an alle Empfänger aus
agent/empfaenger.txt, sobald eine neue Newsletter-Ausgabe online ist.

Die Mail enthält nur Titel, Wochentag, einen Link zur Ausgabenseite und die
Schlagwörter - der volle Inhalt bleibt bewusst auf der Website, die Mail ist
nur der Hinweis darauf.
"""

from __future__ import annotations

import html
import smtplib
import ssl
from datetime import date
from email.message import EmailMessage
from pathlib import Path

from dotenv import load_dotenv
import os

load_dotenv(Path(__file__).parent / ".env")

EMPFAENGER_PFAD = Path(__file__).parent / "empfaenger.txt"

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465

WOCHENTAG_LABEL = {
    "kurzform": "Mittwoch",
    "deep-dive": "Samstag",
}


def _lade_empfaenger() -> list[str]:
    if not EMPFAENGER_PFAD.exists():
        print(f"[WARNUNG] {EMPFAENGER_PFAD} nicht gefunden, Benachrichtigung wird übersprungen.")
        return []

    empfaenger = []
    with open(EMPFAENGER_PFAD, "r", encoding="utf-8") as f:
        for zeile in f:
            zeile = zeile.strip()
            if not zeile or zeile.startswith("#"):
                continue
            empfaenger.append(zeile)
    return empfaenger


def _betreff(datum: date) -> str:
    return f"KI Newsletter – Ausgabe vom {datum.day:02d}.{datum.month:02d}.{datum.year}"


def _html_inhalt(newsletter: dict, website_url: str) -> str:
    titel = html.escape(newsletter.get("titel", ""))
    wochentag = WOCHENTAG_LABEL.get(newsletter.get("modus", ""), "")
    schlagwoerter = newsletter.get("schlagwoerter", [])
    tags_html = "".join(
        f'<span style="display:inline-block;background:#1c1f26;color:#9aa0a6;'
        f'border-radius:6px;padding:0.2rem 0.6rem;font-size:0.85rem;margin:0 0.4rem 0.4rem 0;">'
        f'{html.escape(s)}</span>'
        for s in schlagwoerter
    )

    return f"""<!doctype html>
<html lang="de">
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#0f1115;font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#e6e6e6;">
  <div style="max-width:600px;margin:0 auto;padding:2rem 1rem;">
    <p style="color:#9aa0a6;font-size:0.95rem;margin:0 0 0.5rem;">Neue Ausgabe, {wochentag}</p>
    <h1 style="font-size:1.5rem;line-height:1.3;margin:0 0 1.2rem;">{titel}</h1>
    <p style="text-align:center;margin:2rem 0;">
      <a href="{html.escape(website_url)}"
         style="display:inline-block;background:#7dd3fc;color:#0f1115;font-weight:600;
                text-decoration:none;padding:0.9rem 1.8rem;border-radius:8px;font-size:1rem;">
        Newsletter lesen
      </a>
    </p>
    <div style="margin:1.5rem 0;">{tags_html}</div>
    <p style="color:#6b7280;font-size:0.8rem;margin-top:3rem;border-top:1px solid #23262e;padding-top:1rem;">
      Abmelden? Antworte auf diese Mail mit dem Betreff: Abmelden
    </p>
  </div>
</body>
</html>
"""


def sende_benachrichtigung(newsletter_dict: dict, website_url: str) -> None:
    """Verschickt die Benachrichtigungsmail an alle Empfänger aus empfaenger.txt."""
    empfaenger = _lade_empfaenger()
    if not empfaenger:
        return

    gmail_adresse = os.getenv("GMAIL_ADDRESS")
    gmail_passwort = os.getenv("GMAIL_APP_PASSWORD")
    if not gmail_adresse or not gmail_passwort:
        print("[WARNUNG] GMAIL_ADDRESS/GMAIL_APP_PASSWORD nicht gesetzt, Benachrichtigung wird übersprungen.")
        return

    datum = date.fromisoformat(newsletter_dict["datum"])
    betreff = _betreff(datum)
    inhalt_html = _html_inhalt(newsletter_dict, website_url)

    kontext = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, context=kontext) as server:
        server.login(gmail_adresse, gmail_passwort)
        for empfang in empfaenger:
            nachricht = EmailMessage()
            nachricht["Subject"] = betreff
            nachricht["From"] = gmail_adresse
            nachricht["To"] = empfang
            nachricht.set_content(
                f"{newsletter_dict.get('titel', '')}\n\nNewsletter lesen: {website_url}\n\n"
                "Abmelden? Antworte auf diese Mail mit dem Betreff: Abmelden"
            )
            nachricht.add_alternative(inhalt_html, subtype="html")
            server.send_message(nachricht)

    print(f"Benachrichtigung an {len(empfaenger)} Empfänger verschickt.")


def _test_newsletter() -> dict:
    return {
        "modus": "deep-dive",
        "datum": date.today().isoformat(),
        "titel": "KI-Newsletter Deep-Dive, Testausgabe",
        "schlagwoerter": ["Reasoning", "KI-Agenten", "Regulierung"],
    }


def main() -> None:
    newsletter = _test_newsletter()
    website_url = f"https://scheiblenicolas.github.io/ki-newsletter/ausgaben/{newsletter['datum']}.html"
    sende_benachrichtigung(newsletter, website_url)


if __name__ == "__main__":
    main()
