"""PyLibro — a polished, local-first EPUB library built with NiceGUI."""

from __future__ import annotations

import asyncio
import os
from functools import partial
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse
from nicegui import app, events, run, ui
from starlette.concurrency import run_in_threadpool
from starlette.formparsers import MultiPartParser

from epub_parser import BookInfo, EpubError, EpubLibrary, ImageAsset, human_size
from kindle_service import (
    MAX_KINDLE_ATTACHMENT_BYTES,
    KindleConfigurationError,
    KindleDeliveryError,
    KindleDeliveryService,
    KindleFileError,
    SMTPSettings,
)
from profile_store import ProfileStore, ProfileValidationError

APP_DIR = Path(__file__).parent.resolve()
LIBRARY_DIR = Path(os.getenv("PYLIBRO_LIBRARY_DIR", APP_DIR / "books"))
CACHE_DIR = Path(os.getenv("PYLIBRO_CACHE_DIR", APP_DIR / ".pylibro_cache"))
DATABASE_PATH = Path(os.getenv("PYLIBRO_DATABASE_PATH", APP_DIR / ".pylibro_data" / "pylibro.sqlite3"))
MAX_UPLOAD_MB = int(os.getenv("PYLIBRO_MAX_UPLOAD_MB", "100"))
ALLOW_SERVER_SHUTDOWN = os.getenv("PYLIBRO_ALLOW_SHUTDOWN", "true").lower() == "true"

library = EpubLibrary(LIBRARY_DIR, CACHE_DIR)
profile_store = ProfileStore(DATABASE_PATH)
smtp_settings = SMTPSettings.from_environment()
kindle_delivery = KindleDeliveryService(smtp_settings)
app.add_static_files("/cache", str(CACHE_DIR))
# Keep modest uploads off RAM while still allowing Starlette to spool efficiently.
MultiPartParser.spool_max_size = 8 * 1024 * 1024


