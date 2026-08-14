from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import app as app_module
from kindle_service import (
    MAX_KINDLE_ATTACHMENT_BYTES,
    KindleConfigurationError,
    KindleDeliveryError,
    KindleFileError,
)

client = TestClient(app_module.app)


def fake_book(tmp_path: Path, *, file_size: int = 4) -> SimpleNamespace:
    path = tmp_path / "trusted.epub"
    path.write_bytes(b"epub")
    return SimpleNamespace(
        id="0123456789abcdef",
        title="Trusted Book",
        file_path=path,
        file_size=file_size,
    )


def test_endpoint_rejects_untrusted_book_id_without_delivery(monkeypatch) -> None:
    delivery = MagicMock()
    monkeypatch.setattr(app_module.kindle_delivery, "send_epub", delivery)

    response = client.post("/api/books/not-a-trusted-id/send-to-kindle")

    assert response.status_code == 404
    assert response.json() == {"detail": "Book not found"}
    delivery.assert_not_called()


def test_endpoint_requires_configured_local_profile(tmp_path: Path, monkeypatch) -> None:
    book = fake_book(tmp_path)
    delivery = MagicMock()
    monkeypatch.setattr(app_module.library, "find_by_id", lambda _book_id: book)
    monkeypatch.setattr(app_module.profile_store, "get_profile", lambda: SimpleNamespace(kindle_email=""))
    monkeypatch.setattr(app_module.kindle_delivery, "send_epub", delivery)

    response = client.post(f"/api/books/{book.id}/send-to-kindle")

    assert response.status_code == 409
    delivery.assert_not_called()


def test_endpoint_rejects_oversized_book_before_delivery(tmp_path: Path, monkeypatch) -> None:
    book = fake_book(tmp_path, file_size=MAX_KINDLE_ATTACHMENT_BYTES)
    delivery = MagicMock()
    monkeypatch.setattr(app_module.library, "find_by_id", lambda _book_id: book)
    monkeypatch.setattr(
        app_module.profile_store,
        "get_profile",
        lambda: SimpleNamespace(kindle_email="reader@kindle.com"),
    )
    monkeypatch.setattr(app_module.kindle_delivery, "send_epub", delivery)

    response = client.post(f"/api/books/{book.id}/send-to-kindle")

    assert response.status_code == 413
    delivery.assert_not_called()


def test_endpoint_dispatches_only_resolved_library_book(tmp_path: Path, monkeypatch) -> None:
    book = fake_book(tmp_path)
    delivery = MagicMock()
    monkeypatch.setattr(app_module.library, "find_by_id", lambda _book_id: book)
    monkeypatch.setattr(
        app_module.profile_store,
        "get_profile",
        lambda: SimpleNamespace(kindle_email="reader@kindle.com"),
    )
    monkeypatch.setattr(app_module.kindle_delivery, "send_epub", delivery)

    response = client.post(f"/api/books/{book.id}/send-to-kindle")

    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    delivery.assert_called_once_with("reader@kindle.com", book.file_path, "Trusted Book")


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (KindleConfigurationError("SMTP is not configured."), 503),
        (KindleFileError("The selected EPUB is no longer available."), 422),
        (KindleDeliveryError("The mail server could not accept this EPUB."), 502),
    ],
)
def test_endpoint_maps_safe_delivery_failures(
    tmp_path: Path,
    monkeypatch,
    error: KindleDeliveryError,
    expected_status: int,
) -> None:
    book = fake_book(tmp_path)
    monkeypatch.setattr(app_module.library, "find_by_id", lambda _book_id: book)
    monkeypatch.setattr(
        app_module.profile_store,
        "get_profile",
        lambda: SimpleNamespace(kindle_email="reader@kindle.com"),
    )
    monkeypatch.setattr(
        app_module.kindle_delivery,
        "send_epub",
        MagicMock(side_effect=error),
    )

    response = client.post(f"/api/books/{book.id}/send-to-kindle")

    assert response.status_code == expected_status
    assert response.json() == {"detail": str(error)}
