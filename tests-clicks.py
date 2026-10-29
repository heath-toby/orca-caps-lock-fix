#!/usr/bin/env python3
"""Tests for the press-to-press rule.

``adjust_click_count`` is a pure function of the count Orca arrived at, the
key, whether this is a press, the time now and the window -- so the whole rule
is a table of hold-and-tap sequences, with no Orca and no keyboard involved.

Run after ./install.sh -- it tests the installed package.

Usage: python3 tests-clicks.py
"""

from __future__ import annotations

import os
import sys

import orca.extension_loader  # noqa: F401  (import order: see install.sh)

sys.path.insert(0, os.path.expanduser("~/.local/share/orca/extensions"))

from caps_lock_fix import clicks  # noqa: E402

rows, fails = [], 0


def check(name, got, want):
    global fails
    ok = got == want
    if not ok:
        fails += 1
    # Record what was compared, not a reference to it. These tests pass live
    # lists in, and a list that is appended to later would print its final
    # state beside a verdict reached much earlier -- three rows read
    # "want=[] got=['orca']" and claimed to pass, which was true and looked
    # like a lie.
    rows.append((name, repr(want), repr(got), "ok" if ok else "FAIL"))


WINDOW = 0.5
KEY = "Caps_Lock"


def sequence(*events):
    """Drive a sequence of (pressed, seconds, count_from_orca) events.

    Returns the adjusted count for each, which is what Orca would act on.
    """
    clicks._last_press.clear()
    out = []
    for pressed, when, count in events:
        adjusted, updates = clicks.adjust_click_count(
            count, KEY, pressed, when, WINDOW)
        clicks._last_press.update(updates)
        out.append(adjusted)
    return out


# --- a real double press still works -------------------------------------
# Tap, release, tap again, all inside the window. Orca says 2 on the second
# press and we agree, because the two presses are 200 ms apart.
check("a quick tap-tap is still a double press",
      sequence((True, 0.00, 1), (False, 0.05, 1), (True, 0.20, 2)),
      [1, 1, 2])

check("a tap-tap right at the edge of the window counts",
      sequence((True, 0.00, 1), (False, 0.05, 1), (True, 0.49, 2)),
      [1, 1, 2])

# --- the case this extension exists for ----------------------------------
# Hold the modifier for three seconds, release, press again a tenth of a
# second later. Orca measures from the release and says 2. The presses are
# 3.1 s apart, so this is a single press and caps lock does not latch.
check("a press after a long hold is a single press",
      sequence((True, 0.00, 1), (False, 3.00, 1), (True, 3.10, 2)),
      [1, 1, 1])

check("...however briefly the key was let go",
      sequence((True, 0.00, 1), (False, 3.00, 1), (True, 3.001, 2)),
      [1, 1, 1])

check("a half-second hold is already past the window",
      sequence((True, 0.00, 1), (False, 0.52, 1), (True, 0.55, 2)),
      [1, 1, 1])

check("a hold just inside the window still double-presses",
      sequence((True, 0.00, 1), (False, 0.30, 1), (True, 0.40, 2)),
      [1, 1, 2])

# --- a third press -------------------------------------------------------
check("three quick presses keep whatever Orca makes of them",
      sequence((True, 0.00, 1), (False, 0.05, 1), (True, 0.20, 2),
               (False, 0.25, 2), (True, 0.40, 3)),
      [1, 1, 2, 2, 3])

# --- releases are never touched ------------------------------------------
# A release inherits its count from the press it belongs to, and that press
# has already been adjusted, so there is nothing to do and nothing to record.
check("a release is left exactly as Orca counted it",
      clicks.adjust_click_count(2, KEY, False, 99.0, WINDOW), (2, {}))
check("...and does not become the remembered press time",
      clicks.adjust_click_count(2, KEY, False, 99.0, WINDOW)[1], {})

# --- the first press of the session --------------------------------------
clicks._last_press.clear()
check("a first press with no history is a single press",
      clicks.adjust_click_count(2, KEY, True, 10.0, WINDOW)[0], 1)

# --- it only ever reduces a count ----------------------------------------
# The safety property: the worst this extension can do is fail to pass the
# modifier through, which costs a second double press. It can never invent a
# command.
clicks._last_press.clear()
raised = []
for count in (1, 2, 3):
    for previous in (None, 0.0, 9.9):
        clicks._last_press.clear()
        if previous is not None:
            clicks._last_press[KEY] = previous
        adjusted = clicks.adjust_click_count(count, KEY, True, 10.0, WINDOW)[0]
        if adjusted > count:
            raised.append((count, previous, adjusted))
