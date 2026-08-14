# PyLibro

A modern, local-first EPUB library, reader, and embedded-media inspector built with Python and [NiceGUI](https://nicegui.io/).

## Highlights

- Responsive cover gallery with metadata, search, sorting, polished hover motion, and click-to-highlight selection
- Header Reader and Media actions open the currently highlighted book
- Send EPUBs directly to a saved `@kindle.com` address through configurable SMTP delivery
- Persistent local profile settings with Amazon approved-sender onboarding guidance
- Drag-and-drop multi-file EPUB uploads with archive validation and safe filenames
- Focused in-app reader with table of contents, chapter navigation, light/dark themes, and adjustable type
- Complete embedded-image gallery with masonry layout and full-screen lightbox
- One-click download actions from the shelf, reader, gallery, and lightbox
- Automatic metadata and cover extraction, plus generated covers for books without artwork
- Local-first storage: files remain in your configured library directory

## Project structure

```text
pylibro/
├── app.py             # NiceGUI application, views, and FastAPI endpoints
├── epub_parser.py     # EPUB validation, metadata, chapters, covers, and media
├── kindle_service.py  # SMTP configuration, MIME composition, and Kindle delivery
├── profile_store.py   # SQLite user-profile model and persistence
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

Runtime settings use environment variables. SMTP host and sender are required only when enabling Kindle delivery:

| Variable | Default | Purpose |
|---|---:|---|
| `PYLIBRO_LIBRARY_DIR` | `./books` | Directory scanned for EPUB files |
| `PYLIBRO_CACHE_DIR` | `./.pylibro_cache` | Generated covers and extracted images |
| `PYLIBRO_DATABASE_PATH` | `./.pylibro_data/pylibro.sqlite3` | SQLite database containing the local user profile |
| `PYLIBRO_MAX_UPLOAD_MB` | `100` | Maximum uploaded EPUB size per file |
| `PYLIBRO_MAX_UNCOMPRESSED_MB` | `1024` | Archive expansion safety limit |
| `PYLIBRO_ALLOW_SHUTDOWN` | `true` | Show the server-wide shutdown control in the web header |
| `PYLIBRO_OPEN_BROWSER` | `true` with `run.sh` | Open the app in the default browser when the server is ready |
| `PYLIBRO_HOST` | `0.0.0.0` | Server bind address |
| `PYLIBRO_PORT` | `8080` | Web server port |
| `PYLIBRO_RELOAD` | `false` | Enable NiceGUI development reload |
| `PYLIBRO_SMTP_HOST` | — | Outbound SMTP server; required for Kindle delivery |
| `PYLIBRO_SMTP_PORT` | `587` | Outbound SMTP port |
| `PYLIBRO_SMTP_FROM` | — | Sender address the user must approve with Amazon |
| `PYLIBRO_SMTP_USERNAME` | — | Optional SMTP login username |
| `PYLIBRO_SMTP_PASSWORD` | — | Optional SMTP login password or app password |
| `PYLIBRO_SMTP_STARTTLS` | `true` | Upgrade a plain SMTP connection with STARTTLS |
| `PYLIBRO_SMTP_SSL` | `false` | Use implicit SMTP-over-SSL instead of STARTTLS |
| `PYLIBRO_SMTP_TIMEOUT` | `30` | SMTP connection timeout in seconds |

Example:

```bash
PYLIBRO_LIBRARY_DIR="$HOME/Books" PYLIBRO_PORT=9000 python app.py
```

## Send to Kindle setup

1. Configure an SMTP account or relay. Keep credentials in environment variables rather than source control:

   ```bash
   export PYLIBRO_SMTP_HOST="smtp.example.com"
   export PYLIBRO_SMTP_PORT="587"
   export PYLIBRO_SMTP_FROM="PyLibro Books <books@example.com>"
   export PYLIBRO_SMTP_USERNAME="books@example.com"
   export PYLIBRO_SMTP_PASSWORD="use-an-app-password-or-secret-manager"
   ./run.sh
   ```

   For implicit TLS, commonly on port 465, set `PYLIBRO_SMTP_SSL=true` and `PYLIBRO_SMTP_STARTTLS=false`.

2. In PyLibro, click the **settings** button in the header and save your personal `@kindle.com` address.
3. Follow the in-app Amazon link. Under **Personal Document Settings**, add the exact address shown in PyLibro to the **Approved Personal Document E-mail List**.
4. Use **Send to Kindle** on a library card or in the reader. PyLibro shows a loading state while SMTP runs in a worker thread, followed by the mail server's accepted/error result.

Only EPUBs smaller than 50 MB are accepted by this feature. The profile is stored in the local SQLite database; SMTP credentials are never written there. The equivalent controller endpoint is `POST /api/books/{book_id}/send-to-kindle`. It returns `409` when no Kindle address is saved, `413` for oversized files, `503` for incomplete SMTP configuration, and `502` if the mail server rejects delivery.

SMTP acceptance means the message was handed to the configured mail server. Amazon may send a later conversion or delivery-status email.

## Security and privacy notes

- Uploaded filenames are normalized and files are written atomically.
- ZIP expansion limits and EPUB manifest checks reduce archive-bomb and malformed-file risk.
- Chapter HTML is sanitized before display; scripts, iframes, forms, and unsafe attributes are removed.
- Static routes expose only generated cache files. Original EPUBs are downloaded or mailed only after an opaque book ID resolves inside the configured library.
- SMTP secrets come only from process environment variables and are not exposed in the profile UI or SQLite database.

For a shared/public deployment, place PyLibro behind your normal authentication and HTTPS proxy. PyLibro does not add user accounts by itself, so every visitor who can open this installation can use its single local profile and Kindle-send endpoint. Set `PYLIBRO_ALLOW_SHUTDOWN=false` so remote visitors cannot stop a shared server from the web interface.
