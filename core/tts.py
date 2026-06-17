"""
core/tts.py — Offline Text-to-Speech for WALL-E AI
Uses espeak-ng (pre-installed on Raspberry Pi OS) for instant
audio feedback without requiring a Gemini connection.

Used for:
  - Boot greeting ("Hi, I'm WALL-E!")
  - Wake-word activation greeting
  - Connectivity error announcements

Created by K.Astra and its members.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import threading

from core.logger import get_logger

log = get_logger("tts")


# ── Default voice settings ────────────────────────────────────────────────────
_VOICE   = "en+f3"   # espeak-ng female voice (sounds robotic/friendly)
_SPEED   = 145       # words per minute (140-160 is natural)
_PITCH   = 55        # 0-99, higher = squeakier
_VOLUME  = 180       # 0-200 amplitude

# Cache: pre-rendered WAV bytes keyed by text so repeated phrases don't
# re-synthesize (saves ~200ms per call after first use).
_cache: dict[str, bytes] = {}
_cache_lock = threading.Lock()


def _synthesize(text: str) -> bytes | None:
    """
    Render text to raw WAV bytes using espeak-ng.
    Returns None if espeak-ng is not installed.
    """
    with _cache_lock:
        if text in _cache:
            return _cache[text]

    tmp = tempfile.mktemp(suffix=".wav")
    try:
        result = subprocess.run(
            [
                "espeak-ng",
                "-v", _VOICE,
                "-s", str(_SPEED),
                "-p", str(_PITCH),
                "-a", str(_VOLUME),
                "-w", tmp,
                text,
            ],
            capture_output=True,
            timeout=10,
        )
        if result.returncode != 0:
            log.warning(f"espeak-ng error: {result.stderr.decode()[:200]}")
            return None

        with open(tmp, "rb") as f:
            wav_bytes = f.read()

        with _cache_lock:
            _cache[text] = wav_bytes

        return wav_bytes

    except FileNotFoundError:
        log.warning("espeak-ng not found. Install with: sudo apt install espeak-ng")
        return None
    except Exception as e:
        log.warning(f"TTS synthesis failed: {e}")
        return None
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def speak(text: str, block: bool = True) -> None:
    """
    Speak text aloud through the system audio output.

    Args:
        text:  The text to speak.
        block: If True, waits until playback finishes before returning.
               If False, plays in a background thread.
    """
    if not block:
        t = threading.Thread(target=speak, args=(text, True), daemon=True)
        t.start()
        return

    log.info(f"[TTS] Speaking: '{text}'")

    wav_bytes = _synthesize(text)
    if not wav_bytes:
        # Last-resort fallback: play directly through espeak-ng → ALSA
        try:
            subprocess.run(
                ["espeak-ng", "-v", _VOICE, "-s", str(_SPEED), "-a", str(_VOLUME), text],
                timeout=15, capture_output=True
            )
        except Exception as e:
            log.warning(f"TTS fallback also failed: {e}")
        return

    # Play WAV through sounddevice (routes through PipeWire/PulseAudio properly)
    try:
        import io
        import numpy as np
        import scipy.io.wavfile as wavfile
        import sounddevice as sd

        sr, data = wavfile.read(io.BytesIO(wav_bytes))

        # Normalize dtype for sounddevice
        if data.dtype == np.int16:
            audio = data.astype(np.float32) / 32768.0
        elif data.dtype == np.int32:
            audio = data.astype(np.float32) / 2147483648.0
        else:
            audio = data.astype(np.float32)

        sd.play(audio, samplerate=sr, blocking=True)

    except Exception as e:
        log.warning(f"sounddevice playback failed: {e}. Falling back to direct espeak.")
        try:
            subprocess.run(
                ["espeak-ng", "-v", _VOICE, "-s", str(_SPEED), text],
                timeout=15, capture_output=True
            )
        except Exception:
            pass


# ── Pre-defined phrases ───────────────────────────────────────────────────────
def say_boot_ready() -> None:
    """Spoken once on boot to confirm WALL-E is listening."""
    speak("Hi! I am WALL-E. Say my name to wake me up.", block=False)


def say_session_start(speaker: str = "there") -> None:
    """Spoken immediately when wake word is detected, while Gemini connects."""
    greeting = (
        f"Hi {speaker}! I am WALL-E. How may I help you?"
        if speaker and speaker.lower() not in ("unknown", "user")
        else "Hi! I am WALL-E. How may I help you?"
    )
    speak(greeting, block=True)


def say_connectivity_error() -> None:
    """Spoken when Gemini API is unreachable."""
    speak(
        "There is some error in connectivity. "
        "Please check your internet connection. I will retry shortly.",
        block=True,
    )


def say_quota_error() -> None:
    """Spoken when Gemini API quota is exceeded."""
    speak(
        "My AI brain is temporarily overloaded. "
        "Please wait a moment and try again.",
        block=True,
    )
