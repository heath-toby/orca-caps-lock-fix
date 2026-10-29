"""Count a double press of the Orca modifier from press to press.

Orca treats two presses of its modifier key as a "double click", which passes
the key through to the system -- on the laptop layout that is how Caps Lock
actually latches. The trouble is where it measures from. In
``InputEventManager._determine_keyboard_event_click_count``::

    if event.is_modifier_key():
        last_event = self._last_input_event
    ...
    if event.time - last_event.time > _DOUBLE_CLICK_TIMEOUT:
        return 1

For a modifier key the previous event, after a hold, is the **release**. So the
half-second window runs from the moment you let go, and how long you held the
key is never consulted. Hold Caps Lock for three seconds, release it, press it
again within half a second, and that counts as a double press: caps lock
latches when you were only using the modifier.

This extension changes the question from "was the last *event* for this key
recent?" to "was the last *press* of this key recent?". Nothing else: the
window is Orca's own 0.5 s, and the fix falls out of it, because a press that
follows a long hold cannot be within half a second of the press that started
that hold.

Two deliberate limits:

- **Only the Orca modifier.** Orca has genuine double-press bindings on other
  keys -- spelling a word, for one -- and their timing is not what anyone is
  complaining about. Narrowing this keeps the extension to the thing it is for.
- **It only ever reduces a count to 1, never raises one.** So the worst a bug
  in here can do is fail to pass the modifier through, which costs a second
  double press. It cannot invent a command you did not ask for.
"""

from __future__ import annotations

import logging
import time

from orca import input_event_manager

from .trace import configure as _configure_trace
from .trace import enabled as _tracing
from .trace import log as _trace

_log = logging.getLogger("orca-caps-lock-fix")

# Orca's own _DOUBLE_CLICK_TIMEOUT is 0.5 s, and this matches it. It is a
# setting because hands differ: someone who rests a finger on the modifier
# wants it longer, someone who taps fast wants it shorter.
DEFAULT_WINDOW_MS = 500
WINDOW_MIN_MS, WINDOW_MAX_MS = 100, 2000

_orig_determine = None
_installed = False

# Time of the last press we saw, per key name. Only the Orca modifier is
# tracked, so this holds one or two entries in practice.
_last_press: dict[str, float] = {}

# Set by install(); returns the extension's settings dict. Read per event so a
# change in Orca's preferences takes effect without a reload.
_settings_source = None


def _window_seconds() -> float:
    """The press-to-press window, in seconds."""
    value = DEFAULT_WINDOW_MS
    if _settings_source is not None:
        try:
            value = _settings_source().get("window-ms", DEFAULT_WINDOW_MS)
        except Exception:  # pylint: disable=broad-exception-caught
            value = DEFAULT_WINDOW_MS
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = DEFAULT_WINDOW_MS
    return max(WINDOW_MIN_MS, min(WINDOW_MAX_MS, value)) / 1000.0


def adjust_click_count(count: int, key: str, pressed: bool, now: float,
                       window: float) -> tuple[int, dict[str, float]]:
    """Return the count this press deserves, and the press time to remember.

    Pure, so the whole rule is testable without Orca or a keyboard. Returns
    ``(count, updates)`` where ``updates`` is what to merge into the
    last-press record.

    A release is left exactly as Orca computed it: its count is inherited from
    the press it belongs to, and that press has already been adjusted.
    """
    if not pressed:
        return count, {}
    previous = _last_press.get(key)
    if count > 1 and (previous is None or now - previous > window):
        # Orca saw a double press because the gap from the *release* was
        # short. The gap from the previous press was not.
        return 1, {key: now}
    return count, {key: now}


_LOCK_BIT = 1 << 1


def _describe(event) -> str:
    """One field of the trace: what an event is, as the click counter sees it.

    The mask is the field that matters most and the one the first version of
    this left out. Orca's announcement is computed from it and nothing else::

        return not self.modifiers & (1 << Atspi.ModifierType.SHIFTLOCK)

    so if the mask is stale, Orca says "caps lock on" over and over while the
    real state is alternating underneath it. Toby, exactly: *"the first 'caps
    lock on' means Caps Lock Is Coming On, and then every subsequent one is
    'caps lock is already on'."*
    """
    if event is None:
        return "none"
    try:
        kind = "press" if event.is_pressed_key() else "release"
        says = "on" if not event.modifiers & _LOCK_BIT else "off"
        return (f"{event.keyval_name} {kind} t={event.time:.3f} "
                f"count={event.get_click_count()} "
                f"mask=0x{event.modifiers:x} lockbit="
                f"{'set' if event.modifiers & _LOCK_BIT else 'clear'} "
                f"orca-would-say={says}")
    except Exception:  # pylint: disable=broad-exception-caught
        return "unreadable"


