"""Caps Lock Fix: fix the double press, and say when caps lock is on.

Orca 51 user extension. Install to $XDG_DATA_HOME/orca/extensions/ and
approve with ``orca --approve-extension caps_lock_fix``; Orca re-checks the
hash of every file in the package on each start, so re-approve after editing.

Two independent halves, both about caps lock:

* **the double press**, counted from one press to the next rather than from
  the release of the first, so holding the modifier is not a request to
  toggle the lock; and
* **the indication**, a tone or the letters themselves, when caps lock is on.
  This arrived in 2.1.0 from CapitalBeep, where it had shipped as v2.2.0 and
  did not belong: CapitalBeep is about a capital being *read*, and this is
  about caps lock being *on*.
"""

__version__ = "2.1.0"

from orca.extension import Extension
from orca.extension_preferences import ExtensionPreference

# Import submodules as `from .module import name`, never as
# `from . import module`. The loader imports us as
# orca_user_extension.<name> but never creates `orca_user_extension`
# itself, and `from . import module` goes through __import__ with the
# full dotted path, which insists on importing that absent grandparent.
from .caps_indicator import FREQUENCY_HZ as _FREQUENCY_HZ
from .caps_indicator import MODE_DEFAULT as _MODE_DEFAULT
from .caps_indicator import MODE_EVERY as _MODE_EVERY
from .caps_indicator import MODE_LOWERCASE as _MODE_LOWERCASE
from .caps_indicator import MODE_OFF as _MODE_OFF
from .caps_indicator import MODE_SPEAK as _MODE_SPEAK
from .caps_indicator import PITCH_MAX as _PITCH_MAX
from .caps_indicator import PITCH_MIN as _PITCH_MIN
from .caps_indicator import install as _install_indicator
from .caps_indicator import uninstall as _uninstall_indicator
from .clicks import DEFAULT_WINDOW_MS as _DEFAULT_WINDOW_MS
from .clicks import WINDOW_MAX_MS as _WINDOW_MAX_MS
from .clicks import WINDOW_MIN_MS as _WINDOW_MIN_MS
from .clicks import install as _install_clicks
from .clicks import uninstall as _uninstall_clicks


class CapsLockFix(Extension):
    """Fixes the modifier double press, and reports caps lock being on."""

    GROUP_LABEL = "Caps Lock Fix"
    DESCRIPTION = (
        "Counts a double press of the Orca modifier from one press to the next "
        "rather than from the release of the first, so holding the modifier and "
        "then pressing it again no longer reads as a request to toggle the lock. "
        "Also reports that caps lock is on, by a tone or by reading each letter "
        "as it is typed."
    )
    VERSION = "2.1.0"  # keep in sync with __version__; read by AST, must be a literal
    AUTHOR = "Toby"

    def get_preferences(self) -> list[ExtensionPreference]:
        """Returns this extension's declarative preferences.

        The three original option labels are reproduced **verbatim** from
        CapitalBeep 2.2.0, where this setting lived before. A screen reader
        user navigates a settings dialog by remembered label text, so a port
        that rewords as it moves costs the user the thing they already knew.
        """

        return [
            ExtensionPreference.integer(
                "window-ms",
                "Longest gap between the two presses of a double press, in milliseconds",
                _DEFAULT_WINDOW_MS, _WINDOW_MIN_MS, _WINDOW_MAX_MS,
            ),
            ExtensionPreference.enum(
                "caps-lock-indicator",
                "Warn that caps lock is on",
                (
                    (_MODE_LOWERCASE,
                     "When a lowercase letter is typed, because caps lock is on"),
                    (_MODE_EVERY, "On every letter typed while caps lock is on"),
                    (_MODE_SPEAK, "Speak each letter typed while caps lock is on"),
                    (_MODE_OFF, "Never"),
                ),
                _MODE_DEFAULT,
            ),
            ExtensionPreference.integer(
                "caps-lock-pitch",
                "Pitch of the caps lock warning, in hertz",
                _FREQUENCY_HZ, _PITCH_MIN, _PITCH_MAX,
            ),
            ExtensionPreference.boolean(
                "debug", "Log diagnostics to caps_lock_fix/debug.log", False,
            ),
        ]

    # Both halves are installed unconditionally and read their settings per
    # keypress, so a change in Preferences takes effect at once.

    def on_ready(self) -> None:
        """Patches the click-count decision and the key hook once Orca is up."""

        _install_clicks(lambda: self.settings)
        _install_indicator(lambda: self.settings)

    def on_enabled(self) -> None:
        """Patches them again after a reload."""

        _install_clicks(lambda: self.settings)
        _install_indicator(lambda: self.settings)

    def on_disabled(self) -> None:
        """Restores Orca's own click counting and stops the indication."""

        _uninstall_indicator()
        _uninstall_clicks()
