"""
core/tts.py — Offline Text-to-Speech for WALL-E AI
Uses espeak-ng (pre-installed on Raspberry Pi OS) for instant
audio feedback without requiring a Gemini connection.

Design: plays directly via espeak-ng subprocess → PipeWire/ALSA.
This is far more reliable at boot than sounddevice which needs the
audio pipeline to be configured first.

Created by K.Astra and its members.
"""

from __future__ import annotations

import subprocess
import threading

from core.logger import get_logger

log = get_logger("tts")


# ── Voice settings ────────────────────────────────────────────────────────────
_VOICE   = "en+f3"   # espeak-ng variant: female, slightly robotic
_SPEED   = 145       # words per minute
_PITCH   = 55        # 0–99
_VOLUME  = 180       # 0–200 amplitude


def _espeak(text: str) -> bool:
    """
    Play text through espeak-ng directly to the system audio output.
    Returns True on success, False if espeak-ng is not installed.
    """
    try:
        result = subprocess.run(
            [
                "espeak-ng",
                "-v", _VOICE,
                "-s", str(_SPEED),
                "-p", str(_PITCH),
                "-a", str(_VOLUME),
                text,
            ],
            timeout=20,
            # Do NOT capture output — audio goes directly to the speaker
        )
        return result.returncode == 0
    except FileNotFoundError:
        log.warning(
            "espeak-ng not found. Install with: sudo apt install espeak-ng -y"
        )
        return False
    except subprocess.TimeoutExpired:
        log.warning("espeak-ng timed out.")
        return False
    except Exception as e:
        log.warning(f"espeak-ng error: {e}")
        return False

def play_wake_chime() -> bool:
    """
    Plays a Siri-style instant dual-tone ascending chime.
    Takes ~0.2 seconds and sounds highly professional.
    """
    try:
        import sounddevice as sd
        import numpy as np
        
        fs = 44100
        # Siri-style rising tones: G#4 (415Hz) -> C#5 (554Hz)
        f1, f2 = 415.3, 554.37
        duration1, duration2 = 0.1, 0.15
        
        t1 = np.linspace(0, duration1, int(fs * duration1), False)
        t2 = np.linspace(0, duration2, int(fs * duration2), False)
        
        # Exponential decay envelope for a "ping" sound
        env1 = np.exp(-15 * t1)
        env2 = np.exp(-10 * t2)
        
        # Combine the sine waves with their envelopes
        tone1 = np.sin(2 * np.pi * f1 * t1) * env1
        tone2 = np.sin(2 * np.pi * f2 * t2) * env2
        
        # Concatenate and normalize
        wave = np.concatenate((tone1, tone2))
        wave = wave * 0.5  # 50% volume
        
        # Play instantly (blocks for 0.25s until finished)
        sd.play(wave, fs, blocking=True)
        return True
    except Exception as e:
        log.warning(f"Failed to play wake chime: {e}")
        return False

def speak(text: str, block: bool = True) -> None:
    """
    Speak text aloud.

    Args:
        text:  The text to speak.
        block: If True, waits until playback finishes.
               If False, plays in a background thread (fire and forget).
    """
    if not block:
        t = threading.Thread(target=speak, args=(text, True), daemon=True)
        t.start()
        return

    log.info(f"[TTS] '{text}'")
    _espeak(text)


# ── Pre-defined phrases ───────────────────────────────────────────────────────

def say_boot_ready() -> None:
    """Spoken when all AI models are loaded and WALL-E is listening."""
    speak("Say my name to start", block=False)


def say_session_start(speaker: str = "") -> None:
    """Spoken immediately when wake word is detected, while Gemini connects."""
    name = speaker.strip()
    if name and name.lower() not in ("unknown", "user", ""):
        greeting = f"Hi {name}! I am WALL-E. How may I help you?"
    else:
        greeting = "Hi! I am WALL-E. How may I help you?"
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
