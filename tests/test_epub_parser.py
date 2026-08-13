from io import BytesIO
from pathlib import Path

from ebooklib import epub
from PIL import Image

from epub_parser import EpubError, EpubLibrary


def make_epub(path: Path) -> None:
    image_buffer = BytesIO()
    Image.new("RGB", (80, 120), "#d7ff63").save(image_buffer, "PNG")

    book = epub.EpubBook()
    book.set_identifier("pylibro-test")
    book.set_title("The Test Book")
    book.set_language("en")
    book.add_author("Ada Reader")
    cover = epub.EpubItem(
        uid="cover-image", file_name="images/cover.png", media_type="image/png", content=image_buffer.getvalue()
    )
    book.add_item(cover)
    book.add_metadata("OPF", "meta", "", {"name": "cover", "content": "cover-image"})

    chapter = epub.EpubHtml(title="A Beginning", file_name="text/chapter.xhtml", lang="en")
    chapter.content = '<html><body><h1>A Beginning</h1><p>Hello <strong>reader</strong>.</p><img src="../images/cover.png"><script>alert(1)</script></body></html>'
    book.add_item(chapter)
    book.toc = (chapter,)
    book.spine = ["nav", chapter]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    epub.write_epub(path, book)


def test_inspect_chapters_and_images(tmp_path: Path) -> None:
    books = tmp_path / "books"
    books.mkdir()
    epub_path = books / "test.epub"
    make_epub(epub_path)
    library = EpubLibrary(books, tmp_path / "cache")

    info = library.inspect(epub_path)
    assert info.title == "The Test Book"
    assert info.author == "Ada Reader"
    assert info.chapter_count == 1
    assert info.cover_path.exists()

    chapters = library.get_chapters(epub_path)
    assert len(chapters) == 1
    assert chapters[0].title == "A Beginning"
    assert "<script" not in chapters[0].html
    assert f"/cache/media/{info.id}/images/cover.png" in chapters[0].html

    images = library.extract_images(epub_path)
    assert len(images) == 1
    assert images[0].width == 80
    assert images[0].height == 120


def test_upload_validation_and_duplicate_names(tmp_path: Path) -> None:
    source = tmp_path / "source.epub"
    make_epub(source)
    library = EpubLibrary(tmp_path / "books", tmp_path / "cache")

    first = library.save_upload("../My:Book.epub", source.read_bytes())
    second = library.save_upload("../My:Book.epub", source.read_bytes())
    assert first.file_name == "My_Book.epub"
    assert second.file_name == "My_Book (2).epub"


def test_rejects_non_epub(tmp_path: Path) -> None:
    library = EpubLibrary(tmp_path / "books", tmp_path / "cache")
    try:
        library.save_upload("notes.txt", b"hello")
    except EpubError as error:
        assert "not an EPUB" in str(error)
    else:
        raise AssertionError("Expected EpubError")
