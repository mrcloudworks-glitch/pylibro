# PyLibro

A modern, local-first EPUB library, reader, and embedded-media inspector built with Python and [NiceGUI](https://nicegui.io/).

## Highlights

- Responsive cover gallery with metadata, search, sorting, polished hover motion, and click-to-highlight selection
- Header Reader and Media actions open the currently highlighted book
- Drag-and-drop multi-file EPUB uploads with archive validation and safe filenames
- Focused in-app reader with table of contents, chapter navigation, light/dark themes, and adjustable type
- Bookmarks that remember your chapter, scroll position, font size, and theme between sessions, with "Continue reading" resume buttons
- Set any embedded image as a book's cover in the web app only (the EPUB file itself is never modified)
- Rename any book's title in the web app only — the EPUB file keeps its original metadata
- Complete embedded-image gallery with masonry layout and full-screen lightbox
- One-click download actions from the shelf, reader, gallery, and lightbox
- Send-to-Kindle delivery that emails any EPUB to your device's personal-document address
- Automatic metadata and cover extraction, plus generated covers for books without artwork
- Local-first storage: files remain in your configured library directory

## Project structure

```text
pylibro/
├── app.py             # NiceGUI application and interactive views
├── epub_parser.py     # EPUB validation, metadata, chapters, covers, and media
├── kindle_sender.py   # Optional email-based Send-to-Kindle delivery
├── reader_state.py    # Persistent per-book reading progress (bookmarks)
├── cover_store.py     # Web-app-only cover overrides from embedded images
├── title_store.py     # Web-app-only library title overrides
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

### Send to Kindle

The **Send to Kindle** action appears on every book cover once SMTP settings are configured. It emails the EPUB as an attachment to your device's `@kindle.com` address. Since Amazon retired the official Send-to-Kindle API, this uses the personal-document email route instead.

| Variable | Default | Purpose |
|---|---:|---|
| `PYLIBRO_KINDLE_EMAIL` | *(empty)* | Your device's `@kindle.com` address (from Amazon Manage Your Content and Devices) |
| `PYLIBRO_KINDLE_SMTP_HOST` | *(empty)* | SMTP relay, e.g. `smtp.gmail.com` |
| `PYLIBRO_KINDLE_SMTP_PORT` | `587` | SMTP port — `587` uses STARTTLS, `465` uses implicit TLS |
| `PYLIBRO_KINDLE_SMTP_USER` | *(empty)* | Authenticated sender address |
| `PYLIBRO_KINDLE_SMTP_PASSWORD` | *(empty)* | Sender app password (not your account password) |

Example with Gmail:

```bash
export PYLIBRO_KINDLE_EMAIL="you@kindle.com"
export PYLIBRO_KINDLE_SMTP_HOST="smtp.gmail.com"
export PYLIBRO_KINDLE_SMTP_USER="you@gmail.com"
export PYLIBRO_KINDLE_SMTP_PASSWORD="your-app-password"
```

Two Amazon requirements: the sender address must be listed under **Approved Personal Document E-mail List**, and books must be attached as `.epub` (which PyLibro does). Delivery is asynchronous on Amazon's side — your device may not show the book for a few minutes.

### Bookmarks

The reader saves your place automatically: chapter, position within the chapter, font size, and light/dark theme. Progress is stored locally in `.pylibro_cache/progress.json` (safe to delete). Books with saved progress show a **Ch. X of Y** badge on their cover and a **Continue reading** button, and reopening the book resumes exactly where you left off. You can also hit the bookmark icon in the reader header to save your place (and get a confirmation) at any moment.

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
