"""Tell the user that caps lock is on, by a tone or by reading the letters.

This moved here from CapitalBeep, where it had shipped as v2.2.0, because it
never belonged there. CapitalBeep is about a capital letter being *read*; this
is about caps lock being *on*, which is this extension's subject. Toby, making
the call: *"Leave Capital Beep as Capital Beep. Move the caps lock indicator
to caps lock fix, and that's where we can also add the ability if enabled to
speak each typed character while caps lock is on."*

**Caps lock is inferred from the character that actually arrived, not read
from a lock bit, and that is deliberate.** On Wayland there are two lock
states -- the compositor's and XWayland's copy -- and which one reaches an
add-on depends on how the session routes accessibility key events. The letter
that came out needs none of that settled: it is ground truth, decided by the
same keymap and the same lock state that will type the next one, and it is
also precisely what the indication is about.

- Shift held and a *lowercase* letter arrived: caps lock is on, and this is
  the letter you did not ask for. NVDA's case, on by default there since
  around 2010 as "Beep for lowercase with Capslock", and the default here.
- No shift and an *uppercase* letter arrived: caps lock is on and doing what
  it says. Only the "every letter" and "speak" modes report that.

The inference assumes a layout where shift pairs the cases of a letter, which
Latin and Cyrillic both do.

**The speaking mode is the one Fenrir has**, and it is a better answer than a
tone for anyone who leaves caps lock on by accident: a beep says "something is
wrong", a read letter says what. It speaks through
``SpeechPresenter.speak_character``, which is also the method CapitalBeep
wraps -- so with both add-ons installed, each letter is announced *and* carries
CapitalBeep's capital beep. That is not an accident of wiring, it is the point:
Toby, on hearing it described, *"if it's beeping with each letter, that can
continue connecting with 'these are all capitals', which makes a lot of
sense."*
"""

from __future__ import annotations

import logging
import os

from orca import (
    input_event,
    keybindings,
    presentation_manager,
    speech_manager,
    speech_presenter,
)

from .tone import BeepPlayer
from .tone import render_wav
from .trace import log as _debug

_log = logging.getLogger("orca-caps-lock-fix")

MODE_OFF = "off"
MODE_LOWERCASE = "lowercase"
MODE_EVERY = "every-letter"
MODE_SPEAK = "speak"
MODE_DEFAULT = MODE_LOWERCASE
MODES = (MODE_LOWERCASE, MODE_EVERY, MODE_SPEAK, MODE_OFF)

# An octave above CapitalBeep's 660 Hz capital beep, so the two cannot be
# confused when both are installed. NVDA distinguishes its two beeps the same
# way and uses 3000 Hz, which the pitch setting will take.
FREQUENCY_HZ = 1320
DURATION_MS = 60
FADE_MS = 8
PITCH_MIN, PITCH_MAX = 100, 8000

# A full-scale sine is far louder than speech at the same nominal level.
VOLUME_HEADROOM = 0.35

# Letters arriving with any of these held are commands, not typing. The Orca
# modifier matters especially here: on the laptop layout it *is* Caps_Lock, so
# without this every Orca command would look like a letter typed with caps
# lock on.
#
# **This must be tested against the event's own ``self.modifiers``, not the
# ``modifiers`` argument the constructor was called with.** Orca adds its
# modifier bit inside ``KeyboardEvent.__init__`` and not before it, so the bit
# is never present in the argument. CapitalBeep 2.2.0 shipped with that
# mistake and beeped at Orca+Shift+H.
_NOT_TYPING_MASK = (
    (1 << keybindings.MODIFIER_ORCA)
    | keybindings.ALT_MODIFIER_MASK
    | (1 << 2)  # Atspi.ModifierType.CONTROL
)

# The rendered tone lives outside the extension package: Orca hashes every
# file in it and would refuse to load a package whose contents had changed.
_DATA_DIR = os.path.join(
    os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")),
    "orca", "caps_lock_fix")

