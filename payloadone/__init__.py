"""
PayloadOne — Secure, normalised, idempotent webhook processing.

Public API surface. Import everything you need from this top-level module::

    from payloadone import WebhookManager, PayloadOneConfig
    from payloadone.models.event import UnifiedEvent
    from payloadone.models.enums import Provider, EventType
"""

from .config import PayloadOneConfig
from .core.manager import WebhookManager
from .exceptions import (
    IdempotencyBackendError,
    MisconfigurationError,
    NormalisationError,
    PayloadOneError,
    SignatureVerificationError,
    UnknownProviderError,
)
from .models.enums import EventType, Provider
from .models.event import UnifiedEvent

__version__ = "0.1.0"
__all__ = [
    "WebhookManager",
    "PayloadOneConfig",
    "UnifiedEvent",
    "Provider",
    "EventType",
    "PayloadOneError",
    "SignatureVerificationError",
    "UnknownProviderError",
    "NormalisationError",
    "IdempotencyBackendError",
    "MisconfigurationError",
]
