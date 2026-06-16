"""
pipelines/base.py — AbstractPipeline contract
Every WALL-E pipeline implements this interface.
This makes them:
  - Registerable in core/registry.py
  - Health-queryable from /health endpoint
  - Restartable without touching other pipelines

To add a new capability:
  1. Create pipelines/my_pipeline.py
  2. Inherit from AbstractPipeline
  3. Implement start(), stop(), health()
  4. Register in server.py or main.py via registry.register(MyPipeline())

Created by K.Astra and its members.
"""

from abc import ABC, abstractmethod
from typing import Literal


class AbstractPipeline(ABC):
    """
    Base class for every WALL-E AI pipeline.

    Subclasses MUST implement:
      - start()  → boot the pipeline
      - stop()   → shut it down cleanly
      - health() → return {"status": "ok"|"degraded"|"error", ...}
    """

    # Subclasses should override this with a human-readable name.
    name: str = "unnamed_pipeline"

    @abstractmethod
    async def start(self) -> None:
        """Boot the pipeline. Called once at application startup."""

    @abstractmethod
    async def stop(self) -> None:
        """Shut down the pipeline gracefully. Must be idempotent."""

    @abstractmethod
    async def health(self) -> dict:
        """
        Return the current health status.
        Minimum expected format: {"status": "ok" | "degraded" | "error"}
        """

    def __repr__(self) -> str:
        return f"<Pipeline: {self.name}>"
