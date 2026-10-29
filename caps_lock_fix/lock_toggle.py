"""How the caps lock gets driven, when Orca's own way does not work.

Orca toggles the lock like this::

    GLib.timeout_add(1, toggle, keyboard_event.modifiers, modifier)
    # ... Atspi.generate_keyboard_event(modifier, "", LOCK/UNLOCKMODIFIERS)

and announces it with a second prediction from the same mask::

    return not self.modifiers & (1 << mod)

On a Wayland session that goes wrong in a way no amount of care inside Orca
can fix, because **there are two lock states**. The compositor owns the one
that decides which character a key produces; XWayland keeps a copy, and
AT-SPI's key synthesis and XKB both write to the copy. They agree most of the
time, which is why this looks fine until it doesn't -- and then the typed
characters disagree with both the announcement and every reader available to
an X client.

That was established the hard way, and the only reader that never lied about
it was which characters actually arrived.

So this file offers two alternatives to Orca's way, neither of them the
default, because the thing that decides between them is a person typing:

``wayland``
    Set the lock through ``zwp_virtual_keyboard_v1``, which goes to the
    compositor -- the state that matters. The protocol runs cleanly here. What
    is unproven is whether the compositor applies a virtual keyboard's locked
    modifiers session-wide or only to keys from that virtual keyboard.

``suppress``
    Do nothing at all. On Wayland the physical Caps Lock key still reaches the
    compositor, which still has its lock action -- Orca's ``xkbcomp`` rewrite
    only strips it from XWayland's keymap. So the key may well already latch
    correctly on its own, and every synthetic toggle Orca adds is a *second*
    driver fighting the first. If that is what has been happening, doing
    nothing is the fix.

``orca``
    Leave Orca entirely alone. The default.
"""

from __future__ import annotations

import logging
import time

from orca import input_event, orca_modifier_manager

from .trace import configure as _configure_trace
from .trace import log as _debug
from .wayland_lock import available as _wayland_available
from .wayland_lock import set_lock as _wayland_set

_log = logging.getLogger("orca-caps-lock-fix")

MODE_ORCA = "orca"
MODE_WAYLAND = "wayland"
MODE_SUPPRESS = "suppress"
MODE_DEFAULT = MODE_ORCA

_LOCK_BIT = 1 << 1
_CLAIMED_KEYS = ("Caps_Lock",)

_orig_toggle_lock = None
_orig_get_locking_state = None
_installed = False
_settings_source = None

# What the toggle last set, for the announcement that follows it in the same
# key dispatch -- Orca calls _present() after toggle_modifier.
_just_set: bool | None = None
_just_set_at = 0.0
_HANDOFF_SECONDS = 0.5

def _setting(key, default):
    if _settings_source is None:
        return default
    try:
        return _settings_source().get(key, default)
    except Exception:  # pylint: disable=broad-exception-caught
        return default


def mode() -> str:
    """Which mechanism to use. Unknown values fall back to leaving Orca alone."""
    value = _setting("lock-mode", MODE_DEFAULT)
    if value not in (MODE_ORCA, MODE_WAYLAND, MODE_SUPPRESS):
        return MODE_DEFAULT
    return value


def target_from_mask(modifiers: int) -> bool:
    """The state to ask for, predicted from the event mask as Orca does.

    Deliberately the same prediction Orca makes. The bug was never the
    prediction; it was writing the answer to the wrong lock. Keeping the
    prediction means the announcement and the state cannot disagree with each
    other, whatever the mask happens to say.
    """
    return not modifiers & _LOCK_BIT


def _patched_toggle_lock(self, keyboard_event) -> None:
    """Drive the lock the way the setting asks for."""
    global _just_set, _just_set_at
    try:
        if not keyboard_event.is_pressed_key():
            return
        chosen = mode()
        if (keyboard_event.keyval_name not in _CLAIMED_KEYS
                or chosen == MODE_ORCA):
            _debug(f"orca: handing {keyboard_event.keyval_name} back to Orca")
            _orig_toggle_lock(self, keyboard_event)
            return
        if chosen == MODE_SUPPRESS:
            _debug(f"suppress: doing nothing, mask=0x{keyboard_event.modifiers:x}")
            return
        target = target_from_mask(keyboard_event.modifiers)
        if not _wayland_set(target):
            _debug("wayland: the compositor would not take it; using Orca's way")
            _orig_toggle_lock(self, keyboard_event)
            return
        _just_set = target
        _just_set_at = time.time()
        _debug(f"wayland: mask=0x{keyboard_event.modifiers:x} "
               f"-> asked the compositor for {'on' if target else 'off'}")
    except Exception as error:  # pylint: disable=broad-exception-caught
        _log.warning("CapsLockFix: falling back to Orca's own toggle: %s", error)
        try:
            _orig_toggle_lock(self, keyboard_event)
        except Exception:  # pylint: disable=broad-exception-caught
            pass


