#!/usr/bin/env python3
"""ebay_label_4x6.py -- turn eBay's "letter sheet" shipping label into a real 4x6.

THE PROBLEM: eBay's print page hands back a portrait US-letter PDF
(8.5 x 11 in) with the 6x4 label art parked in the top-left corner and drawn ROTATED 90 degrees (text runs down the sheet). Sent
to a 4x6 thermal printer, it prints sideways and shrunk to fit.

THE FIX, per page:
  1. render the page (pypdfium2, 1 px = 1 pt) and find the ink bounding box;
  2. crop to a 6x4 window centred on that box -- a crop, NOT a resize, so the
     barcodes stay at eBay's exact module widths and keep scanning;
  3. read the rotation eBay applied from the page's own content stream and
     undo it, baking the turn into the content (some Windows print drivers
     ignore a bare /Rotate flag and would print it sideways again).

Why the content stream and not text extraction: on the real file pypdf reports
every text run as upright, because eBay wraps the label in a form XObject and
puts the  0 -1 1 0 e f cm  rotation OUTSIDE it. The outer cm is the truth.

USAGE
  python ebay_label_4x6.py convert eBay_label_*.pdf     # one-off, one output each
  python ebay_label_4x6.py combine eBay_label_*.pdf     # bulk -> ONE multi-page PDF
  python ebay_label_4x6.py watch                        # watch Downloads

Prebuilt apps for Windows, macOS and Linux are on the GitHub Releases page
(built by .github/workflows/build.yml; front end in ebay_label_4x6_app.py)
-- drag PDFs onto the app, or open it with no files for the tray watcher.

Every output lands next to its input as <name>_4x6.pdf. Print it at
"Actual size" / 100%, never "Fit to page".

Deps: pypdf, pypdfium2 (pip install pypdf pypdfium2). pypdfium2 ships its own
PDFium binary, so no poppler install is needed.
"""

import argparse
import fnmatch
import io
import os
import sys
import tempfile
import time

import pypdfium2
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ContentStream, NameObject, RectangleObject

# 4 x 6 in at 72 pt/in. Portrait is what a 4x6 thermal printer feeds.
LABEL_W, LABEL_H = 288, 432

# Pixels lighter than this count as paper. 250, not 255: anti-aliased edges
# and PDFium's light gray rendering of hairlines would otherwise make the
# "blank" margin non-blank and drag the bbox to the sheet edge.
INK_THRESHOLD = 250

# Padding around the ink when the art is BIGGER than 6x4 and we cannot centre
# a fixed window on it (never seen from eBay; a guard, not a measured value).
OVERSIZE_PAD = 6

# Filenames eBay gives a downloaded label: eBay_label_01-23456-78901.pdf.
DEFAULT_PATTERNS = ["ebay_label*.pdf"]

# Suffix for outputs. is_candidate() refuses names ending in it, which is what
# stops the watcher from converting its own output in a loop.
OUT_SUFFIX = "_4x6"

# --- Untrusted-input limits ------------------------------------------------
# The watcher auto-processes anything NAMED like an eBay label in Downloads,
# and any website can put a file there. These caps keep a hostile file from
# turning the converter into a memory / CPU sink. Real labels sit far inside
# every one: ~40 KB, 1 page, 612 x 792 pt.
#
# 25 MB: a 200-label combined sheet from eBay is still well under this.
MAX_INPUT_BYTES = 25 * 1024 * 1024
# 500 pages per file, and per combined output.
MAX_PAGES = 500
# 2000 pt (~27.8 in) per side. We render at 1 px/pt, so this bounds a page's
# render at 4 Mpx / ~4 MB grayscale. Without it a 20000 x 20000 pt page made
# the renderer chew through a 400 Mpx bitmap (36 s in the test, then OOM).
MAX_PAGE_PT = 2000

# Page keys that carry ACTIVE content: /AA = page open/close actions,
# /Annots = links, widgets, JavaScript-bearing annotations. A shipping label
# needs neither, and the app auto-opens its output, so both are dropped.
# (Document-level /OpenAction, /Names JavaScript and /AcroForm never reach
# the output: PdfWriter.add_page copies pages only, not the source catalog.)
ACTIVE_PAGE_KEYS = ("/AA", "/Annots")


# ---------------------------------------------------------------------------
# Naming
# ---------------------------------------------------------------------------

def output_path(path):
    """eBay_label_X.pdf -> eBay_label_X_4x6.pdf, in the same folder."""
    root, ext = os.path.splitext(path)
    return root + OUT_SUFFIX + (ext or ".pdf")


