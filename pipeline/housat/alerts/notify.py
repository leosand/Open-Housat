"""Alertes gratuites : ntfy.sh (push) + SMTP (courriel).
Free alerting: ntfy.sh push + SMTP email. WhatsApp/Twilio prevu phase 2 (canal prefere diaspora).

NOTE V&V (2026-09-15) : module actuellement NON APPELE par le worker (alertes in-app
en MVP) ; sera rebranche en phase 2. Les gardes ci-dessous empechent un blocage
worker si le SMTP est injoignable ou mal configure.
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

import httpx

from housat.config import settings

logger = logging.getLogger(__name__)

# Garde-fou V&V : timeout borne pour ne jamais suspendre le worker sur un SMTP fige.
SMTP_TIMEOUT_S = 10


def send_ntfy(title: str, message: str, *, priority: str = "high") -> bool:
    """Push instantane via ntfy.sh — 0 $, aucun compte requis pour publier."""
    try:
        r = httpx.post(
            f"https://ntfy.sh/{settings.ntfy_topic}",
            content=message.encode("utf-8"),
            headers={"Title": title, "Priority": priority, "Tags": "house_with_garden,satellite"},
            timeout=10,
        )
        r.raise_for_status()
        return True
    except httpx.HTTPError as exc:
        logger.error("ntfy a echoue / ntfy failed: %s", exc)
        return False


def send_email(to: str, subject: str, body: str) -> bool:
    if not settings.smtp_host:
        logger.info("SMTP non configure — courriel ignore: %s", subject)
        return False
    if not to or "@" not in to:  # garde anti-destination invalide (V&V)
        logger.warning("destinataire courriel invalide, envoi ignore: %r", to)
        return False
    msg = EmailMessage()
    msg["From"] = settings.alert_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port,
                          timeout=SMTP_TIMEOUT_S) as s:
            s.starttls()
            if settings.smtp_user:
                s.login(settings.smtp_user, settings.smtp_password)
            s.send_message(msg)
        return True
    except (OSError, smtplib.SMTPException) as exc:  # ne jamais suspendre le pipeline
        logger.error("courriel en echec (trace, non bloquant): %s", exc)
        return False


def alert_milestone(owner_email: str, site_name: str, milestone_label: str, report_url: str = "") -> None:
    """Alerte de franchissement de jalon — FR par defaut (clientele diaspora francophone d'abord)."""
    title = f"Housat — {site_name} : {milestone_label}"
    body = (
        f"Bonjour,\\n\\nNouvelle etape detectee par satellite sur votre chantier « {site_name} » : "
        f"{milestone_label}.\\n{('Rapport : ' + report_url) if report_url else ''}\\n\\n— Housat"
    )
    send_ntfy(title, body)
    send_email(owner_email, title, body)
