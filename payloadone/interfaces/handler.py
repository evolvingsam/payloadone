"""Abstract base class for application-level event handlers."""

from abc import ABC, abstractmethod

from ..models.event import UnifiedEvent


class BaseEventHandler(ABC):
    """
    Contract for a business-logic handler that receives normalised events.

    Handlers are registered against event types via ``WebhookManager.on()``.
    They receive a ``UnifiedEvent`` that has already been:

    - Cryptographically verified (signature check passed)
    - Deduplicated (idempotency check confirmed first occurrence)
    - Normalised (mapped from provider-specific payload to ``UnifiedEvent``)

    A handler implementation should contain only business logic — crediting
    wallets, fulfilling orders, sending emails — with no concern for
    infrastructure-level validation.
    """

    @abstractmethod
    async def handle(self, event: UnifiedEvent) -> None:
        """
        Execute business logic for a verified, deduplicated, normalised event.

        Any exception raised here will propagate up the pipeline. Handlers
        are responsible for their own internal error handling; unhandled
        exceptions will prevent the idempotency ledger from being committed,
        causing the event to be retried on next delivery.

        Args:
            event: The fully populated ``UnifiedEvent`` instance.
        """