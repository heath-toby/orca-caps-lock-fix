#!/usr/bin/env python3
"""Log every change of the caps lock, from outside Orca and outside the toolkit.

Asks the X server directly through XKB, which is the only reader on this
machine that has proved trustworthy: ``Gdk.Keymap.get_caps_lock_state``
reported the lock off while Orca's own event masks carried the lock bit, and
Orca's ``Atspi.generate_keyboard_event`` writes often did not land at all.
XkbGetState agrees with ``xset q`` every time and sees a change 0.04 ms after
it is made.

Nothing here touches the lock. It only watches, so it can be left running
while you press things and compared against
``~/.local/share/orca/caps_lock_fix/debug.log`` afterwards.

Usage:
    python3 tools/watch-lock.py [seconds]      # default 120

Prints one line per transition, with a monotonic offset and a wall clock time
so it lines up with Orca's own log.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import sys
import time

_XKB_USE_CORE_KBD = 0x0100
_LOCK_MASK = 1 << 1


class _XkbStateRec(ctypes.Structure):
    _fields_ = [
        ("group", ctypes.c_ubyte),
        ("locked_group", ctypes.c_ubyte),
        ("base_group", ctypes.c_ushort),
        ("latched_group", ctypes.c_ushort),
        ("mods", ctypes.c_ubyte),
        ("base_mods", ctypes.c_ubyte),
        ("latched_mods", ctypes.c_ubyte),
        ("locked_mods", ctypes.c_ubyte),
        ("compat_state", ctypes.c_ubyte),
        ("grab_mods", ctypes.c_ubyte),
        ("compat_grab_mods", ctypes.c_ubyte),
        ("lookup_mods", ctypes.c_ubyte),
        ("compat_lookup_mods", ctypes.c_ubyte),
        ("ptr_buttons", ctypes.c_ushort),
    ]


def main() -> int:
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 120.0
    path = ctypes.util.find_library("X11")
    if path is None:
        print("libX11 not found", file=sys.stderr)
        return 1
    x11 = ctypes.CDLL(path)
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XkbGetState.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                ctypes.POINTER(_XkbStateRec)]
    display = x11.XOpenDisplay(None)
    if not display:
        print("could not open an X display", file=sys.stderr)
        return 1

    state = _XkbStateRec()

    def read() -> bool:
        x11.XkbGetState(display, _XKB_USE_CORE_KBD, ctypes.byref(state))
        return bool(state.locked_mods & _LOCK_MASK)

    started = time.monotonic()
    last = read()
    print(f"{time.strftime('%H:%M:%S')}  {0.0:7.3f}s  caps lock starts "
          f"{'ON' if last else 'off'}", flush=True)
    changes = 0
    while time.monotonic() - started < seconds:
        now = read()
        if now != last:
            changes += 1
            print(f"{time.strftime('%H:%M:%S')}  "
                  f"{time.monotonic() - started:7.3f}s  -> "
                  f"{'ON' if now else 'off'}", flush=True)
            last = now
        time.sleep(0.002)
    print(f"{time.strftime('%H:%M:%S')}  {time.monotonic() - started:7.3f}s  "
          f"finished: {changes} changes, caps lock "
          f"{'ON' if last else 'off'}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
