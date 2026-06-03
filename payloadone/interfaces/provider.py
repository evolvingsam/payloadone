"""Abstract base class that every payment provider adapter must implement."""

from abc import ABC, abstractmethod

from ..models.event import UnifiedEvent


class BaseProvider(ABC):
    """
    Contract for a payment gateway adapter.

    Each concrete implementation encapsulates all provider-specific knowledge:
    signature algorithms, payload schema, field paths, and event type mapping.
    The core pipeline depends only on this interface, never on concrete adapters.
    """

    @abstractmethod
    def verify_signature(
        self,
        payload: bytes,
        headers: dict[str, str],
        secret_key: str,
    ) -> bool:
        """
        Verify the cryptographic signature of an inbound webhook request.

        Implementations MUST:
        - Use time-constant comparison (``hmac.compare_digest``) to prevent
          timing-oracle attacks.
        - Never raise an exception — return ``False`` on any error condition
          so the pipeline can issue a uniform 401 response.

        Args:
            payload: The raw, unread request body bytes.
            headers: All HTTP request headers as a case-insensitive-friendly dict.
            secret_key: The provider secret retrieved from ``PayloadOneConfig``.

        Returns:
            ``True`` if the signature is valid, ``False`` otherwise.
        """

    @abstractmethod
    def normalise(self, payload: bytes) -> UnifiedEvent:
        """
        Parse a verified raw payload and return a normalised ``UnifiedEvent``.

        The payload has already passed signature verification at this point.

        Implementations MUST:
        - Express monetary amounts as integers in the lowest currency unit.
        - Preserve the original payload in ``UnifiedEvent.raw_payload`` unmodified.
        - Raise ``NormalisationError`` with a descriptive message if any
          required field is missing or cannot be mapped.

        Args:
            payload: The raw request body bytes (JSON-encoded).

        Returns:
            A fully populated ``UnifiedEvent`` instance.

        Raises:
            NormalisationError: If the payload cannot be mapped to a ``UnifiedEvent``.
        """

    @abstractmethod
    def extract_reference(self, payload: bytes) -> str:
        """
        Extract the transaction reference from the raw payload.

        Called before full normalisation so the idempotency check can occur
        before the more expensive normalisation step.

        Args:
            payload: The raw request body bytes (JSON-encoded).

        Returns:
            The transaction reference string.

        Raises:
            NormalisationError: If the reference field is missing or unparseable.
        """
