#!/usr/bin/env python3
"""Tests for the lock-state half: the modes, the announcement, the fallbacks.

What this cannot test is which mode actually works, because the only reader
that has never lied about the caps lock on this machine is which characters
arrive when a key is pressed. ``xset`` and ``Gdk`` both read XWayland's copy of
the state, and that copy demonstrably diverges from the compositor's. So the
rows here cover the machinery and leave the verdict to a person at a keyboard.

Run after ./install.sh -- it tests the installed package.

Usage: python3 tests-lock.py
"""

from __future__ import annotations

import os
import sys
import time

import orca.extension_loader  # noqa: F401  (import order: see install.sh)

sys.path.insert(0, os.path.expanduser("~/.local/share/orca/extensions"))

from caps_lock_fix import lock_toggle, wayland_lock  # noqa: E402

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


ORCA, WAYLAND, SUPPRESS = (lock_toggle.MODE_ORCA, lock_toggle.MODE_WAYLAND,
                           lock_toggle.MODE_SUPPRESS)

# --- the default leaves Orca alone --------------------------------------
lock_toggle._settings_source = None
check("with no settings, the mode is to leave Orca alone", lock_toggle.mode(), ORCA)
check("...and that is the declared default", lock_toggle.MODE_DEFAULT, ORCA)
lock_toggle._settings_source = lambda: {"lock-mode": WAYLAND}
check("a chosen mode is honoured", lock_toggle.mode(), WAYLAND)
lock_toggle._settings_source = lambda: {"lock-mode": "nonsense"}
check("an unknown mode falls back to leaving Orca alone", lock_toggle.mode(), ORCA)


def _raises():
    raise RuntimeError("settings unavailable")


lock_toggle._settings_source = _raises
check("a settings source that throws falls back too", lock_toggle.mode(), ORCA)

# --- the prediction is deliberately Orca's own --------------------------
# The bug was never the prediction; it was writing the answer to the wrong
# lock. Keeping Orca's prediction means the state and the announcement cannot
# disagree with each other, whatever the mask says.
check("an unset lock bit predicts on", lock_toggle.target_from_mask(0x0), True)
check("a set lock bit predicts off", lock_toggle.target_from_mask(0x2), False)
check("other modifiers do not confuse it",
      lock_toggle.target_from_mask(0x100), True)
check("...nor alongside the lock bit",
      lock_toggle.target_from_mask(0x102), False)

# --- the virtual keyboard binds, which is as far as a test can go -------
check("the compositor accepts a virtual keyboard", wayland_lock.available(), True)
check("it takes a request to lock", wayland_lock.set_lock(True), True)
check("...and to unlock", wayland_lock.set_lock(False), True)


# --- the toggle dispatches by mode --------------------------------------
class _FakeEvent:
    def __init__(self, key="Caps_Lock", modifiers=0, pressed=True,
                 locking=True, orca_mod=True):
        self.keyval_name = key
        self.modifiers = modifiers
        self._pressed = pressed
        self._locking = locking
        self._orca_mod = orca_mod

    def is_pressed_key(self):
        return self._pressed

    def is_locking_key(self):
        return self._locking

    def is_orca_modifier(self):
        return self._orca_mod


class _FakeManager:
    pass


to_orca = []
saved_toggle = lock_toggle._orig_toggle_lock
lock_toggle._orig_toggle_lock = lambda self, event: to_orca.append("orca")

lock_toggle._settings_source = lambda: {"lock-mode": ORCA}
lock_toggle._patched_toggle_lock(_FakeManager(), _FakeEvent())
check("in orca mode everything is handed straight back", to_orca, ["orca"])

to_orca.clear()
lock_toggle._settings_source = lambda: {"lock-mode": SUPPRESS}
lock_toggle._just_set = None
lock_toggle._patched_toggle_lock(_FakeManager(), _FakeEvent())
check("in suppress mode nothing happens at all",
      (to_orca, lock_toggle._just_set), ([], None))

to_orca.clear()
lock_toggle._settings_source = lambda: {"lock-mode": WAYLAND}
lock_toggle._patched_toggle_lock(_FakeManager(), _FakeEvent(modifiers=0x0))
check("in wayland mode the compositor is asked, not Orca", to_orca, [])
check("...and it records what it asked for", lock_toggle._just_set, True)
lock_toggle._patched_toggle_lock(_FakeManager(), _FakeEvent(modifiers=0x2))
check("a set lock bit asks for off", lock_toggle._just_set, False)

to_orca.clear()
lock_toggle._patched_toggle_lock(_FakeManager(), _FakeEvent(pressed=False))
check("a release does nothing in any mode", to_orca, [])

to_orca.clear()
lock_toggle._patched_toggle_lock(_FakeManager(), _FakeEvent(key="Shift_Lock"))
check("Shift_Lock is always handed to Orca", to_orca, ["orca"])

