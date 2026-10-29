"""The extension's debug log.

One writer, one handle. It was shared by two modules when there were two --
the click counter and the lock toggle -- so that a line from either could be
read against the other on the same timeline, and against
``tools/true-lock-log.py``, which uses the same wall clock. 2.0.0 removed the
lock toggle, so the click counter is the only writer now; the shape stays
because the file is still read beside that tool, and because two modules each
opening the same path with their own handle is how you get interleaved
half-lines.

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


# Diagnostics get left on. A log that grows without bound for as long as that
# setting is true is a trap, so the file is rolled once past this size and the
# previous run is kept beside it as .log.1.
MAX_BYTES = 2 * 1024 * 1024


def _roll_if_large() -> None:
    """Keep one old log and start a new one, if the current one is big."""
    try:
        if os.path.getsize(PATH) < MAX_BYTES:
            return
    except OSError:
        return
    global _handle
    try:
        if _handle is not None:
            _handle.close()
    except OSError:
        pass
    _handle = None
    try:
        os.replace(PATH, PATH + ".1")
    except OSError:
        pass


def log(message: str) -> None:
    """Append one timestamped line, if diagnostics are on."""
    global _handle
    if not enabled():
        return
    try:
        if _handle is None:
            os.makedirs(_DIR, exist_ok=True)
            _roll_if_large()
            _handle = open(PATH, "a")  # pylint: disable=consider-using-with
        stamp = time.strftime("%H:%M:%S")
        _handle.write(f"{stamp}.{int(time.time() * 1000) % 1000:03d} {message}\n")
        _handle.flush()
        if _handle.tell() >= MAX_BYTES:
            _roll_if_large()
    except Exception:  # pylint: disable=broad-exception-caught
        pass
