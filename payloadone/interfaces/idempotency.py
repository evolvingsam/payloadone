"""Abstract base class for idempotency storage backends."""

from abc import ABC, abstractmethod


class BaseIdempotencyBackend(ABC):
    """
    Contract for an idempotency ledger backend.

    Implementations must guarantee atomicity: a reference that is being
    checked by two concurrent requests must not pass as "not duplicate"
    to both. Use atomic set-if-not-exists (SETNX / INSERT ... ON CONFLICT)
    primitives to satisfy this requirement.
    """

    @abstractmethod
    async def is_duplicate(self, reference: str, provider: str) -> bool:
        """
        Atomically check whether this reference has already been processed.

        This is the primary idempotency gate. The check and the tentative
        reservation should be a single atomic operation so that concurrent
        delivery of the same webhook cannot slip through.

        Args:
            reference: The transaction reference string extracted from the payload.
            provider: The provider name string (e.g. "paystack") used to scope
                      the key and prevent cross-provider reference collisions.

        Returns:
            ``True`` if this reference has already been processed, ``False`` if
            this is the first time it has been seen.

        Raises:
            IdempotencyBackendError: If the backend is unreachable or cannot
                guarantee atomicity.
        """

    @abstractmethod
    async def mark_processed(self, reference: str, provider: str) -> None:
        """
        Persist a reference as fully processed after successful business logic.

        In implementations that perform atomic reservation in ``is_duplicate``,
        this method may be a no-op or may update a status field in the ledger
        to distinguish "in-flight" from "committed".

        Args:
            reference: The transaction reference string.
            provider: The provider name string.

        Raises:
            IdempotencyBackendError: If the backend write fails.
        """
