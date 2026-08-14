"""Persistent local user profile settings for PyLibro.

PyLibro is currently a single-user, local-first application. The schema therefore
stores one profile row while keeping the model and repository boundary ready for
a future authenticated multi-user deployment.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

KINDLE_LOCAL_ATOM = r"[A-Z0-9!#$%&'*+/=?^_`{|}~-]+"
KINDLE_EMAIL_PATTERN = re.compile(rf"{KINDLE_LOCAL_ATOM}(?:\.{KINDLE_LOCAL_ATOM})*@kindle\.com", re.IGNORECASE)


class ProfileValidationError(ValueError):
    """Raised when a profile value is not valid."""


@dataclass(frozen=True, slots=True)
class UserProfile:
    """The local PyLibro user profile."""

    id: int
    kindle_email: str
    updated_at: str


def normalize_kindle_email(value: str | None, *, allow_empty: bool = True) -> str:
    """Normalize and validate a Send to Kindle address."""

    email = (value or "").strip().casefold()
    if not email and allow_empty:
        return ""
    if len(email) > 254 or not KINDLE_EMAIL_PATTERN.fullmatch(email):
        raise ProfileValidationError("Enter a valid @kindle.com email address.")
    return email


class ProfileStore:
    """SQLite-backed repository for the app's singleton local profile."""

    PROFILE_ID = 1

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path).expanduser().resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_schema()

    def get_profile(self) -> UserProfile:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, kindle_email, updated_at FROM user_profiles WHERE id = ?",
                (self.PROFILE_ID,),
            ).fetchone()
        if row is None:  # Defensive fallback if the database was edited externally.
            self._initialize_schema()
            return self.get_profile()
        return UserProfile(id=row["id"], kindle_email=row["kindle_email"], updated_at=row["updated_at"])

    def update_kindle_email(self, value: str | None) -> UserProfile:
        email = normalize_kindle_email(value)
        updated_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute(
                "UPDATE user_profiles SET kindle_email = ?, updated_at = ? WHERE id = ?",
                (email, updated_at, self.PROFILE_ID),
            )
        return UserProfile(id=self.PROFILE_ID, kindle_email=email, updated_at=updated_at)

    def _initialize_schema(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS user_profiles (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    kindle_email TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO user_profiles (id, kindle_email, updated_at) VALUES (?, '', ?)",
                (self.PROFILE_ID, now),
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection
