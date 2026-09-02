"""Provider and credential boundaries for future separately approved TTS work."""

from __future__ import annotations

from enum import Enum
from typing import Protocol


class ProviderState(str, Enum):
    UNAVAILABLE = "UNAVAILABLE"
    READY = "READY"
    GENERATING = "GENERATING"
    SPEAKING = "SPEAKING"
    FALLBACK = "FALLBACK"
    ERROR = "ERROR"


class CredentialAdapter(Protocol):
    """Platform-specific secret retrieval contract. No implementation in Stage 1."""

    def get_secret(self, secret_id: str) -> str:
        """Return a secret without logging or persisting it in shared code."""


class TextToSpeechProvider(Protocol):
    """Future provider contract. Stage 1 publishes no implementation."""

    @property
    def state(self) -> ProviderState:
        """Return the provider's truthful current state."""

    def synthesize(self, text: str) -> bytes:
        """Generate audio only after a later explicit provider authorization."""
