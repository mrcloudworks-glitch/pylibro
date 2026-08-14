import smtplib
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kindle_service import (
    MAX_KINDLE_ATTACHMENT_BYTES,
    KindleConfigurationError,
    KindleDeliveryError,
    KindleDeliveryService,
    KindleFileError,
    SMTPSettings,
)


def smtp_settings(**overrides) -> SMTPSettings:
    values = {
        "host": "smtp.example.com",
        "port": 587,
        "sender": "PyLibro Books <books@example.com>",
        "username": "smtp-user",
        "password": "secret",
        "starttls": True,
        "use_ssl": False,
        "timeout": 12,
    }
    values.update(overrides)
    return SMTPSettings(**values)


def test_sends_epub_with_expected_headers_and_attachment(tmp_path: Path) -> None:
    epub_path = tmp_path / "story.epub"
    epub_path.write_bytes(b"epub test bytes")
    smtp = MagicMock()
    smtp.__enter__.return_value = smtp

    with patch("kindle_service.smtplib.SMTP", return_value=smtp) as smtp_class:
        KindleDeliveryService(smtp_settings()).send_epub(
            "Reader@Kindle.com",
            epub_path,
            "A Story\nWith Spaces",
        )

    smtp_class.assert_called_once_with("smtp.example.com", 587, timeout=12)
    smtp.starttls.assert_called_once()
    smtp.login.assert_called_once_with("smtp-user", "secret")
    message = smtp.send_message.call_args.args[0]
    assert isinstance(message, EmailMessage)
    assert message["From"] == "PyLibro Books <books@example.com>"
    assert message["To"] == "reader@kindle.com"
    assert message["Date"]
    assert message["Message-ID"].endswith("@example.com>")
    assert "A Story With Spaces" in message["Subject"]
    attachment = next(message.iter_attachments())
    assert attachment.get_content_type() == "application/epub+zip"
    assert attachment.get_filename() == "story.epub"
    assert attachment.get_payload(decode=True) == b"epub test bytes"


def test_rejects_epub_at_kindle_size_limit(tmp_path: Path) -> None:
    epub_path = tmp_path / "large.epub"
    with epub_path.open("wb") as output:
        output.truncate(MAX_KINDLE_ATTACHMENT_BYTES)

    with pytest.raises(KindleFileError, match="smaller than 50 MB"):
        KindleDeliveryService(smtp_settings()).send_epub("reader@kindle.com", epub_path, "Large Book")


def test_rejects_missing_smtp_configuration(tmp_path: Path) -> None:
    epub_path = tmp_path / "story.epub"
    epub_path.write_bytes(b"epub")

    with pytest.raises(KindleConfigurationError, match="PYLIBRO_SMTP_HOST"):
        KindleDeliveryService(smtp_settings(host="")).send_epub("reader@kindle.com", epub_path, "Story")


def test_converts_smtp_failure_to_safe_delivery_error(tmp_path: Path) -> None:
    epub_path = tmp_path / "story.epub"
    epub_path.write_bytes(b"epub")
    smtp_error = smtplib.SMTPConnectError(421, b"internal relay details")

    with (
        patch("kindle_service.smtplib.SMTP", side_effect=smtp_error),
        pytest.raises(KindleDeliveryError, match="mail server could not accept") as error,
    ):
        KindleDeliveryService(smtp_settings()).send_epub("reader@kindle.com", epub_path, "Story")

    assert "internal relay details" not in str(error.value)
