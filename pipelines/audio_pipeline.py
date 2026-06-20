"""
pipelines/audio_pipeline.py — WALL-E AI Clean Audio Engine
===========================================================
Industry-standard headless Pi audio using PulseAudio as the audio abstraction
layer — the same role WASAPI/DirectSound plays on Windows.

PulseAudio handles transparently:
  - Sample rate conversion (44100 Hz → 16000 Hz)
  - Automatic Gain Control (AGC) via WebRTC module
  - Noise suppression via WebRTC module
  - Device selection / hot-plug

The Python code stays clean — just requests 16000 Hz from sounddevice and
PulseAudio delivers it, exactly like Windows does.

Hardware audio path:
  USB Mic (44100 Hz hw) → PulseAudio WebRTC (AGC+NS+resample) → 16000 Hz PCM
                                                                ↓
                                               AudioPipeline (this file)
                                                    ↓            ↓
                                             online_queue  offline_queue
                                                    ↓            ↓
                                          Gemini Live     Wake/Nav (Vosk)

Created by K.Astra and its members.
Run scripts/setup_audio_pi.sh on Pi before first use.
"""

import asyncio
import queue
import threading

import numpy as np
import sounddevice as sd

from pipelines.base import AbstractPipeline
from core.config import settings
from core.logger import get_logger

log = get_logger("pipeline.audio")


# ── Device resolution ─────────────────────────────────────────────────────────

def _resolve_device(hint: str) -> int | None:
    """
    Resolve WALLE_MIC_DEVICE to a sounddevice device index.
    Accepts:
      - empty or 'auto' → auto-detects first USB microphone, falls back to system default
      - integer string  → direct device index
      - name substring  → first case-insensitive match (excluding 'auto')
    """
    devices = list(sd.query_devices())
    
    # 1. If explicit integer index
    if hint and hint.isdigit():
        return int(hint)
        
    # 2. If explicit name search hint (excluding 'auto')
    if hint and hint.lower() != "auto":
        hint_lower = hint.lower()
        for idx, dev in enumerate(devices):
            if dev["max_input_channels"] > 0 and hint_lower in dev["name"].lower():
                log.info(f"Audio device matched hint '{hint}': [{idx}] {dev['name']}")
                return idx
        log.warning(f"No audio device matching hint '{hint}' — trying auto-detect.")

    # 3. Auto-detection: search for USB/Mic input device
    for idx, dev in enumerate(devices):
        if dev["max_input_channels"] > 0:
            dev_name = dev["name"].lower()
            if any(k in dev_name for k in ("usb", "mic", "respeaker", "audio")):
                log.info(f"Auto-detected USB/Mic audio device: [{idx}] {dev['name']}")
                return idx
                
    log.info("No USB or Mic device auto-detected — using system default audio source.")
    return None


def list_audio_devices() -> str:
    """Returns a formatted list of all available audio devices for diagnostics."""
    lines = ["Available audio devices (sounddevice):"]
    for idx, dev in enumerate(sd.query_devices()):
        ins  = dev["max_input_channels"]
        outs = dev["max_output_channels"]
        tag = "[in+out]" if ins > 0 and outs > 0 else "[input]" if ins > 0 else "[output]"
        lines.append(f"  [{idx}] {dev['name']} {tag}")
    return "\n".join(lines)


# ── Audio Pipeline ────────────────────────────────────────────────────────────