def is_candidate(name, patterns=None):
    """True when a filename looks like an eBay label we have not yet converted."""
    base = os.path.basename(name).lower()
    if os.path.splitext(base)[0].endswith(OUT_SUFFIX):
        return False
    return any(fnmatch.fnmatch(base, p.lower()) for p in (patterns or DEFAULT_PATTERNS))


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------

def _is_4x6(page):
    """Already a 4x6 page (either orientation, 2 pt slack for rounding)?"""
    w, h = float(page.mediabox.width), float(page.mediabox.height)
    return (abs(w - LABEL_W) <= 2 and abs(h - LABEL_H) <= 2) or \
           (abs(w - LABEL_H) <= 2 and abs(h - LABEL_W) <= 2)


def needs_conversion(data):
    """True if any page of the PDF is not already 4x6."""
    return any(not _is_4x6(p) for p in PdfReader(io.BytesIO(data)).pages)


def _ink_bbox(page):
    """Ink bounding box of a page in PDF points: (x0, y0, x1, y1), y up.

    Renders the single page on its own so the pixel grid matches the
    mediabox exactly (1 px = 1 pt at scale=1).
    """
    w = PdfWriter()
    w.add_page(page)
    buf = io.BytesIO()
    w.write(buf)
    doc = pypdfium2.PdfDocument(buf.getvalue())
    img = doc[0].render(scale=1).to_pil().convert("L")
    doc.close()
    # Ink -> 255, paper -> 0, then PIL's getbbox finds the non-zero extent.
    mask = img.point(lambda p: 255 if p < INK_THRESHOLD else 0)
    box = mask.getbbox()
    if box is None:
        return None
    left, top, right, bottom = box
    mb = page.mediabox
    x_off, y_top = float(mb.left), float(mb.top)
    # Image rows count DOWN from the top; PDF y counts UP from the bottom.
    return (x_off + left, y_top - bottom, x_off + right, y_top - top)


def _content_rotation(page):
    """Clockwise /Rotate needed to stand eBay's art upright: 90, 270 or None.

    Scans the page's top-level content stream for the first `cm` that is a
    pure quarter-turn (a == d == 0). b < 0 means the art's x-axis points DOWN
    the sheet (eBay's real output, text reading top-to-bottom), which takes a
    270-degree clockwise turn to fix; b > 0 is the mirror case, 90.
    """
    contents = page.get_contents()
    if contents is None:
        return None
    for operands, op in ContentStream(contents, page.pdf).operations:
        if op != b"cm" or len(operands) != 6:
            continue
        a, b, c, d = (float(x) for x in operands[:4])
        if abs(a) < 1e-6 and abs(d) < 1e-6 and abs(b) > 1e-6:
            return 270 if b < 0 else 90
    return None


def _check_page(page):
    """Refuse pages whose size would make the 1 px/pt render explode."""
    w, h = abs(float(page.mediabox.width)), abs(float(page.mediabox.height))
    if w > MAX_PAGE_PT or h > MAX_PAGE_PT:
        raise ValueError(f"page too large ({w:.0f} x {h:.0f} pt; limit {MAX_PAGE_PT})")


def _sanitize_page(page):
    """Strip active content from a page in place (see ACTIVE_PAGE_KEYS).

    Done BEFORE PdfWriter.add_page: add_page clones every object the page
    references at that moment, so popping afterwards would leave the
    annotation objects (and their JavaScript) in the output file.
    """
    for key in ACTIVE_PAGE_KEYS:
        if NameObject(key) in page:
            del page[NameObject(key)]
    return page


