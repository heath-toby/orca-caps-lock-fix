#!/usr/bin/env python3
"""A caps lock logger that reads the state which actually decides characters.

Toby asked for this in as many words: *"I think, we need a proper logger.
Outside Orca, outside it all, but rather, something true, that we can read when
caps lock goes on/off, and we can find out what drives it."*

The first attempt (``tools/watch-lock.py``) was built to be trustworthy and was
not, because it read XKB -- and on a Wayland session XKB is XWayland's *copy*
of the lock state, not the compositor's. So is ``xset``, so is
``Gdk.Keymap.get_caps_lock_state``, and so is every mask AT-SPI hands Orca.

This reads both, side by side, and labels which is which:

* **compositor** -- the lock bit in a GDK key event's ``state``, in a window on
  the Wayland backend. GTK gets that from ``wl_keyboard.modifiers``, which is
  the compositor telling its clients what is locked. The character in the same
  line comes from the same keymap and the same state, so it is the real answer
  to "would this key produce a capital".
* **xwayland** -- ``XkbGetState().locked_mods``, read over the X socket with
  ctypes. This is the copy. When the two columns disagree, that disagreement
  is the whole bug.

Run it, click into its window, and then do the thing you want explained: press
caps lock slowly, press it quickly, hold it, and type letters in between. Every
key is a line. Close the window to finish.

Usage: python3 tools/true-lock-log.py [--log PATH]
"""

from __future__ import annotations

# Must be set before GDK opens a display, or this logs XWayland's copy twice
# and says it is the truth.
import os

os.environ.setdefault("GDK_BACKEND", "wayland")

import argparse  # noqa: E402
import ctypes  # noqa: E402
import ctypes.util  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402

_LOCK_BIT = Gdk.ModifierType.LOCK_MASK
_SHIFT_BIT = Gdk.ModifierType.SHIFT_MASK
_XKB_LOCK_BIT = 1 << 1  # XKB's own lock modifier, which is bit 1 there too.
_XKB_USE_CORE_KBD = 0x0100


class _XkbStateRec(ctypes.Structure):
    _fields_ = [
        ("group", ctypes.c_ubyte), ("locked_group", ctypes.c_ubyte),
        ("base_group", ctypes.c_ushort), ("latched_group", ctypes.c_ushort),
        ("mods", ctypes.c_ubyte), ("base_mods", ctypes.c_ubyte),
        ("latched_mods", ctypes.c_ubyte), ("locked_mods", ctypes.c_ubyte),
        ("compat_state", ctypes.c_ubyte), ("grab_mods", ctypes.c_ubyte),
        ("compat_grab_mods", ctypes.c_ubyte), ("lookup_mods", ctypes.c_ubyte),
        ("compat_lookup_mods", ctypes.c_ubyte), ("ptr_buttons", ctypes.c_ushort),
    ]


class XWaylandLock:
    """XWayland's copy of the lock state, or None if it cannot be read."""

    def __init__(self) -> None:
        self._x11 = None
        self._display = None
        try:
            name = ctypes.util.find_library("X11")
            if not name:
                return
            x11 = ctypes.CDLL(name)
            x11.XOpenDisplay.restype = ctypes.c_void_p
            display = x11.XOpenDisplay(None)
            if not display:
                return
            self._x11, self._display = x11, display
        except Exception:  # pylint: disable=broad-exception-caught
            self._x11 = self._display = None

    def read(self) -> bool | None:
        if self._x11 is None:
            return None
        state = _XkbStateRec()
        try:
            if self._x11.XkbGetState(ctypes.c_void_p(self._display),
                                     _XKB_USE_CORE_KBD,
                                     ctypes.byref(state)) != 0:
                return None
        except Exception:  # pylint: disable=broad-exception-caught
            return None
        return bool(state.locked_mods & _XKB_LOCK_BIT)


