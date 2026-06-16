"""
core/registry.py — WALL-E AI pipeline registry
Central store for all active pipelines.
- Tracks lifecycle (start / stop / health)
- Powers the /health endpoint automatically
- Zero changes needed when adding new pipelines — just register them

Created by K.Astra and its members.
"""

import asyncio
from typing import TYPE_CHECKING

from core.logger import get_logger

if TYPE_CHECKING:
    from pipelines.base import AbstractPipeline

log = get_logger("registry")


class PipelineRegistry:
    """
    Lightweight singleton that holds references to all running pipelines.
    
    Usage:
        registry.register(my_pipeline)
        await registry.start_all()
        await registry.stop_all()
        statuses = await registry.health_all()
    """

    def __init__(self):
        self._pipelines: list["AbstractPipeline"] = []

    def register(self, pipeline: "AbstractPipeline") -> "AbstractPipeline":
        """Register a pipeline. Returns the pipeline for chaining."""
        self._pipelines.append(pipeline)
        log.info(f"Registered pipeline: {pipeline.name}")
        return pipeline

    async def start_all(self) -> None:
        """Start all registered pipelines concurrently."""
        if not self._pipelines:
            log.warning("No pipelines registered — nothing to start.")
            return
        log.info(f"Starting {len(self._pipelines)} pipeline(s)...")
        await asyncio.gather(*[p.start() for p in self._pipelines])
        log.info("All pipelines started.")

    async def stop_all(self) -> None:
        """Stop all registered pipelines in reverse order (LIFO)."""
        log.info("Stopping all pipelines...")
        for pipeline in reversed(self._pipelines):
            try:
                await pipeline.stop()
            except Exception as e:
                log.error(f"Error stopping {pipeline.name}: {e}")
        log.info("All pipelines stopped.")

    async def health_all(self) -> dict:
        """Collect health status from every registered pipeline."""
        results = {}
        for p in self._pipelines:
            try:
                results[p.name] = await asyncio.wait_for(p.health(), timeout=2.0)
            except asyncio.TimeoutError:
                results[p.name] = {"status": "timeout"}
            except Exception as e:
                results[p.name] = {"status": "error", "detail": str(e)}

        overall = "ok" if all(
            v.get("status") == "ok" for v in results.values()
        ) else "degraded"

        return {"status": overall, "pipelines": results}

    def get(self, pipeline_name: str) -> "AbstractPipeline | None":
        """Look up a pipeline by name."""
        for p in self._pipelines:
            if p.name == pipeline_name:
                return p
        return None

    @property
    def count(self) -> int:
        return len(self._pipelines)


# ── Singleton ─────────────────────────────────────────────────────────────────
registry = PipelineRegistry()
