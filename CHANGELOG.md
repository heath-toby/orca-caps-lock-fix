# Changelog

## 2.0.0

**The lock-state half is removed.** It was built on a model of caps lock on
Wayland that measurement disproved, and the real cause turned out to be
somewhere else entirely.

What remains is the half that works and that the extension is named for:
counting a double press of the Orca modifier from one press to the next.
Unchanged, 23 test rows, installed unconditionally and reading its window per
keypress.

### Why the rest went

The symptom was that caps lock could only change state about once a second, and
only while Caps Lock was Orca's modifier. Three explanations were built and
shipped as experiments, and all three were wrong:

- *Driving the lock through `zwp_virtual_keyboard_v1`.* Measured: with the lock
  set that way, a key from that same virtual keyboard still produced a lowercase
  `a`, while a virtual key did come out `A` when the physical Caps Lock had the
  seat locked. niri applies the seat's lock to a virtual keyboard's keys but
  does not accept a virtual keyboard's `modifiers` request as setting the seat's
  lock. It also lagged a flat 1.502 s per press until that bug was fixed.
- *Standing aside and letting the key do it.* Pointless once it was established
  that at-spi2-core has only one key-synthesis backend,
  `registryd/deviceeventcontroller-x11.c`, so Orca's `LOCKMODIFIERS` can only
  ever reach XWayland. Orca cannot change the compositor's lock either way.
- *Announcing a state tracked from the characters,* on the theory that Orca's
  mask was dead. It is not: where the compositor implements
  `org.freedesktop.a11y.KeyboardMonitor`, it sends the mask itself in the
  `KeyEvent` signal, serialized with `STATE_MODS_EFFECTIVE`. Orca's
  announcements were correct all along, which Toby said three times.

### What it actually was

niri 26.04, `src/dbus/freedesktop_a11y.rs::process_key`. For a key in the screen
reader's grabbed-modifier set, a press within `repeat_delay` of the previous
press is passed through and changes the lock; outside that window it is the
screen reader's modifier and `src/input/mod.rs` returns early — *"The
accessibility modifier first press must not change XKB state"*. The window is
`config.input.keyboard.repeat_delay`, and Toby's niri config had
`repeat-delay 1000` against niri's default of 600.

The protocol requires the window but not its length, saying only "a reasonable
time frame, for example, the key repeat delay". niri took the example literally.

Found by Toby from the keyboard alone: he noticed the delay vanished when Caps
Lock was not Orca's modifier, which localised it exactly, then changed
`repeat-delay` and watched the window shrink to match. A one-constant patch is
in `~/Development/niri-a11y-modifier/`.

### Removed

- The `lock-mode` setting and both of its experimental values.
- `caps_lock_fix/wayland_lock.py`, a ~250-line raw Wayland client that bound a
  virtual keyboard by hand because there are no Python bindings here. It worked;
  it just could not do the thing it was for. In the history from 1.5.1 if ever
  wanted.
- `caps_lock_fix/lock_toggle.py` and `tests-lock.py`, which existed to serve it.
- `tools/watch-lock.py`, which read XKB — that is, XWayland's copy — and was
  built specifically to be trustworthy. Superseded by
  `tools/true-lock-log.py`, which reads both states and labels which is which.

### Kept

- `tools/true-lock-log.py`.
- The diagnostic log, now one shared writer (`caps_lock_fix/trace.py`), with one
  line per lock-key event: the mask, the click count Orca computed, the count
  this extension returned, and what Orca would announce from that mask.

## 1.5.1

The Wayland mode's lag was a flat 1.502 s per press: `_Connection.pump(seconds)`
checked its deadline only *between* reads and left the blocking `recvmsg` to the
socket's own 1.5 s timeout, waiting for a reply that a `modifiers` request never
draws — inside Orca's main loop, on every press. Fixed with `select`;
1.502 s → 0.000 s per call.

Added `tools/true-lock-log.py`. In its first 22 events it showed XWayland's lock
bit clear on every line while the compositor's was set for 13 of them and
produced real capitals.

## 1.5.0

Made the lock mode live: `install()` had only patched anything when the mode was
already non-default at Orca startup, so changing it in Preferences did nothing
until the next restart and all three values behaved identically. Both halves now
install unconditionally and read their settings per keypress.

## 1.4.0 and earlier

The lock-state experiments, since removed. See 2.0.0 for what they were and why
they went.
