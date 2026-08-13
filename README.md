# PyLibro

A modern, local-first EPUB library, reader, and embedded-media inspector built with Python and [NiceGUI](https://nicegui.io/).

## Highlights

- Responsive cover gallery with metadata, search, sorting, and polished hover motion
- Drag-and-drop multi-file EPUB uploads with archive validation and safe filenames
- Focused in-app reader with table of contents, chapter navigation, light/dark themes, and adjustable type
- Complete embedded-image gallery with masonry layout and full-screen lightbox
- One-click download actions from the shelf, reader, gallery, and lightbox
- Automatic metadata and cover extraction, plus generated covers for books without artwork
- Local-first storage: files remain in your configured library directory

## Project structure

```text
pylibro/
├── app.py             # NiceGUI application and interactive views
├── epub_parser.py     # EPUB validation, metadata, chapters, covers, and media
├── books/             # Default library directory (uploaded EPUBs are ignored by Git)
├── requirements.txt
└── README.md
```

Generated cover thumbnails and extracted media are written to `.pylibro_cache/` and can be deleted at any time; PyLibro recreates them on demand.

## Setup

PyLibro requires Python 3.10 or newer.

```bash
git clone <repository-url>
cd pylibro
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python app.py
```

Open **http://localhost:8080**. Drag one or more `.epub` files into the upload panel, or copy EPUB files into `books/` and refresh the page.

## Configuration

All settings are optional environment variables:

| Variable | Default | Purpose |
|---|---:|---|
| `PYLIBRO_LIBRARY_DIR` | `./books` | Directory scanned for EPUB files |
| `PYLIBRO_CACHE_DIR` | `./.pylibro_cache` | Generated covers and extracted images |
| `PYLIBRO_MAX_UPLOAD_MB` | `100` | Maximum uploaded EPUB size per file |
| `PYLIBRO_MAX_UNCOMPRESSED_MB` | `1024` | Archive expansion safety limit |
| `PYLIBRO_HOST` | `0.0.0.0` | Server bind address |
| `PYLIBRO_PORT` | `8080` | Web server port |
| `PYLIBRO_RELOAD` | `false` | Enable NiceGUI development reload |

Example:

```bash
PYLIBRO_LIBRARY_DIR="$HOME/Books" PYLIBRO_PORT=9000 python app.py
```

## Security and privacy notes

- Uploaded filenames are normalized and files are written atomically.
- ZIP expansion limits and EPUB manifest checks reduce archive-bomb and malformed-file risk.
- Chapter HTML is sanitized before display; scripts, iframes, forms, and unsafe attributes are removed.
- Static routes expose only generated cache files. Original EPUBs are served through an ID-validated download endpoint.

For a shared/public deployment, place PyLibro behind your normal authentication and HTTPS proxy. PyLibro does not add user accounts by itself.
