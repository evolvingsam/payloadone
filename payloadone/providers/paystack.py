"""
Paystack webhook adapter.

Handles HMAC-SHA512 signature verification and payload normalisation
for all Paystack webhook event types.
"""

import hashlib
import hmac
import json
from typing import Any

from ..exceptions import NormalisationError
from ..interfaces.provider import BaseProvider
from ..models.enums import EventType, Provider
from ..models.event import UnifiedEvent

# Maps Paystack event strings to normalised EventType values.
_EVENT_TYPE_MAP: dict[str, EventType] = {
    "charge.success": EventType.PAYMENT_SUCCESS,
    "charge.failed": EventType.PAYMENT_FAILED,
    "refund.processed": EventType.REFUND_PROCESSED,
    "transfer.success": EventType.TRANSFER_SUCCESS,
    "transfer.failed": EventType.TRANSFER_FAILED,
}

_SIGNATURE_HEADER = "x-paystack-signature"


class PaystackProvider(BaseProvider):
    """
    Adapter for Paystack webhooks.

    Signature algorithm: HMAC-SHA512 over the raw request body,
    keyed with the Paystack secret key. The resulting hex digest is
    compared against the ``x-paystack-signature`` header using
    time-constant comparison.
    """

    def verify_signature(
        self,
        payload: bytes,
        headers: dict[str, str],
        secret_key: str,
    ) -> bool:
        """
        Verify the Paystack HMAC-SHA512 webhook signature.

        Returns False (never raises) on any failure so the pipeline can
        issue a uniform 401 without leaking error detail to the caller.
        """
        try:
            # Normalise header lookup to lowercase for framework compatibility.
            normalised_headers = {k.lower(): v for k, v in headers.items()}
            received_signature = normalised_headers.get(_SIGNATURE_HEADER, "")

            if not received_signature:
                return False

            expected = hmac.new(
                secret_key.encode("utf-8"),
                msg=payload,
                digestmod=hashlib.sha512,
            ).hexdigest()

            # Time-constant comparison prevents timing-oracle attacks.
            return hmac.compare_digest(expected, received_signature)
        except Exception:  # noqa: BLE001
            return False

    def extract_reference(self, payload: bytes) -> str:
        """Extract the transaction reference from a Paystack payload."""
        try:
            data: dict[str, Any] = json.loads(payload)
            reference: str = data["data"]["reference"]
            return reference
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise NormalisationError(
                f"Paystack payload is missing required field 'data.reference': {exc}"
            ) from exc

    def normalise(self, payload: bytes) -> UnifiedEvent:
        """
        Translate a verified Paystack payload into a ``UnifiedEvent``.

        Paystack amounts are already denominated in kobo, so no conversion
        is required — the value is cast to int to enforce the type contract.
        """
        try:
            raw: dict[str, Any] = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise NormalisationError(
                f"Paystack payload is not valid JSON: {exc}"
            ) from exc

        try:
            event_str: str = raw["event"]
            data: dict[str, Any] = raw["data"]
            customer: dict[str, Any] = data["customer"]

            event_type = _EVENT_TYPE_MAP.get(event_str)
            if event_type is None:
                raise NormalisationError(
                    f"Paystack event type '{event_str}' has no normalised mapping. "
                    "Update _EVENT_TYPE_MAP in payloadone/providers/paystack.py."
                )

            # Amount is already in kobo; cast to int to enforce no-float contract.
            amount_in_lowest_unit = int(data["amount"])

            first_name: str = customer.get("first_name") or ""
            last_name: str = customer.get("last_name") or ""
            customer_name_parts = [n for n in [first_name, last_name] if n]
            customer_name = " ".join(customer_name_parts) or None

            return UnifiedEvent(
                provider=Provider.PAYSTACK,
                event_type=event_type,
                reference=data["reference"],
                amount_in_lowest_unit=amount_in_lowest_unit,
                currency=data["currency"],
                customer_email=customer["email"],
                customer_name=customer_name,
                metadata=data.get("metadata") or {},
                raw_payload=raw,
                provider_event_id=raw.get("id"),
            )
        except NormalisationError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise NormalisationError(
                f"Failed to normalise Paystack payload — missing or invalid field: {exc}"
            ) from exc