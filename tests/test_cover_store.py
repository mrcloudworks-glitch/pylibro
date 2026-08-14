from cover_store import CoverStore


def test_defaults_to_no_override(tmp_path) -> None:
    store = CoverStore(tmp_path / "cover_overrides.json")
    store.load()
    assert store.get("book-1") is None


def test_set_get_clear(tmp_path) -> None:
    store = CoverStore(tmp_path / "cover_overrides.json")
    store.load()
    store.set("book-1", "images/cover.png")
    assert store.get("book-1") == "images/cover.png"
    store.clear("book-1")
    assert store.get("book-1") is None


def test_set_replaces_previous(tmp_path) -> None:
    store = CoverStore(tmp_path / "cover_overrides.json")
    store.load()
    store.set("book-1", "a.png")
    store.set("book-1", "b.png")
    assert store.get("book-1") == "b.png"


def test_persists_and_reloads(tmp_path) -> None:
    path = tmp_path / "cover_overrides.json"
    first = CoverStore(path)
    first.load()
    first.set("book-1", "images/cover.png")
    first.set("book-2", "back.png")
    first.save()

    second = CoverStore(path)
    second.load()
    assert second.get("book-1") == "images/cover.png"
    assert second.get("book-2") == "back.png"


def test_clear_does_not_affect_other_books(tmp_path) -> None:
    store = CoverStore(tmp_path / "cover_overrides.json")
    store.load()
    store.set("book-1", "a.png")
    store.set("book-2", "b.png")
    store.clear("book-1")
    assert store.get("book-1") is None
    assert store.get("book-2") == "b.png"


def test_load_ignores_missing_file(tmp_path) -> None:
    store = CoverStore(tmp_path / "cover_overrides.json")
    store.load()
    assert store.get("any") is None


def test_load_ignores_corrupt_file(tmp_path) -> None:
    path = tmp_path / "cover_overrides.json"
    path.write_text("not json {{{", "utf-8")
    store = CoverStore(path)
    store.load()
    assert store.get("any") is None