_settings_source = None
_orig_key_init = None
_orig_present_keyboard_event = None
_installed = False
_player: BeepPlayer | None = None
_pitch_rendered: int | None = None


def _setting(key, default):
    if _settings_source is None:
        return default
    try:
        return _settings_source().get(key, default)
    except Exception:  # pylint: disable=broad-exception-caught
        return default


def mode() -> str:
    """Which indication the user asked for. Unknown values fall back."""
    value = _setting("caps-lock-indicator", MODE_DEFAULT)
    if value not in MODES:
        return MODE_DEFAULT
    return value


def pitch() -> int:
    """The warning tone's frequency, clamped to something audible."""
    try:
        value = int(_setting("caps-lock-pitch", FREQUENCY_HZ))
    except (TypeError, ValueError):
        return FREQUENCY_HZ
    return max(PITCH_MIN, min(PITCH_MAX, value))


def caps_lock_indication_wanted(pressed: bool, modifiers: int, text: str,
                                chosen: str) -> bool:
    """True if this key press should report that caps lock is on.

    Pure, so the whole rule is testable without Orca and without a keyboard.
    """
    if not pressed or chosen == MODE_OFF:
        return False
    if modifiers & _NOT_TYPING_MASK:
        return False
    letter = text or ""
    if len(letter) != 1 or not letter.isalpha():
        return False
    shift_held = bool(modifiers & keybindings.SHIFT_MODIFIER_MASK)
    if shift_held and letter.islower():
        return True
    if not shift_held and letter.isupper():
        return chosen in (MODE_EVERY, MODE_SPEAK)
    return False


def _volume() -> float:
    """Track Orca's speech volume, scaled into GStreamer's range."""
    try:
        level = speech_manager.get_manager().get_volume()
    except Exception:  # pylint: disable=broad-exception-caught
        level = 10.0
    return max(0.0, min(1.0, (level / 10.0) * VOLUME_HEADROOM))


def _muted() -> bool:
    """True if Orca's speech is muted, in which case say nothing at all."""
    try:
        return bool(speech_manager.get_manager().get_speech_is_muted())
    except Exception:  # pylint: disable=broad-exception-caught
        return False


def beep() -> None:
    """Play the warning tone, re-rendering it if the pitch has changed."""
    global _player, _pitch_rendered
    if _muted():
        return
    wanted = pitch()
    if _player is None or _pitch_rendered != wanted:
        path = os.path.join(
            _DATA_DIR, f"caps_{wanted}hz_{DURATION_MS}ms_{FADE_MS}fade.wav")
        if not os.path.isfile(path):
            os.makedirs(_DATA_DIR, exist_ok=True)
            if not render_wav(path, wanted, DURATION_MS, FADE_MS):
                _debug(f"indicator: could not render a tone at {wanted}Hz")
                return
        if _player is not None:
            _player.shutdown()
        _player = BeepPlayer(path)
        _pitch_rendered = wanted
        _debug(f"indicator: built a player for {path}")
    _player.play(_volume())


def speak(letter: str) -> None:
    """Read the letter out, the way key echo does.

    Through ``PresentationManager.speak_character``, which is what Orca's own
    key echo reaches: it supplies the capitalisation style from Orca's
    settings and the voice for the character, and it ends at
    ``SpeechPresenter.speak_character`` -- the one point every individually
    read character passes through, and the method CapitalBeep wraps, so a
    capital also carries its beep.

    **Where this is called from matters more than what it calls.** The first
    version spoke from ``KeyboardEvent.__init__`` and only one letter per word
    could be heard, which Toby reported as *"character reading is only word
    reading really, though the capital beep plays."* The beep played because
    it is a separate audio pipeline; the speech did not, because
    ``KeyboardEvent._present`` runs after the constructor and begins::

        if self.is_pressed_key():
            presentation_manager.get_manager().interrupt_presentation()

    Every key press interrupts speech. Anything spoken from the constructor is
    cut off by the very keystroke that produced it. So the speaking mode is
    driven from ``present_keyboard_event`` instead, which is the call at the
    end of ``_present`` -- after that interrupt, and exactly where Orca echoes
    keys itself.
    """
    if _muted():
        return
    try:
        presentation_manager.get_manager().speak_character(letter)
    except Exception as error:  # pylint: disable=broad-exception-caught
        _log.warning("CapsLockFix: could not speak %r: %s", letter, error)
        _debug(f"indicator: could not speak {letter!r}: {error}")


