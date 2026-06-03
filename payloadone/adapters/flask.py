"""
Flask integration adapter for PayloadOne.

Provides a synchronous wrapper around the async WebhookManager pipeline,
bridging Flask's synchronous request handling with PayloadOne's asyncio internals.

Usage::

    from flask import Flask
    from payloadone.adapters.flask import process_webhook_sync

    app = Flask(__name__)

    @app.post("/webhooks/<provider>")
    def webhook(provider: str):
        return process_webhook_sync(manager, provider)
"""

from __future__ import annotations

import asyncio
import json

try:
    from flask import Response, request
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "The Flask adapter requires the 'flask' package. "
        "Install it with: pip install payloadone[flask]"
    ) from exc

from ..core.manager import WebhookManager
from ..exceptions import (
    NormalisationError,
    SignatureVerificationError,
    UnknownProviderError,
)


def process_webhook_sync(
    manager: WebhookManager,
    provider: str,
) -> Response:
    """
    Synchronous entry point for a Flask webhook route.

    Extracts the raw body and headers from Flask's thread-local ``request``
    context, runs the async WebhookManager pipeline in a new event loop,
    and returns an appropriate Flask ``Response``.

    Args:
        manager: A configured ``WebhookManager`` instance.
        provider: The provider string extracted from the URL route parameter.

    Returns:
        A Flask ``Response`` with the correct HTTP status code.
    """
    payload: bytes = request.get_data()
    headers: dict[str, str] = dict(request.headers)

    try:
        asyncio.run(manager.process(provider=provider, payload=payload, headers=headers))
        return Response(
            json.dumps({"status": "acknowledged"}),
            status=200,
            mimetype="application/json",
        )
    except SignatureVerificationError as exc:
        return Response(
            json.dumps({"error": str(exc)}),
            status=401,
            mimetype="application/json",
        )
    except UnknownProviderError as exc:
        return Response(
            json.dumps({"error": str(exc)}),
            status=400,
            mimetype="application/json",
        )
    except NormalisationError as exc:
        return Response(
            json.dumps({"error": str(exc)}),
            status=422,
            mimetype="application/json",
        )


def extract_body_and_headers() -> tuple[bytes, dict[str, str]]:
    """
    Extract raw body and headers from the current Flask request context.

    Useful when you need fine-grained control and prefer to call the
    async ``manager.process()`` yourself.

    Returns:
        A tuple of (raw_body_bytes, headers_dict).
    """
    return request.get_data(), dict(request.headers)
