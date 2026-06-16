"""
pipelines/audio_pipeline.py — WALL-E AI Virtual Split Audio Engine
Captures microphone audio and fans it out to two queues:
  - online_queue  → Gemini Live streaming
  - offline_queue → Navigation / Arduino (offline Vosk)

Pi 5 specifics:
  - Configurable device index/name via WALLE_MIC_DEVICE env var
  - Configurable capture rate via WALLE_CAPTURE_RATE (e.g. 44100 for USB mics)
  - Auto-resamples from capture_rate → sample_rate_in (16000 Hz)
  - Larger blocksize (4096) to avoid ALSA underruns on ARM
  - Lists available devices on startup for easy setup

Created by K.Astra and its members.
"""

import asyncio
import queue
import threading
from math import gcd

import numpy as np
import sounddevice as sd

from pipelines.base import AbstractPipeline
from core.config import settings
from core.logger import get_logger

log = get_logger("pipeline.audio")


def _resample(data: bytes, from_rate: int, to_rate: int) -> bytes:
    """
    Resample int16 PCM audio bytes from from_rate to to_rate.
    Uses numpy linear interpolation — no extra dependencies needed.
    """
    if from_rate == to_rate:
        return data
    samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
    n_in = len(samples)
    n_out = int(round(n_in * to_rate / from_rate))
    if n_out == 0:
        return b""
    x_old = np.linspace(0.0, 1.0, n_in)
    x_new = np.linspace(0.0, 1.0, n_out)
    resampled = np.interp(x_new, x_old, samples)
    return resampled.astype(np.int16).tobytes()


def _resolve_device(device_hint: str) -> int | None:
    """
    Resolve WALLE_MIC_DEVICE / WALLE_SPEAKER_DEVICE to a sounddevice index.
    Accepts:
      - empty string  → None (system default)
      - integer string → direct device index
      - name substring → first matching device
    """
    if not device_hint:
        return None
    # Numeric index
    if device_hint.isdigit():
        return int(device_hint)
    # Name substring match (case-insensitive)
    devices = sd.query_devices()
    hint_lower = device_hint.lower()
    for idx, dev in enumerate(devices):
        if hint_lower in dev["name"].lower():
            log.info(f"Audio device matched: [{idx}] {dev['name']}")
            return idx
    log.warning(f"No audio device matching '{device_hint}' — using system default.")
    return None


def list_audio_devices() -> str:
    """Returns a human-readable list of all available audio devices."""
    lines = ["Available audio devices:"]
    for idx, dev in enumerate(sd.query_devices()):
        ins  = dev["max_input_channels"]
        outs = dev["max_output_channels"]
        marker = ""
        if ins > 0 and outs > 0:
            marker = " [in+out]"
        elif ins > 0:
            marker = " [input]"
        elif outs > 0:
            marker = " [output]"
        lines.append(f"  [{idx}] {dev['name']}{marker}")
    return "\n".join(lines)


class AudioPipeline(AbstractPipeline):
    """
    Microphone capture with virtual split and automatic resampling.

    The sounddevice callback is kept ultra-light (just bytes → raw_queue).
    A dedicated resample worker thread reads from raw_queue, resamples
    from capture_rate → sample_rate_in, then fans out to online/offline queues.

    Pi 5: Set WALLE_MIC_DEVICE to select your USB microphone.
          Set WALLE_CAPTURE_RATE=44100 if your mic only supports 44100 Hz.
    """

    name = "audio_pipeline"

    def __init__(self):
        self.online_queue:  queue.Queue = queue.Queue()
        self.offline_queue: queue.Queue = queue.Queue()
        self._raw_queue:    queue.Queue = queue.Queue()   # raw captured bytes
        self._stream  = None
        self._worker  = None
        self._started = False
        self._device_index: int | None = _resolve_device(settings.mic_device)
        self._capture_rate: int = settings.capture_rate
        self._target_rate:  int = settings.sample_rate_in
        self._needs_resample: bool = (self._capture_rate != self._target_rate)

    # ── Real-time callback — must be fast, NO heavy processing here ──────────

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            log.warning(f"Audio input status: {status}")
        # Put raw bytes into the raw queue; resample worker handles the rest
        self._raw_queue.put(bytes(indata))

    # ── Resample worker — runs in a background daemon thread ─────────────────

    def _resample_worker(self):
        """Drain raw_queue, resample if needed, apply gain, fan out to downstream queues."""
        gain = settings.mic_gain
        while self._started or not self._raw_queue.empty():
            try:
                raw = self._raw_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            data = _resample(raw, self._capture_rate, self._target_rate) \
                   if self._needs_resample else raw
            # Apply software gain to compensate for quiet USB mics
            if gain != 1.0:
                samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                samples = np.clip(samples * gain, -32768, 32767)
                data = samples.astype(np.int16).tobytes()
            self.online_queue.put(data)
            self.offline_queue.put(data)

    # ── Pipeline lifecycle ────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._started:
            return
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._start_stream)

    def _start_stream(self):
        if settings.is_raspberry_pi:
            log.info(list_audio_devices())

        try:
            stream_kwargs = dict(
                samplerate=self._capture_rate,
                blocksize=settings.audio_blocksize,
                dtype="int16",
                channels=1,
                callback=self._audio_callback,
            )
            if self._device_index is not None:
                stream_kwargs["device"] = self._device_index

            self._stream = sd.RawInputStream(**stream_kwargs)
            self._started = True

            # Start resample worker before opening the stream
            self._worker = threading.Thread(
                target=self._resample_worker,
                name="audio-resample",
                daemon=True,
            )
            self._worker.start()

            self._stream.start()

            dev_name = (
                sd.query_devices(self._device_index)["name"]
                if self._device_index is not None
                else "system default"
            )
            resample_info = (
                f" → resampling {self._capture_rate}Hz→{self._target_rate}Hz"
                if self._needs_resample else ""
            )
            log.info(
                f"Microphone stream started — device: '{dev_name}' "
                f"blocksize={settings.audio_blocksize} "
                f"rate={self._capture_rate}Hz{resample_info}"
            )
        except Exception as e:
            self._started = False
            log.error(f"Failed to start microphone: {e}")
            log.error("Tip: set WALLE_MIC_DEVICE=<index or name> in your .env")
            log.error("Tip: set WALLE_CAPTURE_RATE=44100 if your mic uses 44100 Hz")

    async def stop(self) -> None:
        self._started = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=2)
            self._worker = None
        log.info("Microphone stream stopped.")

    async def health(self) -> dict:
        return {
            "status":              "ok" if self._started else "stopped",
            "device":              str(self._device_index or "default"),
            "capture_rate":        self._capture_rate,
            "target_rate":         self._target_rate,
            "resampling":          self._needs_resample,
            "blocksize":           settings.audio_blocksize,
            "raw_queue_size":      self._raw_queue.qsize(),
            "online_queue_size":   self.online_queue.qsize(),
            "offline_queue_size":  self.offline_queue.qsize(),
        }


