"""Caps Lock Fix: count a double press of the Orca modifier press to press.

Orca 51 user extension. Install to $XDG_DATA_HOME/orca/extensions/ and
approve with ``orca --approve-extension caps_lock_fix``; Orca re-checks the
hash of every file in the package on each start, so re-approve after editing.
"""

__version__ = "2.0.0"

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


class CapsLockFix(Extension):
    """Measures a double press of the Orca modifier from press to press."""

    GROUP_LABEL = "Caps Lock Fix"
    DESCRIPTION = (
        "Counts a double press of the Orca modifier from one press to the next "
        "rather than from the release of the first, so holding the modifier and "
        "then pressing it again no longer reads as a request to toggle the lock."
    )
    VERSION = "2.0.0"  # keep in sync with __version__; read by AST, must be a literal
    AUTHOR = "Toby"

    def get_preferences(self) -> list[ExtensionPreference]:
        """Returns this extension's declarative preferences."""

        return [
            ExtensionPreference.integer(
                "window-ms",
                "Longest gap between the two presses of a double press, in milliseconds",
                _DEFAULT_WINDOW_MS, _WINDOW_MIN_MS, _WINDOW_MAX_MS,
            ),
            ExtensionPreference.boolean(
                "debug", "Log diagnostics to caps_lock_fix/debug.log", False,
            ),
        ]

    # Installed unconditionally and reading its settings per keypress, so
    # changing the window in Preferences takes effect at once.

    def on_ready(self) -> None:
        """Patches the click-count decision once Orca is up."""

        _install_clicks(lambda: self.settings)

    def on_enabled(self) -> None:
        """Patches it again after a reload."""

        _install_clicks(lambda: self.settings)

    def on_disabled(self) -> None:
        """Restores Orca's own click counting."""

        _uninstall_clicks()