to_orca.clear()
saved_set = lock_toggle._wayland_set
lock_toggle._wayland_set = lambda on: False
lock_toggle._patched_toggle_lock(_FakeManager(), _FakeEvent())
check("a compositor that refuses falls back to Orca", to_orca, ["orca"])
lock_toggle._wayland_set = saved_set


class _AwkwardEvent(_FakeEvent):
    def is_pressed_key(self):
        raise RuntimeError("no idea")


to_orca.clear()
lock_toggle._patched_toggle_lock(_FakeManager(), _AwkwardEvent())
check("an event that misbehaves falls back to Orca", to_orca, ["orca"])
lock_toggle._orig_toggle_lock = saved_toggle

# --- the announcement reports what was set ------------------------------
saved_announce = lock_toggle._orig_get_locking_state
lock_toggle._orig_get_locking_state = lambda self: "orca decided"

for was_set in (True, False):
    lock_toggle._just_set = was_set
    lock_toggle._just_set_at = time.time()
    word = "on" if was_set else "off"
    check(f"having just set {word}, the announcement says {word}",
          lock_toggle._patched_get_locking_state(_FakeEvent()), was_set)

lock_toggle._just_set = None
check("with nothing just set, Orca's announcement is used",
      lock_toggle._patched_get_locking_state(_FakeEvent()), "orca decided")
lock_toggle._just_set = True
lock_toggle._just_set_at = time.time() - 10.0
check("a stale value is not announced", 
      lock_toggle._patched_get_locking_state(_FakeEvent()), "orca decided")
lock_toggle._just_set_at = time.time()
check("a key that is not the Orca modifier is left to Orca",
      lock_toggle._patched_get_locking_state(
          _FakeEvent(orca_mod=False)), "orca decided")
check("Shift_Lock's announcement is left to Orca",
      lock_toggle._patched_get_locking_state(
          _FakeEvent(key="Shift_Lock")), "orca decided")
lock_toggle._orig_get_locking_state = saved_announce
lock_toggle._just_set = None
lock_toggle._settings_source = None

# --- the seams still exist ----------------------------------------------
from orca import input_event, orca_modifier_manager  # noqa: E402

check("Orca still has the lock toggle this wraps",
      hasattr(type(orca_modifier_manager.get_manager()),
              "_toggle_modifier_lock"), True)
check("...and the announcement it wraps",
      hasattr(input_event.KeyboardEvent, "get_locking_state"), True)

import inspect  # noqa: E402

source = inspect.getsource(input_event.KeyboardEvent.get_locking_state)
check("Orca's announcement is still a prediction from the event mask",
      "not self.modifiers &" in source, True)

# --- the lock request must not hold the main loop ------------------------
# set_lock used to take a flat 1.502 seconds. pump() checked its deadline only
# between reads and left the blocking recvmsg to the socket's own 1.5s
# timeout, waiting for a reply that a modifiers request never draws -- inside
# Orca's main loop, on every press. Toby: "it lags out, and each press just
# queues something, so the response from orca just gets longer, and longer."
if wayland_lock.available():
    started = time.monotonic()
    for _ in range(4):
        wayland_lock.set_lock(True)
        wayland_lock.set_lock(False)
    per_call = (time.monotonic() - started) / 8
    check("a lock request returns in under 20ms", per_call < 0.02, True)

    started = time.monotonic()
    wayland_lock._conn.pump(0.0)
    check("...and pump(0) really means zero", time.monotonic() - started < 0.02, True)

    started = time.monotonic()
    wayland_lock._conn.pump(0.1)
    waited = time.monotonic() - started
    check("...and pump(0.1) waits 0.1s, not the socket timeout",
          0.05 < waited < 0.3, True)

# --- the setting has to be live -----------------------------------------
# install() used to return without patching anything when the mode was 'orca'
# at startup, which is the default. Changing the mode in Preferences then did
# nothing until the next Orca restart -- and all three modes behaved
# identically, because none of them was installed.
lock_toggle.uninstall()
lock_toggle._installed = False
settings = {"lock-mode": ORCA}
lock_toggle.install(lambda: settings)
check("installing in the default mode still patches the toggle",
      lock_toggle._installed, True)
check("...and Orca's own toggle is what it holds",
      lock_toggle._orig_toggle_lock is not None, True)
check("...and the mode it reports is the one set", lock_toggle.mode(), ORCA)
settings["lock-mode"] = SUPPRESS
check("changing the setting takes effect with no reinstall",
      lock_toggle.mode(), SUPPRESS)
settings["lock-mode"] = ORCA

wayland_lock.shutdown()

width = max(len(r[0]) for r in rows)
print()
for name, want, got, status in rows:
    print(f"  {status:4s} {name:<{width}}  want={want}  got={got}")
print(f"\n{len(rows) - fails}/{len(rows)} rows green")
sys.exit(1 if fails else 0)
