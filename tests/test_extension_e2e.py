"""Real-browser test of the Chrome extension (extension/test/e2e.js).

Loads the unpacked extension into Playwright's Chromium and checks: the
background worker starts, the converter page combines two labels, and auto
mode converts an eBay download while ignoring a non-eBay one. Skipped unless
Node can resolve the `playwright` package (CI's extension job installs it).
"""

import os
import shutil
import subprocess
import sys

import pytest
from pypdf import PdfReader

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from test_ebay_label_4x6 import _fake_ebay_label  # noqa: E402
from test_extension import _assert_upright_pages  # noqa: E402

NODE = shutil.which("node")


def _has_playwright():
    if not NODE:
        return False
    r = subprocess.run([NODE, "-e", "require.resolve('playwright')"], cwd=ROOT,
                       capture_output=True, env=dict(os.environ))
    return r.returncode == 0


pytestmark = pytest.mark.skipif(not _has_playwright(), reason="playwright (node) not installed")


def test_extension_in_chromium(tmp_path):
    fixture = tmp_path / "fixture.pdf"
    fixture.write_bytes(_fake_ebay_label())
    r = subprocess.run([NODE, os.path.join(ROOT, "extension", "test", "e2e.js"), str(fixture), str(tmp_path)],
                       cwd=ROOT, capture_output=True, text=True, timeout=180, env=dict(os.environ))
    assert r.returncode == 0, r.stdout + r.stderr
    for step in ("extension loaded", "converter page", "ignores non-eBay", "saved a converted copy",
                 "converts a blob: label after its eBay tab is closed", "ignores blob: labels from other sites"):
        assert step in r.stdout, r.stdout
    _assert_upright_pages(tmp_path / "page_combined.pdf", 2)
    _assert_upright_pages(tmp_path / "auto_out.pdf", 1)
    _assert_upright_pages(tmp_path / "auto_blob_out.pdf", 1)
    assert len(PdfReader(str(tmp_path / "auto_out.pdf")).pages) == 1