check("no input ever makes the count larger than Orca's", raised, [])

# --- a different key does not interfere ----------------------------------
clicks._last_press.clear()
clicks._last_press.update(clicks.adjust_click_count(1, "Caps_Lock", True, 0.0, WINDOW)[1])
check("a key with its own recent press is judged on that press",
      clicks.adjust_click_count(2, "Insert", True, 0.10, WINDOW)[0], 1)

# --- the window comes from the settings ----------------------------------
clicks._settings_source = None
check("with no settings source the window is Orca's own half second",
      clicks._window_seconds(), 0.5)
clicks._settings_source = lambda: {"window-ms": 800}
check("a configured window is honoured", clicks._window_seconds(), 0.8)
clicks._settings_source = lambda: {"window-ms": 99999}
check("an absurd window is clamped",
      clicks._window_seconds(), clicks.WINDOW_MAX_MS / 1000.0)
clicks._settings_source = lambda: {"window-ms": "not a number"}
check("an unusable window falls back",
      clicks._window_seconds(), clicks.DEFAULT_WINDOW_MS / 1000.0)


def _raises():
    raise RuntimeError("settings unavailable")


clicks._settings_source = _raises
check("a settings source that throws falls back rather than breaking the keyboard",
      clicks._window_seconds(), clicks.DEFAULT_WINDOW_MS / 1000.0)
clicks._settings_source = None

# --- the seam, and the wrapper around it ---------------------------------
# The method is private, so this asserts it is still there rather than
# assuming. If a future Orca renames it, install() logs and does nothing --
# which is the reason for doing this in an extension rather than a patch.
from orca import input_event_manager  # noqa: E402

check("Orca still has the method this extension wraps",
      hasattr(input_event_manager.InputEventManager,
              "_determine_keyboard_event_click_count"), True)
check("and Orca's own window is the one this defaults to",
      int(input_event_manager._DOUBLE_CLICK_TIMEOUT * 1000),
      clicks.DEFAULT_WINDOW_MS)


class _FakeEvent:
    def __init__(self, pressed, key, orca_modifier=True):
        self._pressed = pressed
        self.keyval_name = key
        self._orca_modifier = orca_modifier

    def is_pressed_key(self):
        return self._pressed

    def is_orca_modifier(self):
        return self._orca_modifier


saved = clicks._orig_determine
clicks._orig_determine = lambda self, event: 2
clicks._last_press.clear()

check("a non-modifier key is handed straight back to Orca",
      clicks._patched_determine(None, _FakeEvent(True, "k", orca_modifier=False)), 2)
check("a first modifier press is reduced to a single",
      clicks._patched_determine(None, _FakeEvent(True, "Caps_Lock")), 1)
check("...and a second one straight after is the double press",
      clicks._patched_determine(None, _FakeEvent(True, "Caps_Lock")), 2)


def _exploding(self, event):
    return 2


class _AwkwardEvent(_FakeEvent):
    def is_orca_modifier(self):
        raise RuntimeError("no idea")


clicks._orig_determine = _exploding
check("an event that misbehaves leaves Orca's count alone",
      clicks._patched_determine(None, _AwkwardEvent(True, "Caps_Lock")), 2)

clicks._orig_determine = saved

# --- the diagnostic log must not grow for ever ---------------------------
# Diagnostics get left on. A log that appends without bound for as long as
# that setting is true is a trap for the person who forgot.
import tempfile  # noqa: E402

from caps_lock_fix import trace  # noqa: E402

saved_dir, saved_path, saved_handle = trace._DIR, trace.PATH, trace._handle
saved_max = trace.MAX_BYTES
scratch = tempfile.mkdtemp(prefix="caps-lock-fix-trace-")
trace._DIR = scratch
trace.PATH = os.path.join(scratch, "debug.log")
trace._handle = None
trace.MAX_BYTES = 2048
trace.configure(lambda: {"debug": True})

for _ in range(200):
    trace.log("x" * 64)

check("the log rolls once it is large",
      os.path.exists(trace.PATH + ".1"), True)
check("...and the live log is back under the limit",
      os.path.getsize(trace.PATH) < trace.MAX_BYTES, True)

trace.configure(None)
check("a log with no settings source writes nothing", trace.enabled(), False)

trace._DIR, trace.PATH, trace._handle = saved_dir, saved_path, saved_handle
trace.MAX_BYTES = saved_max

width = max(len(r[0]) for r in rows)
print()
for name, want, got, status in rows:
    print(f"  {status:4s} {name:<{width}}  want={want}  got={got}")
print(f"\n{len(rows) - fails}/{len(rows)} rows green")
sys.exit(1 if fails else 0)
