# eBay Label 4x6

eBay's "print shipping label" PDF comes out as a full **8.5 x 11 letter page**
with the label **rotated sideways** in one corner. On a 4x6 thermal printer
(Rollo, Zebra, MUNBYN, Phomemo, ...) it prints sideways and shrunk.

This tool turns it into a proper **upright 4x6 PDF** with the barcodes at
their original size. It can also combine a batch of labels into **one**
multi-page PDF so you can print them all at once.

It runs entirely on your computer. Nothing is uploaded and nothing goes over the network.

## Download

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

The watcher processes any file in Downloads that is *named* like an eBay
label, and any website can download a file with that name. So every input is
treated as untrusted:

- **Size limits**: 25 MB per file, 500 pages, and 2000 pt per page side.
  The page limit is checked before rendering, so an oversized page cannot
  exhaust memory.
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

Each limit has a test in `tests/test_hardening.py`. To report a
vulnerability, see [SECURITY.md](SECURITY.md).

## License

MIT. See [LICENSE](LICENSE).

Not affiliated with or endorsed by eBay Inc. "eBay" is a trademark of eBay Inc.
