# Privacy policy: 4x6 Label Fixer (Chrome extension and desktop app)

_Last updated: 2026-10-15_

**4x6 Label Fixer does not collect, store, sell or share any personal data.
Nothing is sent to the developer or to anyone else.**

Shipping labels contain personal information, such as the buyer's name and
address. That is why the tool is built to work only on your own computer.

## What the extension handles, and where it goes

- **Label PDFs.** Labels you download from eBay, or drop on the converter
  page, are read and converted inside your browser. The upright 4x6 PDF is
  saved to your own Downloads folder. No file or file content leaves your
  computer.
- **Temporary label copy.** On eBay pages, the extension keeps a copy of a
  label PDF the moment eBay creates it, so it can convert it when the
  download finishes. The copy is held in the browser's session memory
  (`chrome.storage.session`), never written to disk, deleted once it has been
  used, and kept for at most 2 hours (at most 20 at a time). It is cleared
  when the browser closes.
- **Settings and status.** The on/off setting for auto-convert, and a single
  line describing the last auto-convert attempt, are stored by your browser.
  That line holds the time, the link type and the website host (for example
  "blob: from www.ebay.com"), and never the full link or any label content.
- **Network.** The extension's only network request is re-reading a label
  you just downloaded from eBay, from the same eBay address, using your
  existing eBay session. It contacts no other server: no analytics, no
  tracking, no ads, no remote code.

## The desktop app

The desktop app (Windows, macOS, Linux) converts files on your computer and
makes no network connections. Its log file stays on your computer and records
only file names and results.

## Not affiliated with eBay

This is an independent open-source tool. It is not made, endorsed or
sponsored by eBay Inc. "eBay" is a trademark of eBay Inc.

## Contact

Source code and issues: https://github.com/EricSchnelker/ebay-label-4x6
Security reports: see [SECURITY.md](SECURITY.md).
