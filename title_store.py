"""Web-app-only title overrides: custom library names shown instead of a book's EPUB title."""

from __future__ import annotations

import json
import threading
from pathlib import Path


class TitleStore:
    """Thread-safe JSON store mapping book ids to a custom library title.

    Overrides change the title shown in the web app only; the original EPUB is
    never modified.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._data: dict[str, str] = {}

    def load(self) -> None:
        with self._lock:
            try:
                if self.path.exists():
                    raw = json.loads(self.path.read_text("utf-8"))
                    self._data = raw if isinstance(raw, dict) else {}
            except (OSError, ValueError):
                self._data = {}

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, indent=2) + "\n", "utf-8")
            tmp.replace(self.path)

    def get(self, book_id: str) -> str | None:
        with self._lock:
            return self._data.get(book_id)

    def set(self, book_id: str, title: str) -> None:
        with self._lock:
            self._data[book_id] = title

    def clear(self, book_id: str) -> None:
        with self._lock:
            self._data.pop(book_id, None)
