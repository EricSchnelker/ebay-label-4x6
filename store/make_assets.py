#!/usr/bin/env python3
"""Generate the Chrome Web Store images: screenshots (1280x800) + small promo tile (440x280).

    python store/make_assets.py          # needs: pypdf pypdfium2 pillow reportlab, node + playwright

PRIVACY RULE: every label in these images is SYNTHETIC. _demo_label() draws a
realistic-looking but entirely fake label (made-up names, 00000 ZIP codes,
a zero-filled tracking number) with the same structure as eBay's real PDF
(a 288x432 form XObject drawn with cm 0 -1 1 0 90 734.46 on a letter sheet),
so the real converter code processes it. Never feed a downloaded label to
this script: real labels carry buyers' names and home addresses.
"""

import io
import json
import os
import subprocess
import sys

import pypdfium2
from PIL import Image, ImageDraw, ImageFont
from reportlab.graphics.barcode import code128
from reportlab.pdfgen import canvas

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import ebay_label_4x6 as core  # noqa: E402

SHOTS = os.path.join(HERE, "screenshots")
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

# Palette shared by every image (matches the extension icon).
BG = (246, 247, 249)
INK = (29, 35, 48)
MUTED = (91, 100, 117)
ACCENT = (0, 100, 200)


def _font(size, bold=False):
    path = FONT_BOLD if bold and os.path.exists(FONT_BOLD) else FONT
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def _demo_label(n=1):
    """A synthetic, eBay-structured label sheet. All data is fake."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(612, 792))
    c.beginForm("label", 0, 0, 288, 432)
    c.setLineWidth(1.5)
    c.rect(8, 8, 272, 416)
    # Postage block
    c.rect(8, 352, 272, 72)
    c.setFont("Helvetica-Bold", 30)
    c.drawString(22, 372, "G")
    c.setFont("Helvetica-Bold", 7)
    c.drawString(64, 408, "US POSTAGE PAID")
    c.setFont("Helvetica", 6.5)
    c.drawString(64, 398, "SAMPLE LABEL")
    c.drawString(64, 389, "0 lbs 4 ozs  Zone 5")
    c.rect(190, 366, 82, 50)
    c.setFont("Helvetica", 5.5)
    c.drawString(196, 388, "DEMO ONLY - NOT VALID")
    # Service banner
    c.setFont("Helvetica-Bold", 15)
    c.drawCentredString(144, 330, "USPS GROUND ADVANTAGE")
    c.line(8, 322, 280, 322)
    # From
    c.setFont("Helvetica", 8)
    for i, line in enumerate(["SAMPLE SELLER", "100 EXAMPLE ST", "ANYTOWN XX 00000"]):
        c.drawString(16, 308 - i * 10, line)
    # To
    c.setFont("Helvetica-Bold", 7)
    c.drawString(40, 238, "SHIP TO:")
    c.setFont("Helvetica", 10)
    for i, line in enumerate([f"DEMO BUYER {n}", "200 PLACEHOLDER AVE", "SAMPLETOWN XX 00000"]):
        c.drawString(40, 222 - i * 13, line)
    # Tracking
    c.line(8, 160, 280, 160)
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(144, 148, "USPS TRACKING #")
    bc = code128.Code128("9400000000000000000000", barHeight=70, barWidth=0.95)
    bc.drawOn(c, 144 - bc.width / 2, 62)
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(144, 48, "9400 0000 0000 0000 0000 00")
    c.endForm()
    c.saveState()
    c.transform(0, -1, 1, 0, 90, 734.46)  # eBay's exact placement
    c.doForm("label")
    c.restoreState()
    c.showPage()
    c.save()
    return buf.getvalue()


def _render(pdf_bytes, page=0, scale=1.0):
    doc = pypdfium2.PdfDocument(pdf_bytes)
    img = doc[page].render(scale=scale).to_pil().convert("RGB")
    doc.close()
    return img


def _framed(img, width):
    """Scale to width, add a thin border + soft shadow so paper reads as paper."""
    h = round(img.height * width / img.width)
    img = img.resize((width, h), Image.LANCZOS)
    out = Image.new("RGB", (width + 12, h + 12), BG)
    d = ImageDraw.Draw(out)
    d.rectangle((8, 8, width + 10, h + 10), fill=(214, 218, 226))
    out.paste(img, (2, 2))
    d.rectangle((1, 1, width + 2, h + 2), outline=(190, 196, 206))
    return out


def shot_before_after(path):
    before_pdf = _demo_label()
    after_pdf = core.convert_bytes(before_pdf)  # the real converter
    W, H = 1280, 800
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    d.text((W // 2, 52), "eBay's label, fixed for your 4x6 printer", font=_font(40, True), fill=INK, anchor="mm")
    d.text((W // 2, 100), "Sideways on a letter page  \u2192  upright 4x6, barcodes untouched",
           font=_font(22), fill=MUTED, anchor="mm")
    # Sized so both papers AND their captions fit inside 800 px.
    before = _framed(_render(before_pdf, scale=0.78), 420)
    after = _framed(_render(after_pdf, scale=1.5), 330)
    top = 140
    im.paste(before, (130, top))
    im.paste(after, (W - 130 - after.width, top + (before.height - after.height) // 2))
    # Arrow
    ax = (130 + before.width + W - 130 - after.width) // 2
    d.polygon([(ax - 60, 445), (ax + 20, 445), (ax + 20, 420), (ax + 70, 470),
               (ax + 20, 520), (ax + 20, 495), (ax - 60, 495)], fill=ACCENT)
    cap_y = top + before.height + 28  # one caption line for both, inside the frame
    assert cap_y + 14 < H, "caption would be cut off"
    d.text((130 + before.width // 2, cap_y), "What eBay gives you (8.5 x 11)",
           font=_font(20), fill=MUTED, anchor="mm")
    d.text((W - 130 - after.width // 2, cap_y), "What you print (4 x 6)",
           font=_font(20, True), fill=INK, anchor="mm")
    im.save(path, optimize=True)


def shot_converter_page(path):
    """The real converter page in Chromium, after combining three demo labels."""
    tmp = os.path.join(HERE, ".tmp")
    os.makedirs(tmp, exist_ok=True)
    inputs = []
    for i in range(3):
        p = os.path.join(tmp, f"demo_label_{i + 1}.pdf")
        with open(p, "wb") as f:
            f.write(_demo_label(i + 1))
        inputs.append(p)
    script = os.path.join(HERE, "shot_converter.js")
    subprocess.run(["node", script, path, *inputs], check=True, timeout=120)
    for p in inputs:
        os.remove(p)
    with Image.open(path) as im:
        im.convert("RGB").save(path, optimize=True)


def promo_small(path):
    W, H = 440, 280
    im = Image.new("RGB", (W, H), (20, 40, 72))
    d = ImageDraw.Draw(im)
    icon = Image.open(os.path.join(ROOT, "extension", "icons", "128.png")).convert("RGBA").resize((96, 96))
    im.paste(icon, (32, (H - 96) // 2 - 20), icon)
    d.text((148, 92), "4x6 Label", font=_font(34, True), fill=(255, 255, 255))
    d.text((148, 132), "Fixer", font=_font(34, True), fill=(255, 255, 255))
    d.text((148, 182), "eBay labels \u2192 upright 4x6", font=_font(17), fill=(190, 210, 235))
    d.text((32, 236), "Automatic  |  Batch  |  Offline", font=_font(15), fill=(150, 175, 210))
    im.save(path, optimize=True)


def main():
    os.makedirs(SHOTS, exist_ok=True)
    shot_before_after(os.path.join(SHOTS, "1-before-after.png"))
    shot_converter_page(os.path.join(SHOTS, "2-converter-page.png"))
    promo_small(os.path.join(HERE, "promo-small-440x280.png"))
    print(json.dumps(sorted(os.listdir(SHOTS))))


if __name__ == "__main__":
    main()