def _trace_decision(self, event, count, adjusted) -> None:
    """Log every input to Orca's click-count decision, for a lock key.

    This exists because of a measurement that should have been impossible:
    Orca called its lock toggle on four Caps Lock presses that were 1.25
    seconds apart, when a double press is supposed to need two presses inside
    half a second. Nothing short of the actual inputs to the decision was
    going to explain that.
    """
    try:
        last = getattr(self, "_last_input_event", None)
        gap = ""
        if last is not None:
            try:
                gap = f" gap={event.time - last.time:+.3f}s"
            except Exception:  # pylint: disable=broad-exception-caught
                gap = ""
        _trace(f"count: {_describe(event)} orca={count} mine={adjusted} "
               f"modifier={event.is_orca_modifier()} "
               f"locking={event.is_locking_key()}"
               f" | last={_describe(last)}{gap}")
    except Exception:  # pylint: disable=broad-exception-caught
        pass


def _patched_determine(self, event):
    """Wrap Orca's click-count decision for the Orca modifier only.

    Anything raised in here falls back to Orca's own answer. This decides
    whether a keystroke is a command, and a wrong answer is a broken keyboard.
    """
    count = _orig_determine(self, event)
    adjusted = count
    try:
        if event.is_orca_modifier():
            key = event.keyval_name or ""
            now = time.time()
            previous = _last_press.get(key)
            adjusted, updates = adjust_click_count(
                count, key, event.is_pressed_key(), now, _window_seconds())
            _last_press.update(updates)
            if adjusted != count:
                gap = "no previous press" if previous is None else f"{now - previous:.3f}s"
                _log.debug(
                    "CapsLockFix: %s pressed %s after the last press, "
                    "counting it as %d rather than %d", key, gap, adjusted, count)
        # Trace every lock key, not only the ones treated as the modifier: if
        # is_orca_modifier() is False here, the adjustment above never runs,
        # and that would itself be the answer.
        if _tracing() and (event.is_locking_key() or event.is_orca_modifier()):
            _trace_decision(self, event, count, adjusted)
        return adjusted
    except Exception as error:  # pylint: disable=broad-exception-caught
        _log.warning("CapsLockFix: leaving the count alone: %s", error)
        return count


def install(settings_source=None) -> None:
    """Patch Orca's click-count decision.

    ``settings_source`` is an optional zero-argument callable returning the
    extension's settings dict, consulted per event.

    The method patched is private, so a future Orca may rename it. That is
    checked for rather than assumed: if it is gone, this logs and does
    nothing, which is the whole point of doing this in an extension instead of
    a source patch -- a patch would fail the build and block the upgrade.
    """
    global _orig_determine, _installed, _settings_source
    _settings_source = settings_source
    _configure_trace(settings_source)
    if _installed:
        return
    target = getattr(
        input_event_manager.InputEventManager,
        "_determine_keyboard_event_click_count", None)
    if target is None:
        _log.warning(
            "CapsLockFix: this Orca has no "
            "InputEventManager._determine_keyboard_event_click_count; "
            "doing nothing.")
        return
    _orig_determine = target
    input_event_manager.InputEventManager._determine_keyboard_event_click_count = (
        _patched_determine)
    _installed = True
    _last_press.clear()
    _log.info("CapsLockFix: counting modifier double presses from press to press.")


def uninstall() -> None:
    """Put Orca's own decision back."""
    global _orig_determine, _installed, _settings_source
    if not _installed:
        return
    input_event_manager.InputEventManager._determine_keyboard_event_click_count = (
        _orig_determine)
    _orig_determine = None
    _settings_source = None
    # Otherwise the trace module keeps a callable into the settings of an
    # extension that is no longer installed, and goes on deciding whether to
    # log from them. See feedback on singleton teardown: shutting a module
    # down has to clear what it handed out, not just what it holds.
    _configure_trace(None)
    _last_press.clear()
    _installed = False
    _log.info("CapsLockFix: restored Orca's own click counting.")
