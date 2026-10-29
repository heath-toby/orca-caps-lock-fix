# Caps Lock Fix for Orca

An Orca 51 user extension with two halves, both about caps lock:

- **the double press**, counted from one press to the next rather than from the
  release of the first, so holding the modifier is not a request to toggle the
  lock; and
- **the indication**, a tone or the letters themselves, when caps lock is on.

## The double press

Orca treats two presses of its modifier key as a double press, which passes the
key through to the system — on the laptop keyboard layout, that is how Caps Lock
is meant to latch. The trouble is where the measuring starts. In
`InputEventManager._determine_keyboard_event_click_count`:

```python
if event.is_modifier_key():
    last_event = self._last_input_event
...
if event.time - last_event.time > _DOUBLE_CLICK_TIMEOUT:
    return 1
```

For a modifier key, the previous event after a hold is the **release**. So the
half-second window runs from the moment you let go, and how long you held the
key is never consulted. Hold Caps Lock for three seconds, release it, press it
again within half a second, and that counts as a double press — so Orca
announces a lock change and asks the system for one, when all you did was use
the modifier and then use it again.

No other screen reader reads a hold, a release, and a press shortly after as a
request to turn caps lock on.

## What it changes

The question becomes "was the last *press* of this key recent?" instead of "was
the last *event* for this key recent?". Nothing else. The window is Orca's own
0.5 s, and the fix falls out of it: a press that follows a long hold cannot be
within half a second of the press that *started* that hold.

Two deliberate limits:

- **Only the Orca modifier.** Orca has genuine double-press bindings on other
  keys — spelling a word, for one — and their timing is not what anyone is
  complaining about.
- **It only ever reduces a count to 1, never raises one.** The worst a bug in
  here can do is fail to pass the modifier through, costing you a second double
  press. It cannot invent a command you did not ask for.

## Telling you caps lock is on

**Orca Preferences → User Extensions → Caps Lock Fix → Warn that caps lock is
on**, with four values:

- *When a lowercase letter is typed, because caps lock is on* — the default.
  You held shift, caps lock was already on, and you got the opposite of what
  you asked for. This is the case NVDA has shipped on by default since about
  2010 under the name "Beep for lowercase with Capslock", and its purpose is
  catching caps lock left on by mistake — classically while typing a password.
- *On every letter typed while caps lock is on* — noisier, but it tells you at
  the first keystroke rather than waiting for you to reach for shift, which is
  what you want at a shell prompt where a whole command may never need shift.
- *Speak each letter typed while caps lock is on* — the one Fenrir has, and a
  better answer than a tone for anyone who left caps lock on by accident: a
  beep says something is wrong, a read letter says what. It speaks through
  `SpeechPresenter.speak_character`, which is also the method CapitalBeep
  wraps, so with both add-ons installed each letter is announced *and* carries
  CapitalBeep's capital beep. That is the point rather than a coincidence: the
  beep on each letter keeps saying "these are all capitals" while the letters
  tell you which.
- *Never*.

*Pitch of the caps lock warning* is 1320 Hz by default, an octave above
CapitalBeep's 660 Hz capital beep so the two cannot be confused. NVDA
distinguishes its two beeps the same way and uses 3000 Hz, which this setting
will take.

### How caps lock is detected

**From the character that actually arrived, not from a lock bit.** Shift held
and a lowercase letter means caps lock is on; so does an unshifted uppercase
one. A lock bit would have to be the *right* lock bit, and on a Wayland
session there are two — the compositor's and XWayland's copy — with which one
reaches an add-on depending on how the session routes accessibility key
events. The letter that came out needs none of that settled: it is decided by
the same keymap and the same lock state that will type the next one.

It works on any layout that pairs its cases under shift, Cyrillic included.

A letter arriving with the Orca modifier, Alt or Control held is a command,
not typing, and is ignored. That matters most on the laptop layout, where
`Caps_Lock` *is* the Orca modifier: without it, Orca+Shift+H to list headings
arrives as a lowercase `h` with shift held, which is exactly the pattern the
default mode looks for. CapitalBeep 2.2.0 shipped with that check reading the
wrong mask and did beep at commands.

### Where this came from

It shipped in CapitalBeep as v2.2.0 and moved here in 2.1.0. CapitalBeep is
about a capital being *read*; this is about caps lock being *on*. The option
labels are reproduced verbatim from there, because a screen reader user
navigates a settings dialog by remembered label text and a port that rewords
as it moves costs them the thing they already knew.

## Install

    ./install.sh
    orca --replace &

