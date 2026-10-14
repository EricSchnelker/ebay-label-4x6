"""eBay Label 4x6 -- the desktop front end (Windows, macOS, Linux) for
ebay_label_4x6.py.

PyInstaller cannot cross-compile, so .github/workflows/build.yml builds once
per OS:
  Windows  eBayLabel4x6.exe                   (windows-latest)
  macOS    eBayLabel4x6-macos-arm64.zip       (an .app bundle; Apple Silicon)
  Linux    eBayLabel4x6-linux-x86_64.tar.gz   (one ELF binary; tarred so the
                                               executable bit survives download)
All the PDF logic lives in ebay_label_4x6.py and is tested there; this file is
only the "how a person starts it" layer.

WAYS IN
  * Drop one or more PDFs onto the app (or pass them on the command line):
      one file  -> <name>_4x6.pdf next to it, opened for printing
      several   -> ONE combined eBay_labels_<time>_4x6.pdf, opened for printing
  * Open the app with no files: a tray / menu-bar icon that
      - watches Downloads and converts every new eBay_label*.pdf on arrival,
      - "Convert / combine PDFs..." opens a multi-select picker (bulk),
      - "Start at login" toggles autostart (on by default after first run),
      - "Quit" stops it.
  * Command line: anything ebay_label_4x6.py takes (convert/combine/watch).

PER-OS PLUMBING
                 autostart                                    state dir (log.txt)
  Windows        HKCU\\...\\CurrentVersion\\Run value          %LOCALAPPDATA%\\eBayLabel4x6
  macOS          ~/Library/LaunchAgents/<id>.plist            ~/Library/Application Support/eBayLabel4x6
  Linux          ~/.config/autostart/eBayLabel4x6.desktop     ~/.local/share/eBayLabel4x6

A windowed app has no console, so print() output goes to log.txt in the state
dir -- read that first if something misbehaves.
"""

import os
import subprocess
import sys
import threading
import time

# Make `import ebay_label_4x6` work both from a checkout (this file's folder)
# and inside the PyInstaller bundle (bundled module).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ebay_label_4x6 as core  # noqa: E402

APP_NAME = "eBayLabel4x6"
IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

# Windows: HKCU Run key = per-user autostart, no admin rights, and no console
# flash at logon (a .cmd in the Startup folder flashes one every time).
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

# Windows: named mutex so a second launch does not start a second watcher
# that would race the first on every download. "Local\" = per logon session.
MUTEX_NAME = "Local\\eBayLabel4x6.SingleInstance"

# macOS: LaunchAgent label (reverse-DNS by convention; also the plist name).
MAC_AGENT_ID = "io.github.ebaylabel4x6"


# ---------------------------------------------------------------------------
# Plumbing
# ---------------------------------------------------------------------------

def _app_dir():
    """Per-user state dir (created on demand) for the log + first-run marker."""
    home = os.path.expanduser("~")
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or home
    elif IS_MAC:
        base = os.path.join(home, "Library", "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share")
    d = os.path.join(base, APP_NAME)
    os.makedirs(d, exist_ok=True)
    return d


