# Caps Lock Fix for Orca

An Orca 51 user extension that counts a double press of the Orca modifier from
one press to the **next press**, rather than from the release of the first.

## The problem

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
- *Log diagnostics*, off by default. Writes to
  `$XDG_DATA_HOME/orca/caps_lock_fix/debug.log`, one line per lock-key event
  with the mask, the click count Orca computed, the count this extension
  returned, and what Orca would announce from that mask.

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
./install.sh && python3 tests-clicks.py
```

23 rows, driving the rule against fake events with no keyboard and no display.
The rule itself is a pure function, `adjust_click_count`, so the whole of it is
testable: a press after a long hold, a genuine quick double press, a release
inheriting its press's count, other keys left alone, and an event that
misbehaves leaving Orca's own count untouched.