def _keyboard_hook(self, pressed, keycode, keysym, modifiers, text):
    """Report caps lock being on, in front of every key Orca builds.

    ``KeyboardEvent.__init__`` is looked up on the class for every event, so a
    patch here always runs -- unlike the key watcher, which AT-SPI is handed as
    a bound method at startup and which a class patch never reaches on AT-SPI
    below 2.60.

    The original runs first and anything raised afterwards is swallowed: this
    sits in front of every keystroke, and no indication is worth breaking the
    keyboard for.
    """
    _orig_key_init(self, pressed, keycode, keysym, modifiers, text)
    try:
        # self.modifiers, not the argument: see _NOT_TYPING_MASK.
        mask = getattr(self, "modifiers", modifiers)
        chosen = mode()
        if chosen == MODE_SPEAK:
            # Not from here: the speech would be interrupted by this very
            # keystroke. See speak(). The event hook below does it.
            return
        if pressed and caps_lock_indication_wanted(pressed, mask, text, chosen):
            _debug(f"indicator: {chosen} tone for {text!r} mask=0x{mask:x}")
            beep()
    except Exception as error:  # pylint: disable=broad-exception-caught
        _log.warning("CapsLockFix: caps lock indication failed: %s", error)


def _present_hook(self, event):
    """Read the letter out after Orca has finished interrupting speech.

    ``_present`` interrupts on every key press and then calls this, which is
    why Orca's own key echo is audible and why a constructor hook is not. The
    original runs first, so this adds to what Orca presents rather than
    replacing it -- with key echo off, which is how Toby reads, Orca presents
    nothing here and the letter is all you hear.
    """
    _orig_present_keyboard_event(self, event)
    try:
        if mode() != MODE_SPEAK:
            return
        text = getattr(event, "_text", "") or ""
        if not caps_lock_indication_wanted(
                event.is_pressed_key(), event.modifiers, text, MODE_SPEAK):
            return
        _debug(f"indicator: speaking {text!r} mask=0x{event.modifiers:x}")
        speak(text)
    except Exception as error:  # pylint: disable=broad-exception-caught
        _log.warning("CapsLockFix: caps lock speech failed: %s", error)


def install(settings_source=None) -> None:
    """Start reporting caps lock. Patched unconditionally; the mode is read
    per keypress, so a change in Preferences takes effect at once."""
    global _settings_source, _orig_key_init, _installed
    global _orig_present_keyboard_event
    _settings_source = settings_source
    if _installed:
        return
    _orig_key_init = input_event.KeyboardEvent.__init__
    input_event.KeyboardEvent.__init__ = _keyboard_hook
    manager_class = type(presentation_manager.get_manager())
    _orig_present_keyboard_event = manager_class.present_keyboard_event
    manager_class.present_keyboard_event = _present_hook
    _installed = True
    _log.info("CapsLockFix: caps lock indication is '%s'.", mode())
    _debug(f"indicator: installed, mode is '{mode()}'")


def uninstall() -> None:
    """Stop reporting, and close the audio device."""
    global _settings_source, _orig_key_init, _installed, _player, _pitch_rendered
    global _orig_present_keyboard_event
    if not _installed:
        return
    input_event.KeyboardEvent.__init__ = _orig_key_init
    _orig_key_init = None
    manager_class = type(presentation_manager.get_manager())
    manager_class.present_keyboard_event = _orig_present_keyboard_event
    _orig_present_keyboard_event = None
    _installed = False
    _settings_source = None
    if _player is not None:
        _player.shutdown()
        _player = None
    _pitch_rendered = None
    _log.info("CapsLockFix: caps lock indication removed.")
