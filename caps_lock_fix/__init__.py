"""Caps Lock Fix: count a double press of the Orca modifier press to press.

Orca 51 user extension. Install to $XDG_DATA_HOME/orca/extensions/ and
approve with ``orca --approve-extension caps_lock_fix``; Orca re-checks the
hash of every file in the package on each start, so re-approve after editing.
"""

__version__ = "1.5.1"

from orca.extension import Extension
from orca.extension_preferences import ExtensionPreference

# Import submodules as `from .module import name`, never as
# `from . import module`. The loader imports us as
# orca_user_extension.<name> but never creates `orca_user_extension`
# itself, and `from . import module` goes through __import__ with the
# full dotted path, which insists on importing that absent grandparent.
from .clicks import DEFAULT_WINDOW_MS as _DEFAULT_WINDOW_MS
from .clicks import WINDOW_MAX_MS as _WINDOW_MAX_MS
from .clicks import WINDOW_MIN_MS as _WINDOW_MIN_MS
from .clicks import install as _install_clicks
from .clicks import uninstall as _uninstall_clicks
from .lock_toggle import MODE_DEFAULT as _MODE_DEFAULT
from .lock_toggle import MODE_ORCA as _MODE_ORCA
from .lock_toggle import MODE_SUPPRESS as _MODE_SUPPRESS
from .lock_toggle import MODE_WAYLAND as _MODE_WAYLAND
from .lock_toggle import install as _install_lock
from .lock_toggle import uninstall as _uninstall_lock


class CapsLockFix(Extension):
    """Measures a double press of the Orca modifier from press to press."""

    GROUP_LABEL = "Caps Lock Fix"
    DESCRIPTION = (
        "Two fixes for caps lock on the laptop keyboard layout, where it is the "
        "Orca modifier. A double press is counted from one press to the next "
        "rather than from the release of the first, so holding the modifier and "
        "pressing it again no longer latches the lock. An experimental second "
        "half, off by default, can also drive the lock state itself, either "
        "through the Wayland compositor or by standing aside and letting the "
        "key do it."
    )
    VERSION = "1.5.1"  # keep in sync with __version__; read by AST, must be a literal
    AUTHOR = "Toby"

    def get_preferences(self) -> list[ExtensionPreference]:
        """Returns this extension's declarative preferences."""

        return [
            ExtensionPreference.integer(
                "window-ms",
                "Longest gap between the two presses of a double press, in milliseconds",
                _DEFAULT_WINDOW_MS, _WINDOW_MIN_MS, _WINDOW_MAX_MS,
            ),
            ExtensionPreference.enum(
                "lock-mode",
                "How to drive the caps lock state (experimental)",
                (
                    (_MODE_ORCA, "Leave it to Orca"),
                    (_MODE_WAYLAND,
                     "Set it through the Wayland compositor"),
                    (_MODE_SUPPRESS,
                     "Do nothing and let the key itself do it"),
                ),
                _MODE_DEFAULT,
            ),
            ExtensionPreference.boolean(
                "debug", "Log diagnostics to caps_lock_fix/debug.log", False,
            ),
        ]

    # Both halves are installed unconditionally and read their settings per
    # keypress, so changing the lock mode in Preferences takes effect at once.
    # The default mode hands the lock straight back to Orca and changes
    # nothing -- and that default is not timidity. There are two lock states
    # on Wayland: the compositor's, which decides which character a key
    # produces, and XWayland's copy, which is what AT-SPI's key synthesis and
    # XKB write to. Driving the copy was measured to *invert* the lock after a
    # rapid double-double press, with typed characters coming out uppercase
    # while every reader available to an X client said off. The two
    # alternatives are experiments, and the only instrument that can judge
    # them is somebody typing.

    def on_ready(self) -> None:
        """Patches the click-count decision once Orca is up."""

        _install_clicks(lambda: self.settings)
        _install_lock(lambda: self.settings)

    def on_enabled(self) -> None:
        """Patches it again after a reload."""

        _install_clicks(lambda: self.settings)
        _install_lock(lambda: self.settings)

    def on_disabled(self) -> None:
        """Restores Orca's own click counting and lock toggle."""

        _uninstall_lock()
        _uninstall_clicks()