def _fix_page(page):
    """Sanitize + crop + rotate one page in place; returns a 4x6 portrait page."""
    _check_page(page)
    _sanitize_page(page)
    if _is_4x6(page):
        return page
    # A pre-existing /Rotate would make the render and the content disagree
    # about which way is up; fold it in first so there is one coordinate frame.
    if int(page.get("/Rotate", 0)) % 360:
        page.transfer_rotation_to_content()

    bbox = _ink_bbox(page)
    if bbox is None:
        return page  # blank page: nothing to crop, leave it alone
    x0, y0, x1, y1 = bbox
    landscape_art = (x1 - x0) > (y1 - y0)

    # Window size on the CURRENT sheet: landscape 6x4 when the art lies on its
    # side (it will be turned upright below), portrait 4x6 when it already
    # stands up and was only shrunk onto a letter sheet.
    win_w, win_h = (LABEL_H, LABEL_W) if landscape_art else (LABEL_W, LABEL_H)
    if (x1 - x0) <= win_w and (y1 - y0) <= win_h:
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        box = [cx - win_w / 2, cy - win_h / 2, cx + win_w / 2, cy + win_h / 2]
    else:
        # Art bigger than 6x4: keep all of it; the printer's fit will shrink
        # it slightly. Better than cutting off a barcode.
        box = [x0 - OVERSIZE_PAD, y0 - OVERSIZE_PAD, x1 + OVERSIZE_PAD, y1 + OVERSIZE_PAD]

    rect = RectangleObject(box)
    page.mediabox = rect
    page.cropbox = rect
    page.trimbox = rect
    page.bleedbox = rect
    page.artbox = rect

    if landscape_art:
        # Default 270: what eBay's own files need (measured on real eBay labels).
        page.rotate(_content_rotation(page) or 270)
        # Bake the turn into the content so a driver that ignores /Rotate
        # still prints it upright.
        page.transfer_rotation_to_content()
    return page


def _reader(data):
    """Open untrusted PDF bytes, enforcing the size + page-count caps."""
    if len(data) > MAX_INPUT_BYTES:
        raise ValueError(f"file too large ({len(data)} bytes; limit {MAX_INPUT_BYTES})")
    # The header may legally sit anywhere in the first 1 KB.
    if b"%PDF-" not in data[:1024]:
        raise ValueError("not a PDF (no %PDF- header)")
    reader = PdfReader(io.BytesIO(data))
    if len(reader.pages) > MAX_PAGES:
        raise ValueError(f"too many pages ({len(reader.pages)}; limit {MAX_PAGES})")
    return reader


def _read_input(path):
    """Read a file with the size cap checked BEFORE loading it into memory."""
    size = os.path.getsize(path)
    if size > MAX_INPUT_BYTES:
        raise ValueError(f"{os.path.basename(path)}: file too large ({size} bytes; limit {MAX_INPUT_BYTES})")
    with open(path, "rb") as f:
        return f.read()


def _atomic_write(dst, data):
    """Write via a temp file in the same folder, then os.replace() it in.

    os.replace swaps the DIRECTORY ENTRY, so a symlink planted at dst is
    replaced rather than followed -- the write can never land somewhere else.
    It also means a crash mid-write leaves no half-written PDF behind.
    """
    folder = os.path.dirname(os.path.abspath(dst))
    fd, tmp = tempfile.mkstemp(prefix=".ebay4x6-", suffix=".pdf", dir=folder)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, dst)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def convert_bytes(data):
    """PDF bytes in -> sanitized 4x6 PDF bytes out (every page fixed)."""
    reader = _reader(data)
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(_fix_page(page))
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def combined_output_name():
    """Timestamped name for a bulk run: eBay_labels_20260101-153000_4x6.pdf.

    Ends in _4x6 on purpose -- is_candidate() then refuses it, so a watcher
    on the same folder never re-converts a combined file.
    """
    return time.strftime("eBay_labels_%Y%m%d-%H%M%S") + OUT_SUFFIX + ".pdf"


def combine_files(paths, dst):
    """Bulk mode: fix every page of every input and write ONE PDF to dst.

    Order is the order given (the GUI sorts by name, which for eBay's
    eBay_label_<order-id>.pdf naming is order-id order). A page that is
    already 4x6 passes through untouched, so mixing fixed and unfixed labels
    is safe. Returns the page count written.
    """
    writer = PdfWriter()
    for path in paths:
        reader = _reader(_read_input(path))
        if len(writer.pages) + len(reader.pages) > MAX_PAGES:
            raise ValueError(f"too many pages in total (limit {MAX_PAGES})")
        for page in reader.pages:
            writer.add_page(_fix_page(page))
    out = io.BytesIO()
    writer.write(out)
    _atomic_write(dst, out.getvalue())
    n = len(writer.pages)
    print(f"[ok] combined {len(paths)} file(s), {n} label(s) -> {dst}")
    return n


def process_paths(paths):
    """The .exe's one entry point for files: returns the PDF to open/print.

    One file -> its own <name>_4x6.pdf -- ALWAYS a fresh, sanitized copy,
    even when the input is already 4x6, because the caller opens the result
    and the original may carry active content.
    Several -> ONE combined file, sorted by name, next to the first input.
    """
    paths = [p for p in paths if p.lower().endswith(".pdf")]
    if not paths:
        raise ValueError("no PDF files given")
    if len(paths) == 1:
        return convert_file(paths[0])
    paths = sorted(paths, key=lambda p: os.path.basename(p).lower())
    dst = os.path.join(os.path.dirname(os.path.abspath(paths[0])), combined_output_name())
    combine_files(paths, dst)
    return dst


