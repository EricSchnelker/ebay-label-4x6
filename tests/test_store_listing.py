"""Chrome Web Store submission checks.

The store rejects an upload or a listing for reasons that are cheap to check
here instead of after a multi-day review: manifest limits, a brand used as if
the extension were eBay's own, missing listing images at the exact sizes the
dashboard demands, a privacy policy that does not exist, or permissions with
no written justification.
"""

import json
import os
import re

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXT = os.path.join(ROOT, "extension")
STORE = os.path.join(ROOT, "store")


def _manifest():
    with open(os.path.join(EXT, "manifest.json"), encoding="utf-8") as f:
        return json.load(f)


def test_manifest_store_limits():
    m = _manifest()
    assert len(m["name"]) <= 75                      # store limit
    assert len(m["description"]) <= 132              # store limit
    assert re.fullmatch(r"\d+(\.\d+){0,3}", m["version"])
    # MAIN-world content scripts (page_hook.js) need Chrome 111+.
    assert int(m.get("minimum_chrome_version", "0")) >= 111
    assert m.get("homepage_url", "").startswith("https://github.com/EricSchnelker/ebay-label-4x6")


def test_name_does_not_present_as_ebay():
    # Brand only descriptively ("for eBay ..."), never as the product's name.
    name = _manifest()["name"]
    assert not name.lower().startswith("ebay"), name
    assert "for eBay" in name


def test_listing_images_exact_sizes():
    shots = sorted(f for f in os.listdir(os.path.join(STORE, "screenshots")) if f.endswith(".png"))
    assert 1 <= len(shots) <= 5
    for f in shots:
        with Image.open(os.path.join(STORE, "screenshots", f)) as im:
            assert im.size == (1280, 800), (f, im.size)
            assert im.mode in ("RGB",), (f, im.mode)  # store rejects alpha in screenshots
    with Image.open(os.path.join(STORE, "promo-small-440x280.png")) as im:
        assert im.size == (440, 280) and im.mode == "RGB"
    with Image.open(os.path.join(EXT, "icons", "128.png")) as im:
        assert im.size == (128, 128)


def test_every_permission_is_justified_and_privacy_policy_exists():
    listing = open(os.path.join(STORE, "listing.md"), encoding="utf-8").read()
    m = _manifest()
    for perm in m["permissions"] + m["host_permissions"]:
        assert f"`{perm}`" in listing, f"no justification for {perm}"
    assert "Single purpose" in listing
    assert "remote code" in listing.lower()
    privacy = open(os.path.join(ROOT, "PRIVACY.md"), encoding="utf-8").read()
    assert "does not collect" in privacy
    # The listing must link the policy at its public URL.
    assert "https://github.com/EricSchnelker/ebay-label-4x6/blob/main/PRIVACY.md" in listing


def test_no_real_label_data_in_store_assets():
    # Screenshots are generated from the synthetic test label only. Guard the
    # generator source against ever pointing at a real downloaded label.
    gen = open(os.path.join(STORE, "make_assets.py"), encoding="utf-8").read()
    assert "def _demo_label" in gen and "SYNTHETIC" in gen
    # The only PDFs it may open are the demo labels it writes itself.
    assert not re.search(r"Downloads|eBay_label_\d|open\([^)]*\.pdf['\"]\s*,\s*['\"]rb", gen)
