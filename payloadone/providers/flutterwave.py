"""
Flutterwave webhook adapter.

Handles secret-hash signature verification and payload normalisation
for all Flutterwave webhook event types.
"""

import hmac
import json
from typing import Any

from ..exceptions import NormalisationError
from ..interfaces.provider import BaseProvider
from ..models.enums import EventType, Provider
from ..models.event import UnifiedEvent

# Flutterwave uses a composite key of (event, status) to determine event type.
# The outer key is the raw event string; the inner key is the data.status value.
# A None inner key matches any status (or status-independent events).
_EVENT_TYPE_MAP: dict[str, dict[str, EventType]] = {
    "charge.completed": {
        "successful": EventType.PAYMENT_SUCCESS,
        "failed": EventType.PAYMENT_FAILED,
    },
    "transfer.completed": {
        "SUCCESSFUL": EventType.TRANSFER_SUCCESS,
        "FAILED": EventType.TRANSFER_FAILED,
    },
}

_SIGNATURE_HEADER = "verif-hash"


class FlutterwaveProvider(BaseProvider):
    """
    Adapter for Flutterwave webhooks.

    Signature algorithm: plain secret hash comparison.
    Flutterwave sends the configured secret hash verbatim in the
    ``verif-hash`` header. Verification is a time-constant string
    comparison of the header value against the configured secret.
    """

    def verify_signature(
        self,
        payload: bytes,
        headers: dict[str, str],
        secret_key: str,
    ) -> bool:
        try:
            normalised_headers = {k.lower(): v for k, v in headers.items()}
            received_hash = normalised_headers.get(_SIGNATURE_HEADER, "").strip()

            if not received_hash:
                return False

            return hmac.compare_digest(secret_key.strip(), received_hash)
        except Exception:
            return False

    def extract_reference(self, payload: bytes) -> str:
        """Extract the transaction reference from a Flutterwave payload."""
        try:
            data: dict[str, Any] = json.loads(payload)
            reference: str = data["data"]["tx_ref"]
            return reference
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise NormalisationError(
                f"Flutterwave payload is missing required field 'data.tx_ref': {exc}"
            ) from exc

    def normalise(self, payload: bytes) -> UnifiedEvent:
        """
        Translate a verified Flutterwave payload into a ``UnifiedEvent``.

        Flutterwave amounts are floating-point (e.g. 50.00 NGN).
        They are multiplied by 100 and cast to int to produce the lowest
        currency unit value (5000 kobo), eliminating floating-point errors.
        """
        try:
            raw: dict[str, Any] = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise NormalisationError(f"Flutterwave payload is not valid JSON: {exc}") from exc

        try:
            event_str: str = raw["event"]
            data: dict[str, Any] = raw["data"]
            status: str = data.get("status", "")
            customer: dict[str, Any] = data["customer"]

            status_map = _EVENT_TYPE_MAP.get(event_str)
            if status_map is None:
                raise NormalisationError(
                    f"Flutterwave event type '{event_str}' has no normalised mapping. "
                    "Update _EVENT_TYPE_MAP in payloadone/providers/flutterwave.py."
                )

            event_type = status_map.get(status)
            if event_type is None:
                raise NormalisationError(
                    f"Flutterwave event '{event_str}' with status '{status}' "
                    "has no normalised mapping."
                )

            # Convert float amount to lowest currency unit integer.
            # round() before int() guards against floating-point imprecision
            # e.g. 50.00 * 100 = 4999.999999 on some platforms.
            raw_amount: float = float(data["amount"])
            amount_in_lowest_unit = int(round(raw_amount * 100))

            customer_name: str | None = customer.get("name") or None

            return UnifiedEvent(
                provider=Provider.FLUTTERWAVE,
                event_type=event_type,
                reference=data["tx_ref"],
                amount_in_lowest_unit=amount_in_lowest_unit,
                currency=data["currency"],
                customer_email=customer["email"],
                customer_name=customer_name,
                metadata=data.get("meta") or {},
                raw_payload=raw,
                provider_event_id=str(data.get("id")) if data.get("id") else None,
            )
        except NormalisationError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise NormalisationError(
                f"Failed to normalise Flutterwave payload — missing or invalid field: {exc}"
            ) from exc
