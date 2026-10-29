# Changelog

## 1.5.1

**The Wayland mode's lag was a bug of mine, and it was a flat 1.502 seconds per
press.** Toby: *"the wayland caps mode is a no go, since it lags out, and each
press of caps just queues something, so the response from orca just gets longer,
and longer, and longer."*

`_Connection.pump(seconds)` checked its deadline only *between* reads and left
the blocking `recvmsg` to the socket's own 1.5s timeout -- so `pump(0.1)` waited
1.502 seconds for a reply that a `modifiers` request never draws, inside Orca's
main loop, on every press. The debug log shows the handler running at 1.518s
intervals like clockwork, which was never his finger. The deadline is now
enforced with `select`, and `set_lock` waits for nothing at all: measured
1.502s -> **0.000s** per call. Three test rows fail if it ever blocks again.

Also: `install()` reported the virtual keyboard's availability in its debug
line, which *bound* one, costing 1.7s of Orca's startup in every mode including
the two that never use it. Now only asked when the mode is `wayland`.

**New: `tools/true-lock-log.py`,** the logger Toby asked for -- *"something
true, that we can read when caps lock goes on/off."* The first attempt read XKB
and was therefore XWayland's copy. This one logs both states side by side and
labels which is which: the compositor's, from a GDK key event's `LOCK_MASK` in a
window on the Wayland backend (`wl_keyboard.modifiers`), against XWayland's,
from `XkbGetState().locked_mods` over ctypes. It also logs the character each
key actually produced, which is the only evidence that has never lied here.

**What it immediately showed, in 22 key events:** XWayland's lock bit was `off`
on every single line, while the compositor's was ON for 13 of them and produced
real capitals. That is the two-states finding, from an instrument that reads
both at once -- and it is why an announcement computed from an X-side mask can
confidently say the opposite of what the keyboard is doing.

**And a negative result for the `wayland` mode:** with the lock set through
`zwp_virtual_keyboard_v1`, a key sent from that same virtual keyboard still
produced a lowercase `a`, and the compositor still reported the lock as off.
A virtual key *did* come out as `A` while the physical Caps Lock had the seat
locked. So the compositor applies the seat's lock to a virtual keyboard's keys,
but does not take a virtual keyboard's `modifiers` request as setting the
seat's lock -- which was the one thing this mode needed to be true. Recommend
removing the mode and its 250 lines; left in place pending Toby's word, since
neither this project nor the clipboard one is under version control yet.

## 1.5.0

**The lock mode is now live, and it was not before.** Reported by Toby: *"Do Nothing,
Leave To Orca, and Use Compositor still seem to do the same thing as each other."*

They did. Two causes, both real.

**1.4.0 only installed the lock patch if the mode was already set to something other
than `orca` when Orca started** -- and `orca` is the default. Changing the setting in
Preferences afterwards therefore did nothing whatsoever until the next Orca restart, so
all three choices behaved identically: as the unpatched Orca. Both halves are now
installed unconditionally and read their settings per keypress. In `orca` mode the patch
hands straight back to Orca's own method and changes nothing, which is the point.

**Even installed, the three modes can only differ on a double press of the Orca
modifier.** Orca reaches its lock toggle from exactly one place, `input_event.py`:

```python
if self.is_orca_modifier():
    if self._click_count == 2:
        orca_modifier_manager.get_manager().toggle_modifier(self)
```

and `is_orca_modifier` is itself two conditions: the key must be in the active layout's
modifier list *and* `_modifiers_are_set` must be true, meaning Orca has applied its
modifier keymap. A single press never reaches the toggle either; it takes a double press.
So whenever any of that does not hold, Orca synthesizes no lock, there is nothing for a
mode to intercept, and all three are identical *by construction* -- while the
announcement still fires, because `_present()` runs for every key regardless. That is how
the setting could look installed and inert at the same time.

Worth knowing for this machine specifically: `desktop-modifier-keys` and
`laptop-modifier-keys` both list `Caps_Lock` here, so Caps Lock is an Orca modifier in
either layout, and the reading that the desktop layout excludes it is wrong. Judging the
modes needs a double press and then a typed letter -- the announcement is a prediction
from the event mask and cannot settle anything.

Also: the test harness stored live list references and printed them after later
mutation, so three rows read `want=[] got=['orca']` and truthfully claimed to pass.
Values are now snapshotted at comparison time. 34 lock rows and 23 click rows, including
four new rows that fail if installing in the default mode ever stops patching.

## 1.4.0

**The lock-state half becomes two experiments, and the default is to leave Orca alone.**

1.2.0 drove the lock through XKB and 1.1.0 through a remembered request. Both were wrong
for the same reason, which took all evening and five discarded instruments to see: **there
are two lock states.** The compositor owns the one that decides which character a key
produces; XWayland keeps a copy, and AT-SPI key synthesis, `XkbLockModifiers`,
`Gdk.Keymap.get_caps_lock_state` and `xset` all read or write the copy.

They agree most of the time. After a rapid double-double press they stop agreeing: typed
characters came out uppercase with the lock bit in their event masks while XKB, xset and
the announcement all said off, and the next quad press resynchronised them. Toby, who was
right and was told otherwise: *"This was not me being mistaken."*

### Added

- **A `lock-mode` setting with three values.** "Leave it to Orca" is the default.
  - *Set it through the Wayland compositor* — `zwp_virtual_keyboard_v1`, which is the only
    route a client has to the authoritative state. Niri advertises it and the protocol runs
    cleanly here: the compositor accepts the keymap and the modifiers request. Spoken
    straight over the wire, since there are no Python Wayland bindings on this machine.
    Unproven: whether the compositor applies a virtual keyboard's locked modifiers
    session-wide or only to keys from that keyboard.
  - *Do nothing and let the key itself do it* — Orca's `xkbcomp` rewrite strips the lock
    action from XWayland's keymap only, so the physical key may already latch the
    compositor's lock correctly and every synthetic toggle is a second driver fighting the
    first.

