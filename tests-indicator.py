#!/usr/bin/env python3
"""Tests for the caps lock indication.

``caps_lock_indication_wanted`` is a pure function of (pressed, modifiers,
text, mode), so the whole rule can be stated as a table and no audio is
involved.

The rule infers caps lock from the character that actually arrived rather than
reading a lock bit. On Wayland there are two lock states -- the compositor's
and XWayland's copy -- and which one reaches an add-on depends on how the
session routes accessibility key events. The letter that came out needs none of
that settled, and it is also the thing the indication is about.

This moved here from CapitalBeep, where it shipped as v2.2.0. These rows came
with it, including the one that caught the bug that version shipped with.

Run after ./install.sh -- it tests the installed package.

Usage: python3 tests-indicator.py
"""

from __future__ import annotations

import os
import sys

import orca.extension_loader  # noqa: F401  (import order: see install.sh)

sys.path.insert(0, os.path.expanduser("~/.local/share/orca/extensions"))

import gi  # noqa: E402
gi.require_version("Atspi", "2.0")
from gi.repository import Atspi  # noqa: E402

from orca import keybindings  # noqa: E402

from caps_lock_fix import caps_indicator as ci  # noqa: E402

rows, fails = [], 0


def check(name, got, want):
    global fails
    ok = got == want
    if not ok:
        fails += 1
    # Record what was compared, not a reference to it: a live list appended to
    # later would print its final state beside a verdict reached earlier.
    rows.append((name, repr(want), repr(got), "ok" if ok else "FAIL"))


SHIFT = keybindings.SHIFT_MODIFIER_MASK
ORCA = keybindings.ORCA_MODIFIER_MASK
ALT = keybindings.ALT_MODIFIER_MASK
CTRL = 1 << 2
NONE = 0

LOWER, EVERY, SPEAK, OFF = (ci.MODE_LOWERCASE, ci.MODE_EVERY,
                            ci.MODE_SPEAK, ci.MODE_OFF)


def wanted(modifiers, text, mode, pressed=True):
    return ci.caps_lock_indication_wanted(pressed, modifiers, text, mode)


# --- the case the default exists for --------------------------------------
# Shift held and a lowercase letter came out: caps lock is on and has just
# given you the opposite of what you asked for. This is NVDA's case.
check("shift plus a lowercase letter reports, in the default mode",
      wanted(SHIFT, "a", LOWER), True)
check("...and in the every-letter mode", wanted(SHIFT, "a", EVERY), True)
check("...and in the speaking mode", wanted(SHIFT, "a", SPEAK), True)

# --- caps lock doing what it says ----------------------------------------
check("an unshifted capital is silent in the default mode",
      wanted(NONE, "A", LOWER), False)
check("...but reports in the every-letter mode", wanted(NONE, "A", EVERY), True)
check("...and in the speaking mode, which is the point of it",
      wanted(NONE, "A", SPEAK), True)

# --- ordinary typing, caps lock off --------------------------------------
check("plain lowercase typing never reports", wanted(NONE, "a", LOWER), False)
check("...not in the every-letter mode", wanted(NONE, "a", EVERY), False)
check("...and not in the speaking mode either", wanted(NONE, "a", SPEAK), False)
check("a properly shifted capital never reports", wanted(SHIFT, "A", LOWER), False)
check("...not in the every-letter mode", wanted(SHIFT, "A", EVERY), False)
check("...and not in the speaking mode", wanted(SHIFT, "A", SPEAK), False)

# --- off is off -----------------------------------------------------------
check("the off mode reports nothing", wanted(SHIFT, "a", OFF), False)
check("...including the unshifted capital", wanted(NONE, "A", OFF), False)

# --- commands are not typing ---------------------------------------------
# The important rows on a laptop layout: Caps_Lock is the Orca modifier
# there, so without these every Orca command would look like a letter typed
# with caps lock on. CapitalBeep 2.2.0 shipped with this term dead, and
# Orca+Shift+H to list headings beeped.
check("an Orca-modified letter is a command, not typing",
      wanted(ORCA, "a", EVERY), False)
check("...and so is a shifted one", wanted(ORCA | SHIFT, "a", LOWER), False)
check("...and the speaking mode does not read it out either",
      wanted(ORCA | SHIFT, "a", SPEAK), False)
check("a control-modified letter is a command", wanted(CTRL, "A", EVERY), False)
check("an alt-modified letter is a command", wanted(ALT, "a", LOWER), False)

# --- only single letters count -------------------------------------------
check("digits do not report", wanted(SHIFT, "1", EVERY), False)
check("punctuation does not report", wanted(SHIFT, ",", EVERY), False)
check("space does not report", wanted(NONE, " ", EVERY), False)
check("a modifier key, which produces no text, does not report",
      wanted(SHIFT, "", EVERY), False)
