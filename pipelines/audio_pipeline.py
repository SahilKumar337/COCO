"""
pipelines/audio_pipeline.py — WALL-E AI Virtual Split Audio Engine
Captures microphone audio and fans it out to two queues:
  - online_queue  → Gemini Live streaming
  - offline_queue → Navigation / Arduino (offline Vosk)

Pi 5 specifics:
  - Configurable device index/name via WALLE_MIC_DEVICE env var
  - Larger blocksize (4096) to avoid ALSA underruns on ARM
  - Lists available devices on startup for easy setup

Created by K.Astra and its members.
"""

import asyncio
import queue

import sounddevice as sd

from pipelines.base import AbstractPipeline
from core.config import settings
from core.logger import get_logger

log = get_logger("pipeline.audio")


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
    Microphone capture with virtual split.
    Starts a sounddevice RawInputStream in a background thread.
    Both queues are unbounded to avoid dropping frames — callers
    are responsible for draining them promptly.

    Pi 5: Set WALLE_MIC_DEVICE to select your USB microphone.
    Run `python -c "import sounddevice as sd; print(sd.query_devices())"` to list devices.
    """

    name = "audio_pipeline"

    def __init__(self):
        self.online_queue:  queue.Queue = queue.Queue()
        self.offline_queue: queue.Queue = queue.Queue()
        self._stream = None
        self._started = False
        self._device_index: int | None = _resolve_device(settings.mic_device)

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            log.warning(f"Audio input status: {status}")
        data = bytes(indata)
        self.online_queue.put(data)
        self.offline_queue.put(data)

    async def start(self) -> None:
        if self._started:
            return
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._start_stream)

    def _start_stream(self):
        # Log available devices on Pi so setup is easy
        if settings.is_raspberry_pi:
            log.info(list_audio_devices())

        try:
            stream_kwargs = dict(
                samplerate=settings.sample_rate_in,
                blocksize=settings.audio_blocksize,
                dtype="int16",
                channels=1,
                callback=self._audio_callback,
            )
            if self._device_index is not None:
                stream_kwargs["device"] = self._device_index

            self._stream = sd.RawInputStream(**stream_kwargs)
            self._stream.start()
            self._started = True

            dev_name = (
                sd.query_devices(self._device_index)["name"]
                if self._device_index is not None
                else "system default"
            )
            log.info(
                f"Microphone stream started — device: '{dev_name}' "
                f"blocksize={settings.audio_blocksize} "
                f"rate={settings.sample_rate_in}Hz"
            )
        except Exception as e:
            log.error(f"Failed to start microphone: {e}")
            log.error("Tip: set WALLE_MIC_DEVICE=<index or name> in your .env")

    async def stop(self) -> None:
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
            self._started = False
            log.info("Microphone stream stopped.")

    async def health(self) -> dict:
        return {
            "status":              "ok" if self._started else "stopped",
            "device":              str(self._device_index or "default"),
            "blocksize":           settings.audio_blocksize,
            "online_queue_size":   self.online_queue.qsize(),
            "offline_queue_size":  self.offline_queue.qsize(),
        }
