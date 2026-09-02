"""Exclusive local-model ownership for Maeve Stage 13."""
from __future__ import annotations
import threading


class ModelScheduler:
    def __init__(self) -> None:
        self.owner = "NONE"
        self._lock = threading.Lock()

    def acquire(self, owner: str) -> bool:
        if owner not in {"STT", "QWEN"}:
            return False
        with self._lock:
            if self.owner != "NONE":
                return False
            self.owner = owner
            return True

    def release(self, owner: str) -> None:
        with self._lock:
            if self.owner == owner:
                self.owner = "NONE"

    def clear(self) -> None:
        with self._lock:
            self.owner = "NONE"
