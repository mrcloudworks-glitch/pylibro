# PyLibro

A modern, local-first EPUB library, reader, and embedded-media inspector built with Python and [NiceGUI](https://nicegui.io/).

## Highlights

- Responsive cover gallery with metadata, search, sorting, polished hover motion, and click-to-highlight selection
- Header Reader and Media actions open the currently highlighted book
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
├── run.sh             # One-command setup and launcher for macOS/Linux
├── books/             # Default library directory (uploaded EPUBs are ignored by Git)
├── requirements.txt
└── README.md
```

Generated cover thumbnails and extracted media are written to `.pylibro_cache/` and can be deleted at any time; PyLibro recreates them on demand.

## Setup

PyLibro requires Python 3.10 or newer.

### One-command start (macOS/Linux)

```bash
git clone <repository-url>
cd pylibro
./run.sh
```

`run.sh` creates `.venv`, installs or refreshes dependencies when `requirements.txt` changes, starts the application, and opens it in your default browser as soon as the server is ready. To use a specific Python executable, run `PYTHON_BIN=python3.12 ./run.sh`. To start without opening a browser, run `PYLIBRO_OPEN_BROWSER=false ./run.sh`.

### Manual start / Windows

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python app.py
```

Open **http://localhost:8080**. Drag one or more `.epub` files into the upload panel, or copy EPUB files into `books/` and refresh the page.

To stop PyLibro, press **Ctrl+C** in its terminal or click the **power button** in the web header and confirm **Stop server**. Stopping the server does not remove any books or cached media.

## Configuration

All settings are optional environment variables:

| Variable | Default | Purpose |
|---|---:|---|
| `PYLIBRO_LIBRARY_DIR` | `./books` | Directory scanned for EPUB files |
| `PYLIBRO_CACHE_DIR` | `./.pylibro_cache` | Generated covers and extracted images |
| `PYLIBRO_MAX_UPLOAD_MB` | `100` | Maximum uploaded EPUB size per file |
| `PYLIBRO_MAX_UNCOMPRESSED_MB` | `1024` | Archive expansion safety limit |
| `PYLIBRO_ALLOW_SHUTDOWN` | `true` | Show the server-wide shutdown control in the web header |
| `PYLIBRO_OPEN_BROWSER` | `true` with `run.sh` | Open the app in the default browser when the server is ready |
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

For a shared/public deployment, place PyLibro behind your normal authentication and HTTPS proxy. PyLibro does not add user accounts by itself. Set `PYLIBRO_ALLOW_SHUTDOWN=false` so remote visitors cannot stop a shared server from the web interface.
