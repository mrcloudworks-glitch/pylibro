"""EPUB parsing and library management for PyLibro.

The UI deliberately delegates every EPUB-specific operation to this module.  This
keeps ebook parsing testable and makes it possible to replace NiceGUI without
rewriting the storage layer.
"""

from __future__ import annotations

import hashlib
import html
import io
import os
import posixpath
import re
import shutil
import tempfile
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote, urlparse

import bleach
import ebooklib
from bs4 import BeautifulSoup
from ebooklib import epub
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD_BYTES = int(os.getenv("PYLIBRO_MAX_UPLOAD_MB", "100")) * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = int(os.getenv("PYLIBRO_MAX_UNCOMPRESSED_MB", "1024")) * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 20_000


class EpubError(ValueError):
    """A user-facing error raised for an invalid or unreadable EPUB."""


@dataclass(frozen=True, slots=True)
class BookInfo:
    """Small, UI-ready representation of a book in the library."""

    id: str
    title: str
    author: str
    file_path: Path
    file_name: str
    file_size: int
    chapter_count: int
    cover_path: Path
    cover_url: str
    modified_at: datetime
    language: str = ""

    @property
    def file_size_display(self) -> str:
        return human_size(self.file_size)


@dataclass(frozen=True, slots=True)
class Chapter:
    id: str
    title: str
    html: str
    source_name: str


@dataclass(frozen=True, slots=True)
class ImageAsset:
    name: str
    media_type: str
    path: Path
    url: str
    width: int | None
    height: int | None
    size: int

    @property
    def size_display(self) -> str:
        return human_size(self.size)


ALLOWED_TAGS = {
    "a",
    "abbr",
    "b",
    "blockquote",
    "br",
    "caption",
    "cite",
    "code",
    "col",
    "colgroup",
    "dd",
    "del",
    "details",
    "dfn",
    "div",
    "dl",
    "dt",
    "em",
    "figcaption",
    "figure",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "i",
    "img",
    "ins",
    "kbd",
    "li",
    "mark",
    "ol",
    "p",
    "pre",
    "q",
    "rp",
    "rt",
    "ruby",
    "s",
    "samp",
    "small",
    "span",
    "strong",
    "sub",
    "summary",
    "sup",
    "table",
    "tbody",
    "td",
    "tfoot",
    "th",
    "thead",
    "tr",
    "u",
    "ul",
    "var",
}
ALLOWED_ATTRIBUTES = {
    "*": ["class", "dir", "id", "lang", "title"],
    "a": ["href", "name", "rel", "target"],
    "blockquote": ["cite"],
    "col": ["span", "width"],
    "colgroup": ["span", "width"],
    "img": ["alt", "height", "loading", "src", "width"],
    "ol": ["reversed", "start", "type"],
    "td": ["colspan", "rowspan"],
    "th": ["colspan", "rowspan", "scope"],
}


def human_size(value: int) -> str:
    size = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def _first_metadata(book: epub.EpubBook, namespace: str, key: str, fallback: str = "") -> str:
    values = book.get_metadata(namespace, key)
    if not values:
        return fallback
    value = values[0][0]
    return str(value).strip() or fallback


def _safe_archive_name(name: str) -> str | None:
    """Return a normalized archive path, or None for unsafe/empty paths."""

    decoded = unquote(urlparse(name).path).replace("\\", "/")
    normalized = posixpath.normpath(decoded).lstrip("/")
    if not normalized or normalized == "." or normalized == ".." or normalized.startswith("../"):
        return None
    parts = PurePosixPath(normalized).parts
    if any(part in {"", ".", ".."} for part in parts):
        return None
    return "/".join(parts)


def _stable_book_id(path: Path) -> str:
    stat = path.stat()
    fingerprint = f"{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}"
    return hashlib.sha256(fingerprint.encode()).hexdigest()[:16]


def _safe_upload_name(name: str) -> str:
    base = Path(name.replace("\\", "/")).name.strip()
    stem = re.sub(r"[^\w .()\-\[\]]+", "_", Path(base).stem, flags=re.UNICODE).strip(" ._")
    stem = stem[:140] or "untitled"
    return f"{stem}.epub"


