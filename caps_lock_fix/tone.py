"""Pre-rendered, click-free beep for CapitalBeep.

A raw sine gated on and off mid-cycle clicks audibly, which matters a lot for a
tone that fires on every capital letter while arrowing through text. So the beep
is rendered once to a small WAV with a raised-cosine fade in and out and played
from a GStreamer pipeline.

Pipeline: filesrc ! wavparse ! audioconvert ! audioresample ! volume ! autoaudiosink

**The pipeline returns to NULL when each beep ends, and that matters on
Bluetooth.** It used to be prerolled to PAUSED and parked there between beeps,
so that a repeat needed only a seek rather than a device reopen. That holds the
audio device open, and on an A2DP output a stream held open across many short
sounds drifts from the transport until what you hand it lands behind the play
point and is discarded. Toby's report: *"the tone can just vanish altogether if
you hear the beep too often"* -- which, reading multilingual text with a beep
on every capital, is often.

Orca's own ``audio_themes`` add-on returns its pipeline to NULL on EOS and
plays as many sounds as you like on A2DP without cutting off; the indent
beeper had the same fault from holding one stream in PLAYING and was fixed the
same way. Wired output forgives all of this, which is why it went unnoticed.

The cost is a device open per beep, tens of milliseconds. Going back to NULL
also means every beep restarts from the top, so a beep arriving while one is
still sounding interrupts it -- which is what you want at arrow-key speed.
"""

from __future__ import annotations

import logging
import math
import os
import struct
import wave

import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst

_log = logging.getLogger("orca-capitalbeep")

SAMPLE_RATE = 48000

_gst_initialised = False


def _ensure_gst() -> None:
    global _gst_initialised
    if not _gst_initialised:
        Gst.init(None)
        _gst_initialised = True


def render_wav(path: str, frequency: int, duration_ms: int, fade_ms: int) -> bool:
    """Render a mono 16-bit sine with fade in/out to path. Returns True on success."""
    try:
        total = max(1, int(SAMPLE_RATE * duration_ms / 1000))
        fade = max(1, min(total // 2, int(SAMPLE_RATE * fade_ms / 1000)))
        frames = bytearray()
        for i in range(total):
            sample = math.sin(2.0 * math.pi * frequency * i / SAMPLE_RATE)
            if i < fade:
                sample *= 0.5 - 0.5 * math.cos(math.pi * i / fade)
            elif i >= total - fade:
                remaining = total - 1 - i
                sample *= 0.5 - 0.5 * math.cos(math.pi * remaining / fade)
            frames += struct.pack("<h", int(max(-1.0, min(1.0, sample)) * 32767))

        os.makedirs(os.path.dirname(path), exist_ok=True)
        with wave.open(path, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(SAMPLE_RATE)
            handle.writeframes(bytes(frames))
        return True
    except Exception as error:
        _log.error("CapitalBeep: could not render %s: %s", path, error)
        return False


class BeepPlayer:
    """Plays one fixed WAV at a caller-supplied volume."""

    def __init__(self, wav_path: str) -> None:
        _ensure_gst()
        self._wav_path = wav_path
        self._pipeline: Gst.Pipeline | None = None
        self._volume: Gst.Element | None = None
        self._build()

    def _build(self) -> None:
        try:
            self._pipeline = Gst.parse_launch(
                "filesrc name=src ! wavparse ! audioconvert ! audioresample "
                "! volume name=vol ! autoaudiosink name=sink"
            )
        except Exception as error:
            _log.error("CapitalBeep: could not build pipeline: %s", error)
            self._pipeline = None
            return

        source = self._pipeline.get_by_name("src")
        self._volume = self._pipeline.get_by_name("vol")
        if source is None or self._volume is None:
            _log.error("CapitalBeep: pipeline is missing expected elements")
            self._pipeline = None
            return

        source.set_property("location", self._wav_path)

        bus = self._pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message::eos", self._on_eos)
        bus.connect("message::error", self._on_error)

        # Deliberately left in NULL. Nothing is prerolled and the device is not
        # held between beeps: see the module docstring.

    def _on_eos(self, _bus: Gst.Bus, _message: Gst.Message) -> None:
        """The beep finished: close the device.

        A message can still be in flight after shutdown() has dropped the
        pipeline, so never assume it is still there.
        """
        if self._pipeline is not None:
            self._pipeline.set_state(Gst.State.NULL)

    def _on_error(self, _bus: Gst.Bus, message: Gst.Message) -> None:
        error, info = message.parse_error()
        _log.error("CapitalBeep: %s (%s)", error, info)
        if self._pipeline is not None:
            self._pipeline.set_state(Gst.State.NULL)

    def play(self, volume: float) -> None:
        """Play the beep from the top, closing the device when it ends.

        A beep still sounding is cut short in favour of the new one: at
        arrow-key speed the beep you want is the one for the letter you are on.
        """
        if self._pipeline is None or self._volume is None:
            return

        self._volume.set_property("volume", max(0.0, min(1.0, volume)))
        # NULL first: it interrupts anything still sounding and rewinds the
        # file, so no seek is needed and nothing is carried over from the last
        # beep.
        self._pipeline.set_state(Gst.State.NULL)
        self._pipeline.set_state(Gst.State.PLAYING)

    def shutdown(self) -> None:
        """Release the pipeline."""
        pipeline, self._pipeline = self._pipeline, None
        if pipeline is not None:
            pipeline.set_state(Gst.State.NULL)
            bus = pipeline.get_bus()
            if bus is not None:
                # Otherwise the watch keeps a GSource -- and this object --
                # alive for the rest of the session.
                bus.remove_signal_watch()
        self._volume = None