To remove it again:

    ./uninstall.sh
    orca --replace &

`install.sh` copies the package to
`$XDG_DATA_HOME/orca/extensions/caps_lock_fix` and approves it with
`orca --approve-extension`. Orca re-checks the hash of every file in the package
on each start, so re-run the installer after editing anything.

## Settings

**Orca Preferences → User Extensions → Caps Lock Fix**

- *Longest gap between the two presses of a double press*, 500 ms by default,
  matching Orca's own `_DOUBLE_CLICK_TIMEOUT`. Hands differ: someone who rests a
  finger on the modifier wants it longer, someone who taps fast wants it shorter.
  Read per keypress, so a change takes effect immediately.
- *Warn that caps lock is on*, and *Pitch of the caps lock warning* — see
  [Telling you caps lock is on](#telling-you-caps-lock-is-on) above.
- *Log diagnostics*, off by default. Writes to
  `$XDG_DATA_HOME/orca/caps_lock_fix/debug.log`, one line per lock-key event
  with the mask, the click count Orca computed, the count this extension
  returned, and what Orca would announce from that mask. It rolls past 2MB and
  keeps one previous log as `debug.log.1`, because diagnostics get left on.

All of them are read when needed rather than cached, so a change takes effect
on the next keypress with no restart.

## What this does **not** fix

On a Wayland session, whether a Caps Lock press changes the lock at all is not
Orca's decision. Where the compositor implements
`org.freedesktop.a11y.KeyboardMonitor`, a press of a key the screen reader has
grabbed as a modifier is **required by that protocol** to be ignored unless a
second press of the same key arrives "within a reasonable time frame, for
example, the key repeat delay".

niri 26.04 takes that example literally, in
`src/dbus/freedesktop_a11y.rs::process_key`:

```rust
// Modifier pressed twice; handle it as normal.
if time <= last_press.saturating_add(repeat_delay) {
    return KbMonBlock::Pass;
}
```

So with `repeat-delay 1000` in `~/.config/niri/config.kdl`, caps lock can only
change state about once a second, and the only way to shorten that is to make
every held key start repeating sooner. Lowering `repeat-delay` shrinks the
window immediately — niri hot-reloads its config — and
`~/Development/niri-a11y-modifier/` holds a one-constant patch that gives the
accessibility window its own 500 ms instead, matching Orca.

Worth knowing: niri already measures that window press-to-press, which is
exactly what this extension does to Orca. The two gates are independent, and
this one governs what Orca announces and asks for, not what the compositor does.

## The logger

`tools/true-lock-log.py` opens a small window and writes one line per key event
to `$XDG_DATA_HOME/orca/caps_lock_fix/true-lock.log`:

```
19:58:02.030 press   F   produced='F'  UPPER  compositor=ON  xwayland=off  +934ms   <-- THEY DISAGREE
```

Each line carries the character the key actually produced, the compositor's lock
state (a GDK key event's `LOCK_MASK` on the Wayland backend, which comes from
`wl_keyboard.modifiers`), XWayland's copy of it (`XkbGetState().locked_mods`),
and the gap since the previous key. It refuses to claim anything if it finds
itself on the X11 backend, because then both columns would be the same copy.

It exists because every other instrument used on this problem lied, and the
character that arrived never did.

## Why an extension and not a patch to Orca

The method patched is private, so a future Orca may rename it. That is checked
for rather than assumed: if it is gone, the extension logs and does nothing, and
Orca starts normally. A source patch would fail the build and block the upgrade.

## Tests

```
./install.sh && python3 tests-clicks.py && python3 tests-indicator.py
```

`tests-clicks.py` is 26 rows, driving the rule against fake events with no
keyboard and no display.
The rule itself is a pure function, `adjust_click_count`, so the whole of it is
testable: a press after a long hold, a genuine quick double press, a release
inheriting its press's count, other keys left alone, and an event that
misbehaves leaving Orca's own count untouched. Plus the diagnostic log rolling
once it is large.

`tests-indicator.py` is 49 rows. `caps_lock_indication_wanted` is also a pure
function of (pressed, modifiers, text, mode), so the whole rule is a table —
each mode against a shifted lowercase letter, an unshifted capital, ordinary
typing, Orca and Alt and Control commands, digits, punctuation, releases and
Cyrillic. The rest cover the keyboard hook, which sits in front of every key
Orca builds: that its signature still matches the constructor it replaces,
that the event is built before anything looks at it, that an indication which
raises still leaves the key forwarded, that the right mode beeps or speaks,
and that it tests the event's own mask rather than the argument.
