"""
Event dispatcher — invokes all registered handlers for a given event type.
"""

import asyncio
import logging
from collections import defaultdict
from collections.abc import Callable, Coroutine
from typing import Any

from ..interfaces.handler import BaseEventHandler
from ..models.enums import EventType
from ..models.event import UnifiedEvent

logger = logging.getLogger(__name__)

# A handler can be either a BaseEventHandler subclass instance
# or a plain async function with the signature (event: UnifiedEvent) -> None.
HandlerCallable = Callable[[UnifiedEvent], Coroutine[Any, Any, None]]


class Dispatcher:
    """
    Registry and invoker for event handlers.

    Handlers are registered per event type. When an event is dispatched,
    all registered handlers for that event type are invoked concurrently
    via ``asyncio.gather``.

    If a handler raises an exception, it is logged but does not prevent
    other handlers from running. The caller (pipeline) decides whether to
    propagate or swallow errors based on its own contract.
    """

    def __init__(self) -> None:
        self._handlers: dict[EventType, list[HandlerCallable]] = defaultdict(list)

    def register(
        self,
        event_type: EventType,
        handler: "BaseEventHandler | HandlerCallable",
    ) -> None:
        """
        Register a handler for a specific event type.

        Args:
            event_type: The ``EventType`` this handler should receive.
            handler: Either a ``BaseEventHandler`` instance (its ``handle``
                     method is called) or a plain async callable.
        """
        if isinstance(handler, BaseEventHandler):
            callable_handler: HandlerCallable = handler.handle
        else:
            callable_handler = handler

        self._handlers[event_type].append(callable_handler)
        logger.debug(
            "Registered handler '%s' for event type '%s'.",
            getattr(callable_handler, "__qualname__", repr(callable_handler)),
            event_type.value,
        )

    def register_function(
        self,
        event_type: EventType,
        fn: HandlerCallable,
    ) -> None:
        """Convenience alias used by the ``@manager.on`` decorator."""
        self.register(event_type, fn)

    async def dispatch(self, event: UnifiedEvent) -> None:
        """
        Invoke all registered handlers for the event's type concurrently.

        If no handlers are registered for the event type, a debug log is
        emitted and the method returns immediately (not an error).

        Individual handler exceptions are caught, logged, and re-raised
        so the pipeline can decide handling strategy. With multiple handlers,
        all are awaited regardless of individual failures; a combined
        ``ExceptionGroup`` is raised if any fail.

        Args:
            event: The fully verified, deduplicated, normalised ``UnifiedEvent``.
        """
        handlers = self._handlers.get(event.event_type, [])

        if not handlers:
            logger.debug(
                "No handlers registered for event type '%s' (reference: %s). Skipping dispatch.",
                event.event_type.value,
                event.reference,
            )
            return

        logger.debug(
            "Dispatching event '%s' (reference: %s) to %d handler(s).",
            event.event_type.value,
            event.reference,
            len(handlers),
        )

        tasks = [handler(event) for handler in handlers]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        errors = [r for r in results if isinstance(r, BaseException)]
        if errors:
            for error in errors:
                logger.error(
                    "Handler raised an exception for event '%s' (reference: %s): %s",
                    event.event_type.value,
                    event.reference,
                    error,
                    exc_info=error,
                )
            # Re-raise the first error so the pipeline can decide whether
            # to prevent idempotency commitment.
            raise errors[0]
