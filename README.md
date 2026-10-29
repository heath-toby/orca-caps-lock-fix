# Caps Lock Fix for Orca

Counts a double press of the Orca modifier key from one press to the next,
rather than from the release of the first.

**This is for the laptop keyboard layout**, where `Caps_Lock` is the Orca
modifier and Orca drives the lock itself. In the desktop layout the modifier
is `Insert`, Caps Lock latches natively and Orca never touches it, so there is
nothing here to fix — the same rule still applies to passing `Insert` through,
but no lock can go wrong.

One thing to know before blaming this extension for a caps lock oddity:
**Orca does not fully apply a keyboard-layout change without a restart.** It
restores the X keymap but keeps its grab and its idea of which keys are the
modifier, so after switching laptop → desktop mid-session Caps Lock still
behaves as the Orca modifier — single presses swallowed, double presses
toggling — until Orca is restarted. Compare
`ps -o lstart= -p $(pgrep -x orca)` with `stat -c '%y' ~/.config/dconf/user`;
if the settings are newer than the process, restart Orca before diagnosing
anything else.

## The problem

Orca treats two presses of its modifier as a "double click" and passes the key
through to the system. On the **laptop** keyboard layout the modifier is
`Caps_Lock`, so that double press is how caps lock actually latches.

The trouble is where Orca measures from. In
`InputEventManager._determine_keyboard_event_click_count`:

```python
if event.is_modifier_key():
    last_event = self._last_input_event
...
if event.time - last_event.time > _DOUBLE_CLICK_TIMEOUT:
    return 1
```

For a modifier key the previous event, after a hold, is the **release**. So the
half-second window runs from the moment you let go, and how long you held the
key is never consulted at all. Hold the modifier for three seconds, release it,
press it again a tenth of a second later, and Orca counts a double press: caps
lock latches when you were only using the modifier.

## The second problem: there are two lock states

The compositor owns the lock state that decides which character a key
produces. XWayland keeps a copy, and everything available to an X client reads
or writes the copy — AT-SPI's key synthesis, `XkbLockModifiers`,
`Gdk.Keymap.get_caps_lock_state`, `xset`. They agree most of the time, which is
why this looks fine until it doesn't.

Proven here the hard way. After a rapid double-double press, typed characters
came out uppercase with the lock bit in their event masks, while XKB, `xset`
and Orca's announcement all said off — and the next quad press put them back in
agreement. Every reader an X client has was wrong together, for about twenty
seconds. The only instrument that never lied was which characters actually
arrived.

Orca's own mechanism writes the copy too, and it does worse than that: in one
trace a dozen alternating `LOCKMODIFIERS` requests went out while nothing
changed at all, then the lock appeared seconds later with no request near it.

So the lock-state half of this extension offers two experiments, and **neither
is the default**:

- **Set it through the Wayland compositor.** `zwp_virtual_keyboard_v1` is the
  only route a client has to the state that matters, and Niri advertises it.
  The protocol runs cleanly — the compositor takes the keymap and the modifiers
  request without complaint. What is unproven is whether it applies a virtual
  keyboard's locked modifiers session-wide or only to keys sent from that
  virtual keyboard.
- **Do nothing and let the key itself do it.** Orca's `xkbcomp` rewrite strips
  the lock action from *XWayland's* keymap only; the compositor still has it.
  So the physical key may already latch correctly on its own, and every
  synthetic toggle Orca adds is a second driver fighting the first. If that is
  what has been happening, doing nothing is the fix.

Both are in Orca Preferences → User Extensions → Caps Lock Fix. Switch one on,
press caps lock, and **type a letter** — that is the only test that means
anything.

## What this changes

One question, from "was the last *event* for this key recent?" to "was the last
*press* of this key recent?".

Nothing else. The window is Orca's own `_DOUBLE_CLICK_TIMEOUT` of 0.5 s, and
the fix falls out of it: a press that follows a long hold cannot be within half
a second of the press that began that hold, so it is a single press.

Two deliberate limits:

- **Only the Orca modifier.** Orca has genuine double-press bindings on other
  keys — spelling a word, for one — and their timing is not what anyone is
  complaining about.
