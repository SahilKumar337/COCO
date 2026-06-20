"""
main.py — WALL-E AI Hardware Orchestrator
Entry point for hardware (desktop/Pi) mode.
Wake word → Identify speaker → Run WALL-E session → Sleep → Repeat

Boot sequence:
  1. AudioPipeline    — mic capture + virtual split
  2. IdentityPipeline — ECAPA-TDNN voice + face biometrics
  3. FaceEngine       — background camera recognition
  4. WakePipeline     — faster-whisper wake word detection
  5. NavigationPipeline — offline Vosk + Arduino serial
  6. WalleSession     — Gemini Live (hardware mode)

Created by K.Astra and its members.
"""

import asyncio
import os
import sys
import threading

from dotenv import load_dotenv
load_dotenv()

from core.config import settings
from core.logger import get_logger
from core.registry import registry
from core.tts import speak, say_boot_ready, say_connectivity_error, say_quota_error
from pipelines.audio_pipeline import AudioPipeline
from pipelines.wake_pipeline import WakePipeline
from pipelines.identity_pipeline import IdentityPipeline
from pipelines.navigation_pipeline import NavigationPipeline
from pipelines.gemini_pipeline import WalleSession
from face_engine import FaceEngine, FACE_AVAILABLE
from storage.db import init_db
from storage.people import migrate_from_json

# Optional emotion eye engine (Pi only; silently skipped on other platforms)
try:
    from emotion_engine import EmotionEngine
    _EMOTION_AVAILABLE = True
except ImportError:
    EmotionEngine = None  # type: ignore
    _EMOTION_AVAILABLE = False

log = get_logger("main")


async def run():
    log.info("=" * 60)
    log.info("  WALL-E AI  v2.0  — Hardware Mode")
    log.info("  Created by K.Astra and its members  |  Ctrl+C to quit")
    log.info("=" * 60)

    # ── Initialize database ────────────────────────────────────────────────────
    init_db()
    if os.path.exists("walle_memory.json"):
        log.info("Migrating old JSON memory to database...")
        migrate_from_json()

    # Boot pipelines ──────────────────────────────────────────────────────
    audio_pipeline    = registry.register(AudioPipeline())
    # identity_pipeline = registry.register(IdentityPipeline()) # Disabled to free up CPU
    nav_pipeline      = registry.register(NavigationPipeline(audio_pipeline.offline_queue))
    
    wake_pipeline = None
    if settings.wake_word_enabled:
        wake_pipeline = registry.register(WakePipeline(audio_pipeline.online_queue))

    log.info(f"Registered {registry.count} pipelines.")

    # ── Face engine (not a pipeline — runs its own thread) ────────────────────
    face_engine = FaceEngine()

    # ── Emotion eye engine (hardware only, fails gracefully if ESP32 not connected) ─
    emotion_engine = None
    if _EMOTION_AVAILABLE and settings.eye_enabled:
        log.info(f"Booting EmotionEngine on {settings.eye_serial_port}...")
        emotion_engine = EmotionEngine(
            port=settings.eye_serial_port,
            baudrate=settings.eye_serial_baud,
            enabled=True,
        )
    elif not _EMOTION_AVAILABLE:
        log.info("EmotionEngine not available (emotion_engine.py not found or pyserial missing).")
    else:
        log.info("EmotionEngine disabled (WALLE_EYES_ENABLED=0).")

    # ── Start everything (loads Whisper + SpeechBrain + Vosk — takes 60-90s on Pi) ─
    speak("AI initializing", block=False)
    await registry.start_all()

    if FACE_AVAILABLE:
        face_engine.start()
        # identity_pipeline.attach_face_engine(face_engine) # Disabled

    if settings.wake_word_enabled:
        log.info(f"Wake variants: {settings.wake_variants}")
        log.info(f"Anti-impersonation: ENABLED — owner requires strict voiceprint")
    else:
        log.info("Wake word detection: DISABLED (Direct interaction mode)")
    log.info(f"Face recognition: {'ENABLED' if FACE_AVAILABLE else 'DISABLED (voice only)'}")
    log.info(f"Emotion eyes: {'ENABLED on ' + settings.eye_serial_port if emotion_engine else 'DISABLED'}")

    # ── Ready greeting — all models loaded, now listening ─────────────────────
    say_boot_ready()

    # Eyes: boot-open animation now that everything is ready
    if emotion_engine:
        emotion_engine.boot_open()

    try:
        while True:
            # ── Wait for wake word ─────────────────────────────────────────────
            if settings.wake_word_enabled and wake_pipeline is not None:
                log.info(f"Waiting for wake word {settings.wake_variants}...")
                audio_file_path = await wake_pipeline.wait_for_wake()

                # Clean up temp audio file
                try:
                    os.unlink(audio_file_path)
                except Exception:
                    pass
            else:
                log.info("Wake word bypassed (Direct interaction mode).")

            # ── Identify speaker (Disabled to free CPU for Gemini) ────────────
            speaker_name = "Unknown"
            await asyncio.sleep(0.1)  # Yield event loop to ensure audio buffers are ready

            # Flush any physical echo/stale audio that the microphone just recorded!
            import queue
            while not audio_pipeline.online_queue.empty():
                try:
                    audio_pipeline.online_queue.get_nowait()
                except queue.Empty:
                    break

            # ── Start WALL-E session ───────────────────────────────────────────
            log.info(f"Starting WALL-E session for '{speaker_name}'...")
            
            # Stop offline navigation/Vosk to free up CPU and GIL for the active Gemini session
            if nav_pipeline:
                await nav_pipeline.stop()

            session = WalleSession(
                mode="hardware",
                current_user=speaker_name,
                face_engine=face_engine,
                recognizer=None,
                audio_queue=audio_pipeline.online_queue,
                identity_pipeline=None,
                emotion_engine=emotion_engine,
            )

            sleeping = threading.Event()

            def on_sleep():
                log.info("Farewell detected — WALL-E going to sleep.")
                sleeping.set()
                session.stop()

            try:
                session_task = asyncio.create_task(session.run(on_sleep_callback=on_sleep))

                while not session_task.done() and not sleeping.is_set():
                    await asyncio.sleep(0.5)

                if not session_task.done():
                    session_task.cancel()
                    try:
                        await session_task
                    except asyncio.CancelledError:
                        pass
                else:
                    exc = session_task.exception()
                    if exc:
                        raise exc

            except Exception as e:
                err_str = str(e).lower()
                if "quota" in err_str:
                    log.warning("API quota exceeded — waiting 30s before retry.")
                    say_quota_error()
                    await asyncio.sleep(30)
                elif "1011" in err_str or "1008" in err_str or "unavailable" in err_str or "connect" in err_str:
                    log.warning(f"Gemini connectivity error: {e}")
                    say_connectivity_error()
                    await asyncio.sleep(5)
                else:
                    log.error(f"Session error: {e}")
                    say_connectivity_error()
                    await asyncio.sleep(2)
            finally:
                # Restart offline navigation when returning to standby mode
                if nav_pipeline:
                    await nav_pipeline.start()

    finally:
        log.info("Shutting down WALL-E AI...")
        if FACE_AVAILABLE:
            face_engine.stop()
        if emotion_engine:
            emotion_engine.shutdown()
        await registry.stop_all()


if __name__ == "__main__":
    if not settings.gemini_api_key:
        print("ERROR: Set GEMINI_API_KEY first.")
        print("  set GEMINI_API_KEY=your_key_here")
        sys.exit(1)
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\n[WALL-E] Shutting down. Goodbye.")
