"""
PayloadOne exception hierarchy.

All exceptions are explicit, carry meaningful messages, and map cleanly
to HTTP response codes in the framework adapter layer.
"""


class PayloadOneError(Exception):
    """Base exception for all PayloadOne errors."""


class SignatureVerificationError(PayloadOneError):
    """
    Raised when a webhook signature fails cryptographic validation.

    HTTP mapping: 401 Unauthorized.
    The pipeline halts immediately; no downstream code executes.
    """


class UnknownProviderError(PayloadOneError):
    """
    Raised when an inbound request carries an unregistered provider identifier.

    HTTP mapping: 400 Bad Request.
    """


class NormalisationError(PayloadOneError):
    """
    Raised when a verified payload cannot be mapped to a UnifiedEvent.

    This indicates a structural mismatch — e.g. a provider changed their
    payload schema — and requires adapter maintenance.

    HTTP mapping: 422 Unprocessable Entity.
    """


class IdempotencyBackendError(PayloadOneError):
    """
    Raised when the idempotency store is unreachable, times out,
    or cannot guarantee atomic check-and-set semantics.

    This is a hard error; the pipeline must not proceed without
    an idempotency guarantee.
    """


class MisconfigurationError(PayloadOneError):
    """
    Raised at initialisation time when required configuration values are
    absent, of the wrong type, or mutually inconsistent.

    PayloadOne fails loudly at startup rather than silently degrading
    at request time.
    """
