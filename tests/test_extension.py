"""Tests for the Chrome extension's converter (extension/label4x6.js).

Runs the real extension code under Node via extension/test/convert_cli.js and
checks the output with the same render-based assertions as the desktop tests
(output exactly 4x6, label upright, no active content). Skipped when Node is
not installed; CI installs it.
"""

import json
import os
import shutil
import subprocess
import sys

import pypdfium2
import pytest
from pypdf import PdfReader

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from test_ebay_label_4x6 import _dark_fraction, _fake_ebay_label  # noqa: E402
from test_hardening import _active_content, _armed_label, _blank  # noqa: E402

CLI = os.path.join(os.path.dirname(HERE), "extension", "test", "convert_cli.js")
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")


def _run(tmp_path, *pdfs):
    ins = []
    for i, data in enumerate(pdfs):
        p = tmp_path / f"in{i}.pdf"
        p.write_bytes(data)
        ins.append(str(p))
    out = tmp_path / "out.pdf"
    r = subprocess.run([NODE, CLI, str(out), *ins], capture_output=True, text=True, timeout=60)
    return r, out


def _assert_upright_pages(path, n):
    r = PdfReader(str(path))
    assert len(r.pages) == n
    doc = pypdfium2.PdfDocument(str(path))
    for i in range(n):
        p = r.pages[i]
        assert (round(float(p.mediabox.width)), round(float(p.mediabox.height))) == (288, 432)
        img = doc[i].render(scale=1).to_pil().convert("L")
        # TOP bar in the top band, nothing like it in the bottom band.
        assert _dark_fraction(img, (40, 0, 248, 90)) > 0.15
        assert _dark_fraction(img, (40, 342, 248, 432)) < 0.05
    doc.close()


@pytest.mark.parametrize("rotate_deg", [-90, 90])
def test_extension_makes_upright_4x6(tmp_path, rotate_deg):
    r, out = _run(tmp_path, _fake_ebay_label(rotate_deg))
    assert r.returncode == 0, r.stderr
    _assert_upright_pages(out, 1)


def test_extension_combines(tmp_path):
    r, out = _run(tmp_path, _fake_ebay_label(-90), _fake_ebay_label(90), _fake_ebay_label(-90))
    assert r.returncode == 0, r.stderr
    _assert_upright_pages(out, 3)


def test_extension_strips_active_content(tmp_path):
    armed = _armed_label()
    assert _active_content(armed)
    r, out = _run(tmp_path, armed)
    assert r.returncode == 0, r.stderr
    data = out.read_bytes()
    assert _active_content(data) == []
    assert b"JavaScript" not in data


def test_extension_already_4x6_passes_clean(tmp_path):
    r, out = _run(tmp_path, _blank(288, 432))
    assert r.returncode == 0, r.stderr
    assert len(PdfReader(str(out)).pages) == 1


def test_extension_refuses_non_ebay_layout(tmp_path):
    # A plain letter page with no 4x6 label form must be refused, not guessed at.
    r, _ = _run(tmp_path, _blank(612, 792))
    assert r.returncode == 2 and "does not look like an eBay label" in r.stderr


def test_extension_refuses_non_pdf(tmp_path):
    r, _ = _run(tmp_path, b"MZ\x90\x00 not a pdf")
    assert r.returncode == 2 and "not a PDF" in r.stderr


def test_extension_names():
    r = subprocess.run([NODE, CLI, "--names", "eBay_label_01-2.pdf", "C:\\dl\\EBAY_LABEL_x.PDF",
                        "eBay_label_01-2_4x6.pdf", "invoice.pdf"],
                       capture_output=True, text=True, timeout=30)
    got = json.loads(r.stdout)
    assert got == [[True, "eBay_label_01-2_4x6.pdf"], [True, "EBAY_LABEL_x_4x6.pdf"],
                   [False, "eBay_label_01-2_4x6_4x6.pdf"], [False, "invoice_4x6.pdf"]]


def _content_bomb():
    """A letter page whose content stream is ~60 KB of Flate that inflates to
    60 MB of spaces -- a decompression bomb aimed at the content parser."""
    import zlib
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, NameObject, StreamObject
    w = PdfWriter()
    page = w.add_blank_page(612, 792)
    raw = b" " * (60 * 1024 * 1024)
    s = StreamObject()
    s._data = zlib.compress(raw, 9)
    s[NameObject("/Filter")] = NameObject("/FlateDecode")
    page[NameObject("/Contents")] = w._add_object(s)
    import io as _io
    buf = _io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def _node_peak_mb(stderr):
    import re
    m = re.search(r"maxrss_kb=(\d+)", stderr)
    assert m, stderr
    return int(m.group(1)) / 1024


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="exact peak memory via /proc (VmHWM)")
def test_extension_refuses_content_bomb_without_inflating(tmp_path):
    bomb = _content_bomb()
    assert len(bomb) < 200 * 1024  # small on disk...
    # Baseline: the SAME refusal path on a harmless letter page. (A successful
    # conversion is no baseline: pdf-lib's save alone peaks ~115 MB.)
    r_ok, _ = _run(tmp_path, _blank(612, 792))
    assert r_ok.returncode == 2, r_ok.stderr
    baseline = _node_peak_mb(r_ok.stderr)
    r, _ = _run(tmp_path, bomb)
    # ...refused as not-an-eBay-label, and WITHOUT inflating the 60 MB: the
    # converter's own peak stays within 30 MB of refusing a harmless page
    # (measured: ~57 vs ~57 MB fixed; ~126 MB when the bomb was inflated).
    assert r.returncode == 2 and "does not look like an eBay label" in r.stderr, r.stderr
    peak = _node_peak_mb(r.stderr)
    assert peak < baseline + 30, f"peak {peak:.0f} MB vs baseline {baseline:.0f} MB: the bomb was inflated"
