"""
FastAPI integration adapter for PayloadOne.

Provides an exception handler installer and a thin route helper that
maps PayloadOne exceptions to the correct HTTP responses automatically.

Usage::

    from fastapi import FastAPI, Request
    from payloadone.adapters.fastapi import install_exception_handlers, process_webhook

    app = FastAPI()
    install_exception_handlers(app)

    @app.post("/webhooks/{provider}")
    async def webhook(provider: str, request: Request):
        return await process_webhook(manager, provider, request)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from fastapi import FastAPI, Request

    from ..core.manager import WebhookManager

try:
    from fastapi import Request
    from fastapi.responses import JSONResponse
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "The FastAPI adapter requires the 'fastapi' package. "
        "Install it with: pip install payloadone[fastapi]"
    ) from exc

from ..exceptions import (
    NormalisationError,
    SignatureVerificationError,
    UnknownProviderError,
)


def install_exception_handlers(app: "FastAPI") -> None:
    """
    Register PayloadOne exception handlers on a FastAPI application instance.

    After calling this, any ``SignatureVerificationError``, ``UnknownProviderError``,
    or ``NormalisationError`` raised during webhook processing will be converted
    to the correct HTTP response automatically.

    Args:
        app: The FastAPI application instance.
    """
    from fastapi import Request as _Request

    @app.exception_handler(SignatureVerificationError)
    async def handle_signature_error(
        _request: _Request, exc: SignatureVerificationError
    ) -> JSONResponse:
        return JSONResponse(status_code=401, content={"error": str(exc)})

    @app.exception_handler(UnknownProviderError)
    async def handle_unknown_provider(
        _request: _Request, exc: UnknownProviderError
    ) -> JSONResponse:
        return JSONResponse(status_code=400, content={"error": str(exc)})

    @app.exception_handler(NormalisationError)
    async def handle_normalisation_error(
        _request: _Request, exc: NormalisationError
    ) -> JSONResponse:
        return JSONResponse(status_code=422, content={"error": str(exc)})


async def process_webhook(
    manager: "WebhookManager",
    provider: str,
    request: "Request",
) -> JSONResponse:
    """
    Convenience helper: extract body and headers from a FastAPI Request
    and delegate to the WebhookManager.

    Args:
        manager: A configured ``WebhookManager`` instance.
        provider: The provider string extracted from the URL route parameter.
        request: The incoming FastAPI ``Request`` object.

    Returns:
        A ``JSONResponse`` with status 200 on success.

    Raises:
        SignatureVerificationError, UnknownProviderError, NormalisationError:
            These propagate up to FastAPI's exception handlers if
            ``install_exception_handlers`` has been called, or to the
            caller otherwise.
    """
    payload = await request.body()
    headers = dict(request.headers)
    await manager.process(provider=provider, payload=payload, headers=headers)
    return JSONResponse(status_code=200, content={"status": "acknowledged"})