def _redirect_output():
    """No console (windowed .exe, .app, autostart): send prints to log.txt.

    Started from a terminal, output stays on the terminal. Line-buffered
    append; a line per label, so no rotation needed.
    """
    if sys.stdout is None or not sys.stdout.isatty():
        log = open(os.path.join(_app_dir(), "log.txt"), "a", buffering=1, encoding="utf-8")
        sys.stdout = sys.stderr = log
    print(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')} start argv={sys.argv[1:]}")


def _message(text, title="eBay Label 4x6", error=False):
    """Show a short notice the native way; always also logged."""
    print(f"[{title}] {text}")
    try:
        if IS_WINDOWS:
            import ctypes
            flags = 0x10 if error else 0x40  # MB_ICONERROR / MB_ICONINFORMATION
            ctypes.windll.user32.MessageBoxW(None, text, title, flags)
        elif IS_MAC:
            # AppleScript strings: escape backslashes and quotes.
            esc = text.replace("\\", "\\\\").replace('"', '\\"')
            subprocess.run(["osascript", "-e", f'display alert "{title}" message "{esc}"'],
                           check=False, timeout=60)
        else:
            # notify-send ships with mainstream Linux desktops; when absent
            # (headless) the log line above is the record.
            subprocess.run(["notify-send", title, text], check=False, timeout=5)
    except Exception:
        pass


def _open(path):
    """Open a PDF (or folder) in the default app, ready to print.

    Always absolute: a relative name starting with "-" (e.g. a downloaded
    "-x.pdf") would otherwise be parsed by xdg-open / open as an option.
    """
    path = os.path.abspath(path)
    try:
        if IS_WINDOWS:
            os.startfile(path)
        else:
            subprocess.Popen(["open" if IS_MAC else "xdg-open", path],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        print(f"[warn] could not open {path}: {e}")


def _launch_argv():
    """The argv autostart should run: the frozen app, or python + this file.

    Windows prefers pythonw.exe from a checkout so no console window opens.
    """
    if getattr(sys, "frozen", False):
        return [sys.executable]
    exe = sys.executable
    if IS_WINDOWS:
        pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if os.path.exists(pyw):
            exe = pyw
    return [exe, os.path.abspath(__file__)]


def _desktop_exec(argv):
    """Quote argv for a freedesktop .desktop Exec= line.

    Per the Desktop Entry spec: each arg in double quotes; inside them, the
    characters  " ` $ \  are backslash-escaped; and since Exec also expands
    %f/%u-style field codes, a literal % is written %%. Skipping this would
    let a path containing $(...) or a backtick run a command at every login.
    """
    out = []
    for a in argv:
        for ch in ("\\", '"', "`", "$"):
            a = a.replace(ch, "\\" + ch)
        out.append('"' + a.replace("%", "%%") + '"')
    return " ".join(out)


def _autostart_file():
    """macOS LaunchAgent plist / Linux .desktop path (None on Windows)."""
    home = os.path.expanduser("~")
    if IS_MAC:
        return os.path.join(home, "Library", "LaunchAgents", MAC_AGENT_ID + ".plist")
    if not IS_WINDOWS:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
        return os.path.join(base, "autostart", APP_NAME + ".desktop")
    return None


def autostart_enabled():
    if not IS_WINDOWS:
        return os.path.exists(_autostart_file())
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP_NAME)
            return True
    except OSError:
        return False


def set_autostart(on):
    argv = _launch_argv()
    if IS_WINDOWS:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, " ".join(f'"{a}"' for a in argv))
            else:
                try:
                    winreg.DeleteValue(k, APP_NAME)
                except OSError:
                    pass
        return
    path = _autostart_file()
    if not on:
        if os.path.exists(path):
            os.remove(path)
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if IS_MAC:
        # plistlib writes valid XML and escapes the paths for us.
        import plistlib
        with open(path, "wb") as f:
            plistlib.dump({"Label": MAC_AGENT_ID, "ProgramArguments": argv,
                           "RunAtLoad": True}, f)
    else:
        exec_line = _desktop_exec(argv)
        with open(path, "w") as f:
            f.write("[Desktop Entry]\nType=Application\nName=eBay Label 4x6\n"
                    f"Exec={exec_line}\nX-GNOME-Autostart-enabled=true\n")


