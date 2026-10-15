# eBay Label 4x6

eBay's "print shipping label" PDF comes out as a full **8.5 x 11 letter page**
with the label **rotated sideways** in one corner. On a 4x6 thermal printer
(Rollo, Zebra, MUNBYN, Phomemo, ...) it prints sideways and shrunk.

This tool turns it into a proper **upright 4x6 PDF** with the barcodes at
their original size. It can also combine a batch of labels into **one**
multi-page PDF so you can print them all at once.

It comes as a **Chrome extension** (any OS, converts at the moment of
download) and a **desktop app** for Windows, macOS and Linux. Both run
entirely on your computer. Nothing is uploaded.

## Chrome extension (recommended)

Listed in the browser as **4x6 Label Fixer for eBay Shipping Labels**. Works
in Chrome 111+, Edge, Brave and other Chromium browsers on any OS. Chrome Web
Store submission material (listing text, permission justifications, images)
is in [`store/`](store/listing.md); the privacy policy is
[PRIVACY.md](PRIVACY.md).

1. Download `eBayLabel4x6-chrome-extension.zip` from the
   [latest release](../../releases/latest) and unzip it.
2. Open `chrome://extensions`, switch on **Developer mode** (top right),
   click **Load unpacked**, and pick the unzipped folder.

Then:

- **Automatic.** When you download a label from eBay (`eBay_label_*.pdf`),
  the extension saves an upright `eBay_label_*_4x6.pdf` next to it in
  Downloads. You can turn this off on the converter page.
- **Converter page.** Click the extension's toolbar icon. Drop one or more
  label PDFs on the page and you get them back as 4x6. Several at once are
  combined into one PDF by default.

If the automatic copy can't be made (for example, the eBay link has already
expired), a notification opens the converter page so you can drop the file
there.

**Permissions and why:** `downloads` (to see when a label finishes
downloading and save the 4x6 copy), `notifications` (to tell you when
auto-convert needs a hand), `storage` (the on/off setting and the last
auto-convert result), `scripting` and host access to `https://*.ebay.com/*`
only. An extension can't read files from disk. eBay's print page builds the
label PDF inside the page (a `blob:` link), so the extension copies the label
at the moment eBay creates it. That copy is held in memory until the
download finishes, then converted and thrown away. It works even if you've
already closed the eBay tab. The extension makes no network requests of its
own beyond re-reading a label from eBay, and reads no other sites.

The converter page shows the result of the last auto-convert, so if one
fails you can see why.

## Desktop app

Grab the build for your system from the
[latest release](../../releases/latest):

| System | File | How to run |
|---|---|---|
| Windows 10/11 | `eBayLabel4x6.exe` | Double-click. The first time, SmartScreen may say "Windows protected your PC" because the exe is not code-signed: click **More info -> Run anyway**. |
| macOS (Apple Silicon) | `eBayLabel4x6-macos-arm64.zip` | Unzip, move `eBayLabel4x6.app` to Applications. The app is not notarized, so the first time **right-click -> Open -> Open**. |
| Linux x86_64 | `eBayLabel4x6-linux-x86_64.tar.gz` | `tar xzf eBayLabel4x6-linux-x86_64.tar.gz && ./eBayLabel4x6` |

