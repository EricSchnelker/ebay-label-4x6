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


# --- Decompression bombs -----------------------------------------------------
# Found 2026-10 by adversarial review: a 600 KB file whose content stream
# inflates to 600 MB drove the desktop converter to a 1.27 GB peak (12 s).
# The watcher would do that on its own to any "eBay_label*.pdf" a website
# drops into Downloads. Each test runs the converter in a fresh process and
# reads its peak memory (VmHWM) so an inflate cannot hide.

import subprocess
import zlib

from pypdf.generic import DictionaryObject as _D, NumberObject, StreamObject

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _flate_bomb_stream(mb):
    co = zlib.compressobj(9)
    chunk = b" " * (1 << 20)
    s = StreamObject()
    s._data = b"".join(co.compress(chunk) for _ in range(mb)) + co.flush()
    s[NameObject("/Filter")] = NameObject("/FlateDecode")
    return s


def _bomb_pdf(where, mb=600):
    w = PdfWriter()
    page = w.add_blank_page(612, 792)
    if where == "content":
        page[NameObject("/Contents")] = w._add_object(_flate_bomb_stream(mb))
    elif where == "form":
        # Bomb hidden one level down, inside a form XObject the page draws.
        form = _flate_bomb_stream(mb)
        form.update({NameObject("/Type"): NameObject("/XObject"),
                     NameObject("/Subtype"): NameObject("/Form"),
                     NameObject("/BBox"): ArrayObject([NumberObject(0), NumberObject(0),
                                                       NumberObject(288), NumberObject(432)])})
        page[NameObject("/Resources")] = _D({NameObject("/XObject"): _D({NameObject("/F"): w._add_object(form)})})
        draw = StreamObject()
        draw._data = b"q 0 -1 1 0 90 734 cm /F Do Q"
        page[NameObject("/Contents")] = w._add_object(draw)
    elif where == "image":
        # A tiny stream claiming a 100000 x 100000 px image: the renderer
        # would allocate for the declared size.
        img = StreamObject()
        img._data = zlib.compress(b"\x00" * 1024)
        img.update({NameObject("/Type"): NameObject("/XObject"), NameObject("/Subtype"): NameObject("/Image"),
                    NameObject("/Width"): NumberObject(100000), NameObject("/Height"): NumberObject(100000),
                    NameObject("/ColorSpace"): NameObject("/DeviceGray"),
                    NameObject("/BitsPerComponent"): NumberObject(8),
                    NameObject("/Filter"): NameObject("/FlateDecode")})
        page[NameObject("/Resources")] = _D({NameObject("/XObject"): _D({NameObject("/I"): w._add_object(img)})})
        draw = StreamObject()
        draw._data = b"q 612 0 0 792 0 0 cm /I Do Q"
        page[NameObject("/Contents")] = w._add_object(draw)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def _convert_in_child(path):
    code = (
        "import re, sys; sys.path.insert(0, %r)\n"
        "import ebay_label_4x6 as m\n"
        "try:\n    m.convert_file(%r); print('RESULT converted')\n"
        "except ValueError as e:\n    print('RESULT refused', e)\n"
        "print('PEAK_KB', re.search(r'VmHWM:\\s+(\\d+)', open('/proc/self/status').read()).group(1))\n"
    ) % (ROOT, str(path))
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
    out = r.stdout
    assert "PEAK_KB" in out, r.stdout + r.stderr
    return out.split("RESULT ")[1].splitlines()[0], int(out.split("PEAK_KB ")[1].split()[0]) / 1024


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="peak memory via /proc (VmHWM)")
@pytest.mark.parametrize("where", ["content", "form", "image"])
def test_decompression_bomb_refused_without_inflating(tmp_path, where):
    p = tmp_path / f"eBay_label_{where}.pdf"
    p.write_bytes(_bomb_pdf(where))
    assert p.stat().st_size < 2 * 1024 * 1024
    result, peak_mb = _convert_in_child(p)
    assert result.startswith("refused"), result
    assert peak_mb < 250, f"{where} bomb: peak {peak_mb:.0f} MB"


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="peak memory via /proc (VmHWM)")
def test_real_shaped_label_still_converts_under_the_budget(tmp_path):
    p = tmp_path / "eBay_label_ok.pdf"
    p.write_bytes(_fake_ebay_label())
    result, _ = _convert_in_child(p)
    assert result == "converted"
