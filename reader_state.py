"""Persistent per-book reading progress for the PyLibro reader."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

_FIELDS = ("index", "ratio", "font", "light")


def _defaults() -> dict[str, Any]:
    return {"index": 0, "ratio": 0.0, "font": 19, "light": False}


class ReaderState:
    """Thread-safe JSON store mapping book ids to their last reading position."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._data: dict[str, dict[str, Any]] = {}

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

    def get(self, book_id: str) -> dict[str, Any]:
        with self._lock:
            entry = self._data.get(book_id, {})
        state = _defaults()
        state.update({key: entry[key] for key in _FIELDS if key in entry})
        return state

    def update(self, book_id: str, **fields: Any) -> None:
        with self._lock:
            entry = self._data.setdefault(book_id, _defaults())
            for key, value in fields.items():
                if key in _FIELDS and value is not None:
                    entry[key] = value