def convert_file(path):
    """Convert one file to <name>_4x6.pdf; returns the output path.

    An input that is already 4x6 still gets a sanitized copy written (its
    pages pass through _fix_page untouched apart from the active-content
    strip), so the output is always safe to auto-open.
    """
    data = _read_input(path)
    dst = output_path(path)
    _atomic_write(dst, convert_bytes(data))
    print(f"[ok] {path} -> {dst}")
    return dst


# ---------------------------------------------------------------------------
# Watcher
# ---------------------------------------------------------------------------

def _default_downloads():
    """~/Downloads -- where Chrome/Edge drop eBay's label on Windows."""
    return os.path.join(os.path.expanduser("~"), "Downloads")


def _stable(path, wait=1.0):
    """True once the file size stops changing (download finished writing).

    Chrome writes to .crdownload and renames at the end, so this is mostly a
    guard for browsers/print-to-PDF that write the final name incrementally.
    """
    try:
        s1 = os.path.getsize(path)
        time.sleep(wait)
        return s1 > 0 and os.path.getsize(path) == s1
    except OSError:
        return False


def watch(folder, patterns, open_after, interval, enabled=None, on_converted=None):
    """Poll `folder` and convert each new eBay label once.

    Polling (2 s) instead of a filesystem-event library: zero extra deps, and
    a label download is a once-in-a-while event, not a hot path.
    `enabled` (optional callable) lets the tray app pause watching: while it
    returns False, new files are marked seen but NOT converted, so turning the
    watch back on does not suddenly convert everything downloaded meanwhile.
    `on_converted` (optional callable) receives each output path; the desktop
    app passes its cross-platform opener. Without it, open_after opens the
    result on Windows only (os.startfile).
    """
    print(f"[watch] {folder}  patterns={patterns}  (Ctrl+C to stop)")
    # Files present at start are NOT converted -- only new downloads -- unless
    # their 4x6 twin is missing AND they are recent (last 10 min), which
    # catches a label downloaded just before the watcher came up at logon.
    seen = set()
    now = time.time()
    for name in os.listdir(folder):
        p = os.path.join(folder, name)
        if not is_candidate(name, patterns):
            continue
        recent = now - os.path.getmtime(p) < 600
        if os.path.exists(output_path(p)) or not recent:
            seen.add(p)
    while True:
        try:
            for name in os.listdir(folder):
                p = os.path.join(folder, name)
                if p in seen or not is_candidate(name, patterns) or not _stable(p):
                    continue
                seen.add(p)
                if enabled is not None and not enabled():
                    continue
                try:
                    dst = convert_file(p)
                    if dst and on_converted:
                        on_converted(dst)
                    elif dst and open_after and hasattr(os, "startfile"):
                        os.startfile(dst)  # opens in the default PDF viewer, ready to print
                except Exception as e:  # one bad file must not kill the watcher
                    print(f"[error] {p}: {e}")
            time.sleep(interval)
        except KeyboardInterrupt:
            return


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("convert", help="convert the given PDFs")
    c.add_argument("files", nargs="+")

    m = sub.add_parser("combine", help="convert many PDFs into ONE multi-page 4x6 PDF")
    m.add_argument("files", nargs="+")
    m.add_argument("-o", "--out", help="output path (default: timestamped, next to the first file)")

    w = sub.add_parser("watch", help="watch a folder and convert new eBay labels")
    w.add_argument("--dir", default=_default_downloads())
    w.add_argument("--pattern", action="append",
                   help="filename glob (repeatable); default ebay_label*.pdf")
    w.add_argument("--no-open", action="store_true", help="don't open the result")
    w.add_argument("--interval", type=float, default=2.0)


    a = ap.parse_args()
    if a.cmd == "convert":
        for path in a.files:
            convert_file(path)
    elif a.cmd == "combine":
        dst = a.out or os.path.join(os.path.dirname(os.path.abspath(a.files[0])), combined_output_name())
        combine_files(a.files, dst)
    elif a.cmd == "watch":
        watch(a.dir, a.pattern or DEFAULT_PATTERNS, not a.no_open, a.interval)


if __name__ == "__main__":
    main()
