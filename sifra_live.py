"""
sifra_live.py — DEPRECATED
This file is kept as a backward-compatibility stub only.
All logic has been consolidated into pipelines/gemini_pipeline.py.

Use WalleSession from pipelines.gemini_pipeline instead.
Created by K.Astra and its members.
"""

import warnings
warnings.warn(
    "sifra_live.py is deprecated. Use `from pipelines.gemini_pipeline import WalleSession` instead.",
    DeprecationWarning,
    stacklevel=2,
)

from pipelines.gemini_pipeline import WalleSession as CocoSession
import queue
vision_queue: queue.Queue = queue.Queue()

__all__ = ["CocoSession", "vision_queue"]
