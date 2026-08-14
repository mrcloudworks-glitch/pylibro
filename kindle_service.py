"""SMTP delivery service for sending EPUB files to Kindle."""

from __future__ import annotations

import os
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
from pathlib import Path

from profile_store import ProfileValidationError, normalize_kindle_email

MAX_KINDLE_ATTACHMENT_BYTES = 50 * 1024 * 1024


class KindleDeliveryError(RuntimeError):
    """A safe, user-facing Kindle delivery failure."""


class KindleConfigurationError(KindleDeliveryError):
    """Raised when outbound SMTP is not configured correctly."""


class KindleFileError(KindleDeliveryError):
    """Raised when the selected file cannot be sent to Kindle."""


def _environment_integer(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return 0


def _environment_boolean(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


@dataclass(frozen=True, slots=True)
class SMTPSettings:
    """Outbound SMTP configuration loaded from environment variables."""

    host: str
    port: int
    sender: str
    username: str = ""
    password: str = field(default="", repr=False)
    starttls: bool = True
    use_ssl: bool = False
    timeout: int = 30

    @classmethod
    def from_environment(cls) -> SMTPSettings:
        return cls(
            host=os.getenv("PYLIBRO_SMTP_HOST", "").strip(),
            port=_environment_integer("PYLIBRO_SMTP_PORT", 587),
            sender=os.getenv("PYLIBRO_SMTP_FROM", "").strip(),
            username=os.getenv("PYLIBRO_SMTP_USERNAME", "").strip(),
            password=os.getenv("PYLIBRO_SMTP_PASSWORD", ""),
            starttls=_environment_boolean("PYLIBRO_SMTP_STARTTLS", True),
            use_ssl=_environment_boolean("PYLIBRO_SMTP_SSL", False),
            timeout=_environment_integer("PYLIBRO_SMTP_TIMEOUT", 30),
        )

    @property
    def sender_address(self) -> str:
        return parseaddr(self.sender)[1]

    def validate(self) -> None:
        if not self.host:
            raise KindleConfigurationError("Kindle delivery is not configured: set PYLIBRO_SMTP_HOST.")
        if not 1 <= self.port <= 65535:
            raise KindleConfigurationError("Kindle delivery is not configured: PYLIBRO_SMTP_PORT is invalid.")
        if not self.sender_address or "\n" in self.sender or "\r" in self.sender:
            raise KindleConfigurationError("Kindle delivery is not configured: set a valid PYLIBRO_SMTP_FROM address.")
        if self.use_ssl and self.starttls:
            raise KindleConfigurationError("Kindle delivery cannot enable both SMTP SSL and STARTTLS.")
        if bool(self.username) != bool(self.password):
            raise KindleConfigurationError(
                "Kindle delivery is not configured: both SMTP username and password are required for login."
            )
        if not 1 <= self.timeout <= 300:
            raise KindleConfigurationError("Kindle delivery is not configured: PYLIBRO_SMTP_TIMEOUT is invalid.")


class KindleDeliveryService:
    """Compose an EPUB email and submit it to an SMTP server."""

    def __init__(self, settings: SMTPSettings) -> None:
        self.settings = settings

    def send_epub(self, kindle_email: str, epub_path: str | Path, book_title: str) -> None:
        """Send one EPUB and return after the SMTP server accepts it."""

        self.settings.validate()
        try:
            recipient = normalize_kindle_email(kindle_email, allow_empty=False)
        except ProfileValidationError as exc:
            raise KindleDeliveryError(str(exc)) from exc

        try:
            path = Path(epub_path).resolve()
            file_size = path.stat().st_size
        except (OSError, RuntimeError) as exc:
            raise KindleFileError("The selected EPUB is no longer available.") from exc
        if not path.is_file() or path.suffix.casefold() != ".epub":
            raise KindleFileError("The selected EPUB is no longer available.")
        if file_size >= MAX_KINDLE_ATTACHMENT_BYTES:
            raise KindleFileError("Send to Kindle requires an EPUB smaller than 50 MB.")

        safe_title = " ".join(book_title.split())[:160] or path.stem
        message = EmailMessage()
        message["From"] = self.settings.sender
        message["To"] = recipient
        message["Date"] = formatdate(localtime=False)
        message["Message-ID"] = make_msgid(domain=self.settings.sender_address.rsplit("@", 1)[-1])
        message["Subject"] = f"PyLibro · {safe_title}"
        message.set_content(
            f"PyLibro attached “{safe_title}” for delivery to your Kindle.\n\n"
            "Amazon will process the EPUB and may send a separate delivery status email."
        )
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise KindleFileError("The selected EPUB could not be read.") from exc
        message.add_attachment(
            content,
            maintype="application",
            subtype="epub+zip",
            filename=path.name,
        )

        try:
            if self.settings.use_ssl:
                with smtplib.SMTP_SSL(
                    self.settings.host,
                    self.settings.port,
                    timeout=self.settings.timeout,
                    context=ssl.create_default_context(),
                ) as smtp:
                    self._authenticate_and_send(smtp, message)
            else:
                with smtplib.SMTP(self.settings.host, self.settings.port, timeout=self.settings.timeout) as smtp:
                    smtp.ehlo()
                    if self.settings.starttls:
                        smtp.starttls(context=ssl.create_default_context())
                        smtp.ehlo()
                    self._authenticate_and_send(smtp, message)
        except (OSError, smtplib.SMTPException) as exc:
            raise KindleDeliveryError(
                "The mail server could not accept this EPUB. Check the SMTP settings and try again."
            ) from exc

    def _authenticate_and_send(self, smtp: smtplib.SMTP, message: EmailMessage) -> None:
        if self.settings.username:
            smtp.login(self.settings.username, self.settings.password)
        smtp.send_message(message)