def _patched_get_locking_state(self):
    """Announce what the toggle set, when it was this extension that set it.

    **Report it; do not recompute it.** Orca announces after toggling, so by
    the time this runs the state has changed. An earlier version recomputed the
    next transition here and announced the exact opposite.

    Nothing more than that. A version of this tracked the "real" state from the
    characters arriving, on the theory that Orca's mask was dead -- Orca does
    rewrite XWayland's keymap to ``NoAction()`` while Caps Lock is its
    modifier, and XWayland's lock bit was measured clear across 125 events. But
    the mask Orca gets does not come from XWayland at all: on this session the
    compositor sends it directly, in the ``mods`` argument of the
    ``org.freedesktop.a11y.KeyboardMonitor.KeyEvent`` signal. So Orca's
    announcements are already correct, which is what Toby said three times
    while I kept measuring the wrong bit.
    """
    try:
        if not self.is_locking_key() or not self.is_orca_modifier():
            return _orig_get_locking_state(self)
        if self.keyval_name not in _CLAIMED_KEYS:
            return _orig_get_locking_state(self)
        if _just_set is None or time.time() - _just_set_at > _HANDOFF_SECONDS:
            return _orig_get_locking_state(self)
        _debug(f"announce: saying {'on' if _just_set else 'off'}")
        return _just_set
    except Exception as error:  # pylint: disable=broad-exception-caught
        _log.warning("CapsLockFix: leaving the announcement to Orca: %s", error)
        return _orig_get_locking_state(self)


def install(settings_source=None) -> None:
    """Patch the toggle and the announcement. The mode is read per keypress.

    Deliberately unconditional, including for ``orca`` mode, where the patch
    hands straight back to Orca's own method and changes nothing. An earlier
    version skipped the patch when the mode was ``orca`` at startup -- which
    meant changing the setting in Preferences did nothing at all until the
    next Orca restart, and all three modes behaved identically. Reading the
    setting per keypress is what makes the choice live.
    """
    global _orig_toggle_lock, _orig_get_locking_state, _installed, _settings_source
    _settings_source = settings_source
    _configure_trace(settings_source)
    if _installed:
        return
    manager_class = type(orca_modifier_manager.get_manager())
    toggle = getattr(manager_class, "_toggle_modifier_lock", None)
    locking_state = getattr(input_event.KeyboardEvent, "get_locking_state", None)
    if toggle is None or locking_state is None:
        _log.warning("CapsLockFix: this Orca does not have both "
                     "_toggle_modifier_lock and get_locking_state; leaving "
                     "the lock alone.")
        return
    _orig_toggle_lock = toggle
    _orig_get_locking_state = locking_state
    manager_class._toggle_modifier_lock = _patched_toggle_lock
    input_event.KeyboardEvent.get_locking_state = _patched_get_locking_state
    _installed = True
    chosen = mode()
    _log.info("CapsLockFix: lock toggle patched; mode is '%s'.", chosen)
    # Only ask about the virtual keyboard when something is going to use it:
    # binding one means a round trip for the compositor's keymap, which costs
    # about 1.7s, and that is not something to spend on Orca's startup in a
    # mode that will never touch it.
    extra = ""
    if chosen == MODE_WAYLAND:
        extra = f" (virtual keyboard available: {_wayland_available()})"
    _debug(f"installed; mode is '{chosen}'{extra}")


def uninstall() -> None:
    """Put Orca's own toggle and announcement back."""
    global _orig_toggle_lock, _orig_get_locking_state, _installed
    global _settings_source, _just_set
    if not _installed:
        return
    type(orca_modifier_manager.get_manager())._toggle_modifier_lock = _orig_toggle_lock
    input_event.KeyboardEvent.get_locking_state = _orig_get_locking_state
    _orig_toggle_lock = None
    _orig_get_locking_state = None
    _settings_source = None
    _just_set = None
    _installed = False
    _log.info("CapsLockFix: restored Orca's own lock toggle.")
