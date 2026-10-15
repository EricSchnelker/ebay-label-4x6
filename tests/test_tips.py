"""Tip links: one source of truth (extension/tips.json), shown on the converter
page, in the README and on GitHub's Sponsor button (.github/FUNDING.yml).

A tip link moves money, so it is checked like one: https only, and only on the
known payment sites. A typo'd or guessed handle sends tips to a stranger, so
no entry may be added without the owner confirming the exact URL.
"""

import json
import os
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALLOWED_HOSTS = {"github.com", "ko-fi.com", "buymeacoffee.com", "www.buymeacoffee.com",
                 "paypal.me", "www.paypal.me", "venmo.com", "account.venmo.com"}


def _tips():
    with open(os.path.join(ROOT, "extension", "tips.json"), encoding="utf-8") as f:
        return json.load(f)


def test_tips_are_safe_links():
    tips = _tips()
    assert tips, "at least one tip link"
    for t in tips:
        assert set(t) == {"name", "url"}, t
        u = urlparse(t["url"])
        assert u.scheme == "https" and u.hostname in ALLOWED_HOSTS, t["url"]
        assert not u.username and not u.password and not u.query and not u.fragment, t["url"]


def test_github_sponsors_points_at_the_repo_owner():
    urls = [t["url"] for t in _tips()]
    assert "https://github.com/sponsors/EricSchnelker" in urls


def test_tips_shown_everywhere_from_the_same_list():
    tips = _tips()
    readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
    funding = open(os.path.join(ROOT, ".github", "FUNDING.yml"), encoding="utf-8").read()
    for t in tips:
        assert t["url"] in readme, f"README is missing {t['url']}"
    assert "github: [EricSchnelker]" in funding
    # The converter page renders the list from tips.json, never a hardcoded copy.
    page_js = open(os.path.join(ROOT, "extension", "convert.js"), encoding="utf-8").read()
    assert "tips.json" in page_js
    import re
    assert not re.search(r"\.innerHTML\s*[+]?=|insertAdjacentHTML|outerHTML\s*=", page_js)  # DOM APIs only
