"""Set the caps lock through the compositor, with a Wayland virtual keyboard.

**Why this exists.** ``XkbLockModifiers`` writes XWayland's private copy of the
lock state, and that is not the copy which decides what characters you get.
Proven the hard way: after a rapid double-double press, typed characters came
out uppercase with the lock bit in their event masks while XKB and Orca's
announcement both said off. The compositor owns the state that matters.

``zwp_virtual_keyboard_v1`` is the only route a client has to it. Niri
advertises ``zwp_virtual_keyboard_manager_v1``, and the protocol runs cleanly
here: the compositor accepts the keymap and the modifiers request without
complaint.

**What is not proven** is whether the compositor applies a virtual keyboard's
locked modifiers to the session as a whole, or only to keys sent from that
virtual keyboard. ``xset`` cannot answer it, because xset reads the X copy. The
only reader that has never lied about this is which characters actually arrive
when a key is pressed, and that needs a person at the keyboard. So this ships
behind a setting, off by default.

Spoken straight over the wire, because there are no Python Wayland bindings
here: enough of the protocol to bind a seat and the virtual keyboard manager,
borrow the compositor's own keymap from ``wl_keyboard.keymap``, hand it to a
virtual keyboard, and send modifiers.
"""

from __future__ import annotations

import array
import logging
import os
import select
import socket
import struct
import time

_log = logging.getLogger("orca-caps-lock-fix")

_DISPLAY = 1
_REGISTRY = 2
_SYNC = 3
_SEAT = 4
_MANAGER = 5
_KEYBOARD = 6
_VKBD = 7

LOCK_MASK = 1 << 1

# Opcodes, from wayland.xml and virtual-keyboard-unstable-v1.xml.
_DISPLAY_SYNC, _DISPLAY_GET_REGISTRY = 0, 1
_REGISTRY_BIND = 0
_SEAT_GET_KEYBOARD = 1
_MANAGER_CREATE = 0
_VKBD_KEYMAP, _VKBD_KEY, _VKBD_MODIFIERS = 0, 1, 2


def _message(obj: int, opcode: int, body: bytes = b"") -> bytes:
    size = 8 + len(body)
    return struct.pack("<II", obj, (size << 16) | opcode) + body


def _wl_string(text: str) -> bytes:
    raw = text.encode() + b"\0"
    return struct.pack("<I", len(raw)) + raw + b"\0" * ((-len(raw)) % 4)


