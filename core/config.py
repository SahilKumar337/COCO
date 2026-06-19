"""
core/config.py — WALL-E AI centralized configuration
Single source of truth for all environment-based settings.
Every module imports from here — no scattered os.environ.get() calls.
Includes Raspberry Pi 5 auto-detection and Pi-optimized defaults.
Created by K.Astra and its members.
"""

import os
import platform
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


def _detect_raspberry_pi() -> bool:
    """Returns True when running on any Raspberry Pi hardware."""
    # Check /proc/device-tree/model (most reliable)
    try:
        with open("/proc/device-tree/model", "r") as f:
            model = f.read().lower()
            if "raspberry pi" in model:
                return True
    except (FileNotFoundError, PermissionError):
        pass
    # Fallback: check /proc/cpuinfo
    try:
        with open("/proc/cpuinfo", "r") as f:
            for line in f:
                if line.startswith("Hardware") and "BCM" in line:
                    return True
                if line.startswith("Model") and "Raspberry Pi" in line:
                    return True
    except (FileNotFoundError, PermissionError):
        pass
    # Env override (for testing or Docker on Pi)
    return os.environ.get("WALLE_PI_MODE", "").lower() in ("1", "true", "yes")


IS_RASPBERRY_PI = _detect_raspberry_pi()


