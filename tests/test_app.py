"""Tests for ebay_label_4x6_app.py's per-OS plumbing (autostart, single
instance, file dispatch). The tray UI itself needs a desktop session and is
exercised by hand; everything it calls into is covered here or in
test_ebay_label_4x6.py.

The macOS / Linux autostart writers are plain file writes, so both are tested
on any POSIX runner by flipping the module's platform flags.
"""

import os
import plistlib
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ebay_label_4x6_app as app  # noqa: E402

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="file-based autostart is macOS/Linux")


@pytest.fixture
def home(tmp_path, monkeypatch):
    # Point every per-user path at a temp dir so tests never touch the real
    # autostart entries of whoever runs them.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    return tmp_path


@posix_only
def test_linux_autostart_roundtrip(home, monkeypatch):
    monkeypatch.setattr(app, "IS_MAC", False)
    assert not app.autostart_enabled()
    app.set_autostart(True)
    entry = open(app._autostart_file()).read()
    assert entry.startswith("[Desktop Entry]") and "Exec=" in entry
    assert app.autostart_enabled()
    app.set_autostart(False)
    assert not app.autostart_enabled()


@posix_only
def test_mac_launch_agent_is_valid_plist(home, monkeypatch):
    monkeypatch.setattr(app, "IS_MAC", True)
    app.set_autostart(True)
    path = app._autostart_file()
    assert path.endswith(os.path.join("Library", "LaunchAgents", app.MAC_AGENT_ID + ".plist"))
    with open(path, "rb") as f:
        plist = plistlib.load(f)
    assert plist["RunAtLoad"] is True and plist["ProgramArguments"] == app._launch_argv()
    app.set_autostart(False)
    assert not os.path.exists(path)


@posix_only
def test_single_instance_lock(home, tmp_path):
    import subprocess
    assert app._single_instance() is True
    # A second process must see the lock held and back off.
    code = ("import sys; sys.path.insert(0, %r); import ebay_label_4x6_app as a; "
            "print(a._single_instance())") % os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         env=dict(os.environ)).stdout.strip()
    assert out == "False"


def test_run_files_reports_non_pdf(monkeypatch):
    # Dropping a non-PDF must surface an error, not crash the app.
    seen = []
    monkeypatch.setattr(app, "_message", lambda text, **k: seen.append(text))
    app.run_files(["notes.txt"])
    assert seen and "no PDF" in seen[0]


def test_desktop_exec_escaping():
    # freedesktop Exec rules: inside double quotes, " ` $ \ are backslash-
    # escaped, and a literal % must be %%. An unescaped $ or ` in a path
    # would otherwise be expanded by the launcher's shell-like parser.
    line = app._desktop_exec(['/opt/my app/run', '/home/u/$HOME `x` "q" 100%\\'])
    assert line == '"/opt/my app/run" "/home/u/\\$HOME \\`x\\` \\"q\\" 100%%\\\\"'
