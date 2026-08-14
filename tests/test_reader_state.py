from reader_state import ReaderState


def test_defaults_for_unknown_book(tmp_path) -> None:
    store = ReaderState(tmp_path / "progress.json")
    store.load()
    assert store.get("missing") == {"index": 0, "ratio": 0.0, "font": 19, "light": False}


def test_update_and_get_roundtrip(tmp_path) -> None:
    store = ReaderState(tmp_path / "progress.json")
    store.load()
    store.update("book-1", index=4, ratio=0.5, font=22, light=True)
    assert store.get("book-1") == {"index": 4, "ratio": 0.5, "font": 22, "light": True}


def test_partial_update_keeps_other_fields(tmp_path) -> None:
    store = ReaderState(tmp_path / "progress.json")
    store.load()
    store.update("book-1", index=2, font=20)
    store.update("book-1", index=3)
    state = store.get("book-1")
    assert state["index"] == 3
    assert state["font"] == 20
    assert state["ratio"] == 0.0
    assert state["light"] is False


def test_persists_and_reloads(tmp_path) -> None:
    path = tmp_path / "progress.json"
    first = ReaderState(path)
    first.load()
    first.update("book-1", index=7, ratio=0.25, font=21, light=True)
    first.save()

    second = ReaderState(path)
    second.load()
    assert second.get("book-1") == {"index": 7, "ratio": 0.25, "font": 21, "light": True}


def test_load_ignores_missing_file(tmp_path) -> None:
    store = ReaderState(tmp_path / "progress.json")
    store.load()
    assert store.get("any") == {"index": 0, "ratio": 0.0, "font": 19, "light": False}


def test_load_ignores_corrupt_file(tmp_path) -> None:
    path = tmp_path / "progress.json"
    path.write_text("not json {{{", "utf-8")
    store = ReaderState(path)
    store.load()
    assert store.get("any") == {"index": 0, "ratio": 0.0, "font": 19, "light": False}


def test_unknown_fields_are_ignored(tmp_path) -> None:
    store = ReaderState(tmp_path / "progress.json")
    store.load()
    store.update("book-1", index=1, nonsense="ignored")
    assert "nonsense" not in store.get("book-1")
    assert store.get("book-1")["index"] == 1
