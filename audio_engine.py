"""
audio_engine.py — DEPRECATED
Kept as a backward-compatibility stub.
Use pipelines.audio_pipeline.AudioPipeline instead.
Created by K.Astra and its members.
"""

import warnings
warnings.warn(
    "audio_engine.py is deprecated. Use `from pipelines.audio_pipeline import AudioPipeline` instead.",
    DeprecationWarning,
    stacklevel=2,
)

# Thin compatibility wrapper (sync interface)
import queue
import sounddevice as sd
from core.config import settings
from core.logger import get_logger

log = get_logger("audio_engine.compat")


class AudioEngine:
    """Legacy-compatible wrapper around the new AudioPipeline."""

    def __init__(self, samplerate=16000, channels=1):
        self.samplerate = samplerate
        self.channels   = channels
        self.online_queue:  queue.Queue = queue.Queue()
        self.offline_queue: queue.Queue = queue.Queue()
        self._stream = None

    def audio_callback(self, indata, frames, time, status):
        if status:
            log.warning(f"Audio status: {status}")
        data = bytes(indata)
        self.offline_queue.put(data)
        self.online_queue.put(data)

    def start(self):
        try:
            self._stream = sd.RawInputStream(
                samplerate=self.samplerate,
                blocksize=8000,
                dtype="int16",
                channels=self.channels,
                callback=self.audio_callback,
            )
            self._stream.start()
            log.info("AudioEngine (compat) started.")
        except Exception as e:
            log.error(f"AudioEngine failed to start: {e}")

    def stop(self):
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
