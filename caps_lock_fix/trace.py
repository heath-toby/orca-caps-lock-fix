"""One debug log, shared by both halves of the extension.

Both the click counter and the lock toggle want to write to the same file, on
the same timeline, so that a line from one can be read against a line from the
other -- and against ``tools/true-lock-log.py``, which uses the same wall
clock. Two modules each opening the same path with their own handle is how you
get interleaved half-lines.

Never inside the extension package: Orca hashes every file in it and would
refuse to load a package whose log had grown.
"""

from __future__ import annotations

import os
import time

_DIR = os.path.join(
    os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")),
    "orca", "caps_lock_fix")
PATH = os.path.join(_DIR, "debug.log")

_settings_source = None
_handle = None


def configure(settings_source=None) -> None:
    """Remember where to read the ``debug`` setting from."""
    global _settings_source
    _settings_source = settings_source


def enabled() -> bool:
    """True if the user asked for diagnostics."""
    if _settings_source is None:
        return False
    try:
        return bool(_settings_source().get("debug", False))
    except Exception:  # pylint: disable=broad-exception-caught
        return False


def log(message: str) -> None:
    """Append one timestamped line, if diagnostics are on."""
    global _handle
    if not enabled():
        return
    try:
        if _handle is None:
            os.makedirs(_DIR, exist_ok=True)
            _handle = open(PATH, "a")  # pylint: disable=consider-using-with
        stamp = time.strftime("%H:%M:%S")
        _handle.write(f"{stamp}.{int(time.time() * 1000) % 1000:03d} {message}\n")
        _handle.flush()
    except Exception:  # pylint: disable=broad-exception-caught
        pass