class _Connection:
    """A minimal Wayland client: send requests, collect events and fds."""

    def __init__(self) -> None:
        runtime = os.environ.get("XDG_RUNTIME_DIR")
        display = os.environ.get("WAYLAND_DISPLAY")
        if not runtime or not display:
            raise OSError("no Wayland session")
        path = display if display.startswith("/") else os.path.join(runtime, display)
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(1.5)
        self.sock.connect(path)
        self._buf = b""
        self.fds: list[int] = []

    def send(self, data: bytes, fd: int | None = None) -> None:
        if fd is None:
            self.sock.sendall(data)
            return
        self.sock.sendmsg(
            [data],
            [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", [fd]))])

    def pump(self, seconds: float = 0.4) -> None:
        """Read whatever has arrived, for at most ``seconds``.

        The deadline is enforced by ``select``, not by the socket timeout.
        An earlier version checked the clock only *between* reads and left
        the blocking ``recvmsg`` to the socket's own 1.5s timeout -- so
        ``pump(0.1)`` waited a flat 1.502 seconds for a reply the compositor
        never sends, inside Orca's main loop, on every caps lock press. That
        was the lag, and ``seconds=0`` now really means "take what is already
        here and return".
        """
        end = time.monotonic() + seconds
        while True:
            remaining = end - time.monotonic()
            if remaining < 0:
                return
            try:
                ready, _, _ = select.select([self.sock], [], [], remaining)
            except OSError:
                return
            if not ready:
                return
            try:
                data, ancdata, _flags, _addr = self.sock.recvmsg(65536, 4096)
            except (BlockingIOError, socket.timeout):
                return
            except OSError:
                return
            if not data:
                return
            for level, kind, payload in ancdata:
                if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                    self.fds.extend(array.array("i", payload).tolist())
            self._buf += data

    def events(self) -> list[tuple[int, int, bytes]]:
        out, i = [], 0
        while i + 8 <= len(self._buf):
            obj, word = struct.unpack_from("<II", self._buf, i)
            size, opcode = word >> 16, word & 0xFFFF
            if size < 8 or i + size > len(self._buf):
                break
            out.append((obj, opcode, self._buf[i + 8:i + size]))
            i += size
        self._buf = self._buf[i:]
        return out

    def first_error(self) -> str | None:
        for obj, opcode, body in self.events():
            if obj == _DISPLAY and opcode == 0 and len(body) >= 12:
                length = struct.unpack_from("<I", body, 8)[0]
                return body[12:12 + length - 1].decode("utf-8", "replace")
        return None

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


_conn: _Connection | None = None
_ready = False
_failed = False


def _setup() -> bool:
    """Bind everything and hand the compositor's keymap to a virtual keyboard."""
    global _conn, _ready, _failed
    if _ready:
        return True
    if _failed:
        return False
    try:
        conn = _Connection()
        conn.send(_message(_DISPLAY, _DISPLAY_GET_REGISTRY,
                           struct.pack("<I", _REGISTRY)))
        conn.send(_message(_DISPLAY, _DISPLAY_SYNC, struct.pack("<I", _SYNC)))
        conn.pump(0.6)

        seat = manager = None
        seat_version = 1
        for obj, opcode, body in conn.events():
            if obj != _REGISTRY or opcode != 0 or len(body) < 12:
                continue
            name = struct.unpack_from("<I", body, 0)[0]
            length = struct.unpack_from("<I", body, 4)[0]
            iface = body[8:8 + length - 1].decode("utf-8", "replace")
            version = struct.unpack_from("<I", body, 8 + ((length + 3) & ~3))[0]
            if iface == "wl_seat":
                seat, seat_version = name, version
            elif iface == "zwp_virtual_keyboard_manager_v1":
                manager = name
        if seat is None or manager is None:
            _log.info("CapsLockFix: no virtual keyboard protocol on this "
                      "compositor; leaving the lock alone.")
            conn.close()
            _failed = True
            return False

        conn.send(_message(_REGISTRY, _REGISTRY_BIND,
                           struct.pack("<I", seat) + _wl_string("wl_seat")
                           + struct.pack("<II", min(seat_version, 7), _SEAT)))
        conn.send(_message(_REGISTRY, _REGISTRY_BIND,
                           struct.pack("<I", manager)
                           + _wl_string("zwp_virtual_keyboard_manager_v1")
                           + struct.pack("<II", 1, _MANAGER)))
        # Borrow the compositor's own keymap rather than compiling one: the
        # virtual keyboard must be given a keymap before anything else, and
        # this is both correct by construction and free.
        conn.send(_message(_SEAT, _SEAT_GET_KEYBOARD, struct.pack("<I", _KEYBOARD)))
        conn.pump(0.8)

        keymap_format = keymap_size = None
        keymap_fd = None
        for obj, opcode, body in conn.events():
            if obj == _KEYBOARD and opcode == 0 and len(body) >= 8:
                keymap_format, keymap_size = struct.unpack_from("<II", body, 0)
                if conn.fds:
                    keymap_fd = conn.fds.pop(0)
        if keymap_fd is None or keymap_size is None:
            _log.warning("CapsLockFix: the compositor sent no keymap; "
                         "leaving the lock alone.")
            conn.close()
            _failed = True
            return False

        conn.send(_message(_MANAGER, _MANAGER_CREATE,
                           struct.pack("<II", _SEAT, _VKBD)))
        conn.send(_message(_VKBD, _VKBD_KEYMAP,
                           struct.pack("<II", keymap_format, keymap_size)),
                  fd=keymap_fd)
        os.close(keymap_fd)
        conn.pump(0.3)
        error = conn.first_error()
        if error:
            _log.warning("CapsLockFix: the compositor refused the virtual "
                         "keyboard: %s", error)
            conn.close()
            _failed = True
            return False
        _conn = conn
        _ready = True
        _log.info("CapsLockFix: a virtual keyboard is bound to the compositor.")
        return True
    except Exception as error:  # pylint: disable=broad-exception-caught
        _log.warning("CapsLockFix: could not set up a virtual keyboard: %s", error)
        _failed = True
        return False


def available() -> bool:
    """True if the compositor accepted a virtual keyboard."""
    return _setup()


def set_lock(on: bool) -> bool:
    """Ask the compositor to lock or unlock the caps lock."""
    if not _setup() or _conn is None:
        return False
    try:
        _conn.send(_message(_VKBD, _VKBD_MODIFIERS,
                            struct.pack("<IIII", 0, 0,
                                        LOCK_MASK if on else 0, 0)))
        # Nothing is waited for. The request draws no reply; a protocol error
        # would arrive asynchronously and is caught by the next pump. Orca's
        # main loop is in the middle of a key event and must not be held.
        _conn.pump(0.0)
        error = _conn.first_error()
        if error:
            _log.warning("CapsLockFix: the compositor rejected the modifiers "
                         "request: %s", error)
            return False
        return True
    except Exception as error:  # pylint: disable=broad-exception-caught
        _log.warning("CapsLockFix: could not send modifiers: %s", error)
        return False


def shutdown() -> None:
    """Drop the connection."""
    global _conn, _ready
    if _conn is not None:
        _conn.close()
    _conn = None
    _ready = False
