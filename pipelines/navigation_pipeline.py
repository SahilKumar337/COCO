"""
pipelines/navigation_pipeline.py — WALL-E AI Offline Navigation
Wraps NavigationEngine in AbstractPipeline for registry integration.
Listens on the offline audio queue, transcribes with Vosk (offline),
and sends movement commands to Arduino via SerialEngine.
Created by K.Astra and its members.
"""

import asyncio
import threading

from pipelines.base import AbstractPipeline
from core.logger import get_logger

log = get_logger("pipeline.navigation")


class NavigationPipeline(AbstractPipeline):
    """
    Offline navigation pipeline.
    Starts NavigationEngine in a daemon thread — listens for movement
    commands ("forward", "stop", "left", "right") via Vosk offline STT.

    This pipeline is optional — if Vosk or the Arduino is not available,
    it degrades gracefully without crashing other pipelines.
    """

    name = "navigation_pipeline"

    def __init__(self, offline_audio_queue):
        self._audio_queue = offline_audio_queue
        self._engine = None
        self._thread: threading.Thread | None = None
        self._ready = False

    async def start(self) -> None:
        if self._ready or self._engine is not None:
            return
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._start_engine)

    def _start_engine(self):
        try:
            from navigation_engine import NavigationEngine
            self._engine = NavigationEngine(self._audio_queue)
            self._engine.daemon = True
            self._engine.start()
            self._ready = True
            log.info("Navigation pipeline started.")
        except ImportError:
            log.warning("Vosk not installed — navigation pipeline disabled.")
        except Exception as e:
            log.warning(f"Navigation pipeline failed to start: {e}")

    async def stop(self) -> None:
        if self._engine:
            self._engine.stop()
            try:
                self._engine.join(timeout=2)
            except Exception:
                pass
            self._engine = None
            self._ready = False
            log.info("Navigation pipeline stopped.")

    async def health(self) -> dict:
        return {
            "status": "ok" if self._ready else "disabled",
            "detail": "Vosk offline STT + Arduino Serial",
        }
