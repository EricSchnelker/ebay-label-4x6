"""Security / robustness tests.

Threat model: the Downloads watcher auto-processes any file NAMED like an eBay
label, and any website can drop such a file there (a drive-by download). So
every input is untrusted:
  * a page sized to make the renderer allocate gigabytes (render = 1 px/pt),
  * a huge file or page count meant to pin the CPU,
  * active content (JavaScript actions, link annotations, open actions) that
    would ride into the output -- which the app then OPENS automatically,
  * a pre-planted symlink at the output path, to redirect our write.
"""

import io
import os
import sys

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (ArrayObject, DictionaryObject, NameObject,
                           TextStringObject)
from reportlab.pdfgen import canvas

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ebay_label_4x6 as core  # noqa: E402
from test_ebay_label_4x6 import _fake_ebay_label  # noqa: E402


def _blank(w, h, pages=1):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(w, h))
    for _ in range(pages):
        c.drawString(10, 10, "x")
        c.showPage()
    c.save()
    return buf.getvalue()


def test_giant_page_is_refused_not_rendered():
    # 20000 x 20000 pt at 1 px/pt = 400 Mpx: must be refused before render.
    with pytest.raises(ValueError, match="page too large"):
        core.convert_bytes(_blank(20000, 20000))


def test_too_many_pages_is_refused():
    with pytest.raises(ValueError, match="too many pages"):
        core.convert_bytes(_blank(612, 792, pages=core.MAX_PAGES + 1))


def test_oversized_file_is_refused(tmp_path):
    p = tmp_path / "eBay_label_big.pdf"
    p.write_bytes(b"%PDF-1.4\n" + b"0" * (core.MAX_INPUT_BYTES + 1))
    with pytest.raises(ValueError, match="too large"):
        core.convert_file(str(p))


def test_non_pdf_is_refused(tmp_path):
    p = tmp_path / "eBay_label_fake.pdf"
    p.write_bytes(b"MZ\x90\x00 definitely an exe")
    with pytest.raises(ValueError, match="not a PDF"):
        core.convert_file(str(p))


def _armed_label():
    """A real-shaped label carrying JS in every place we know of."""
    r = PdfReader(io.BytesIO(_fake_ebay_label()))
    w = PdfWriter()
    w.append(r)
    js = DictionaryObject({NameObject("/S"): NameObject("/JavaScript"),
                           NameObject("/JS"): TextStringObject("app.alert(1)")})
    page = w.pages[0]
    page[NameObject("/AA")] = DictionaryObject({NameObject("/O"): js})
    link = DictionaryObject({
        NameObject("/Type"): NameObject("/Annot"),
        NameObject("/Subtype"): NameObject("/Link"),
        NameObject("/Rect"): ArrayObject([]),
        NameObject("/A"): js,
    })
    page[NameObject("/Annots")] = ArrayObject([w._add_object(link)])
    w.add_js("app.alert('doc')")
    w._root_object[NameObject("/OpenAction")] = js
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def _active_content(pdf_bytes):
    r = PdfReader(io.BytesIO(pdf_bytes))
    found = [k for k in ("/OpenAction", "/AA", "/Names", "/AcroForm") if k in r.trailer["/Root"]]
    for p in r.pages:
        found += [k for k in ("/AA", "/Annots") if k in p]
    return found


def test_active_content_is_stripped():
    armed = _armed_label()
    assert _active_content(armed)  # the fixture really is armed
    out = core.convert_bytes(armed)
    assert _active_content(out) == []
    assert b"JavaScript" not in out


def test_active_content_stripped_in_combine(tmp_path):
    a = tmp_path / "eBay_label_a.pdf"
    a.write_bytes(_armed_label())
    out = tmp_path / "c.pdf"
    core.combine_files([str(a), str(a)], str(out))
    assert _active_content(out.read_bytes()) == []


def test_already_4x6_page_is_still_sanitized():
    # The pass-through path must not become a way to smuggle JS through.
    r = PdfReader(io.BytesIO(_blank(288, 432)))
    w = PdfWriter()
    w.append(r)
    w.pages[0][NameObject("/AA")] = DictionaryObject()
    w._root_object[NameObject("/OpenAction")] = DictionaryObject()
    buf = io.BytesIO()
    w.write(buf)
    assert _active_content(core.convert_bytes(buf.getvalue())) == []


@pytest.mark.skipif(not hasattr(os, "symlink") or sys.platform == "win32", reason="posix symlinks")
def test_planted_symlink_at_output_is_replaced_not_followed(tmp_path):
    src = tmp_path / "eBay_label_x.pdf"
    src.write_bytes(_fake_ebay_label())
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me")
    os.symlink(victim, core.output_path(str(src)))
    dst = core.convert_file(str(src))
    assert victim.read_text() == "keep me"
    assert not os.path.islink(dst) and PdfReader(dst).pages