check("no text at all does not report", wanted(SHIFT, None, EVERY), False)
check("a multi-character string does not report", wanted(SHIFT, "ab", EVERY), False)

# --- releases ------------------------------------------------------------
check("a key release never reports", wanted(SHIFT, "a", LOWER, pressed=False), False)

# --- not just Latin ------------------------------------------------------
# Toby reads Russian, and Cyrillic pairs its cases under shift exactly as
# Latin does, so the same inference holds.
check("Cyrillic: shift plus a lowercase letter reports",
      wanted(SHIFT, "д", LOWER), True)
check("Cyrillic: an unshifted capital reports in the every-letter mode",
      wanted(NONE, "Д", EVERY), True)
check("Cyrillic: plain lowercase typing does not report",
      wanted(NONE, "д", LOWER), False)

# --- the settings are read defensively -----------------------------------
ci._settings_source = lambda: {"caps-lock-indicator": "nonsense"}
check("an unknown mode falls back to the default", ci.mode(), ci.MODE_DEFAULT)
ci._settings_source = lambda: {"caps-lock-indicator": SPEAK}
check("a known mode is honoured", ci.mode(), SPEAK)
ci._settings_source = lambda: {"caps-lock-pitch": 99999}
check("an absurd pitch is clamped", ci.pitch(), ci.PITCH_MAX)
ci._settings_source = lambda: {"caps-lock-pitch": 1}
check("...at both ends", ci.pitch(), ci.PITCH_MIN)
ci._settings_source = lambda: {"caps-lock-pitch": "not a number"}
check("an unusable pitch falls back", ci.pitch(), ci.FREQUENCY_HZ)
ci._settings_source = lambda: {}
check("an absent setting falls back to the default", ci.mode(), ci.MODE_DEFAULT)


def _raises():
    raise RuntimeError("settings unavailable")


ci._settings_source = _raises
check("a settings source that throws falls back rather than breaking the keyboard",
      ci.mode(), ci.MODE_DEFAULT)
ci._settings_source = None
check("no settings source at all falls back too", ci.mode(), ci.MODE_DEFAULT)

check("the default mode is the one NVDA has shipped for years",
      ci.MODE_DEFAULT, ci.MODE_LOWERCASE)
check("the tone is pitched an octave clear of CapitalBeep's 660Hz",
      ci.FREQUENCY_HZ >= 660 * 2, True)

# --- the hook must never break the keyboard ------------------------------
# This sits in front of every key Orca handles. A signature that does not
# match, or an exception that escapes, does not cost an announcement -- it
# costs the keyboard, which for this user is everything.
import inspect  # noqa: E402

from orca import input_event  # noqa: E402

real = inspect.signature(input_event.KeyboardEvent.__init__)
hook = inspect.signature(ci._keyboard_hook)
check("the hook takes the same parameters as the constructor it replaces",
      list(hook.parameters), list(real.parameters))

# Why the constructor rather than InputEventManager.process_keyboard_event,
# which is the obvious seam: on AT-SPI below 2.60, Orca hands
# Atspi.Device.add_key_watcher the *bound* process_keyboard_event at startup,
# so AT-SPI keeps the pre-patch object and a class patch is never called. A
# constructor is looked up on the class when it runs, so it works either way.
check("this AT-SPI is old enough for that to have mattered",
      Atspi.get_version()[1] < 60, True)

forwarded = []


def _fake_original(self, pressed, keycode, keysym, modifiers, text):
    forwarded.append((pressed, text))


class _Event:
    pass


_saved_original = ci._orig_key_init
ci._orig_key_init = _fake_original
ci._settings_source = lambda: {"caps-lock-indicator": OFF}

ci._keyboard_hook(_Event(), True, 0, 0, SHIFT, "a")
check("the hook builds the event before looking at it", forwarded, [(True, "a")])

# And if the indication itself blows up -- no audio device, a GStreamer fault,
# speech unavailable -- the key must still get through.
_saved_beep, _saved_speak = ci.beep, ci.speak


def _exploding():
    raise RuntimeError("no audio device")


ci.beep = _exploding
ci._settings_source = lambda: {"caps-lock-indicator": LOWER}
forwarded.clear()
ci._keyboard_hook(_Event(), True, 0, 0, SHIFT, "a")
check("an indication that raises still leaves the event built",
      forwarded, [(True, "a")])

# --- beep or speak, according to the mode --------------------------------
beeps, spoken = [], []
ci.beep = lambda: beeps.append(1)
ci.speak = lambda letter: spoken.append(letter)


class _PlainEvent:
    def __init__(self):
        self.modifiers = SHIFT


ci._settings_source = lambda: {"caps-lock-indicator": LOWER}
beeps.clear(); spoken.clear()
ci._keyboard_hook(_PlainEvent(), True, 0, 0, SHIFT, "h")
check("the default mode beeps and says nothing", (len(beeps), spoken), (1, []))

