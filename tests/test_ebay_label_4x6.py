"""Tests for ebay_label_4x6.py -- the eBay letter-sheet -> 4x6 label fixer.

Run:  python -m pytest -q

Why synthetic PDFs: a real eBay label carries a buyer's name and home address,
so one can never be committed as a fixture. The fake below reproduces the two
properties that made the real one print "sideways and small":
  1. a portrait US-letter sheet (612 x 792 pt) with the label art in the
     top-left corner, and
  2. the art drawn through a  0 -1 1 0 e f cm  rotation, so its text runs
     top-to-bottom on the sheet.
A solid black bar marks the label's own TOP edge, so the test can prove the
output is upright by rendering it -- no OCR, no reliance on text extraction
(which is exactly what lies on the real file: pypdf reports the text as upright
because the rotation sits outside the form XObject).
"""

import io
import os
import sys

import pypdfium2
import pytest
from pypdf import PdfReader
from reportlab.pdfgen import canvas

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ebay_label_4x6 as mod  # noqa: E402  (path set up on the line above)


def _fake_ebay_label(rotate_deg=-90):
    """Build a letter sheet shaped exactly like eBay's real label PDF.

    Measured on real eBay labels: the label is ONE form XObject with
    /BBox [0 0 288 432] (a 4x6 portrait in its own space), and the page
    content is just   q 0 -1 1 0 90 734.46 cm /Xf1 Do Q   -- the form drawn
    turned 90 degrees into the top-left of a 612 x 792 sheet, text running
    DOWN the sheet. That structure matters: the Chrome extension lifts the
    form out directly, and the desktop converter must cope with it too.

    rotate_deg=-90 reproduces eBay. +90 is the mirror (x-axis pointing UP),
    kept so the direction logic is tested both ways rather than hard-coding
    eBay's current habit.
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(612, 792))
    # The label, in its own upright 4x6 space.
    c.beginForm("label", 0, 0, 288, 432)
    c.rect(9, 16, 270, 400, stroke=1, fill=0)   # body, inset like eBay's art
    c.rect(9, 386, 270, 30, stroke=0, fill=1)   # TOP marker bar
    c.setFont("Helvetica", 12)
    c.drawString(29, 216, "USPS GROUND ADVANTAGE")
    c.endForm()
    c.saveState()
    if rotate_deg == -90:
        # eBay's exact matrix: (x, y) -> (y + 90, 734.46 - x).
        c.transform(0, -1, 1, 0, 90, 734.46)
    else:
        # Mirror: (x, y) -> (522 - y, x + 60); same footprint, lower on the sheet.
        c.transform(0, 1, -1, 0, 522, 60)
    c.doForm("label")
    c.restoreState()
    c.showPage()
    c.save()
    return buf.getvalue()


def _render_gray(pdf_bytes):
    """Render page 1 at 72 dpi (1 px = 1 pt) to a grayscale PIL image."""
    doc = pypdfium2.PdfDocument(pdf_bytes)
    img = doc[0].render(scale=1).to_pil().convert("L")
    doc.close()
    return img


def _dark_fraction(img, box):
    """Share of pixels darker than mid-gray inside box=(l, t, r, b)."""
    region = img.crop(box)
    px = list(region.getdata())
    return sum(1 for p in px if p < 128) / max(1, len(px))


@pytest.mark.parametrize("rotate_deg", [-90, 90])
def test_output_is_upright_4x6(rotate_deg):
    out = mod.convert_bytes(_fake_ebay_label(rotate_deg))
    page = PdfReader(io.BytesIO(out)).pages[0]
    # 4 x 6 in portrait, and the rotation baked into the content, not left as
    # a /Rotate flag that some Windows print drivers ignore.
    assert (round(float(page.mediabox.width)), round(float(page.mediabox.height))) == (288, 432)
    assert int(page.get("/Rotate", 0)) == 0
    img = _render_gray(out)
    assert img.size == (288, 432)
    # The TOP bar must land in the top band of the output, not a side.
    assert _dark_fraction(img, (40, 0, 248, 90)) > 0.15
    assert _dark_fraction(img, (40, 342, 248, 432)) < 0.05


def test_already_4x6_is_left_alone():
    # A file that is already a 4x6 portrait page must not be "fixed" again.
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(288, 432))
    c.drawString(20, 400, "already fine")
    c.showPage()
    c.save()
    assert mod.needs_conversion(buf.getvalue()) is False


def test_letter_sheet_needs_conversion():
    assert mod.needs_conversion(_fake_ebay_label()) is True


def test_output_name():
    # The *_4x6 suffix is also what stops the watcher re-converting its own output.
    assert mod.output_path(r"C:\dl\eBay_label_06-1.pdf").endswith("eBay_label_06-1_4x6.pdf")
    assert mod.is_candidate("eBay_label_01-23456-78901.pdf")
    assert not mod.is_candidate("eBay_label_01-23456-78901_4x6.pdf")
    assert not mod.is_candidate("invoice.pdf")


def test_combine_many_into_one(tmp_path):
    # Bulk mode: N eBay sheets (one mirrored, one already 4x6) -> ONE PDF,
    # one upright 4x6 page per label, in the order given.
    a = tmp_path / "eBay_label_a.pdf"
    b = tmp_path / "eBay_label_b.pdf"
    ok = tmp_path / "already_4x6.pdf"
    a.write_bytes(_fake_ebay_label(-90))
    b.write_bytes(_fake_ebay_label(90))
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(288, 432))
    c.drawString(20, 400, "already fine")
    c.showPage()
    c.save()
    ok.write_bytes(buf.getvalue())

    out = tmp_path / "combined.pdf"
    n = mod.combine_files([str(a), str(b), str(ok)], str(out))
    assert n == 3
    pages = PdfReader(str(out)).pages
    assert len(pages) == 3
    for p in pages:
        assert (round(float(p.mediabox.width)), round(float(p.mediabox.height))) == (288, 432)
        assert int(p.get("/Rotate", 0)) == 0
    # Each converted label is upright: render pages 1-2 and check the TOP bar.
    doc = pypdfium2.PdfDocument(str(out))
    for i in (0, 1):
        img = doc[i].render(scale=1).to_pil().convert("L")
        assert _dark_fraction(img, (40, 0, 248, 90)) > 0.15
        assert _dark_fraction(img, (40, 342, 248, 432)) < 0.05
    doc.close()


def test_combined_name_is_not_a_candidate():
    # The watcher must never pick up a combined output and convert it again.
    name = mod.combined_output_name()
    assert name.endswith("_4x6.pdf")
    assert not mod.is_candidate(name)


def test_process_paths_one_vs_many(tmp_path):
    # What the .exe does with dropped / picked files: one -> its own _4x6,
    # several -> one combined file next to the first.
    a = tmp_path / "eBay_label_a.pdf"
    b = tmp_path / "eBay_label_b.pdf"
    a.write_bytes(_fake_ebay_label())
    b.write_bytes(_fake_ebay_label())
    single = mod.process_paths([str(a)])
    assert single == str(tmp_path / "eBay_label_a_4x6.pdf")
    both = mod.process_paths([str(b), str(a)])
    assert os.path.dirname(both) == str(tmp_path) and both.endswith("_4x6.pdf")
    assert len(PdfReader(both).pages) == 2
