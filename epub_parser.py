"""EPUB parsing and library management for PyLibro.

The UI deliberately delegates every EPUB-specific operation to this module.  This
keeps ebook parsing testable and makes it possible to replace NiceGUI without
rewriting the storage layer.
"""

from __future__ import annotations

import hashlib
import io
import os
import posixpath
import random
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
from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

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
        fallback = self.cover_dir / f"{book_id}.png"
        if output.exists():
            return output
        legacy_svg = self.cover_dir / f"{book_id}.svg"
        if legacy_svg.exists():
            # Older PyLibro versions wrote SVG placeholders, which some UI image
            # components cannot render. Regenerate them as PNG so covers always show.
            legacy_svg.unlink()
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

        EpubLibrary._render_placeholder_png(fallback, book_id, title, author)
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

    PLACEHOLDER_SIZE = (480, 720)
    _FONT_CANDIDATES_TITLE = (
        "/usr/share/fonts/noto-cjk/NotoSerifCJK-SemiBold.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSerif-Bold.ttf",
    )
    _FONT_CANDIDATES_BODY = (
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
    )

    @staticmethod
    def _load_cover_font(candidates: tuple[str, ...], size: int) -> ImageFont.FreeTypeFont:
        for path in candidates:
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
        return ImageFont.load_default(size=size)

    @staticmethod
    def _hex_to_rgb(value: str) -> tuple[int, int, int]:
        return tuple(int(value[i : i + 2], 16) for i in (1, 3, 5))

    @staticmethod
    def _draw_letterspaced(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, font, fill, tracking: int = 0) -> None:
        x, y = xy
        for character in text:
            draw.text((x, y), character, font=font, fill=fill)
            x += draw.textlength(character, font=font) + tracking

    @classmethod
    def _render_placeholder_png(cls, path: Path, book_id: str, title: str, author: str) -> None:
        palettes = [
            ("#28334a", "#d9ff63"),
            ("#351f45", "#ff9b8b"),
            ("#173c3b", "#8ee8c6"),
            ("#442822", "#ffc26f"),
            ("#182c4f", "#91bdff"),
            ("#3c2134", "#ef9fc7"),
        ]
        background, accent = palettes[int(book_id[:2], 16) % len(palettes)]
        width, height = cls.PLACEHOLDER_SIZE
        bottom = (13, 16, 23)
        top = cls._hex_to_rgb(background)
        accent_rgb = cls._hex_to_rgb(accent)

        image = Image.new("RGB", (width, height), bottom)
        draw = ImageDraw.Draw(image)
        for y in range(height):
            ratio = y / (height - 1)
            color = tuple(round(top[i] + (bottom[i] - top[i]) * ratio) for i in range(3))
            draw.line([(0, y), (width, y)], fill=color)

        rng = random.Random(book_id)
        for _ in range(1000):
            x, y = rng.randint(0, width - 1), rng.randint(0, height - 1)
            base = image.getpixel((x, y))
            draw.point((x, y), fill=tuple(round(base[i] + (255 - base[i]) * 0.055) for i in range(3)))

        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        odraw = ImageDraw.Draw(overlay)
        odraw.rectangle((52, 82, 122, 87), fill=accent_rgb + (255,))
        odraw.ellipse((371, 57, 441, 127), outline=accent_rgb + (191,), width=2)
        odraw.ellipse((385, 71, 427, 113), outline=accent_rgb + (102,), width=2)
        image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
        draw = ImageDraw.Draw(image)

        label_font = cls._load_cover_font(cls._FONT_CANDIDATES_BODY, 15)
        title_font = cls._load_cover_font(cls._FONT_CANDIDATES_TITLE, 39)
        author_font = cls._load_cover_font(cls._FONT_CANDIDATES_BODY, 18)

        cls._draw_letterspaced(draw, (52, 100), "PYLIBRO EDITION", label_font, accent_rgb, tracking=5)
        title_lines = EpubLibrary._wrap_cover_text(title, 18, 4)
        for index, line in enumerate(title_lines):
            draw.text((52, 258 + index * 58), line, font=title_font, fill=(255, 255, 255))
        author_color = tuple(round(255 * 0.7 + bottom[i] * 0.3) for i in range(3))
        draw.text((52, 650), author[:36], font=author_font, fill=author_color)

        image.save(path, "PNG", optimize=True)

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