class AudioPipeline(AbstractPipeline):
    """
    Microphone capture with virtual fan-out to two queues.

    Design philosophy (industry standard):
      - The real-time sounddevice callback is kept ultra-light:
        just bytes → _raw_queue. No processing whatsoever.
      - A background daemon thread reads _raw_queue, optionally applies
        a software gain multiplier (default 1.0 when PulseAudio AGC is active),
        and fans out to the downstream queues.
      - Sample rate conversion and AGC are handled by PulseAudio (run
        scripts/setup_audio_pi.sh once on the Pi). The Python code always
        requests settings.sample_rate_in (16000 Hz) and the audio server
        delivers it, exactly as Windows WASAPI does.

    Environment variables (all optional):
      WALLE_MIC_DEVICE    — device index or name substring (default: PA default)
      WALLE_SAMPLE_RATE   — target sample rate in Hz (default: 16000)
      WALLE_CAPTURE_RATE  — set equal to WALLE_SAMPLE_RATE after PA setup
      WALLE_MIC_GAIN      — software gain multiplier (default: 1.0, PA handles AGC)
      WALLE_AUDIO_BLOCKSIZE — samples per callback block (default: 4096 on Pi)
    """

    name = "audio_pipeline"

    def __init__(self):
        self.online_queue:  queue.Queue = queue.Queue()
        self.offline_queue: queue.Queue = queue.Queue()
        self._raw_queue:    queue.Queue = queue.Queue()

        self._stream: sd.RawInputStream | None = None
        self._worker: threading.Thread | None = None
        self._started: bool = False

        self._device_index: int | None = _resolve_device(settings.mic_device)
        self._sample_rate:  int   = settings.sample_rate_in   # always 16000
        self._gain:         float = settings.mic_gain          # 1.0 after PA setup

    # ── Real-time callback — MUST be ultra-light ──────────────────────────────

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            log.warning(f"Audio status: {status}")
        self._raw_queue.put(bytes(indata))

    # ── Background worker — safe for heavier processing ───────────────────────

    def _process_worker(self):
        """
        Reads raw PCM from _raw_queue, applies optional software gain,
        and fans out to the downstream queues.

        With PulseAudio AGC active, gain should be 1.0 (no-op).
        The gain option is kept as a safety valve for environments
        where PulseAudio is not available.
        """
        use_agc = settings.mic_agc
        apply_gain = (self._gain != 1.0) or use_agc or settings.noise_gate_enabled
        log.info(
            f"Audio worker started — gain={self._gain}x "
            f"({'PulseAudio AGC active' if not apply_gain else 'software processing active'}) "
            f"AGC={'ENABLED' if use_agc else 'DISABLED'} "
            f"NoiseGate={'ENABLED' if settings.noise_gate_enabled else 'DISABLED'}"
        )
        
        log_counter = 0

        while self._started or not self._raw_queue.empty():
            try:
                raw = self._raw_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if apply_gain:
                arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
                raw_rms = float(np.sqrt(np.mean(arr ** 2)))

                if settings.noise_gate_enabled:
                    # 1. Asymmetrical valley tracker for dynamic noise floor estimation
                    if not hasattr(self, "_noise_floor"):
                        self._noise_floor = max(raw_rms, 150.0)
                    
                    if raw_rms < self._noise_floor:
                        # Quick fall to lower noise floor
                        self._noise_floor = self._noise_floor + 0.15 * (raw_rms - self._noise_floor)
                    else:
                        # Extremely slow rise (so speech peaks don't bias the floor estimate)
                        self._noise_floor = self._noise_floor + 0.003 * (raw_rms - self._noise_floor)
                    
                    self._noise_floor = min(max(self._noise_floor, 50.0), 2000.0)

                    # 2. Speech classification & hangover
                    is_speech = (raw_rms > self._noise_floor * settings.noise_gate_threshold) and (raw_rms > settings.noise_gate_min_rms)
                    
                    if not hasattr(self, "_speech_hangover_blocks"):
                        self._speech_hangover_blocks = 0
                    
                    if is_speech:
                        self._speech_hangover_blocks = 3  # keep open for ~768ms

                    # 3. Apply noise gate & AGC
                    if self._speech_hangover_blocks > 0:
                        self._speech_hangover_blocks -= 1
                        # Gate is OPEN — apply gain and optional AGC adaptation
                        if use_agc:
                            target_rms = 1500.0
                            ideal_gain = target_rms / raw_rms
                            min_gain = max(1.0, settings.mic_gain / 2.0)
                            ideal_gain = min(max(ideal_gain, min_gain), 32.0)

                            if ideal_gain > self._gain:
                                self._gain = self._gain + 0.02 * (ideal_gain - self._gain)
                            else:
                                self._gain = self._gain + 0.20 * (ideal_gain - self._gain)

                            log_counter += 1
                            if log_counter % 20 == 0:
                                log.info(f"[AGC] Speech active, dynamic gain={self._gain:.2f}x (raw RMS={raw_rms:.0f}, noise floor={self._noise_floor:.0f})")
                        
                        arr = arr * self._gain
                    else:
                        # Gate is CLOSED — silence/attenuate signal and decay gain back to base
                        self._gain = self._gain + 0.01 * (settings.mic_gain - self._gain)
                        arr = arr * settings.noise_gate_attenuation
                        
                        log_counter += 1
                        if log_counter % 40 == 0:
                            log.debug(f"[NoiseGate] Closed (raw RMS={raw_rms:.0f}, noise floor={self._noise_floor:.0f})")
                else:
                    # Legacy AGC without noise gate
                    if use_agc:
                        if raw_rms > 350.0:
                            target_rms = 1500.0
                            ideal_gain = target_rms / raw_rms
                            min_gain = max(1.0, settings.mic_gain / 2.0)
                            ideal_gain = min(max(ideal_gain, min_gain), 32.0)

                            if ideal_gain > self._gain:
                                self._gain = self._gain + 0.02 * (ideal_gain - self._gain)
                            else:
                                self._gain = self._gain + 0.20 * (ideal_gain - self._gain)

                            log_counter += 1
                            if log_counter % 20 == 0:
                                log.info(f"[AGC] Dynamic gain adjusted to {self._gain:.2f}x (raw RMS={raw_rms:.0f})")
                        else:
                            self._gain = self._gain + 0.01 * (settings.mic_gain - self._gain)
                    
                    arr = arr * self._gain

                arr = np.clip(arr, -32768, 32767)
                raw = arr.astype(np.int16).tobytes()

            self.online_queue.put(raw)
            self.offline_queue.put(raw)

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
            kwargs: dict = dict(
                samplerate=self._sample_rate,
                blocksize=settings.audio_blocksize,
                dtype="int16",
                channels=1,
                callback=self._audio_callback,
            )
            if self._device_index is not None:
                kwargs["device"] = self._device_index

            self._stream = sd.RawInputStream(**kwargs)
            self._started = True

            # Start background worker before opening stream
            self._worker = threading.Thread(
                target=self._process_worker,
                name="audio-worker",
                daemon=True,
            )
            self._worker.start()

            self._stream.start()

            dev = (
                sd.query_devices(self._device_index)["name"]
                if self._device_index is not None
                else "PulseAudio default source"
            )
            log.info(
                f"✅ Microphone started — '{dev}' @ {self._sample_rate} Hz "
                f"blocksize={settings.audio_blocksize} gain={self._gain}x"
            )

        except Exception as exc:
            self._started = False
            log.error(f"Failed to open microphone: {exc}")
            log.error("Did you run scripts/setup_audio_pi.sh on the Pi?")
            log.error("Tip: WALLE_MIC_DEVICE=<index> to select a specific device.")

    async def stop(self) -> None:
        self._started = False
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=2)
            self._worker = None
        log.info("Microphone stopped.")

    async def health(self) -> dict:
        return {
            "status":             "ok" if self._started else "stopped",
            "device":             str(self._device_index or "PA default"),
            "sample_rate":        self._sample_rate,
            "gain":               self._gain,
            "blocksize":          settings.audio_blocksize,
            "raw_queue_size":     self._raw_queue.qsize(),
            "online_queue_size":  self.online_queue.qsize(),
            "offline_queue_size": self.offline_queue.qsize(),
        }
