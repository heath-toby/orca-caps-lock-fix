# Changelog

## 2.1.1

**The speaking mode could only be heard one letter per word.** Reported by
Toby: *"character reading is only word reading really, though the capital beep
plays. It might be interrupting each character, but as far as I can tell, only
the first letter of each word is spoken."*

The beep playing while the speech did not is the whole diagnosis. The hook was
firing for every letter -- CapitalBeep's tone proves it, because that tone is
driven by the same call -- so the fault was not in the detection but in *where
the speaking happened from*. `KeyboardEvent.__init__` runs before
`KeyboardEvent._present`, and `_present` opens with:

```python
if self.is_pressed_key():
    presentation_manager.get_manager().interrupt_presentation()
```

**Every key press interrupts speech.** Anything spoken from the constructor is
cut off by the very keystroke that produced it. The beep survived because it is
a separate audio pipeline with nothing to interrupt it.

So the speaking mode is driven from `PresentationManager.present_keyboard_event`
instead -- the call at the end of `_present`, after that interrupt, and exactly
where Orca echoes keys itself. It goes through
`PresentationManager.speak_character`, which supplies the capitalisation style
from Orca's own settings and still ends at `SpeechPresenter.speak_character`, so
the letter keeps CapitalBeep's capital beep.

The two beeping modes stay on the constructor hook, where they work and where
they are reached for every key regardless of what Orca decides to present.

56 test rows, up from 49, including one that fails if the speaking mode ever
speaks from the constructor again.

## 2.1.0

**The caps lock indication moves in, and learns to speak.**

A tone for "caps lock is on" shipped in CapitalBeep as v2.2.0 and did not
belong there: CapitalBeep is about a capital being *read*, and this is about
caps lock being *on*, which is this extension's whole subject. Toby, making the
call: *"Leave Capital Beep as Capital Beep. Move the caps lock indicator to
caps lock fix, and that's where we can also add the ability if enabled to speak
each typed character while caps lock is on."*

So **Orca Preferences → User Extensions → Caps Lock Fix → Warn that caps lock
is on** now has four values. The first three are the ones from CapitalBeep,
under the same labels verbatim — a screen reader user navigates a dialog by
remembered label text, and a port that rewords as it moves costs them what they
already knew:

- *When a lowercase letter is typed, because caps lock is on* (the default, and
  NVDA's since about 2010)
- *On every letter typed while caps lock is on*
- **new:** *Speak each letter typed while caps lock is on*
- *Never*

The new one is the mode Fenrir has, and it is a better answer than a tone for
anyone who left caps lock on by accident: a beep says something is wrong, a
read letter says what. It speaks through `SpeechPresenter.speak_character`,
which is also the method CapitalBeep wraps — so with both add-ons installed
each letter is announced *and* carries CapitalBeep's capital beep. That is the
point rather than a coincidence of wiring. Toby: *"if it's beeping with each
letter, that can continue connecting with 'these are all capitals', which makes
a lot of sense."*

Also moved across: the pitch setting, the detection from the arrived character
rather than a lock bit, the "a letter with the Orca modifier held is a command"
exclusion — reading the event's own mask, as CapitalBeep 2.2.1 had to be fixed
to do — and the 1320 Hz default, an octave above the capital beep so the two
cannot be confused. `tone.py` came with it, so this add-on now renders and
plays audio where before it made no sound at all.

49 test rows for the indication, ported from CapitalBeep and extended for the
speaking mode, plus 26 for the double press.

## 2.0.1

Three fixes from a code review of 2.0.0, one of them destructive.

**`./uninstall.sh --purge` wiped a different add-on's settings.**
`SETTINGS_NAME` was `"indent-beeper"`, carried over from the project this
script was adapted from, so `--purge` reset
`/org/gnome/orca/default/extensions/indent-beeper/` — destroying Indent
Beeper's tone volume, duration and beep-on-change — while leaving this
extension's own `window-ms` and `debug` in place and reporting that it had
removed them.

**The diagnostic log grew without bound.** Diagnostics get left on, and a file
that appends for as long as that setting is true is a trap for whoever forgot.
It now rolls past 2MB and keeps one previous log beside it as `debug.log.1`.

**`uninstall()` left the trace module holding a callable into the settings of
an uninstalled extension**, where it went on deciding whether to log from them.
Cleared now — shutting a module down has to release what it handed out, not
only what it holds.

Also: `trace.py`'s docstring still described itself as shared between two
halves of the extension, and 2.0.0 removed the other half. 26 test rows, up
from 23.

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