@app.get("/api/books/{book_id}/download")
def download_endpoint(book_id: str) -> FileResponse:
    book = library.find_by_id(book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    return FileResponse(
        path=book.file_path,
        filename=book.file_name,
        media_type="application/epub+zip",
    )


@app.post("/api/books/{book_id}/send-to-kindle")
async def send_to_kindle_endpoint(book_id: str) -> dict[str, str]:
    """Send a library-owned EPUB to the configured local user's Kindle."""

    # PyLibro has one local profile and no account system. Resolving the opaque
    # ID through EpubLibrary authorizes access to this installation's library
    # without accepting a user-controlled filesystem path.
    book = await run_in_threadpool(library.find_by_id, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    profile = await run_in_threadpool(profile_store.get_profile)
    if not profile.kindle_email:
        raise HTTPException(status_code=409, detail="Configure a Kindle email in Profile settings first.")
    if book.file_size >= MAX_KINDLE_ATTACHMENT_BYTES:
        raise HTTPException(status_code=413, detail="Send to Kindle requires an EPUB smaller than 50 MB.")
    try:
        await run_in_threadpool(
            kindle_delivery.send_epub,
            profile.kindle_email,
            book.file_path,
            book.title,
        )
    except KindleConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except KindleFileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except KindleDeliveryError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"status": "accepted", "book_id": book.id, "message": "EPUB accepted by the outbound mail server."}


ui.add_head_html(
    """
    <meta name="theme-color" content="#090b0f">
    <meta name="description" content="A beautiful, local-first EPUB library and reader.">
    """,
    shared=True,
)

ui.add_css(
    r"""
    :root {
      --ink: #f5f7f2;
      --muted: #92988f;
      --muted-2: #676d68;
      --surface: #111419;
      --surface-2: #171b21;
      --line: rgba(255, 255, 255, .085);
      --acid: #d7ff63;
      --acid-soft: rgba(215, 255, 99, .14);
      --orange: #ff9c67;
    }
    * { box-sizing: border-box; }
    html { scroll-behavior: smooth; background: #090b0f; }
    body.pylibro-body {
      margin: 0; color: var(--ink); background:
        radial-gradient(circle at 84% 2%, rgba(90, 113, 54, .11), transparent 29rem),
        radial-gradient(circle at 8% 38%, rgba(82, 69, 125, .08), transparent 28rem), #090b0f;
      font-family: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      min-height: 100vh;
    }
    .nicegui-content { padding: 0 !important; }
    .q-focus-helper { opacity: 0 !important; }

    /* Header */
    .app-header {
      height: 76px; padding: 0 4vw; color: var(--ink) !important;
      background: rgba(9, 11, 15, .74) !important;
      border-bottom: 1px solid rgba(255,255,255,.065);
      backdrop-filter: blur(22px) saturate(150%); -webkit-backdrop-filter: blur(22px);
      z-index: 50;
    }
    .header-inner { width: min(1440px, 100%); margin: auto; height: 100%; }
    .brand-mark {
      width: 37px; height: 37px; border-radius: 11px; display: grid; place-items: center;
      color: #10130d; background: var(--acid); box-shadow: 0 0 28px rgba(215,255,99,.18);
      transform: rotate(-3deg);
    }
    .brand-name { font-size: 20px; font-weight: 760; letter-spacing: -.55px; }
    .brand-name span { color: var(--acid); }
    .nav-pill { color: #a8ada6 !important; border-radius: 12px; font-size: 13px; letter-spacing: .1px; transition: color .2s, background .2s; }
    .nav-pill.active { color: var(--ink) !important; background: rgba(255,255,255,.07); }
    .nav-pill.selection-ready { color: var(--acid) !important; background: rgba(215,255,99,.075); }
    .add-book-btn {
      background: var(--acid) !important; color: #14180d !important; font-weight: 750;
      border-radius: 13px !important; height: 42px; padding-inline: 18px !important;
      box-shadow: 0 8px 30px rgba(193,234,76,.12);
    }
    .header-icon-btn {
      width: 42px; height: 42px; color: #929992 !important; border: 1px solid var(--line);
      background: rgba(255,255,255,.025) !important; transition: color .2s, border-color .2s, background .2s;
    }
    .settings-btn:hover {
      color: var(--acid) !important; border-color: rgba(215,255,99,.32); background: rgba(215,255,99,.07) !important;
    }
    .stop-server-btn:hover {
      color: #ff8f86 !important; border-color: rgba(255,105,97,.35); background: rgba(255,105,97,.08) !important;
    }
    .shutdown-card {
      width: min(440px, calc(100vw - 32px)); padding: 30px !important; color: var(--ink) !important;
      border: 1px solid var(--line); border-radius: 22px !important; background: #15191f !important;
      box-shadow: 0 28px 80px rgba(0,0,0,.55) !important;
    }
    .shutdown-icon {
      width: 54px; height: 54px; display: grid; place-items: center; color: #ff8f86;
      border-radius: 16px; border: 1px solid rgba(255,105,97,.2); background: rgba(255,105,97,.08);
    }
    .shutdown-title { margin-top: 20px; font-size: 21px; font-weight: 720; letter-spacing: -.5px; }
    .shutdown-copy { margin-top: 8px; color: #878e87; font-size: 13px; line-height: 1.65; }
    .shutdown-confirm { color: #fff !important; background: #d95c55 !important; border-radius: 11px !important; font-weight: 700; }
    .profile-card {
      width: min(560px, calc(100vw - 28px)); max-height: calc(100vh - 40px); padding: 0 !important; overflow-x: hidden; overflow-y: auto;
      color: var(--ink) !important; border: 1px solid var(--line); border-radius: 24px !important;
      background: #14181e !important; box-shadow: 0 30px 90px rgba(0,0,0,.58) !important;
    }
    .profile-header { width: 100%; padding: 24px 26px 19px; border-bottom: 1px solid var(--line); }
    .profile-title { font-size: 21px; font-weight: 740; letter-spacing: -.55px; }
    .profile-subtitle { color: #777e77; font-size: 12px; margin-top: 4px; }
    .profile-body { width: 100%; padding: 24px 26px 26px; }
    .kindle-input { width: 100%; border: 1px solid var(--line); border-radius: 14px; background: rgba(255,255,255,.035); }
    .kindle-input .q-field__control, .kindle-input .q-field__native { color: var(--ink) !important; }
    .kindle-guide { width: 100%; margin-top: 18px; padding: 17px; border: 1px solid rgba(215,255,99,.15); border-radius: 15px; background: rgba(215,255,99,.045); }
    .kindle-guide-icon { color: var(--acid); margin-top: 1px; }
    .kindle-guide-title { color: #dfe4dc; font-size: 12px; font-weight: 720; }
    .kindle-guide-copy { color: #858c84; font-size: 11px; line-height: 1.6; margin-top: 5px; }
    .sender-address { color: var(--acid); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; word-break: break-all; }
    .amazon-settings-link { color: #b9d95f !important; font-size: 11px; margin-top: 9px; text-decoration: none; }
    .profile-save { color: #11150c !important; background: var(--acid) !important; border-radius: 11px !important; font-weight: 750; }
    .smtp-warning { color: #f1ac78; font-size: 10px; line-height: 1.5; margin-top: 9px; }

    /* Hero */
    .page-shell { width: min(1440px, 92vw); margin: 0 auto; padding: 118px 0 70px; }
    .hero-section {
      position: relative; overflow: hidden; min-height: 390px; padding: clamp(28px, 4vw, 58px);
      border: 1px solid var(--line); border-radius: 30px;
      background: linear-gradient(120deg, rgba(22,26,31,.96), rgba(13,16,20,.9));
      box-shadow: 0 28px 90px rgba(0,0,0,.28);
    }
    .hero-section::before {
      content: ""; position: absolute; width: 480px; height: 480px; right: -120px; top: -240px;
      border-radius: 50%; background: radial-gradient(circle, rgba(215,255,99,.14), transparent 67%);
      pointer-events: none;
    }
    .hero-section::after {
      content: ""; position: absolute; width: 260px; height: 260px; left: 43%; bottom: -210px;
      border: 1px solid rgba(215,255,99,.14); border-radius: 50%; box-shadow: 0 0 0 44px rgba(215,255,99,.018), 0 0 0 88px rgba(215,255,99,.012);
    }
    .hero-grid { position: relative; z-index: 1; display: grid; grid-template-columns: 1.2fr .8fr; gap: 64px; align-items: center; width: 100%; }
    .eyebrow { color: var(--acid); text-transform: uppercase; letter-spacing: 3.2px; font-size: 11px; font-weight: 760; }
    .hero-title { margin: 14px 0 16px; max-width: 750px; font-size: clamp(42px, 5vw, 76px); line-height: .98; letter-spacing: -4px; font-weight: 720; }
    .hero-title em { color: var(--acid); font-family: Georgia, serif; font-weight: 400; }
    .hero-copy { max-width: 590px; color: #979d96; font-size: 16px; line-height: 1.7; }
    .stats-row { gap: 34px; margin-top: 34px; }
    .stat-block { min-width: 86px; }
    .stat-number { font-size: 25px; line-height: 1; font-weight: 720; letter-spacing: -.8px; }
    .stat-label { margin-top: 8px; color: var(--muted-2); font-size: 10px; text-transform: uppercase; letter-spacing: 1.7px; }
    .stat-divider { width: 1px; height: 40px; background: var(--line); }

    /* Uploader */
    .upload-zone { width: 100%; min-height: 245px; border-radius: 22px !important; overflow: hidden; background: transparent !important; box-shadow: none !important; }
    .upload-zone .q-uploader__header { min-height: 245px; padding: 0 !important; border: 1px dashed rgba(215,255,99,.34); border-radius: 22px; background: rgba(215,255,99,.035) !important; transition: .25s ease; }
    .upload-zone .q-uploader__header:hover { border-color: rgba(215,255,99,.72); background: rgba(215,255,99,.065) !important; transform: translateY(-2px); }
    .upload-zone .q-uploader__header-content { min-height: 245px; padding: 28px !important; flex-direction: column; justify-content: center; text-align: center; gap: 9px; }
    .upload-zone .q-uploader__title { font-size: 16px; font-weight: 700; letter-spacing: -.2px; }
    .upload-zone .q-uploader__subtitle { color: #7f877d; font-size: 12px; }
    .upload-zone .q-uploader__list { display: none; }
    .upload-zone .q-uploader__header .q-btn { color: var(--acid) !important; background: rgba(215,255,99,.1); }
    .upload-note { color: #636a63; font-size: 10px; letter-spacing: .4px; text-align: center; margin-top: 8px; }

    /* Toolbar */
    .library-section { padding-top: 68px; }
    .section-kicker { color: var(--acid); font-size: 10px; font-weight: 750; letter-spacing: 2.6px; text-transform: uppercase; }
    .section-title { font-size: clamp(30px, 3vw, 43px); font-weight: 700; letter-spacing: -1.8px; margin-top: 5px; }
    .library-count { color: #6f756f; font-size: 13px; margin-left: 4px; }
    .toolbar { gap: 12px; }
    .search-box, .sort-box { border: 1px solid var(--line); background: rgba(255,255,255,.035); border-radius: 14px; min-height: 47px; }
    .search-box { width: min(310px, 42vw); }
    .sort-box { width: 175px; }
    .search-box .q-field__control, .sort-box .q-field__control { color: var(--ink) !important; min-height: 47px; }
    .search-box .q-field__native, .sort-box .q-field__native, .search-box .q-icon, .sort-box .q-icon { color: #b6bbb4 !important; }

    /* Book grid and cards */
    .book-grid { display: grid !important; grid-template-columns: repeat(auto-fill, minmax(222px, 1fr)); gap: 32px 25px; margin-top: 34px; width: 100%; }
    .book-card {
      width: 100%; padding: 0 !important; overflow: visible !important; border-radius: 20px !important;
      color: var(--ink) !important; background: transparent !important; box-shadow: none !important;
      animation: card-in .48s both;
    }
    @keyframes card-in { from { opacity: 0; transform: translateY(18px); } to { opacity: 1; transform: none; } }
    .book-cover-wrap {
      position: relative; overflow: hidden; width: 100%; aspect-ratio: .69; border-radius: 18px;
      background: #171b21; box-shadow: 0 17px 35px rgba(0,0,0,.34); transition: transform .35s cubic-bezier(.2,.75,.25,1), box-shadow .35s;
    }
    .book-card:hover .book-cover-wrap { transform: translateY(-9px) scale(1.018); box-shadow: 0 28px 55px rgba(0,0,0,.5); }
    .book-cover-wrap.highlighted-cover {
      transform: translateY(-7px) scale(1.015);
      box-shadow: 0 0 0 3px var(--acid), 0 0 0 9px rgba(215,255,99,.11), 0 28px 58px rgba(0,0,0,.52), 0 0 42px rgba(215,255,99,.16);
    }
    .book-card:hover .book-cover-wrap.highlighted-cover {
      transform: translateY(-10px) scale(1.022);
      box-shadow: 0 0 0 3px var(--acid), 0 0 0 10px rgba(215,255,99,.14), 0 34px 68px rgba(0,0,0,.58), 0 0 52px rgba(215,255,99,.2);
    }
    .cover-image { width: 100%; height: 100%; cursor: pointer; border-radius: inherit; }
    .cover-image:focus-visible { outline: 3px solid var(--acid); outline-offset: -5px; }
    .cover-image .q-img__image { transition: transform .55s cubic-bezier(.2,.75,.25,1), filter .35s; }
    .book-card:hover .cover-image .q-img__image, .highlighted-cover .cover-image .q-img__image { transform: scale(1.045); }
    .cover-shade { position: absolute; inset: 0; background: linear-gradient(to top, rgba(5,7,9,.96), transparent 62%); opacity: .32; transition: opacity .3s; pointer-events: none; }
    .book-card:hover .cover-shade { opacity: .88; }
    .format-badge { position: absolute; left: 13px; top: 13px; border-radius: 8px !important; padding: 6px 8px; color: #15180f !important; background: var(--acid) !important; font-size: 9px; font-weight: 800; letter-spacing: 1px; pointer-events: none; }
    .cover-highlight-mark {
      position: absolute; left: 66px; top: 13px; z-index: 3; display: grid; place-items: center;
      width: 26px; height: 26px; color: #11150c; background: var(--acid); border-radius: 50%;
      box-shadow: 0 5px 18px rgba(0,0,0,.35); opacity: 0; transform: scale(.55) rotate(-20deg);
      transition: opacity .24s ease, transform .32s cubic-bezier(.2,.9,.3,1.4); pointer-events: none;
    }
    .highlighted-cover .cover-highlight-mark { opacity: 1; transform: scale(1) rotate(0); }
    .cover-actions { position: absolute; right: 11px; top: 11px; display: flex; gap: 7px; opacity: 0; transform: translateY(-7px); transition: .28s ease; }
    .book-card:hover .cover-actions { opacity: 1; transform: none; }
    .cover-icon { width: 36px; height: 36px; color: #fff !important; background: rgba(10,12,15,.7) !important; border: 1px solid rgba(255,255,255,.16); backdrop-filter: blur(10px); }
    .hover-meta { position: absolute; left: 16px; right: 16px; bottom: 16px; opacity: 0; transform: translateY(12px); transition: .3s ease; pointer-events: none; }
    .book-card:hover .hover-meta { opacity: 1; transform: none; }
    .hover-meta-row { color: #d5d9d2; font-size: 11px; margin-top: 7px; }
    .hover-meta-row .q-icon { color: var(--acid); opacity: .85; }
    .book-info { padding: 18px 4px 2px; }
    .book-title { overflow: hidden; display: -webkit-box; -webkit-line-clamp: 1; -webkit-box-orient: vertical; font-size: 16px; font-weight: 690; letter-spacing: -.25px; }
    .book-author { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; color: #797f79; font-size: 12px; margin-top: 5px; }
    .book-bottom { width: 100%; margin-top: 14px; }
    .read-btn { border-radius: 11px !important; min-height: 38px; padding-inline: 15px !important; color: #11150c !important; background: var(--acid) !important; font-size: 11px; font-weight: 800; letter-spacing: .4px; }
    .more-btn { color: #828882 !important; border: 1px solid var(--line); width: 38px; height: 38px; }

    /* Empty state */
    .empty-state { grid-column: 1 / -1; min-height: 310px; display: grid; place-items: center; width: 100%; border: 1px dashed rgba(255,255,255,.12); border-radius: 24px; background: rgba(255,255,255,.018); text-align: center; }
    .empty-orbit { width: 78px; height: 78px; margin: auto; display: grid; place-items: center; border-radius: 50%; border: 1px solid rgba(215,255,99,.25); background: var(--acid-soft); color: var(--acid); box-shadow: 0 0 0 12px rgba(215,255,99,.025); }
    .empty-title { font-size: 20px; font-weight: 700; margin-top: 22px; }
    .empty-copy { max-width: 380px; color: #6f766f; font-size: 13px; margin-top: 8px; line-height: 1.6; }

    /* Reader */
    .reader-dialog-card { width: 100vw !important; height: 100vh !important; max-width: none !important; padding: 0 !important; border-radius: 0 !important; overflow: hidden; color: #e9ece6 !important; background: #0c0f13 !important; }
    .reader-header { height: 70px; flex: 0 0 70px; width: 100%; padding: 0 24px; border-bottom: 1px solid rgba(255,255,255,.08); background: rgba(13,16,20,.93); }
    .reader-book-title { max-width: 330px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 14px; font-weight: 700; }
    .reader-book-author { color: #686f69; font-size: 10px; margin-top: 2px; }
    .reader-tool { color: #aeb4ad !important; border-radius: 11px; }
    .reader-download { color: #12160d !important; background: var(--acid) !important; border-radius: 11px !important; font-weight: 750; }
    .kindle-send-btn {
      color: #dce2d8 !important; border: 1px solid rgba(215,255,99,.22); border-radius: 11px !important;
      background: rgba(215,255,99,.055) !important; font-weight: 680;
    }
    .reader-surface { flex: 1 1 auto; min-height: 0; width: 100%; --reader-font-size: 19px; }
    .reader-layout { flex-wrap: nowrap !important; width: 100%; height: 100%; gap: 0; }
    .toc-panel { width: 285px; flex: 0 0 285px; height: 100%; padding: 28px 18px; border-right: 1px solid rgba(255,255,255,.07); background: #101319; }
    .reader-mini-cover { width: 48px; height: 70px; border-radius: 6px; overflow: hidden; box-shadow: 0 8px 18px rgba(0,0,0,.35); }
    .toc-eyebrow { color: #5f665f; font-size: 9px; letter-spacing: 2px; text-transform: uppercase; margin: 28px 8px 12px; }
    .toc-scroll { height: calc(100% - 120px); width: 100%; }
    .toc-button { justify-content: flex-start !important; width: 100%; min-height: 42px; padding: 7px 11px !important; border-radius: 10px !important; color: #747b75 !important; font-size: 11px; text-align: left; }
    .toc-button .q-btn__content { justify-content: flex-start; flex-wrap: nowrap; text-overflow: ellipsis; overflow: hidden; white-space: nowrap; }
    .toc-button.active { color: var(--ink) !important; background: rgba(215,255,99,.08) !important; border-left: 2px solid var(--acid); }
    .reader-main { position: relative; flex: 1 1 auto; min-width: 0; height: 100%; transition: background .25s, color .25s; }
    .reader-dark .reader-main { color: #dce0da; background: #0c0f13; }
    .reader-light .reader-main { color: #292d29; background: #f4f1e9; }
    .reader-progress { position: absolute; top: 0; left: 0; right: 0; z-index: 3; height: 2px !important; color: var(--acid) !important; }
    .reader-scroll { width: 100%; height: 100%; }
    .reader-article { width: min(760px, calc(100% - 64px)); margin: 0 auto; padding: 74px 0 130px; }
    .chapter-label { color: #767d76; font-size: 10px; letter-spacing: 2.5px; text-transform: uppercase; }
    .chapter-heading { margin: 12px 0 38px; font-family: Georgia, "Times New Roman", serif; font-size: clamp(30px, 4vw, 47px); line-height: 1.13; letter-spacing: -1.3px; }
    .epub-content { font-family: Georgia, "Times New Roman", serif; font-size: var(--reader-font-size); line-height: 1.85; }
    .epub-content p { margin: 0 0 1.45em; }
    .epub-content h1, .epub-content h2, .epub-content h3, .epub-content h4 { margin: 1.7em 0 .75em; font-family: Georgia, serif; line-height: 1.25; }
    .epub-content img { display: block; max-width: 100%; max-height: 76vh; width: auto; height: auto; margin: 2.5em auto; border-radius: 6px; }
    .epub-content blockquote { margin: 2em 0; padding: 3px 0 3px 25px; border-left: 2px solid var(--acid); opacity: .84; font-style: italic; }
    .epub-content a { color: #81a525; text-decoration: underline; text-underline-offset: 3px; }
    .epub-content table { max-width: 100%; border-collapse: collapse; font-size: .84em; }
    .epub-content td, .epub-content th { padding: 8px; border: 1px solid currentColor; }
    .reader-controls { position: absolute; z-index: 5; left: 50%; bottom: 22px; transform: translateX(-50%); min-width: 290px; padding: 8px 11px; border: 1px solid rgba(255,255,255,.1); border-radius: 16px; background: rgba(20,24,29,.86); backdrop-filter: blur(18px); box-shadow: 0 14px 40px rgba(0,0,0,.3); }
    .page-indicator { min-width: 68px; color: #929890; font-size: 10px; text-align: center; letter-spacing: 1px; }

    /* Gallery and lightbox */
    .gallery-card { width: 100vw !important; height: 100vh !important; max-width: none !important; padding: 0 !important; border-radius: 0 !important; overflow: hidden; color: var(--ink) !important; background: #0a0c10 !important; }
    .gallery-header { width: 100%; min-height: 78px; padding: 16px 4vw; border-bottom: 1px solid var(--line); background: rgba(14,17,21,.9); }
    .gallery-title { font-size: 18px; font-weight: 720; letter-spacing: -.4px; }
    .gallery-subtitle { color: #6e756f; font-size: 11px; margin-top: 3px; }
    .gallery-scroll { width: 100%; height: calc(100vh - 78px); }
    .media-masonry { width: min(1380px, 92vw); margin: 0 auto; padding: 38px 0 80px; columns: 5 220px; column-gap: 18px; }
    .media-tile { position: relative; break-inside: avoid; overflow: hidden; margin-bottom: 18px; min-height: 120px; border: 1px solid var(--line); border-radius: 16px; background: #15191f; cursor: zoom-in; }
    .media-image { width: 100%; min-height: 130px; transition: transform .4s ease, filter .3s; }
    .media-tile:hover .media-image { transform: scale(1.025); filter: brightness(.75); }
    .media-caption { position: absolute; inset: auto 0 0; padding: 36px 13px 12px; opacity: 0; transform: translateY(5px); transition: .25s; background: linear-gradient(transparent, rgba(5,7,9,.92)); pointer-events: none; }
    .media-tile:hover .media-caption { opacity: 1; transform: none; }
    .media-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; font-weight: 650; }
    .media-detail { color: #949a94; font-size: 9px; margin-top: 3px; }
    .lightbox-card { width: 100vw !important; height: 100vh !important; max-width: none !important; padding: 0 !important; border-radius: 0 !important; display: grid !important; place-items: center; color: white !important; background: rgba(2,3,5,.96) !important; }
    .lightbox-image { width: min(90vw, 1500px); height: 82vh; }
    .lightbox-top { position: absolute; z-index: 2; top: 20px; left: 24px; right: 24px; }

    .loading-card { min-width: 230px; padding: 30px !important; align-items: center; color: var(--ink) !important; background: #171b20 !important; border: 1px solid var(--line); border-radius: 18px !important; }
    .loading-copy { color: #8d938d; font-size: 12px; margin-top: 13px; }
    .footer { color: #515751; font-size: 11px; padding: 70px 0 5px; }

    @media (max-width: 900px) {
      .nav-group { display: none !important; }
      .hero-grid { grid-template-columns: 1fr; gap: 40px; }
      .hero-title { letter-spacing: -2.5px; }
      .toc-panel { display: none !important; }
      .reader-article { width: min(680px, calc(100% - 40px)); padding-top: 48px; }
      .reader-book-author, .reader-font-divider { display: none !important; }
      .reader-book-title { max-width: 170px; }
    }
    @media (max-width: 640px) {
      .app-header { padding: 0 18px; height: 66px; }
      .brand-name { font-size: 17px; }
      .add-book-btn { width: 42px; padding: 0 !important; font-size: 0; }
      .page-shell { width: calc(100vw - 28px); padding-top: 86px; }
      .hero-section { border-radius: 22px; padding: 28px 20px; }
      .hero-title { font-size: 43px; }
      .hero-copy { font-size: 14px; }
      .stats-row { gap: 15px; justify-content: space-between; }
      .stat-divider { display: none; }
      .toolbar-row { align-items: flex-start !important; gap: 18px; }
      .toolbar { width: 100%; }
      .search-box { width: calc(100% - 107px); }
      .sort-box { width: 95px; }
      .book-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 28px 14px; }
      .book-title { font-size: 14px; }
      .read-btn span.block { display: none; }
      .read-btn { width: 42px; padding: 0 !important; }
      .hover-meta, .cover-actions { opacity: 1; transform: none; }
      .hover-meta { display: none; }
      .format-badge { font-size: 7px; }
      .reader-header { padding: 0 10px; }
      .reader-download span.block, .kindle-send-btn span.block { display: none; }
      .reader-download, .kindle-send-btn { width: 40px; padding: 0 !important; }
      .reader-book-meta { display: none !important; }
      .reader-article { width: calc(100% - 34px); }
      .reader-controls { min-width: 260px; bottom: 12px; }
      .media-masonry { columns: 2 130px; column-gap: 10px; padding-top: 18px; }
      .media-tile { margin-bottom: 10px; border-radius: 11px; }
    }
    """,
    shared=True,
)


def trigger_download(book: BookInfo) -> None:
    ui.download(f"/api/books/{book.id}/download", filename=book.file_name)
    ui.notify("Your EPUB download is ready", icon="download", color="positive", position="bottom-right")


def format_chapter_count(count: int) -> str:
    return f"{count} chapter" if count == 1 else f"{count} chapters"


@ui.page("/")
def library_page() -> None:
    ui.query("body").classes("pylibro-body")
    state: dict[str, list[BookInfo]] = {"books": library.discover()}
    highlighted_cover: dict[str, str | None] = {"book_id": None}
    cover_elements = {}
    selected_action_buttons: list[object] = []
    uploader_ref: dict[str, object] = {}
    try:
        smtp_settings.validate()
    except KindleConfigurationError as exc:
        smtp_configuration_error = str(exc)
    else:
        smtp_configuration_error = ""

    def get_highlighted_book() -> BookInfo | None:
        selected_id = highlighted_cover["book_id"]
        return next((book for book in state["books"] if book.id == selected_id), None)

    async def open_highlighted_reader() -> None:
        book = get_highlighted_book()
        if book is None:
            ui.notify("Highlight a book cover first", icon="auto_stories", position="bottom-right")
            return
        await show_reader(book)

    async def open_highlighted_media() -> None:
        book = get_highlighted_book()
        if book is None:
            ui.notify("Highlight a book cover first", icon="collections", position="bottom-right")
            return
        await show_gallery(book)

    def open_upload_picker() -> None:
        uploader = uploader_ref.get("uploader")
        if uploader is not None:
            uploader.run_method("pickFiles")

    async def open_profile_settings() -> None:
        profile = await run.io_bound(profile_store.get_profile)
        kindle_email_input.set_value(profile.kindle_email)
        profile_dialog.open()

    async def save_profile_settings() -> None:
        profile_save_button.props("loading")
        try:
            profile = await run.io_bound(profile_store.update_kindle_email, kindle_email_input.value)
        except ProfileValidationError as exc:
            ui.notify(str(exc), type="negative", icon="alternate_email", position="bottom-right")
            return
        finally:
            profile_save_button.props(remove="loading")
        profile_dialog.close()
        if profile.kindle_email:
            ui.notify("Kindle email saved", icon="check_circle", color="positive", position="bottom-right")
        else:
            ui.notify("Kindle email cleared", icon="info", position="bottom-right")

    async def send_book_to_kindle(book: BookInfo) -> None:
        profile = await run.io_bound(profile_store.get_profile)
        if not profile.kindle_email:
            ui.notify(
                "Add your @kindle.com address in Profile settings first",
                type="warning",
                icon="alternate_email",
                position="bottom-right",
            )
            kindle_email_input.set_value("")
            profile_dialog.open()
            return
        if book.file_size >= MAX_KINDLE_ATTACHMENT_BYTES:
            ui.notify(
                "Send to Kindle requires an EPUB smaller than 50 MB",
                type="negative",
                icon="warning_amber",
                position="bottom-right",
            )
            return

        loading = _loading_dialog(f"Sending “{book.title}” to Kindle…")
        loading.open()
        try:
            await run.io_bound(
                kindle_delivery.send_epub,
                profile.kindle_email,
                book.file_path,
                book.title,
            )
        except KindleDeliveryError as exc:
            ui.notify(str(exc), type="negative", icon="error_outline", position="bottom-right", timeout=6500)
            return
        finally:
            loading.close()
            loading.delete()
        ui.notify(
            f"“{book.title}” was accepted for Kindle delivery",
            icon="send",
            color="positive",
            position="bottom-right",
            timeout=4500,
        )

    async def shutdown_server() -> None:
        shutdown_dialog.close()
        if os.getenv("PYLIBRO_RELOAD", "false").lower() == "true":
            ui.notify(
                "Server shutdown is unavailable while development reload is enabled.",
                type="warning",
                icon="warning_amber",
                position="bottom-right",
            )
            return
        ui.notify(
            "PyLibro is shutting down…",
            type="ongoing",
            icon="power_settings_new",
            position="center",
            timeout=900,
        )
        await asyncio.sleep(0.75)  # let the browser render the final status message
        app.shutdown()

    shutdown_dialog = ui.dialog().props('persistent transition-show="scale" transition-hide="scale"')
    with shutdown_dialog, ui.card().classes("shutdown-card"):
        with ui.element("div").classes("shutdown-icon"):
            ui.icon("power_settings_new", size="27px")
        ui.label("Stop the PyLibro server?").classes("shutdown-title")
        ui.label(
            "This closes the web app for every connected reader. Your EPUB files and reading library will stay safely on disk."
        ).classes("shutdown-copy")
        with ui.row().classes("w-full justify-end gap-2 q-mt-lg"):
            ui.button("Keep running", on_click=shutdown_dialog.close).props("flat no-caps color=grey-5")
            ui.button("Stop server", icon="power_settings_new", on_click=shutdown_server).props(
                "unelevated no-caps"
            ).classes("shutdown-confirm")

    profile_dialog = ui.dialog().props('transition-show="scale" transition-hide="scale"')
    with profile_dialog, ui.card().classes("profile-card"):
        with ui.row().classes("profile-header items-center justify-between no-wrap"):
            with ui.column().classes("gap-0"):
                ui.label("Profile & Kindle").classes("profile-title")
                ui.label("Send books from your shelf without downloading first").classes("profile-subtitle")
            ui.button(icon="close", on_click=profile_dialog.close).props("flat round color=grey-5")
        with ui.column().classes("profile-body gap-0"):
            kindle_email_input = (
                ui.input(label="Your Send to Kindle email", placeholder="your-name@kindle.com")
                .props("outlined clearable dark type=email autocomplete=email")
                .classes("kindle-input")
            )
            ui.label("You can clear this field to remove the saved address.").classes("profile-subtitle q-mt-sm")
            with ui.row().classes("kindle-guide items-start no-wrap gap-3"):
                ui.icon("verified_user", size="21px").classes("kindle-guide-icon")
                with ui.column().classes("gap-0"):
                    ui.label("Approve PyLibro with Amazon first").classes("kindle-guide-title")
                    ui.label(
                        "In Amazon, open Manage Your Content and Devices → Preferences → Personal Document Settings, then add this address to your Approved Personal Document E-mail List:"
                    ).classes("kindle-guide-copy")
                    if smtp_settings.sender_address:
                        ui.label(smtp_settings.sender_address).classes("sender-address q-mt-sm")
                    else:
                        ui.label("Outbound sender not configured").classes("sender-address q-mt-sm")
                    if smtp_configuration_error:
                        ui.label(smtp_configuration_error).classes("smtp-warning")
                    ui.link(
                        "Open Amazon Content & Devices settings",
                        "https://www.amazon.com/hz/mycd/myx#/home/settings",
                        new_tab=True,
                    ).classes("amazon-settings-link")
                    ui.label("Only EPUB files smaller than 50 MB can be sent.").classes("kindle-guide-copy q-mt-sm")
            with ui.row().classes("w-full justify-end gap-2 q-mt-lg"):
                ui.button("Cancel", on_click=profile_dialog.close).props("flat no-caps color=grey-5")
                profile_save_button = (
                    ui.button("Save Kindle email", icon="save", on_click=save_profile_settings)
                    .props("unelevated no-caps")
                    .classes("profile-save")
                )

    with ui.header().classes("app-header"):
        with ui.row().classes("header-inner items-center justify-between no-wrap"):
            with ui.row().classes("items-center no-wrap gap-3"):
                with ui.element("div").classes("brand-mark"):
                    ui.icon("auto_stories", size="22px")
                ui.html("Py<span>Libro</span>").classes("brand-name")
            with ui.row().classes("nav-group items-center gap-1"):
                ui.button("Library", icon="grid_view").props("flat no-caps").classes("nav-pill active")
                reader_nav = (
                    ui.button("Reader", icon="menu_book", on_click=open_highlighted_reader)
                    .props("flat no-caps")
                    .classes("nav-pill")
                )
                media_nav = (
                    ui.button("Media", icon="photo_library", on_click=open_highlighted_media)
                    .props("flat no-caps")
                    .classes("nav-pill")
                )
                selected_action_buttons.extend((reader_nav, media_nav))
            with ui.row().classes("header-actions items-center no-wrap gap-2"):
                ui.button(icon="settings", on_click=open_profile_settings).props(
                    'flat round aria-label="Open profile and Kindle settings"'
                ).classes("header-icon-btn settings-btn").tooltip("Profile & Kindle")
                if ALLOW_SERVER_SHUTDOWN:
                    ui.button(icon="power_settings_new", on_click=shutdown_dialog.open).props(
                        'flat round aria-label="Stop PyLibro server"'
                    ).classes("header-icon-btn stop-server-btn").tooltip("Stop server")
                ui.button("Add book", icon="add", on_click=open_upload_picker).props("unelevated no-caps").classes(
                    "add-book-btn"
                )

    with ui.column().classes("page-shell gap-0"):
        with ui.element("section").classes("hero-section"):
            with ui.element("div").classes("hero-grid"):
                with ui.column().classes("gap-0"):
                    ui.label("Your private reading space").classes("eyebrow")
                    ui.html("Stories, <em>beautifully</em><br>kept.").classes("hero-title")
                    ui.label(
                        "Collect, explore, and read your EPUB library in a calm, focused space — entirely under your control."
                    ).classes("hero-copy")
                    with ui.row().classes("stats-row items-center no-wrap"):
                        with ui.column().classes("stat-block gap-0"):
                            books_stat = ui.label("0").classes("stat-number")
                            ui.label("Books").classes("stat-label")
                        ui.element("div").classes("stat-divider")
                        with ui.column().classes("stat-block gap-0"):
                            chapters_stat = ui.label("0").classes("stat-number")
                            ui.label("Chapters").classes("stat-label")
                        ui.element("div").classes("stat-divider")
                        with ui.column().classes("stat-block gap-0"):
                            storage_stat = ui.label("0 B").classes("stat-number")
                            ui.label("On shelf").classes("stat-label")
                with ui.column().classes("w-full gap-0"):
                    uploader = (
                        ui.upload(
                            label="Drop EPUBs here or choose a file",
                            multiple=True,
                            auto_upload=True,
                            max_file_size=MAX_UPLOAD_MB * 1024 * 1024,
                            max_total_size=MAX_UPLOAD_MB * 1024 * 1024 * 3,
                        )
                        .props("accept=.epub flat dark color=primary")
                        .classes("upload-zone")
                    )
                    uploader_ref["uploader"] = uploader
                    ui.label(f"EPUB ONLY  ·  UP TO {MAX_UPLOAD_MB} MB PER FILE").classes("upload-note")

        with ui.element("section").classes("library-section"):
            with ui.row().classes("toolbar-row w-full items-end justify-between"):
                with ui.column().classes("gap-0"):
                    ui.label("Curated collection").classes("section-kicker")
                    with ui.row().classes("items-baseline gap-2"):
                        ui.label("Your library").classes("section-title")
                        count_label = ui.label().classes("library-count")
                with ui.row().classes("toolbar items-center no-wrap"):
                    search = (
                        ui.input(placeholder="Search title or author", on_change=lambda: render_books.refresh())
                        .props("borderless dense dark debounce=250")
                        .classes("search-box")
                    )
                    search.add_slot("prepend", '<q-icon name="search" />')
                    sort = (
                        ui.select(
                            {"recent": "Recent", "title": "Title A–Z", "author": "Author A–Z"},
                            value="recent",
                            on_change=lambda: render_books.refresh(),
                        )
                        .props("borderless dense dark options-dense")
                        .classes("sort-box")
                    )

            async def show_reader(book: BookInfo) -> None:
                loading = _loading_dialog("Preparing your reading room…")
                loading.open()
                try:
                    chapters = await run.io_bound(library.get_chapters, book.file_path)
                except EpubError as exc:
                    ui.notify(str(exc), type="negative", icon="error_outline", position="bottom-right")
                    return
                finally:
                    loading.close()
                    loading.delete()

                reader = ui.dialog().props('maximized transition-show="slide-left" transition-hide="slide-right"')
                reader_state = {"index": 0, "font": 19, "light": False}
                refs: dict[str, object] = {}
                toc_buttons: list[object] = []

                def show_chapter(index: int) -> None:
                    index = max(0, min(index, len(chapters) - 1))
                    reader_state["index"] = index
                    chapter = chapters[index]
                    refs["content"].set_content(chapter.html)
                    refs["heading"].set_text(chapter.title)
                    refs["chapter_label"].set_text(f"Chapter {index + 1} of {len(chapters)}")
                    refs["page"].set_text(f"{index + 1}  /  {len(chapters)}")
                    refs["progress"].set_value((index + 1) / len(chapters))
                    refs["previous"].set_enabled(index > 0)
                    refs["next"].set_enabled(index < len(chapters) - 1)
                    for button_index, button in enumerate(toc_buttons):
                        button.classes(
                            add="active" if button_index == index else "",
                            remove="" if button_index == index else "active",
                        )
                    ui.run_javascript(
                        "const el=document.querySelector('.reader-scroll .q-scrollarea__container'); if(el) el.scrollTo({top:0,behavior:'smooth'});"
                    )

                def adjust_font(delta: int) -> None:
                    reader_state["font"] = max(14, min(30, reader_state["font"] + delta))
                    refs["surface"].style(f"--reader-font-size: {reader_state['font']}px")
                    refs["font_value"].set_text(str(reader_state["font"]))

                def toggle_reader_theme() -> None:
                    reader_state["light"] = not reader_state["light"]
                    if reader_state["light"]:
                        refs["surface"].classes(add="reader-light", remove="reader-dark")
                        refs["theme"].props("icon=dark_mode")
                    else:
                        refs["surface"].classes(add="reader-dark", remove="reader-light")
                        refs["theme"].props("icon=light_mode")

                with reader, ui.card().classes("reader-dialog-card"):
                    with ui.row().classes("reader-header items-center justify-between no-wrap"):
                        with ui.row().classes("items-center no-wrap gap-3"):
                            ui.button(icon="arrow_back", on_click=reader.close).props("flat round").classes(
                                "reader-tool"
                            )
                            with ui.column().classes("reader-book-meta gap-0"):
                                ui.label(book.title).classes("reader-book-title")
                                ui.label(book.author).classes("reader-book-author")
                        with ui.row().classes("items-center no-wrap gap-1"):
                            ui.button(icon="text_decrease", on_click=partial(adjust_font, -1)).props(
                                "flat round"
                            ).classes("reader-tool")
                            refs["font_value"] = ui.label("19").classes("reader-font-divider text-xs text-grey-6")
                            ui.button(icon="text_increase", on_click=partial(adjust_font, 1)).props(
                                "flat round"
                            ).classes("reader-tool")
                            refs["theme"] = (
                                ui.button(icon="light_mode", on_click=toggle_reader_theme)
                                .props("flat round")
                                .classes("reader-tool")
                            )
                            ui.button(
                                "Send to Kindle",
                                icon="send",
                                on_click=partial(send_book_to_kindle, book),
                            ).props("flat no-caps").classes("kindle-send-btn")
                            ui.button("Download", icon="download", on_click=partial(trigger_download, book)).props(
                                "unelevated no-caps"
                            ).classes("reader-download")
                    refs["surface"] = ui.element("div").classes("reader-surface reader-dark")
                    with refs["surface"]:
                        with ui.row().classes("reader-layout"):
                            with ui.column().classes("toc-panel gap-0"):
                                with ui.row().classes("items-center no-wrap gap-3"):
                                    ui.image(book.cover_url).props("fit=cover").classes("reader-mini-cover")
                                    with ui.column().classes("gap-0"):
                                        ui.label("Contents").classes("text-sm text-weight-bold")
                                        ui.label(format_chapter_count(len(chapters))).classes("text-xs text-grey-7")
                                ui.label("Table of contents").classes("toc-eyebrow")
                                with ui.scroll_area().classes("toc-scroll"):
                                    with ui.column().classes("w-full gap-1"):
                                        for index, chapter in enumerate(chapters):
                                            toc_buttons.append(
                                                ui.button(chapter.title, on_click=partial(show_chapter, index))
                                                .props("flat no-caps align=left")
                                                .classes("toc-button")
                                            )
                            with ui.element("main").classes("reader-main"):
                                refs["progress"] = (
                                    ui.linear_progress(value=1 / len(chapters))
                                    .props("instant-feedback")
                                    .classes("reader-progress")
                                )
                                with ui.scroll_area().classes("reader-scroll"):
                                    with ui.column().classes("reader-article gap-0"):
                                        refs["chapter_label"] = ui.label().classes("chapter-label")
                                        refs["heading"] = ui.label().classes("chapter-heading")
                                        refs["content"] = ui.html("", sanitize=False).classes("epub-content")
                                with ui.row().classes("reader-controls items-center justify-center no-wrap"):
                                    refs["previous"] = (
                                        ui.button(
                                            icon="arrow_back", on_click=lambda: show_chapter(reader_state["index"] - 1)
                                        )
                                        .props("flat round")
                                        .classes("reader-tool")
                                    )
                                    refs["page"] = ui.label().classes("page-indicator")
                                    refs["next"] = (
                                        ui.button(
                                            icon="arrow_forward",
                                            on_click=lambda: show_chapter(reader_state["index"] + 1),
                                        )
                                        .props("flat round")
                                        .classes("reader-tool")
                                    )
                show_chapter(0)
                reader.open()

            async def show_gallery(book: BookInfo) -> None:
                loading = _loading_dialog("Extracting every embedded image…")
                loading.open()
                try:
                    images = await run.io_bound(library.extract_images, book.file_path)
                except EpubError as exc:
                    ui.notify(str(exc), type="negative", icon="error_outline", position="bottom-right")
                    return
                finally:
                    loading.close()
                    loading.delete()
                if not images:
                    ui.notify(
                        "No embedded images were found in this EPUB",
                        icon="image_not_supported",
                        position="bottom-right",
                    )
                    return

                gallery = ui.dialog().props('maximized transition-show="fade" transition-hide="fade"')
                lightbox = ui.dialog().props('maximized transition-show="fade" transition-hide="fade"')
                lightbox_refs: dict[str, object] = {}
                active_asset: dict[str, ImageAsset | None] = {"value": None}

                def open_lightbox(asset: ImageAsset) -> None:
                    active_asset["value"] = asset
                    lightbox_refs["image"].set_source(asset.url)
                    lightbox_refs["name"].set_text(asset.name)
                    lightbox.open()

                def download_active_image() -> None:
                    asset = active_asset["value"]
                    if asset is not None:
                        ui.download(asset.url, filename=asset.name)

                with lightbox, ui.card().classes("lightbox-card"):
                    with ui.row().classes("lightbox-top items-center justify-between no-wrap"):
                        lightbox_refs["name"] = ui.label().classes("text-sm text-grey-4")
                        with ui.row().classes("items-center gap-2"):
                            ui.button(icon="download", on_click=download_active_image).props("flat round color=white")
                            ui.button(icon="close", on_click=lightbox.close).props("flat round color=white")
                    lightbox_refs["image"] = ui.image().props("fit=contain").classes("lightbox-image")

                with gallery, ui.card().classes("gallery-card"):
                    with ui.row().classes("gallery-header items-center justify-between no-wrap"):
                        with ui.row().classes("items-center no-wrap gap-3"):
                            ui.button(icon="arrow_back", on_click=gallery.close).props("flat round color=grey-5")
                            with ui.column().classes("gap-0"):
                                ui.label(f"Inside {book.title}").classes("gallery-title")
                                ui.label(
                                    f"{len(images)} embedded image{'s' if len(images) != 1 else ''} · click any image to inspect"
                                ).classes("gallery-subtitle")
                        ui.button("Download EPUB", icon="download", on_click=partial(trigger_download, book)).props(
                            "unelevated no-caps"
                        ).classes("reader-download")
                    with ui.scroll_area().classes("gallery-scroll"):
                        with ui.element("div").classes("media-masonry"):
                            for asset in images:
                                with ui.element("div").classes("media-tile").on("click", partial(open_lightbox, asset)):
                                    ui.image(asset.url).props("fit=contain loading=lazy").classes("media-image")
                                    with ui.column().classes("media-caption gap-0"):
                                        ui.label(asset.name).classes("media-name")
                                        dimensions = (
                                            f"{asset.width} × {asset.height}"
                                            if asset.width and asset.height
                                            else asset.media_type.split("/")[-1].upper()
                                        )
                                        ui.label(f"{dimensions}  ·  {asset.size_display}").classes("media-detail")
                ui.notify(
                    f"Extracted {len(images)} images", icon="collections", color="positive", position="bottom-right"
                )
                gallery.open()

            def toggle_cover_highlight(book_id: str) -> None:
                previous_id = highlighted_cover["book_id"]
                if previous_id in cover_elements:
                    cover_elements[previous_id].classes(remove="highlighted-cover")

                highlighted_cover["book_id"] = None if previous_id == book_id else book_id
                selected_id = highlighted_cover["book_id"]
                if selected_id in cover_elements:
                    cover_elements[selected_id].classes(add="highlighted-cover")

                for button in selected_action_buttons:
                    button.classes(
                        add="selection-ready" if selected_id else "",
                        remove="" if selected_id else "selection-ready",
                    )

            def book_card(book: BookInfo, index: int) -> None:
                with ui.card().props("flat").classes("book-card").style(f"animation-delay:{min(index * 45, 360)}ms"):
                    cover = ui.element("div").classes("book-cover-wrap")
                    if highlighted_cover["book_id"] == book.id:
                        cover.classes(add="highlighted-cover")
                    cover_elements[book.id] = cover
                    with cover:
                        cover_image = (
                            ui.image(book.cover_url)
                            .props('fit=cover no-spinner role=button tabindex=0 aria-label="Highlight this book cover"')
                            .classes("cover-image")
                            .on("click", partial(toggle_cover_highlight, book.id))
                            .on(
                                "keydown",
                                partial(toggle_cover_highlight, book.id),
                                js_handler="""(event) => {
                                    if (event.key === 'Enter' || event.key === ' ') {
                                        event.preventDefault();
                                        emit();
                                    }
                                }""",
                            )
                        )
                        cover_image.tooltip("Click to highlight cover")
                        ui.element("div").classes("cover-shade")
                        ui.badge("EPUB").classes("format-badge")
                        with ui.element("div").classes("cover-highlight-mark"):
                            ui.icon("check", size="17px")
                        with ui.row().classes("cover-actions no-wrap"):
                            ui.button(icon="photo_library", on_click=partial(show_gallery, book)).props(
                                "flat round"
                            ).classes("cover-icon").tooltip("Inspect embedded images")
                            ui.button(icon="download", on_click=partial(trigger_download, book)).props(
                                "flat round"
                            ).classes("cover-icon").tooltip("Download EPUB")
                        with ui.column().classes("hover-meta gap-0"):
                            with ui.row().classes("hover-meta-row items-center gap-2 no-wrap"):
                                ui.icon("person", size="14px")
                                ui.label(book.author)
                            with ui.row().classes("hover-meta-row items-center gap-2 no-wrap"):
                                ui.icon("subject", size="14px")
                                ui.label(format_chapter_count(book.chapter_count))
                            with ui.row().classes("hover-meta-row items-center gap-2 no-wrap"):
                                ui.icon("data_usage", size="14px")
                                ui.label(book.file_size_display)
                    with ui.column().classes("book-info gap-0"):
                        ui.label(book.title).classes("book-title").tooltip(book.title)
                        ui.label(book.author).classes("book-author")
                        with ui.row().classes("book-bottom items-center justify-between no-wrap"):
                            ui.button("Start reading", icon="auto_stories", on_click=partial(show_reader, book)).props(
                                "unelevated no-caps"
                            ).classes("read-btn")
                            with ui.row().classes("items-center no-wrap gap-1"):
                                ui.button(icon="send", on_click=partial(send_book_to_kindle, book)).props(
                                    'flat round aria-label="Send this EPUB to Kindle"'
                                ).classes("more-btn").tooltip("Send to Kindle")
                                ui.button(icon="photo_library", on_click=partial(show_gallery, book)).props(
                                    "flat round"
                                ).classes("more-btn").tooltip("Media gallery")

            @ui.refreshable
            def render_books() -> None:
                cover_elements.clear()
                query = (search.value or "").casefold().strip()
                books = [
                    book
                    for book in state["books"]
                    if not query or query in book.title.casefold() or query in book.author.casefold()
                ]
                if sort.value == "title":
                    books.sort(key=lambda book: book.title.casefold())
                elif sort.value == "author":
                    books.sort(key=lambda book: book.author.casefold())
                else:
                    books.sort(key=lambda book: book.modified_at, reverse=True)
                count_label.set_text(f"{len(books):02d}")
                with ui.element("div").classes("book-grid"):
                    if not books:
                        with ui.element("div").classes("empty-state"):
                            with ui.column().classes("items-center gap-0 px-6"):
                                with ui.element("div").classes("empty-orbit"):
                                    ui.icon("auto_stories", size="31px")
                                ui.label("Your next story starts here").classes("empty-title")
                                copy = (
                                    "No books match this search. Try a different title or author."
                                    if query
                                    else "Drop an EPUB into the upload area above and its cover, chapters, and artwork will appear here."
                                )
                                ui.label(copy).classes("empty-copy")
                                if not query:
                                    ui.button("Choose an EPUB", icon="add", on_click=open_upload_picker).props(
                                        "unelevated no-caps"
                                    ).classes("add-book-btn q-mt-md")
                    for index, book in enumerate(books):
                        book_card(book, index)

            def update_stats() -> None:
                books = state["books"]
                books_stat.set_text(f"{len(books):02d}")
                chapters_stat.set_text(str(sum(book.chapter_count for book in books)))
                storage_stat.set_text(human_size(sum(book.file_size for book in books)))

            async def handle_upload(event: events.UploadEventArguments) -> None:
                try:
                    data = await event.file.read()
                    book = await run.io_bound(library.save_upload, event.file.name, data)
                    state["books"] = await run.io_bound(library.discover)
                    update_stats()
                    render_books.refresh()
                    ui.notify(
                        f"“{book.title}” joined your library",
                        icon="auto_stories",
                        color="positive",
                        position="bottom-right",
                        timeout=3500,
                    )
                except EpubError as exc:
                    ui.notify(str(exc), type="negative", icon="error_outline", position="bottom-right", timeout=5000)
                except Exception:
                    ui.notify(
                        "The upload could not be processed. Please try another EPUB.",
                        type="negative",
                        icon="error_outline",
                        position="bottom-right",
                    )
                finally:
                    uploader.reset()

            uploader.on_upload(handle_upload)
            uploader.on_rejected(
                lambda: ui.notify(
                    f"Only EPUB files up to {MAX_UPLOAD_MB} MB are accepted",
                    type="warning",
                    icon="warning_amber",
                    position="bottom-right",
                )
            )
            update_stats()
            render_books()

        with ui.row().classes("footer w-full items-center justify-between"):
            ui.label("PYLIBRO  ·  YOUR LIBRARY, YOUR FILES")
            ui.label("Made for unhurried reading")


def _loading_dialog(message: str):
    dialog = ui.dialog().props("persistent")
    with dialog, ui.card().classes("loading-card"):
        ui.spinner("dots", size="42px", color="primary")
        ui.label(message).classes("loading-copy")
    return dialog


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(
        title="PyLibro — Your EPUB Library",
        favicon="📚",
        host=os.getenv("PYLIBRO_HOST", "0.0.0.0"),
        port=int(os.getenv("PYLIBRO_PORT", "8080")),
        reload=os.getenv("PYLIBRO_RELOAD", "false").lower() == "true",
        show=os.getenv("PYLIBRO_OPEN_BROWSER", "false").lower() == "true",
    )