- `tools/watch-lock.py`, which logs lock changes from outside Orca, with a warning at the
  top that it reads XKB and therefore XWayland's copy.

### Removed

- The XKB reader and writer, and the propagation window from 1.1.0. Both were built on the
  premise that there was one lock state.

### Notes

- The prediction is deliberately still Orca's own, `not modifiers & Lock`. The bug was
  never the prediction; it was writing the answer to the wrong lock. Keeping it means the
  state and the announcement cannot disagree with each other.
- 30 rows on the lock half, 23 on the double press. What they cannot test is which mode
  works, because the only trustworthy reader is a person typing.

## 1.2.0

**The lock is read and set through XKB, so repeated double presses alternate.**

1.1.0 tried to work around a stale modifier mask by remembering which way the last toggle
asked the lock to go. It did alternate its requests correctly — and it made things worse,
because the premise was wrong twice over. Measured from inside Orca:

- **`Atspi.generate_keyboard_event(mask, "", LOCKMODIFIERS)`**, which is Orca's own
  mechanism, often changes nothing. In one twenty-second trace the extension asked for on,
  off, on, off a dozen times while the mask on incoming events stayed off throughout, then
  showed the lock engaged seconds later with no request anywhere near it. So requests were
  being alternated against a state that was not moving.
- **`Gdk.Keymap.get_caps_lock_state`** does not track the lock here at all. It read False on
  every line of that trace, including lines where the event mask itself read `0x102` — the
  lock bit set. Every "landed"/"never landed" line 1.1.0 logged was therefore worthless.

`XkbGetState` and `XkbLockModifiers` do both jobs server-side, with no keymap action and no
key synthesis: the call returns in 0.02 ms and the new state is readable 0.04 ms later,
cross-checked against `xset q`. So the toggle now reads the lock, sets the opposite, and
hands the announcement the value it set. There is nothing left to predict, remember or
schedule, and the propagation-window setting introduced in 1.1.0 is gone with it.

### Fixed

- **The announcement is no longer inverted.** 1.1.0 recomputed the next transition inside
  `get_locking_state`, but Orca announces *after* toggling — `_present()` at line 753
  against `toggle_modifier` at line 746 — so it reported the state after a second
  transition. Toby: *"it is now opposite. 'Caps lock off,' means, caps lock is off, turning
  on now."* It now reports the value that was set, and eight rows pin that down.

- **Repeated double presses alternate on, off, on, off**, as asked for.

### Changed

- `Shift_Lock` is left entirely to Orca. Orca maps it to the Shift modifier rather than
  Lock, and XKB's Lock is the caps lock.
- `tests-lock.py` is 26 rows and drives the real XKB calls, flipping the lock and putting it
  back. Three of them are about the premise rather than the fix: that XKB is available, that
  the lock reads back immediately after being set, and that Orca's announcement is still
  computed from the event mask alone — if upstream ever stops predicting, this extension can
  be retired.

## 1.1.0

**A toggle no longer repeats the last one.**

A lock change is not immediate: Orca schedules it and the request goes over D-Bus to the
AT-SPI registry and then to XTEST before the X server acts. Until it lands, key events
still carry the old lock bit — and Orca computes both the direction of the toggle and the
spoken announcement from that bit. So a second double press arriving inside that window
reads the same stale mask and goes the same way again, announcement included. Reported by
Toby: *"you just get a repeat of whatever is about to happen... I have to wait patiently,
even a second, and then that solves the issue."*

The toggle now remembers which way it last asked the lock to go. If the mask has not caught
up with that request, the request is used; once a mask agrees with it, the request has
landed and the mask is authoritative again. The announcement reads from the same place, so
the two cannot disagree. Past the propagation window — a new setting, 1000 ms by default —
a disagreeing mask is taken at face value, because by then it means something else changed
the lock.

It does not read the live X lock state, deliberately: `Gdk.Keymap.get_caps_lock_state`
reported the lock off while Orca's own event stream carried the lock bit, which under Niri
and XWayland is not a disagreement worth betting a keyboard on.

Every path falls back to Orca's own behaviour if anything raises or the key is not one of
the two lock keys. This change has no safety net as comfortable as 1.0.0's — that one could
only ever reduce a click count, where a wrong direction here leaves the lock wrong — so the
fallbacks matter more.

- `tests-lock.py`, 23 rows, the rule being a pure function and therefore a table.
- One row asserts the *premise*: that Orca's announcement is still computed from the event
  mask alone. If upstream ever starts consulting the real state, that row fails and this
  extension can be retired.

## 1.0.0

First release.

Counts a double press of the Orca modifier from one press to the next rather
than from the release of the first, so that holding the modifier and then
pressing it again no longer latches caps lock on the laptop keyboard layout.

Reported by Toby: *"if you hold caps lock, release caps lock then press caps
lock, it counts as a double press and enables caps lock."* The cause is that
`InputEventManager._determine_keyboard_event_click_count` compares a modifier
press against `self._last_input_event`, which after a hold is the release — so
Orca's half-second window runs from when you let go and the hold duration is
never consulted.

- The window is Orca's own `_DOUBLE_CLICK_TIMEOUT` of 0.5 s, exposed as a
  setting because hands differ.
- Only the Orca modifier is affected; Orca's genuine double-press bindings on
  other keys are left alone.
- The count is only ever reduced to 1, never raised, so the worst case is a
  double press that needs repeating rather than a command firing unbidden.
- 23 test rows, the rule being a pure function and therefore a table.
