from pathlib import Path

import pytest

from profile_store import ProfileStore, ProfileValidationError, normalize_kindle_email


def test_profile_store_persists_kindle_email(tmp_path: Path) -> None:
    database = tmp_path / "data" / "pylibro.sqlite3"
    store = ProfileStore(database)

    assert store.get_profile().kindle_email == ""
    profile = store.update_kindle_email("  My.Reader@Kindle.com ")

    assert profile.kindle_email == "my.reader@kindle.com"
    assert ProfileStore(database).get_profile().kindle_email == "my.reader@kindle.com"

    store.update_kindle_email("")
    assert ProfileStore(database).get_profile().kindle_email == ""


def test_kindle_email_validation() -> None:
    assert normalize_kindle_email("") == ""
    assert normalize_kindle_email("reader+books@kindle.com") == "reader+books@kindle.com"

    for invalid_email in (
        "reader@example.com",
        "reader@kindle.com.example",
        "reader@subdomain.kindle.com",
        ".reader@kindle.com",
        "reader..books@kindle.com",
        "reader@kindle.co",
    ):
        with pytest.raises(ProfileValidationError, match="@kindle.com"):
            normalize_kindle_email(invalid_email)
