"""
WebhookManager — the primary public interface for PayloadOne.

Wires together configuration, provider adapters, idempotency backend,
dispatcher, and pipeline into a single, cohesive entry point.
"""

import logging
from collections.abc import Callable, Coroutine
from typing import Any

from ..config import PayloadOneConfig
from ..exceptions import MisconfigurationError
from ..idempotency.redis_backend import RedisIdempotencyBackend
from ..interfaces.handler import BaseEventHandler
from ..interfaces.idempotency import BaseIdempotencyBackend
from ..interfaces.provider import BaseProvider
from ..models.enums import EventType, Provider
from ..models.event import UnifiedEvent
from ..providers.flutterwave import FlutterwaveProvider
from ..providers.paystack import PaystackProvider
from .dispatcher import Dispatcher
from .pipeline import WebhookPipeline

logger = logging.getLogger(__name__)

HandlerCallable = Callable[[UnifiedEvent], Coroutine[Any, Any, None]]

# Default provider adapter registry.
# To add a new provider, add an entry here — no changes to core pipeline required.
_DEFAULT_PROVIDER_REGISTRY: dict[Provider, type[BaseProvider]] = {
    Provider.PAYSTACK: PaystackProvider,
    Provider.FLUTTERWAVE: FlutterwaveProvider,
}


class WebhookManager:
    """
    Top-level orchestrator for PayloadOne.

    Responsibilities:
    - Initialise and wire all subsystems from a ``PayloadOneConfig``.
    - Expose the ``@manager.on(event_type)`` decorator for handler registration.
    - Expose the ``process()`` method as the single entry point for inbound webhooks.

    Usage::

        config = PayloadOneConfig(
            secret_keys={"paystack": "sk_live_...", "flutterwave": "FLWSECK_..."},
            idempotency_backend="redis",
            redis_url="redis://localhost:6379",
        )
        manager = WebhookManager(config=config)

        @manager.on("payment.success")
        async def handle_payment(event: UnifiedEvent):
            await credit_wallet(event.reference, event.amount_in_lowest_unit)
    """

    def __init__(
        self,
        config: PayloadOneConfig,
        *,
        idempotency_backend: BaseIdempotencyBackend | None = None,
        extra_providers: dict[Provider, BaseProvider] | None = None,
    ) -> None:
        """
        Initialise the WebhookManager.

        Args:
            config: A fully validated ``PayloadOneConfig`` instance.
            idempotency_backend: Override the default idempotency backend.
                                 Useful for testing with an in-memory stub.
            extra_providers: Additional or replacement provider adapters,
                             keyed by ``Provider`` enum. Allows registering
                             custom adapters without modifying library code.
        """
        self._config = config
        self._dispatcher = Dispatcher()

        # Build provider registry from defaults, filtered to configured providers.
        self._provider_registry: dict[Provider, BaseProvider] = {}
        for provider_enum, adapter_class in _DEFAULT_PROVIDER_REGISTRY.items():
            if provider_enum.value in config.secret_keys:
                self._provider_registry[provider_enum] = adapter_class()

        if extra_providers:
            self._provider_registry.update(extra_providers)

        # Initialise idempotency backend.
        if idempotency_backend is not None:
            self._idempotency = idempotency_backend
        else:
            self._idempotency = self._build_idempotency_backend(config)

        self._pipeline = WebhookPipeline(
            provider_registry=self._provider_registry,
            idempotency_backend=self._idempotency,
            dispatcher=self._dispatcher,
            secret_keys=config.secret_keys,
        )

        logger.info(
            "WebhookManager initialised with providers: %s, backend: %s.",
            [p.value for p in self._provider_registry],
            config.idempotency_backend,
        )

    @staticmethod
    def _build_idempotency_backend(config: PayloadOneConfig) -> BaseIdempotencyBackend:
        """
        Instantiate the appropriate idempotency backend from configuration.

        PostgreSQL backend requires an asyncpg Pool which must be created
        asynchronously. For PostgreSQL, users should instantiate
        ``PostgresIdempotencyBackend`` directly and pass it via
        ``idempotency_backend`` parameter.
        """
        if config.idempotency_backend == "redis":
            assert config.redis_url is not None  # already validated in config
            return RedisIdempotencyBackend(
                redis_url=config.redis_url,
                ttl_seconds=config.idempotency_ttl_seconds,
            )

        if config.idempotency_backend == "postgres":
            raise MisconfigurationError(
                "PostgreSQL backend requires async pool initialisation. "
                "Create a PostgresIdempotencyBackend with an asyncpg Pool and pass it "
                "via WebhookManager(config=config, idempotency_backend=your_backend)."
            )

        raise MisconfigurationError(
            f"Unknown idempotency_backend '{config.idempotency_backend}'."
        )

    def on(
        self,
        event_type: "EventType | str",
    ) -> Callable[[HandlerCallable], HandlerCallable]:
        """
        Decorator factory for registering an async handler function.

        Args:
            event_type: The event type to listen for. Accepts either an
                        ``EventType`` enum value or its string representation
                        (e.g. ``"payment.success"``).

        Returns:
            A decorator that registers the wrapped function and returns it unchanged.

        Example::

            @manager.on("payment.success")
            async def handle_payment(event: UnifiedEvent) -> None:
                await credit_wallet(event.reference, event.amount_in_lowest_unit)
        """
        if isinstance(event_type, str):
            try:
                event_type = EventType(event_type)
            except ValueError:
                valid = [e.value for e in EventType]
                raise MisconfigurationError(
                    f"'{event_type}' is not a valid EventType. "
                    f"Valid values are: {valid}"
                ) from None

        resolved_event_type = event_type  # capture for closure

        def decorator(fn: HandlerCallable) -> HandlerCallable:
            self._dispatcher.register_function(resolved_event_type, fn)
            return fn

        return decorator

    def register_handler(
        self,
        event_type: "EventType | str",
        handler: "BaseEventHandler | HandlerCallable",
    ) -> None:
        """
        Programmatically register a handler (alternative to the ``@on`` decorator).

        Args:
            event_type: The event type to listen for.
            handler: A ``BaseEventHandler`` instance or an async callable.
        """
        if isinstance(event_type, str):
            event_type = EventType(event_type)
        self._dispatcher.register(event_type, handler)

    async def process(
        self,
        provider: "Provider | str",
        payload: bytes,
        headers: dict[str, str],
    ) -> None:
        """
        Process a single inbound webhook request through the full pipeline.

        This is the main entry point called from your web framework route handler.
        It runs all seven pipeline stages and raises appropriate exceptions on failure.

        Args:
            provider: The provider identifier, either as a ``Provider`` enum value
                      or its string representation (e.g. ``"paystack"``).
            payload: The raw request body bytes, as received from the HTTP request.
            headers: All HTTP request headers as a dictionary.

        Raises:
            UnknownProviderError: If the provider is not configured.
            SignatureVerificationError: If the signature check fails (→ HTTP 401).
            NormalisationError: If the payload cannot be mapped to UnifiedEvent (→ HTTP 422).
            IdempotencyBackendError: If the idempotency store is unavailable.
        """
        if isinstance(provider, str):
            try:
                provider = Provider(provider)
            except ValueError:
                from ..exceptions import UnknownProviderError
                valid = [p.value for p in Provider]
                raise UnknownProviderError(
                    f"'{provider}' is not a registered provider. "
                    f"Valid providers are: {valid}"
                ) from None

        await self._pipeline.execute(
            provider=provider,
            payload=payload,
            headers=headers,
        )