# --- the speaking mode must not speak from the constructor ---------------
# KeyboardEvent._present runs after the constructor and opens with
# `if self.is_pressed_key(): interrupt_presentation()`, so anything spoken
# from __init__ is cut off by the very keystroke that produced it. The beep
# survived because it is a separate audio pipeline; the speech did not, and
# Toby heard one letter per word: "character reading is only word reading
# really, though the capital beep plays."
ci._settings_source = lambda: {"caps-lock-indicator": SPEAK}
beeps.clear(); spoken.clear()
ci._keyboard_hook(_PlainEvent(), True, 0, 0, SHIFT, "h")
check("the speaking mode does nothing from the constructor",
      (beeps, spoken), ([], []))

# --- it speaks from the seam after that interrupt ------------------------
presented = []


def _fake_present(self, event):
    presented.append(getattr(event, "_text", None))


class _PresentEvent:
    """An event as present_keyboard_event receives it."""

    def __init__(self, text, modifiers=SHIFT, pressed=True):
        self._text = text
        self.modifiers = modifiers
        self._pressed = pressed

    def is_pressed_key(self):
        return self._pressed


_saved_present = ci._orig_present_keyboard_event
ci._orig_present_keyboard_event = _fake_present

spoken.clear(); presented.clear()
ci._present_hook(None, _PresentEvent("h"))
check("the speaking mode reads the letter from the present hook",
      spoken, ["h"])
check("...after letting Orca present the event first", presented, ["h"])

spoken.clear()
ci._present_hook(None, _PresentEvent("h", modifiers=SHIFT | ORCA))
check("...and an Orca command is still not read out", spoken, [])

spoken.clear()
ci._present_hook(None, _PresentEvent("h", pressed=False))
check("...nor is a key release", spoken, [])

ci._settings_source = lambda: {"caps-lock-indicator": LOWER}
spoken.clear(); presented.clear()
ci._present_hook(None, _PresentEvent("h"))
check("a beeping mode says nothing from the present hook", spoken, [])
check("...but Orca still gets to present the event", presented, ["h"])

ci._settings_source = lambda: {"caps-lock-indicator": SPEAK}


def _exploding_present(self, event):
    raise RuntimeError("presentation failed")


ci._orig_present_keyboard_event = _exploding_present
raised = False
try:
    ci._present_hook(None, _PresentEvent("h"))
except RuntimeError:
    raised = True
check("a failure in Orca's own presentation is not swallowed by this hook",
      raised, True)
ci._orig_present_keyboard_event = _saved_present

# --- the mask tested must be the event's own -----------------------------
# Orca ORs its modifier bit into self.modifiers *inside* the constructor, so
# the bit is never present in the `modifiers` argument. CapitalBeep 2.2.0
# tested the argument, which made the whole Orca-modifier term dead code.
class _OrcaModifierEvent:
    """An event whose own mask carries Orca's modifier bit, as Orca's does."""

    def __init__(self):
        self.modifiers = SHIFT | ORCA


ci._settings_source = lambda: {"caps-lock-indicator": SPEAK}
beeps.clear(); spoken.clear()
ci._keyboard_hook(_OrcaModifierEvent(), True, 0, 0, SHIFT, "h")
check("an Orca command is neither beeped nor read out",
      (beeps, spoken), ([], []))

ci._settings_source = lambda: {"caps-lock-indicator": LOWER}
beeps.clear()
ci._keyboard_hook(_Event(), True, 0, 0, SHIFT, "h")
check("an event with no mask of its own falls back to the argument",
      len(beeps), 1)

ci.beep, ci.speak = _saved_beep, _saved_speak
ci._orig_key_init = _saved_original
ci._settings_source = None

# --- speaking goes through the method CapitalBeep wraps ------------------
# Not an implementation detail: SpeechPresenter.speak_character is the single
# point every individually-read character passes through, and it is the
# instance method CapitalBeep patches. So a letter read out here also carries
# CapitalBeep's capital beep when both add-ons are installed, which is the
# behaviour Toby asked for rather than a coincidence of wiring.
from orca import speech_presenter  # noqa: E402

check("SpeechPresenter still has the method the speaking mode calls",
      callable(getattr(speech_presenter.get_presenter(), "speak_character", None)),
      True)

said = []
_presenter = speech_presenter.get_presenter()
_saved_speak_character = _presenter.speak_character
_presenter.speak_character = lambda character, *a, **k: said.append(character)
ci.speak("Q")
check("...and the speaking mode calls it with the letter", said, ["Q"])
_presenter.speak_character = _saved_speak_character

width = max(len(r[0]) for r in rows)
print()
for name, want, got, status in rows:
    print(f"  {status:4s} {name:<{width}}  want={want}  got={got}")
print(f"\n{len(rows) - fails}/{len(rows)} rows green")
sys.exit(1 if fails else 0)
