"""Email EPUBs to a Kindle address over SMTP.

Amazon no longer offers an official Send-to-Kindle API, so PyLibro uses the
classic personal-document route: the EPUB is mailed as an attachment to the
device's @kindle.com address from a sender email that is whitelisted in the
recipient's Amazon account.

Configuration is read from the environment at call time so deployments can
change settings without restarting:

- ``PYLIBRO_KINDLE_EMAIL``       target @kindle.com address
- ``PYLIBRO_KINDLE_SMTP_HOST``   SMTP relay, e.g. smtp.gmail.com
- ``PYLIBRO_KINDLE_SMTP_PORT``   SMTP port, 587 (STARTTLS) or 465 (implicit TLS)
- ``PYLIBRO_KINDLE_SMTP_USER``   authenticated sender address
- ``PYLIBRO_KINDLE_SMTP_PASSWORD`` sender app password
"""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

CONFIG_MISSING = "Send to Kindle is not configured — set {}."


class KindleConfigError(ValueError):
    """Raised when a send is requested but the SMTP settings are incomplete."""


def _settings() -> dict[str, str | int]:
    return {
        "recipient": os.getenv("PYLIBRO_KINDLE_EMAIL", "").strip(),
        "smtp_host": os.getenv("PYLIBRO_KINDLE_SMTP_HOST", "").strip(),
        "smtp_port": int(os.getenv("PYLIBRO_KINDLE_SMTP_PORT", "587")),
        "smtp_user": os.getenv("PYLIBRO_KINDLE_SMTP_USER", "").strip(),
        "smtp_password": os.getenv("PYLIBRO_KINDLE_SMTP_PASSWORD", ""),
    }


def is_configured() -> bool:
    settings = _settings()
    return bool(
        settings["recipient"]
        and settings["smtp_host"]
        and settings["smtp_user"]
        and settings["smtp_password"]
    )


def recipient_email() -> str:
    return str(_settings()["recipient"])


def build_message(file_path: str | Path, title: str, recipient: str) -> EmailMessage:
    """Build the MIME message without touching the network, for easy testing."""
    path = Path(file_path)
    settings = _settings()
    message = EmailMessage()
    message["From"] = str(settings["smtp_user"])
    message["To"] = recipient
    message["Subject"] = title
    message.set_content(f"Sent from PyLibro.\n\nYour copy of “{title}” is attached as an EPUB.")
    message.add_attachment(path.read_bytes(), maintype="application", subtype="epub+zip", filename=path.name)
    return message


def _require_configured() -> dict[str, str | int]:
    settings = _settings()
    fields = (
        ("PYLIBRO_KINDLE_EMAIL", settings["recipient"]),
        ("PYLIBRO_KINDLE_SMTP_HOST", settings["smtp_host"]),
        ("PYLIBRO_KINDLE_SMTP_USER", settings["smtp_user"]),
        ("PYLIBRO_KINDLE_SMTP_PASSWORD", settings["smtp_password"]),
    )
    missing = ", ".join(name for name, value in fields if not value)
    if missing:
        raise KindleConfigError(CONFIG_MISSING.format(missing))
    return settings


def send_book(file_path: str | Path, title: str, recipient: str | None = None) -> None:
    """Email ``file_path`` (an EPUB) to the Kindle address via SMTP."""
    settings = _require_configured()
    if not recipient:
        recipient = str(settings["recipient"])
    message = build_message(file_path, title, recipient)
    host = str(settings["smtp_host"])
    port = int(settings["smtp_port"])
    user = str(settings["smtp_user"])
    password = str(settings["smtp_password"])
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=30) as server:
            server.login(user, password)
            server.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(user, password)
            server.send_message(message)
