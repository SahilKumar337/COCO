"""
pipelines/identity_pipeline.py — WALL-E AI Biometric Identity
Fuses voice (SpeechBrain ECAPA-TDNN) + face recognition to identify
the current speaker with anti-impersonation protection.

Extracted from main.py — independently swappable.
To add a new biometric (e.g., iris scan): add a method here, touch nothing else.
Created by K.Astra and its members.
"""

import asyncio
import os
import tempfile

import numpy as np
import scipy.io.wavfile as wav

from pipelines.base import AbstractPipeline
from core.config import settings
from core.logger import get_logger

log = get_logger("pipeline.identity")


class IdentityPipeline(AbstractPipeline):
    """
    Speaker + face biometric identification.

    Anti-impersonation policy:
      - Owner MUST pass strict voice verification; face alone is NOT sufficient.
      - If face matches owner but voice does NOT → classify Unknown and log alert.
      - Non-owner users: voice first, face as fallback.
    """

    name = "identity_pipeline"

    def __init__(self):
        self._recognizer = None    # SpeechBrain ECAPA-TDNN
        self._face_engine = None   # FaceEngine instance (injected)
        self._ready = False

    async def start(self) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._load_model)

    def _load_model(self):
        try:
            from speechbrain.inference.speaker import SpeakerRecognition
            log.info("Loading speaker recognition model (ECAPA-TDNN)...")
            self._recognizer = SpeakerRecognition.from_hparams(
                source="speechbrain/spkrec-ecapa-voxceleb",
                savedir="tmp_model",
            )
            self._ready = True
            log.info("Speaker recognition model loaded.")
        except Exception as e:
            log.error(f"Failed to load speaker model: {e}")

    async def stop(self) -> None:
        self._ready = False
        self._recognizer = None

    async def health(self) -> dict:
        return {
            "status": "ok" if self._ready else "not_ready",
            "voice_model": "ECAPA-TDNN",
            "face_engine": self._face_engine is not None,
            "owner_ref_file_exists": os.path.exists(settings.owner_ref_file),
        }

    def attach_face_engine(self, face_engine) -> None:
        """Inject a FaceEngine instance at runtime."""
        self._face_engine = face_engine

    # ── Voice identification ──────────────────────────────────────────────────
    def identify_by_voice(self, audio_path: str) -> tuple[str, float]:
        """
        Compare audio against known voice references.
        Returns (name, score).
        """
        if not self._recognizer:
            return "Unknown", 0.0

        known_voices = {
            settings.owner_name: {
                "file":      settings.owner_ref_file,
                "threshold": settings.owner_voice_threshold,
            },
        }

        best_match    = "Unknown"
        highest_score = 0.0

        for name, cfg in known_voices.items():
            if not os.path.exists(cfg["file"]):
                log.debug(f"Skipping {name}: ref file '{cfg['file']}' not found")
                continue
            score, _ = self._recognizer.verify_files(audio_path, cfg["file"])
            similarity = score.item()
            log.debug(f"Voice similarity {name}: {similarity:.3f} (threshold: {cfg['threshold']})")

            if similarity > cfg["threshold"] and similarity > highest_score:
                highest_score = similarity
                best_match    = name

        return best_match, highest_score

    # ── Face identification ───────────────────────────────────────────────────
    def identify_by_face(self) -> tuple[str, float]:
        """Returns (name, confidence) from the face engine."""
        if self._face_engine:
            return self._face_engine.get_current_identity()
        return "Unknown", 0.0

    # ── Fused identification ──────────────────────────────────────────────────
    async def identify(self, audio_path: str) -> str:
        """
        Full biometric fusion: voice + face with anti-impersonation logic.
        Returns the resolved speaker name.
        """
        loop = asyncio.get_event_loop()
        voice_name, voice_score = await loop.run_in_executor(
            None, self.identify_by_voice, audio_path
        )
        log.info(f"Voice result: {voice_name} ({voice_score:.3f})")

        face_name, face_score = self.identify_by_face()
        if face_name != "Unknown":
            log.info(f"Face result: {face_name} ({face_score:.2f})")

        # Owner path: voice MUST match
        if voice_name == settings.owner_name:
            log.info(f"✅ Owner ({settings.owner_name}) voice verified.")
            return settings.owner_name

        # Anti-impersonation: face looks like owner but voice doesn't match
        if face_name == settings.owner_name and voice_name != settings.owner_name:
            log.warning(
                "⚠️  IMPERSONATION ALERT: Face resembles owner but voiceprint did NOT match. Access denied."
            )
            return "Unknown"

        # Another enrolled voice matched
        if voice_name != "Unknown":
            return voice_name

        # Voice unknown → face fallback (non-owner only)
        if face_name not in ("Unknown", settings.owner_name) and face_score > 0.4:
            log.info(f"Voice unknown — using face ID: {face_name}")
            return face_name

        return "Unknown"

    # ── Voice buffer ID (used mid-session) ───────────────────────────────────
    async def identify_from_buffer(self, audio_bytes: bytes) -> str:
        """
        Identify speaker from raw PCM bytes (used inside Gemini session).
        Writes to a temp WAV file, runs verification, cleans up.
        """
        if not self._recognizer or not os.path.exists(settings.owner_ref_file):
            return "Unknown"
        if len(audio_bytes) < settings.sample_rate_in * 1 * 2:
            return "Unknown"

        tmp = tempfile.mktemp(suffix=".wav")
        try:
            audio_arr = np.frombuffer(audio_bytes, dtype=np.int16)
            wav.write(tmp, settings.sample_rate_in, audio_arr)
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._sync_voice_check, tmp)
        except Exception as e:
            log.error(f"Voice buffer ID error: {e}")
            return "Unknown"
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def _sync_voice_check(self, audio_path: str) -> str:
        try:
            score, _ = self._recognizer.verify_files(audio_path, settings.owner_ref_file)
            similarity = score.item()
            if similarity > settings.owner_voice_threshold:
                log.debug(f"Owner voice confirmed (score: {similarity:.3f})")
                return settings.owner_name
            if similarity > 0.30:
                log.warning(f"Partial owner voice match ({similarity:.3f}) — below threshold. Not verified.")
        except Exception as e:
            log.error(f"SpeechBrain verification error: {e}")
        return "Unknown"