def _single_instance():
    """True if we are the only tray instance (holds the lock for our lifetime)."""
    if IS_WINDOWS:
        try:
            import ctypes
            ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
            return ctypes.windll.kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS
        except Exception:
            return True
    # macOS / Linux: an flock on a file in the state dir. The handle is parked
    # on the function so it is never garbage-collected (closing it drops the lock).
    import fcntl
    fh = open(os.path.join(_app_dir(), "instance.lock"), "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return False
    _single_instance.handle = fh
    return True


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------

def run_files(paths):
    """Drop mode: convert one / combine many, then open the result."""
    try:
        out = core.process_paths(paths)
        _open(out)
    except Exception as e:
        print(f"[error] {e}")
        _message(f"Could not convert:\n{e}", error=True)


def _pick_files():
    """Multi-select file picker (tkinter ships with the python.org builds)."""
    import tkinter
    from tkinter import filedialog
    root = tkinter.Tk()
    root.withdraw()
    root.attributes("-topmost", True)  # otherwise it can open behind other windows
    paths = filedialog.askopenfilenames(
        title="Pick eBay label PDFs (select several to combine into one)",
        initialdir=core._default_downloads(),
        filetypes=[("PDF files", "*.pdf")],
    )
    root.destroy()
    return list(paths)


def _icon_image():
    """A 64x64 tray icon drawn at runtime: a white label with a barcode."""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((10, 4, 54, 60), radius=4, fill=(255, 255, 255, 255),
                        outline=(30, 30, 30, 255), width=3)
    for i, x in enumerate(range(16, 49, 3)):
        d.rectangle((x, 36, x + (1 if i % 3 else 2), 54), fill=(0, 0, 0, 255))
    d.rectangle((16, 12, 48, 16), fill=(0, 100, 200, 255))
    d.rectangle((16, 20, 40, 23), fill=(80, 80, 80, 255))
    return img


def run_tray():
    """No-files mode: tray / menu-bar icon + Downloads watcher."""
    if not _single_instance():
        _message("eBay Label 4x6 is already running -- look for its tray / menu-bar icon.")
        return
    import pystray

    # First run: turn autostart on, which is the point of a watcher. The
    # marker means a later "off" from the menu is respected on next launch.
    marker = os.path.join(_app_dir(), "autostart_initialised")
    try:
        if not os.path.exists(marker):
            set_autostart(True)
            open(marker, "w").close()
        elif autostart_enabled():
            set_autostart(True)  # re-point it in case the app was moved
    except Exception as e:
        print(f"[warn] autostart: {e}")

    state = {"watch": True}
    folder = core._default_downloads()

    def watcher():
        # core.watch() loops forever; this daemon thread dies with the app.
        core.watch(folder, core.DEFAULT_PATTERNS, open_after=False, interval=2.0,
                   enabled=lambda: state["watch"], on_converted=_open)

    def on_pick(icon, _item):
        paths = _pick_files()
        if paths:
            run_files(paths)

    def on_toggle_watch(icon, _item):
        state["watch"] = not state["watch"]

    def on_toggle_autostart(icon, _item):
        try:
            set_autostart(not autostart_enabled())
        except Exception as e:
            _message(f"Could not change autostart:\n{e}", error=True)

    menu = pystray.Menu(
        pystray.MenuItem("Convert / combine PDFs...", on_pick, default=True),
        pystray.MenuItem("Watch Downloads", on_toggle_watch, checked=lambda _i: state["watch"]),
        pystray.MenuItem("Start at login", on_toggle_autostart, checked=lambda _i: autostart_enabled()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Open Downloads", lambda i, _x: _open(folder)),
        pystray.MenuItem("Open log", lambda i, _x: _open(os.path.join(_app_dir(), "log.txt"))),
        pystray.MenuItem("Quit", lambda icon, _i: icon.stop()),
    )
    threading.Thread(target=watcher, daemon=True).start()
    # pystray must own the main thread (required by macOS AppKit).
    pystray.Icon(APP_NAME, _icon_image(), "eBay Label 4x6", menu).run()


def main():
    _redirect_output()
    args = sys.argv[1:]
    # macOS Finder adds -psn_0_XXXX when launching an app bundle; ignore it.
    args = [a for a in args if not a.startswith("-psn_")]
    if args and args[0] in ("convert", "combine", "watch", "-h", "--help"):
        core.main()  # CLI passthrough
    elif args:
        run_files(args)  # dropped files (macOS: delivered as argv by --argv-emulation)
    else:
        run_tray()


if __name__ == "__main__":
    main()
