"""
pipelines/wake_pipeline.py — WALL-E AI Wake Word Detection
Listens on the online audio queue for the configurable wake word variants
using faster-whisper. Returns the audio file path that triggered the wake.

Extracted from main.py — now independently swappable.
To upgrade wake engine: replace this file only.
Created by K.Astra and its members.
"""

import asyncio
import os
import queue
import tempfile
import time

import numpy as np
import scipy.io.wavfile as wav

from pipelines.base import AbstractPipeline
from core.config import settings
from core.logger import get_logger

log = get_logger("pipeline.wake")


class WakePipeline(AbstractPipeline):
    """
    Wake word detection pipeline using faster-whisper (tiny model).
    Runs a sliding window over the audio queue and transcribes chunks
    looking for any of the configured wake_variants.

    Usage:
        wake = WakePipeline(audio_queue)
        await wake.start()
        audio_path = await wake.wait_for_wake()
    """

    name = "wake_pipeline"

    def __init__(self, audio_queue: queue.Queue):
        self._audio_queue = audio_queue
        self._model = None
        self._ready = False

    async def start(self) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._load_model)

    def _load_model(self):
        try:
            from faster_whisper import WhisperModel
            model_size    = settings.whisper_model_size
            compute_type  = settings.whisper_compute_type
            log.info(
                f"Loading wake word model (whisper-{model_size}, "
                f"compute={compute_type}, pi={settings.is_raspberry_pi})..."
            )
            self._model = WhisperModel(
                model_size, device="cpu", compute_type=compute_type
            )
            self._ready = True
            log.info(f"Wake word model loaded: whisper-{model_size} ({compute_type})")
        except Exception as e:
            log.error(f"Failed to load wake word model: {e}")

    async def stop(self) -> None:
        self._ready = False
        self._model = None

    async def health(self) -> dict:
        return {
            "status": "ok" if self._ready else "not_ready",
            "model": "whisper-tiny",
            "wake_variants": settings.wake_variants,
        }

    async def wait_for_wake(self) -> str:
        """
        Block until a wake word is detected.
        Returns the path to the audio temp file that triggered the wake.
        Caller is responsible for deleting the file after use.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._listen_blocking)

    def _listen_blocking(self) -> str:
        """Blocking wake word listener. Runs in a thread pool executor."""
        sr = settings.sample_rate_in
        bytes_per_sec = sr * 2  # int16 = 2 bytes
        chunk_bytes = int(bytes_per_sec * (settings.wake_chunk_ms / 1000.0))
        buffer = bytearray()

        log.info(f"Listening for wake word: {settings.wake_variants}")

        while True:
            try:
                data = self._audio_queue.get(timeout=1.0)
                buffer.extend(data)

                if len(buffer) >= chunk_bytes:
                    process_buf = buffer[:chunk_bytes]
                    # Slide window: drop first 0.5 s to avoid boundary misses
                    del buffer[:int(bytes_per_sec * 0.5)]

                    audio_arr = np.frombuffer(process_buf, dtype="int16").astype(np.float32)

                    # Normalize audio to 60% max amplitude so VAD detects quiet mics
                    peak = np.abs(audio_arr).max()
                    if peak > 0:
                        audio_arr = audio_arr * (32767 * 0.6 / peak)
                    audio_arr = audio_arr.astype(np.int16)

                    tmp = tempfile.mktemp(suffix=".wav")
                    wav.write(tmp, sr, audio_arr)

                    segs, _ = self._model.transcribe(
                        tmp,
                        beam_size=1,
                        language="en",
                        vad_filter=True,
                        vad_parameters={
                            "threshold": 0.2,              # Lower = more sensitive (default 0.5)
                            "min_speech_duration_ms": 200, # Detect short words like "wally"
                            "min_silence_duration_ms": 300,
                        },
                    )
                    text = " ".join(s.text for s in segs).lower().strip()

                    if any(v in text for v in settings.wake_variants):
                        log.info(f"Wake word detected: '{text}'")
                        return tmp   # caller must delete

                    os.unlink(tmp)

            except queue.Empty:
                continue
            except Exception as e:
                log.error(f"Wake listener error: {e}")
                time.sleep(1)