Intel Macs and other platforms can [run from source](#run-from-source).

`SHA256SUMS.txt` on each release lists the checksums. Each binary is built
from the tagged source by the public GitHub Actions workflow in
`.github/workflows/build.yml`.

## Use it

**Convert one label.** Drag the eBay PDF onto the app. A `..._4x6.pdf`
appears next to it and opens, ready to print.

**Combine many.** Drag several PDFs onto the app at once, or open the app and
pick **Convert / combine PDFs...** and multi-select them. You get one
`eBay_labels_<date-time>_4x6.pdf` with one label per page.

**Automatic.** Open the app with no files and it sits in the system tray
(macOS: menu bar). It watches your **Downloads** folder, and every new
`eBay_label*.pdf` is converted and opened as soon as it finishes downloading.
It starts at login by default. Turn that off in the tray menu
(**Start at login**).

> **Print at "Actual size" / 100% scale**, not "Fit to page", on 4x6 label
> stock. The output is already exactly 4x6.

## Run from source

Python 3.10+:

```sh
pip install -r requirements.txt
python ebay_label_4x6_app.py                  # tray app
python ebay_label_4x6.py convert label.pdf    # one file  -> label_4x6.pdf
python ebay_label_4x6.py combine *.pdf -o all_4x6.pdf
python ebay_label_4x6.py watch                # watch Downloads in a terminal
```

Run the tests with `pip install -r requirements-build.txt && python -m pytest -q`.
The extension tests need Node. For the browser test, also run
`npm install --no-save playwright@1.56.1 && npx playwright install chromium`.

## How it works

1. Render the page with PDFium and find the label's ink bounding box.
2. Crop a 6x4 window around it. This is a **crop, not a resize**, so the
   barcode bar widths stay exactly as eBay generated them and still scan.
3. Read the 90-degree rotation eBay applied from the page's own content stream
   and undo it. The fix is baked into the page content, not left as a
   `/Rotate` flag, because some printer drivers ignore that flag.

Pages that are already 4x6 pass through unchanged, except for the safety
steps below.

## Security

### Chrome extension

- Auto mode acts only on labels from an `https://` eBay origin (`ebay.com`
  or a subdomain). That can be the download link itself, the origin inside a
  `blob:` link, or the page that made a `data:` link. These are exact host
  checks, so another site that names its file `eBay_label.pdf` is not
  auto-processed. A `blob:` label is read only from a page whose origin is
  that blob's origin. A redirect away from eBay during the re-download is
  refused.
- The page hook on eBay pages is a tiny wrapper around
  `URL.createObjectURL`. It always calls the original and returns its result
  unchanged, so it can't alter or break the page. A captured copy is used
  only if that exact `blob:` link is then downloaded under an
  `eBay_label*.pdf` name. Copies stay in session memory only (never written
  to disk), at most 20 for at most 2 hours.
- The output is a new PDF that receives only the label itself: the 4x6
  form object and its fonts and images. Annotations, page actions,
  JavaScript, form fields and open actions in the source cannot reach it.
  A PDF that doesn't match eBay's layout is refused, not guessed at.
- Inputs are capped (25 MB, 500 pages). Page content is size-checked
  *before* it is decompressed: at most 16 KB compressed, and 1 MB once
  decompressed. A small file built to inflate to a huge size (a "zip bomb")
  is refused without being expanded. The page content parser is a small
  linear tokenizer that gives up on anything unusual.
- Extension pages run under a strict CSP: `script-src 'self'`, no inline
  scripts, no remote code. The only library is pdf-lib 1.17.1, vendored
  with its MIT license.

### Desktop app

The watcher processes any file in Downloads that is *named* like an eBay
label, and any website can download a file with that name. So every input is
treated as untrusted:

- **Size limits**: 25 MB per file, 500 pages, and 2000 pt per page side.
  The page limit is checked before rendering, so an oversized page cannot
  exhaust memory.
- **Decompression bombs**: before rendering, every stream the page uses
  (content, nested forms, images, fonts) is measured with a capped streaming
  decompressor. Nothing is fully decompressed during this check. Pages over
  64 MB decoded, or images over 50 megapixels, are refused. Before this
  check, a 600 KB test file reached 1.27 GB of memory. It is now refused in
  0.25 s.
- **Active content is stripped**: page actions, annotations, links,
  JavaScript and form fields never reach the output. The output is a fresh
  PDF that contains only page content. This applies even to files that are
  already 4x6, because the app opens its output automatically.
- **Safe writes**: output is written to a temporary file and atomically
  moved into place. A symlink planted at the output path gets replaced, not
  followed.
- **No network, no shell**: helper programs (`xdg-open`, `open`,
  `notify-send`, `osascript`) are started with argument lists, never through
  a shell. The Linux autostart entry is escaped per the Desktop Entry spec.

Each desktop limit has a test in `tests/test_hardening.py`. The extension's
equivalents are in `tests/test_extension.py`, and `tests/test_extension_e2e.py`
loads the extension into real Chromium. To report a
vulnerability, see [SECURITY.md](SECURITY.md).

## Support

The tool is free and open source. If it saves you time, tips are welcome:

- [GitHub Sponsors](https://github.com/sponsors/EricSchnelker)

## License

MIT. See [LICENSE](LICENSE).

Not affiliated with or endorsed by eBay Inc. "eBay" is a trademark of eBay Inc.
