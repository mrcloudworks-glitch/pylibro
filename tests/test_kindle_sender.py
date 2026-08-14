from pathlib import Path
from unittest import mock

import kindle_sender
from kindle_sender import KindleConfigError, build_message, is_configured, send_book

CONFIG = {
    "PYLIBRO_KINDLE_EMAIL": "test@kindle.com",
    "PYLIBRO_KINDLE_SMTP_HOST": "smtp.example.com",
    "PYLIBRO_KINDLE_SMTP_USER": "me@example.com",
    "PYLIBRO_KINDLE_SMTP_PASSWORD": "hunter2",
}


def apply_config(monkeypatch) -> None:
    for name, value in CONFIG.items():
        monkeypatch.setenv(name, value)


def clear_config(monkeypatch) -> None:
    for name in CONFIG:
        monkeypatch.delenv(name, raising=False)


def test_not_configured_by_default(monkeypatch) -> None:
    clear_config(monkeypatch)
    assert not is_configured()


def test_configured_when_all_settings_present(monkeypatch) -> None:
    apply_config(monkeypatch)
    assert is_configured()
    assert kindle_sender.recipient_email() == "test@kindle.com"


def test_build_message_attaches_epub(tmp_path: Path, monkeypatch) -> None:
    apply_config(monkeypatch)
    book = tmp_path / "book.epub"
    book.write_bytes(b"PK\x03\x04test")
    message = build_message(book, "My Book", "test@kindle.com")
    assert message["To"] == "test@kindle.com"
    assert message["From"] == "me@example.com"
    assert message["Subject"] == "My Book"
    attachment = next(message.iter_attachments())
    assert attachment.get_filename() == "book.epub"
    assert attachment.get_content_type() == "application/epub+zip"
    assert attachment.get_payload(decode=True) == b"PK\x03\x04test"


def test_send_book_uses_smtp_starttls(tmp_path: Path, monkeypatch) -> None:
    apply_config(monkeypatch)
    book = tmp_path / "book.epub"
    book.write_bytes(b"PK\x03\x04test")
    server = mock.MagicMock()
    server.__enter__.return_value = server
    with mock.patch.object(kindle_sender.smtplib, "SMTP", return_value=server) as smtp:
        send_book(book, "My Book")
    smtp.assert_called_once_with("smtp.example.com", 587, timeout=30)
    server.starttls.assert_called_once()
    server.login.assert_called_once_with("me@example.com", "hunter2")
    server.send_message.assert_called_once()
    (message,) = server.send_message.call_args.args
    assert message["To"] == "test@kindle.com"


def test_send_book_uses_smtp_ssl_on_port_465(tmp_path: Path, monkeypatch) -> None:
    apply_config(monkeypatch)
    monkeypatch.setenv("PYLIBRO_KINDLE_SMTP_PORT", "465")
    book = tmp_path / "book.epub"
    book.write_bytes(b"PK\x03\x04test")
    server = mock.MagicMock()
    server.__enter__.return_value = server
    with mock.patch.object(kindle_sender.smtplib, "SMTP_SSL", return_value=server) as smtp_ssl:
        send_book(book, "My Book")
    smtp_ssl.assert_called_once_with("smtp.example.com", 465, timeout=30)
    server.login.assert_called_once()
    server.send_message.assert_called_once()


def test_send_book_raises_when_not_configured(tmp_path: Path, monkeypatch) -> None:
    clear_config(monkeypatch)
    book = tmp_path / "book.epub"
    book.write_bytes(b"PK\x03\x04test")
    try:
        send_book(book, "My Book")
    except KindleConfigError as error:
        assert "PYLIBRO_KINDLE_EMAIL" in str(error)
        assert "PYLIBRO_KINDLE_SMTP_HOST" in str(error)
    else:
        raise AssertionError("Expected KindleConfigError")