- **It only ever reduces a count to 1, never raises one.** The worst a bug in
  here can do is fail to pass the modifier through, which costs you a second
  double press. It cannot invent a command you did not ask for. A test row
  asserts that across every combination of inputs.

## Install

```
./install.sh
orca --replace &
```

Installs as an Orca 51 user extension into
`~/.local/share/orca/extensions/caps_lock_fix/` and approves it. Re-running
is safe, and re-approves — which is what you want after editing, since Orca
hash-checks every file in the package.

## Settings

Orca Preferences → User Extensions → Caps Lock Fix.

**Longest gap between the two presses of a double press** — 500 ms by default,
matching Orca's own constant. Hands differ: rest a finger on the modifier and
you want it longer, tap fast and you want it shorter.

**How to drive the caps lock state** — "Leave it to Orca" by default; the two
experiments above are the other values.

**Log diagnostics** — writes a line per toggle to
`~/.local/share/orca/caps_lock_fix/debug.log`.

`tools/watch-lock.py` logs every change of the lock from outside Orca
entirely. Useful, with one caveat written at the top of it: it reads XKB, which
is XWayland's copy, so it tells you what X thinks rather than what your
keyboard is doing.

## The logger

`tools/true-lock-log.py` opens a small window and writes one line per key event
to `~/.local/share/orca/caps_lock_fix/true-lock.log`:

```
19:58:02.030 press   F   produced='F'  UPPER  compositor=ON  xwayland=off  +934ms   <-- THEY DISAGREE
```

Each line carries the character the key actually produced, the compositor's lock
state (a GDK key event's `LOCK_MASK` on the Wayland backend, which comes from
`wl_keyboard.modifiers`), XWayland's copy of it (`XkbGetState().locked_mods`),
and the gap since the previous key. It refuses to claim anything if it finds
itself on the X11 backend, because then both columns would be the same copy.

`tools/watch-lock.py` is the earlier version, and it reads XKB only -- which is
to say XWayland's copy. Keep it for reference; do not use it to decide anything.

## Testing the two lock experiments

They can only show a difference under all three of these at once:

1. Caps Lock has to actually be the Orca modifier. Orca reaches its lock toggle only
   from `if self.is_orca_modifier(): if self._click_count == 2:`, and
   `is_orca_modifier` wants both the key in the active layout's modifier list and
   `_modifiers_are_set`. Check with
   `dconf read /org/gnome/orca/default/keybindings/desktop-modifier-keys` and the laptop
   equivalent; if `Caps_Lock` is in neither, no mode here can do anything.
2. A **double press**. A single press never reaches the toggle either.
3. **Then type a letter.** The announcement is not evidence: it is a prediction from the
   event mask, and the whole point is that it can disagree with the compositor. The
   characters that arrive are the only instrument that has never lied about this.

The mode can be changed in Preferences and takes effect on the next keypress; no restart.

## When it does nothing

In the **desktop** keyboard layout the Orca modifier is `Insert`, which has no
lock to latch — the same rule still applies to passing `Insert` through, but
there is no caps lock to go wrong. The behaviour this exists for is the laptop
layout, where `Caps_Lock` is the modifier.

## Why an extension and not a patch to Orca

The method wrapped is private, so a future Orca could rename it. That is
checked for rather than assumed: if it is gone, `install()` logs and does
nothing. A source patch would instead fail to apply and block the upgrade.

An extension is also reversible with a keystroke, which matters for input
handling, and it survives Orca upgrades without rebasing.

## Tests

```
./install.sh && python3 tests-clicks.py
```

```
python3 tests-lock.py
```

23 rows each. Both rules are pure functions — the click count of (what Orca
arrived at, the key, whether this is a press, the time, the window), the lock
direction of (what the mask says, what was last requested, how long ago, the
window) — so both are tables, with no Orca and no keyboard involved. The
remaining rows cover the settings, the safety properties above, and the fact
that Orca still has each method being wrapped.

One row asserts the premise rather than the fix: that Orca's announcement is
still `not self.modifiers &` and nothing else, so if upstream ever starts
consulting the real state, the row fails and this extension can be retired.