class EpubLibrary:
    """Discover, validate and parse EPUB files from a designated directory."""

    def __init__(self, library_dir: str | Path = "books", cache_dir: str | Path = ".pylibro_cache") -> None:
        self.library_dir = Path(library_dir).expanduser().resolve()
        self.cache_dir = Path(cache_dir).expanduser().resolve()
        self.cover_dir = self.cache_dir / "covers"
        self.media_dir = self.cache_dir / "media"
        for directory in (self.library_dir, self.cover_dir, self.media_dir):
            directory.mkdir(parents=True, exist_ok=True)
        self.errors: list[tuple[str, str]] = []

    def discover(self) -> list[BookInfo]:
        """Scan the library, skipping bad books but retaining their error messages."""

        books: list[BookInfo] = []
        self.errors.clear()
        paths = sorted(self.library_dir.glob("*.epub"), key=lambda path: path.stat().st_mtime, reverse=True)
        for path in paths:
            try:
                books.append(self.inspect(path))
            except Exception as exc:  # one damaged book should never hide the rest
                self.errors.append((path.name, str(exc)))
        return books

    def inspect(self, path: str | Path) -> BookInfo:
        path = Path(path).resolve()
        self._assert_in_library(path)
        if not path.is_file() or path.suffix.lower() != ".epub":
            raise EpubError("Only .epub files can be opened.")

        try:
            book = epub.read_epub(str(path), options={"ignore_ncx": True})
        except Exception as exc:
            raise EpubError(f"Could not read EPUB: {exc}") from exc

        book_id = _stable_book_id(path)
        title = _first_metadata(book, "DC", "title", path.stem)
        author = _first_metadata(book, "DC", "creator", "Unknown author")
        language = _first_metadata(book, "DC", "language")
        cover_path = self._ensure_cover(book, book_id, title, author)
        chapter_count = len(list(self._document_items(book)))
        stat = path.stat()
        return BookInfo(
            id=book_id,
            title=title,
            author=author,
            file_path=path,
            file_name=path.name,
            file_size=stat.st_size,
            chapter_count=chapter_count,
            cover_path=cover_path,
            cover_url=f"/cache/covers/{quote(cover_path.name)}?v={stat.st_mtime_ns}",
            modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
            language=language,
        )

    def save_upload(self, original_name: str, data: bytes) -> BookInfo:
        """Validate upload bytes and atomically add them to the library."""

        if not original_name.lower().endswith(".epub"):
            raise EpubError("That file is not an EPUB. Please choose a .epub file.")
        if not data:
            raise EpubError("The uploaded file is empty.")
        if len(data) > MAX_UPLOAD_BYTES:
            raise EpubError(f"EPUBs are limited to {human_size(MAX_UPLOAD_BYTES)}.")

        self._validate_archive(data)
        filename = _safe_upload_name(original_name)
        destination = self._available_destination(filename)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.library_dir, suffix=".epub", delete=False) as handle:
                handle.write(data)
                temp_path = Path(handle.name)
            # Parsing catches malformed package manifests that a ZIP check cannot.
            try:
                epub.read_epub(str(temp_path), options={"ignore_ncx": True})
            except Exception as exc:
                raise EpubError(f"This EPUB appears to be damaged: {exc}") from exc
            temp_path.replace(destination)
            temp_path = None
            return self.inspect(destination)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    def get_chapters(self, path: str | Path) -> list[Chapter]:
        path = Path(path).resolve()
        self._assert_in_library(path)
        book = self._read(path)
        book_id = _stable_book_id(path)
        self._extract_media_items(book, book_id)

        chapters: list[Chapter] = []
        for index, item in enumerate(self._document_items(book), start=1):
            raw = item.get_content().decode("utf-8", errors="replace")
            soup = BeautifulSoup(raw, "html.parser")
            for unwanted in soup(["script", "style", "iframe", "object", "embed", "form"]):
                unwanted.decompose()
            body = soup.body or soup
            self._rewrite_resource_urls(body, item.file_name, book_id)
            heading = body.find(["h1", "h2", "h3"])
            title = heading.get_text(" ", strip=True) if heading else ""
            title = title or getattr(item, "title", "") or Path(item.file_name).stem.replace("_", " ")
            title = re.sub(r"\s+", " ", title).strip() or f"Chapter {index}"
            safe_html = bleach.clean(
                "".join(str(child) for child in body.contents),
                tags=ALLOWED_TAGS,
                attributes=ALLOWED_ATTRIBUTES,
                protocols={"http", "https", "mailto"},
                strip=True,
            )
            if not BeautifulSoup(safe_html, "html.parser").get_text(strip=True) and "<img" not in safe_html:
                continue
            chapters.append(
                Chapter(
                    id=f"chapter-{index}",
                    title=title[:180],
                    html=safe_html,
                    source_name=item.file_name,
                )
            )
        if not chapters:
            raise EpubError("No readable chapters were found in this EPUB.")
        return chapters

    def extract_images(self, path: str | Path) -> list[ImageAsset]:
        path = Path(path).resolve()
        self._assert_in_library(path)
        book = self._read(path)
        book_id = _stable_book_id(path)
        extracted = self._extract_media_items(book, book_id)
        assets: list[ImageAsset] = []
        for item, output_path, safe_name in extracted:
            width: int | None = None
            height: int | None = None
            try:
                with Image.open(output_path) as image:
                    width, height = image.size
            except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
                pass  # SVG and unusual-but-browser-readable formats are still included
            assets.append(
                ImageAsset(
                    name=Path(safe_name).name,
                    media_type=item.media_type or "application/octet-stream",
                    path=output_path,
                    url=f"/cache/media/{book_id}/{quote(safe_name, safe='/')}",
                    width=width,
                    height=height,
                    size=output_path.stat().st_size,
                )
            )
        return assets

    def find_by_id(self, book_id: str) -> BookInfo | None:
        if not re.fullmatch(r"[0-9a-f]{16}", book_id):
            return None
        return next((book for book in self.discover() if book.id == book_id), None)

    def _read(self, path: Path) -> epub.EpubBook:
        try:
            return epub.read_epub(str(path), options={"ignore_ncx": True})
        except Exception as exc:
            raise EpubError(f"Could not read EPUB: {exc}") from exc

    def _assert_in_library(self, path: Path) -> None:
        try:
            path.relative_to(self.library_dir)
        except ValueError as exc:
            raise EpubError("The requested book is outside the library directory.") from exc

    @staticmethod
    def _validate_archive(data: bytes) -> None:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                members = archive.infolist()
                if len(members) > MAX_ARCHIVE_MEMBERS:
                    raise EpubError("This EPUB contains too many archive entries.")
                total_size = sum(member.file_size for member in members)
                if total_size > MAX_UNCOMPRESSED_BYTES:
                    raise EpubError("The uncompressed EPUB is too large to process safely.")
                names = {member.filename for member in members}
                if "META-INF/container.xml" not in names:
                    raise EpubError("This file is missing the EPUB container manifest.")
        except zipfile.BadZipFile as exc:
            raise EpubError("This file is not a valid EPUB/ZIP archive.") from exc

    def _available_destination(self, filename: str) -> Path:
        candidate = self.library_dir / filename
        counter = 2
        while candidate.exists():
            candidate = self.library_dir / f"{Path(filename).stem} ({counter}).epub"
            counter += 1
        return candidate

    @staticmethod
    def _document_items(book: epub.EpubBook) -> Iterable[ebooklib.epub.EpubItem]:
        """Yield readable spine documents in reading order, excluding navigation pages."""

        seen: set[str] = set()
        for entry in book.spine:
            item_id = entry[0] if isinstance(entry, (tuple, list)) else entry
            item = book.get_item_with_id(item_id)
            if item is None or item.get_type() != ebooklib.ITEM_DOCUMENT:
                continue
            if EpubLibrary._is_navigation_document(item):
                continue
            seen.add(item.get_id())
            yield item
        # Some hand-authored EPUBs have an incomplete spine; keep their documents usable.
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            if item.get_id() in seen:
                continue
            if not EpubLibrary._is_navigation_document(item):
                yield item

    @staticmethod
    def _is_navigation_document(item: ebooklib.epub.EpubItem) -> bool:
        properties = set(getattr(item, "properties", []) or [])
        return "nav" in properties or isinstance(item, epub.EpubNav) or item.get_id().casefold() in {"nav", "toc"}

    def _ensure_cover(self, book: epub.EpubBook, book_id: str, title: str, author: str) -> Path:
        output = self.cover_dir / f"{book_id}.webp"
        fallback = self.cover_dir / f"{book_id}.svg"
        if output.exists():
            return output
        if fallback.exists():
            return fallback

        cover_item = self._find_cover_item(book)
        if cover_item is not None:
            try:
                with Image.open(io.BytesIO(cover_item.get_content())) as source:
                    image = ImageOps.exif_transpose(source)
                    image.thumbnail((720, 1080), Image.Resampling.LANCZOS)
                    if image.mode not in {"RGB", "RGBA"}:
                        image = image.convert("RGBA")
                    if image.mode == "RGBA":
                        background = Image.new("RGB", image.size, "#12141a")
                        background.paste(image, mask=image.getchannel("A"))
                        image = background
                    else:
                        image = image.convert("RGB")
                    image.save(output, "WEBP", quality=88, method=6)
                return output
            except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
                pass

        fallback.write_text(self._placeholder_svg(book_id, title, author), encoding="utf-8")
        return fallback

    @staticmethod
    def _find_cover_item(book: epub.EpubBook):
        cover_ids: list[str] = []
        for _value, attributes in book.get_metadata("OPF", "cover"):
            content = attributes.get("content") if attributes else None
            if content:
                cover_ids.append(content)
        for cover_id in cover_ids:
            item = book.get_item_with_id(cover_id)
            if item is not None:
                return item
        for item in book.get_items_of_type(ebooklib.ITEM_COVER):
            return item
        image_items = list(book.get_items_of_type(ebooklib.ITEM_IMAGE))
        return next((item for item in image_items if "cover" in item.file_name.lower()), None)

    @staticmethod
    def _placeholder_svg(book_id: str, title: str, author: str) -> str:
        palettes = [
            ("#28334a", "#d9ff63"),
            ("#351f45", "#ff9b8b"),
            ("#173c3b", "#8ee8c6"),
            ("#442822", "#ffc26f"),
            ("#182c4f", "#91bdff"),
            ("#3c2134", "#ef9fc7"),
        ]
        background, accent = palettes[int(book_id[:2], 16) % len(palettes)]
        title_lines = EpubLibrary._wrap_cover_text(title, 18, 4)
        title_markup = "".join(
            f'<text x="52" y="{300 + index * 58}" class="title">{html.escape(line)}</text>'
            for index, line in enumerate(title_lines)
        )
        return f'''<svg xmlns="http://www.w3.org/2000/svg" width="480" height="720" viewBox="0 0 480 720">
<defs><linearGradient id="bg" x2="1" y2="1"><stop stop-color="{background}"/><stop offset="1" stop-color="#0d1017"/></linearGradient><pattern id="grain" width="28" height="28" patternUnits="userSpaceOnUse"><circle cx="2" cy="2" r="1" fill="#fff" opacity=".055"/></pattern></defs>
<rect width="480" height="720" rx="4" fill="url(#bg)"/><rect width="480" height="720" fill="url(#grain)"/>
<path d="M52 82h70" stroke="{accent}" stroke-width="5"/><circle cx="406" cy="92" r="35" fill="none" stroke="{accent}" stroke-width="2" opacity=".75"/><circle cx="406" cy="92" r="21" fill="none" stroke="{accent}" opacity=".4"/>
<text x="52" y="126" fill="{accent}" font-family="Arial,sans-serif" font-size="15" letter-spacing="5">PYLIBRO EDITION</text>
{title_markup}
<text x="52" y="650" fill="#fff" opacity=".7" font-family="Arial,sans-serif" font-size="18">{html.escape(author[:36])}</text>
<style>.title{{fill:#fff;font:700 39px Georgia,serif;letter-spacing:-1px}}</style></svg>'''

    @staticmethod
    def _wrap_cover_text(value: str, width: int, limit: int) -> list[str]:
        words = value.split()
        lines: list[str] = []
        current: list[str] = []
        for word in words:
            if current and len(" ".join(current + [word])) > width:
                lines.append(" ".join(current))
                current = [word]
                if len(lines) == limit:
                    break
            else:
                current.append(word)
        if current and len(lines) < limit:
            lines.append(" ".join(current))
        if not lines:
            lines = ["Untitled"]
        if len(lines) == limit and len(" ".join(words)) > len(" ".join(lines)):
            lines[-1] = lines[-1].rstrip(".,;: ") + "…"
        return lines

    def _extract_media_items(self, book: epub.EpubBook, book_id: str):
        target_root = self.media_dir / book_id
        target_root.mkdir(parents=True, exist_ok=True)
        extracted = []
        # media_type is more complete than ITEM_IMAGE: cover items and SVG assets
        # can use distinct EbookLib item types while still being browser images.
        image_items = (
            item for item in book.get_items() if (getattr(item, "media_type", "") or "").lower().startswith("image/")
        )
        for item in image_items:
            safe_name = _safe_archive_name(item.file_name)
            if safe_name is None:
                continue
            output_path = target_root.joinpath(*PurePosixPath(safe_name).parts)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            content = item.get_content()
            if not output_path.exists() or output_path.stat().st_size != len(content):
                output_path.write_bytes(content)
            extracted.append((item, output_path, safe_name))
        return extracted

    @staticmethod
    def _rewrite_resource_urls(body: BeautifulSoup, document_name: str, book_id: str) -> None:
        document_dir = posixpath.dirname(document_name)
        for image in body.find_all("img"):
            source = image.get("src", "")
            parsed = urlparse(source)
            if not source or parsed.scheme in {"data", "http", "https"} or source.startswith("//"):
                continue
            resolved = _safe_archive_name(posixpath.join(document_dir, unquote(parsed.path)))
            if resolved:
                image["src"] = f"/cache/media/{book_id}/{quote(resolved, safe='/')}"
                image["loading"] = "lazy"
            else:
                image.attrs.pop("src", None)
        for anchor in body.find_all("a"):
            href = anchor.get("href", "")
            if href.startswith(("http://", "https://", "mailto:")):
                anchor["target"] = "_blank"
                anchor["rel"] = "noopener noreferrer"


def clear_runtime_cache(cache_dir: str | Path) -> None:
    """Convenience hook for deployments that want to rebuild generated media."""

    path = Path(cache_dir)
    if path.exists():
        shutil.rmtree(path)