@dataclass
class WalleConfig:
    # ── API Keys ───────────────────────────────────────────────────────────────
    gemini_api_key: str = field(
        default_factory=lambda: (
            os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""
        )
    )

    # ── Server ─────────────────────────────────────────────────────────────────
    host: str = field(default_factory=lambda: os.environ.get("HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(os.environ.get("PORT", "8000")))
    environment: str = field(
        default_factory=lambda: os.environ.get("ENVIRONMENT", "development")
    )

    # ── Database ───────────────────────────────────────────────────────────────
    database_url: str | None = field(
        default_factory=lambda: os.environ.get("DATABASE_URL")
    )
    db_file: str = field(
        default_factory=lambda: os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "walle_memory.db",
        )
    )

    # ── Gemini / AI ───────────────────────────────────────────────────────────
    gemini_models: list = field(
        default_factory=lambda: [
            "models/gemini-2.5-flash-native-audio-latest",
            "models/gemini-2.5-flash-native-audio-preview-12-2025",
            "models/gemini-2.5-flash-native-audio-preview-09-2025",
        ]
    )
    default_voice: str = field(
        default_factory=lambda: os.environ.get("WALLE_VOICE", "Aoede")
    )
    default_persona: str = field(
        default_factory=lambda: os.environ.get(
            "WALLE_PERSONA", "Professional Executive Assistant"
        )
    )
    default_user_name: str = field(
        default_factory=lambda: os.environ.get("WALLE_USER_NAME", "K.Astra")
    )
    session_limit_sec: int = 7200   # 2-hour sessions
    reconnect_delay: float = 1.5
    heartbeat_sec: int = 20
    silence_duration_ms: int = 2000  # VAD silence threshold (2 seconds)

    # ── Audio ─────────────────────────────────────────────────────────────────
    # sample_rate_in: target rate delivered to Whisper and Gemini (must be 16000)
    sample_rate_in: int = field(
        default_factory=lambda: int(os.environ.get("WALLE_SAMPLE_RATE", "16000"))
    )
    # capture_rate: raw hardware capture rate (set to mic's native rate, e.g. 44100)
    # If different from sample_rate_in, AudioPipeline resamples automatically.
    capture_rate: int = field(
        default_factory=lambda: int(os.environ.get("WALLE_CAPTURE_RATE",
            os.environ.get("WALLE_SAMPLE_RATE", "16000")))
    )
    sample_rate_out: int = 24000
    # Pi 5: use larger blocksize (4096) to avoid ALSA underruns on ARM
    # Windows/Mac: smaller blocksize (8000) for lower latency
    audio_blocksize: int = field(
        default_factory=lambda: (
            int(os.environ.get("WALLE_AUDIO_BLOCKSIZE", "4096"))
            if IS_RASPBERRY_PI
            else int(os.environ.get("WALLE_AUDIO_BLOCKSIZE", "8000"))
        )
    )
    # Audio device index (-1 = auto-detect / system default)
    # Override with WALLE_MIC_DEVICE=<index> or WALLE_MIC_DEVICE=<name substring>
    mic_device: str = field(
        default_factory=lambda: os.environ.get("WALLE_MIC_DEVICE", "")
    )
    speaker_device: str = field(
        default_factory=lambda: os.environ.get("WALLE_SPEAKER_DEVICE", "")
    )
    # Software gain multiplier for quiet USB mics (1.0 = no gain, 16.0 = 16x boost)
    # Increase if RMS logs show levels below 100 when speaking.
    mic_gain: float = field(
        default_factory=lambda: float(os.environ.get("WALLE_MIC_GAIN", "16.0"))
    )
    # Enable software Automatic Gain Control (AGC).
    # If 1, dynamically adjusts gain to keep voice at optimal volume.
    mic_agc: bool = field(
        default_factory=lambda: os.environ.get("WALLE_MIC_AGC", "0").lower() in ("1", "true", "yes")
    )

    # ── Wake Word ─────────────────────────────────────────────────────────────
    wake_variants: list = field(
        default_factory=lambda: [
            "wall-e", "walle", "wally", "wali", "wole",
            "ollie", "olly", "oli", "ali"
        ]
    )
    wake_chunk_ms: int = 1500
    # Pi 5 uses tiny model — same as default (good quality, fast on ARM64 w/ 8GB)
    whisper_model_size: str = field(
        default_factory=lambda: os.environ.get("WALLE_WHISPER_MODEL", "tiny")
    )
    # Pi 5 has 4 Cortex-A76 cores — use int8 quantization for faster inference
    whisper_compute_type: str = field(
        default_factory=lambda: os.environ.get(
            "WALLE_WHISPER_COMPUTE",
            "int8" if IS_RASPBERRY_PI else "default"
        )
    )

    # ── Speaker / Face Identity ───────────────────────────────────────────────
    owner_name: str = field(
        default_factory=lambda: os.environ.get("WALLE_OWNER_NAME", "Sahil")
    )
    owner_ref_file: str = field(
        default_factory=lambda: os.environ.get(
            "WALLE_OWNER_REF_FILE", "sahil_reference.wav"
        )
    )
    owner_voice_threshold: float = 0.45
    default_voice_threshold: float = 0.20
    speaker_cooldown_sec: float = 4.0
    # Pi 5: use fewer torch threads to prevent CPU thrash during audio I/O
    torch_num_threads: int = field(
        default_factory=lambda: int(
            os.environ.get("WALLE_TORCH_THREADS",
                           "2" if IS_RASPBERRY_PI else "0")  # 0 = PyTorch default
        )
    )

    # ── Security ──────────────────────────────────────────────────────────────
    ws_max_payload_bytes: int = 512 * 1024  # 512 KB
    ws_queue_maxsize: int = 1000

    # ── Raspberry Pi ──────────────────────────────────────────────────────────
    is_raspberry_pi: bool = field(default_factory=lambda: IS_RASPBERRY_PI)
    # Pi 5: face detection interval (seconds). Longer = lower CPU load.
    pi_face_detect_interval: float = field(
        default_factory=lambda: float(
            os.environ.get("WALLE_FACE_INTERVAL", "3.0" if IS_RASPBERRY_PI else "2.0")
        )
    )
    # Pi 5: camera resolution (lower = faster face detection)
    pi_camera_width: int = field(
        default_factory=lambda: int(os.environ.get("WALLE_CAM_W", "320" if IS_RASPBERRY_PI else "640"))
    )
    pi_camera_height: int = field(
        default_factory=lambda: int(os.environ.get("WALLE_CAM_H", "240" if IS_RASPBERRY_PI else "480"))
    )

    # ── Emotion Eyes (ESP32 OLED displays) ──────────────────────────────────
    # Serial port for ESP32 eye controller (separate from Arduino motor controller)
    # Pi: typically /dev/ttyUSB0 or /dev/ttyUSB1.  Override: WALLE_EYE_PORT=...
    eye_serial_port: str = field(
        default_factory=lambda: os.environ.get("WALLE_EYE_PORT", "/dev/ttyUSB1")
    )
    eye_serial_baud: int = field(
        default_factory=lambda: int(os.environ.get("WALLE_EYE_BAUD", "115200"))
    )
    # Auto-enable on Pi, auto-disable on Windows/Mac (no serial ESP32 there)
    eye_enabled: bool = field(
        default_factory=lambda: os.environ.get(
            "WALLE_EYES_ENABLED",
            "1" if IS_RASPBERRY_PI else "0"
        ).lower() not in ("0", "false", "no")
    )

    # ── Deployment detection ──────────────────────────────────────────────────
    @property
    def is_production(self) -> bool:
        return bool(
            os.environ.get("RAILWAY_ENVIRONMENT")
            or os.environ.get("RENDER")
            or self.environment == "production"
        )

    @property
    def is_postgres(self) -> bool:
        return bool(
            self.database_url and self.database_url.startswith("postgres")
        )


# ── Singleton ─────────────────────────────────────────────────────────────────
settings = WalleConfig()

# Resolve API key ambiguity — pin exactly one key so the SDK doesn't warn
if settings.gemini_api_key:
    os.environ["GEMINI_API_KEY"] = settings.gemini_api_key
    if "GOOGLE_API_KEY" in os.environ and "GEMINI_API_KEY" in os.environ:
        del os.environ["GOOGLE_API_KEY"]

# Apply PyTorch thread limit early (before any SpeechBrain import)
if settings.torch_num_threads > 0:
    try:
        import torch
        torch.set_num_threads(settings.torch_num_threads)
    except ImportError:
        pass
