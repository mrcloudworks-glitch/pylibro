from title_store import TitleStore


def test_defaults_to_no_override(tmp_path) -> None:
    store = TitleStore(tmp_path / "title_overrides.json")
    store.load()
    assert store.get("book-1") is None


def test_set_get_clear(tmp_path) -> None:
    store = TitleStore(tmp_path / "title_overrides.json")
    store.load()
    store.set("book-1", "My Custom Title")
    assert store.get("book-1") == "My Custom Title"
    store.clear("book-1")
    assert store.get("book-1") is None


def test_set_replaces_previous(tmp_path) -> None:
    store = TitleStore(tmp_path / "title_overrides.json")
    store.load()
    store.set("book-1", "First")
    store.set("book-1", "Second")
    assert store.get("book-1") == "Second"


def test_persists_and_reloads(tmp_path) -> None:
    path = tmp_path / "title_overrides.json"
    first = TitleStore(path)
    first.load()
    first.set("book-1", "Renamed Title")
    first.set("book-2", "Another")
    first.save()

    second = TitleStore(path)
    second.load()
    assert second.get("book-1") == "Renamed Title"
    assert second.get("book-2") == "Another"


def test_clear_does_not_affect_other_books(tmp_path) -> None:
    store = TitleStore(tmp_path / "title_overrides.json")
    store.load()
    store.set("book-1", "A")
    store.set("book-2", "B")
    store.clear("book-1")
    assert store.get("book-1") is None
    assert store.get("book-2") == "B"


def test_load_ignores_missing_file(tmp_path) -> None:
    store = TitleStore(tmp_path / "title_overrides.json")
    store.load()
    assert store.get("any") is None


def test_load_ignores_corrupt_file(tmp_path) -> None:
    path = tmp_path / "title_overrides.json"
    path.write_text("not json {{{", "utf-8")
    store = TitleStore(path)
    store.load()
    assert store.get("any") is None
