"""Normalised webhook event model — the single output shape of PayloadOne."""

from typing import Any

from pydantic import BaseModel, EmailStr

from .enums import EventType, Provider


class UnifiedEvent(BaseModel):
    """
    A provider-agnostic representation of a payment webhook event.

    All monetary values are expressed as integers in the lowest currency unit
    (kobo for NGN, cents for USD) to eliminate floating-point errors.
    """

    provider: Provider
    """The payment gateway that originated this event."""

    event_type: EventType
    """Normalised event classification, independent of provider naming conventions."""

    reference: str
    """Unique transaction reference used for idempotency keying."""

    amount_in_lowest_unit: int
    """
    Monetary amount in the lowest indivisible unit of the currency.
    E.g. 5000 kobo = ₦50.00. Never a float.
    """

    currency: str
    """ISO 4217 three-letter currency code, e.g. 'NGN', 'USD'."""

    customer_email: EmailStr
    """Validated email address of the customer."""

    customer_name: str | None = None
    """Full name of the customer, if available from the provider."""

    metadata: dict[str, Any] = {}
    """Standardised passthrough metadata from the original checkout session."""

    raw_payload: dict[str, Any]
    """The original, unmodified provider payload for debugging and edge-case access."""

    provider_event_id: str | None = None
    """The provider's own event or notification identifier, if present."""

    model_config = {"frozen": True}