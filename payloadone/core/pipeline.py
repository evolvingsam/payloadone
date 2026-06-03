"""
The PayloadOne processing pipeline.

Executes the seven ordered stages of webhook processing:

  1. Provider identification
  2. Signature verification
  3. Idempotency check
  4. Payload normalisation
  5. Event dispatch
  6. Idempotency commit
  7. Return result

Each stage is strictly ordered. A failure at any stage short-circuits
the pipeline; no later stage is executed.
"""

import logging
from dataclasses import dataclass

from ..exceptions import (
    SignatureVerificationError,
    UnknownProviderError,
)
from ..interfaces.idempotency import BaseIdempotencyBackend
from ..interfaces.provider import BaseProvider
from ..models.enums import Provider
from ..models.event import UnifiedEvent
from .dispatcher import Dispatcher

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PipelineResult:
    """
    Describes the outcome of a pipeline execution.

    Attributes:
        event: The normalised ``UnifiedEvent``, or ``None`` if the pipeline
               was short-circuited before normalisation.
        was_duplicate: ``True`` if the event was skipped because its reference
                       had already been processed.
        http_status: Suggested HTTP status code to return to the gateway.
    """

    event: UnifiedEvent | None
    was_duplicate: bool
    http_status: int


class WebhookPipeline:
    """
    Orchestrates the ordered processing pipeline for a single inbound webhook.

    This class holds no mutable state. A new pipeline instance can be created
    per request, or a single instance can be reused across requests; both are safe.
    """

    def __init__(
        self,
        provider_registry: dict[Provider, BaseProvider],
        idempotency_backend: BaseIdempotencyBackend,
        dispatcher: Dispatcher,
        secret_keys: dict[str, str],
    ) -> None:
        """
        Args:
            provider_registry: Mapping of ``Provider`` enum → concrete adapter.
            idempotency_backend: The active idempotency ledger backend.
            dispatcher: The event dispatcher for invoking registered handlers.
            secret_keys: Mapping of provider name → secret key for signature verification.
        """
        self._registry = provider_registry
        self._idempotency = idempotency_backend
        self._dispatcher = dispatcher
        self._secret_keys = secret_keys

    async def execute(
        self,
        provider: Provider,
        payload: bytes,
        headers: dict[str, str],
    ) -> PipelineResult:
        """
        Run the full 7-stage pipeline for an inbound webhook request.

        Args:
            provider: The provider enum value extracted from the route.
            payload: The raw request body bytes.
            headers: All HTTP request headers.

        Returns:
            A ``PipelineResult`` describing the outcome.

        Raises:
            UnknownProviderError: If the provider has no registered adapter.
            SignatureVerificationError: If the signature check fails.
            NormalisationError: If the payload cannot be mapped to a UnifiedEvent.
            IdempotencyBackendError: If the idempotency store is unavailable.
        """
        # Stage 1: Provider identification
        adapter = self._registry.get(provider)
        if adapter is None:
            raise UnknownProviderError(
                f"No adapter registered for provider '{provider.value}'. "
                "Ensure this provider's secret key is present in PayloadOneConfig."
            )

        secret_key = self._secret_keys.get(provider.value, "")

        # Stage 2: Signature verification
        logger.debug("Stage 2 — verifying signature for provider '%s'.", provider.value)
        is_valid = adapter.verify_signature(payload, headers, secret_key)
        if not is_valid:
            raise SignatureVerificationError(
                f"Signature verification failed for provider '{provider.value}'. "
                "The request was rejected."
            )

        # Stage 3: Idempotency check (extract reference first, before full normalisation)
        logger.debug("Stage 3 — checking idempotency for provider '%s'.", provider.value)
        reference = adapter.extract_reference(payload)
        is_duplicate = await self._idempotency.is_duplicate(reference, provider.value)

        if is_duplicate:
            logger.info(
                "Duplicate webhook detected — reference '%s' from provider '%s'. "
                "Returning 200 without re-processing.",
                reference,
                provider.value,
            )
            return PipelineResult(event=None, was_duplicate=True, http_status=200)

        # Stage 4: Payload normalisation
        logger.debug("Stage 4 — normalising payload for provider '%s'.", provider.value)
        event = adapter.normalise(payload)

        # Stage 5: Event dispatch
        logger.debug("Stage 5 — dispatching event '%s'.", event.event_type.value)
        await self._dispatcher.dispatch(event)

        # Stage 6: Idempotency commit
        logger.debug("Stage 6 — committing idempotency for reference '%s'.", reference)
        await self._idempotency.mark_processed(reference, provider.value)

        # Stage 7: Return success result
        logger.info(
            "Successfully processed event '%s' (reference: %s, provider: %s).",
            event.event_type.value,
            reference,
            provider.value,
        )
        return PipelineResult(event=event, was_duplicate=False, http_status=200)