def describe_key(event) -> str:
    """What this key produced, which is the only unimpeachable evidence."""
    name = Gdk.keyval_name(event.keyval) or f"0x{event.keyval:x}"
    produced = event.string or ""
    if produced == "\r":
        produced = "\\r"
    elif produced == "\n":
        produced = "\\n"
    elif produced == "\t":
        produced = "\\t"
    elif produced and not produced.isprintable():
        produced = repr(produced)
    case = ""
    if len(produced) == 1 and produced.isalpha():
        case = " UPPER" if produced.isupper() else " lower"
    return f"{name:<12} produced={produced!r:<6}{case}"


class Logger:
    """Writes one line per key event, and keeps the running comparison."""

    def __init__(self, path: str) -> None:
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.handle = open(path, "a", buffering=1)  # pylint: disable=consider-using-with
        self.xwayland = XWaylandLock()
        self.started = time.monotonic()
        self.last_key_at: float | None = None
        self.keys = 0
        self.divergences = 0
        self.transitions = 0
        self.last_compositor: bool | None = None

    def say(self, line: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        millis = int(time.time() * 1000) % 1000
        self.handle.write(f"{stamp}.{millis:03d} {line}\n")

    def banner(self) -> None:
        display = Gdk.Display.get_default()
        backend = type(display).__name__ if display is not None else "none"
        wayland = "Wayland" in backend
        self.say(f"--- started; GDK backend is {backend} ---")
        if not wayland:
            self.say("!!! NOT the Wayland backend: the 'compositor' column "
                     "below is XWayland's copy as well, and this log cannot "
                     "settle anything. Run with GDK_BACKEND=wayland.")
        if self.xwayland.read() is None:
            self.say("--- XWayland's copy could not be read; that column "
                     "will say '?' ---")
        self.say(f"--- XWayland says caps lock is "
                 f"{_onoff(self.xwayland.read())} right now ---")
        return wayland

    def key(self, event, pressed: bool) -> None:
        self.keys += 1
        now = time.monotonic()
        gap = "" if self.last_key_at is None else f" +{(now - self.last_key_at)*1000:.0f}ms"
        self.last_key_at = now

        compositor = bool(event.state & _LOCK_BIT)
        shift = bool(event.state & _SHIFT_BIT)
        x_state = self.xwayland.read()

        if self.last_compositor is not None and compositor != self.last_compositor:
            self.transitions += 1
        self.last_compositor = compositor

        flag = ""
        if x_state is not None and x_state != compositor:
            self.divergences += 1
            flag = "   <-- THEY DISAGREE"

        self.say(f"{'press  ' if pressed else 'release'} "
                 f"{describe_key(event)}  "
                 f"compositor={_onoff(compositor)} "
                 f"xwayland={_onoff(x_state)}"
                 f"{' shift' if shift else ''}"
                 f"{gap}{flag}")

    def finish(self) -> None:
        self.say(f"--- finished: {self.keys} key events, "
                 f"{self.transitions} compositor lock changes, "
                 f"{self.divergences} lines where the two states disagreed ---")
        self.handle.close()


def _onoff(value: bool | None) -> str:
    if value is None:
        return "?"
    return "ON " if value else "off"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--log",
        default=os.path.join(
            os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")),
            "orca", "caps_lock_fix", "true-lock.log"))
    args = parser.parse_args()

    logger = Logger(args.log)
    wayland = logger.banner()

    window = Gtk.Window(title="Caps lock logger")
    window.set_default_size(560, 180)
    label = Gtk.Label()
    label.set_line_wrap(True)
    label.set_margin_start(12)
    label.set_margin_end(12)
    label.set_text(
        "Caps lock logger. Every key you press in this window is written to\n"
        f"{args.log}\n\n"
        + ("Reading the compositor's lock state and XWayland's copy side by side."
           if wayland else
           "WARNING: not on the Wayland backend. This log cannot settle anything.")
        + "\n\nPress caps lock slowly, then quickly, then hold it, typing letters\n"
          "in between. Close this window when you are done.")
    window.add(label)
    window.connect("key-press-event", lambda _w, event: logger.key(event, True))
    window.connect("key-release-event", lambda _w, event: logger.key(event, False))
    window.connect("destroy", lambda _w: Gtk.main_quit())
    window.show_all()
    window.present()
    Gtk.main()

    logger.finish()
    print(f"log written to {args.log}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
