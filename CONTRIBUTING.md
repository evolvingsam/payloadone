# Contributing to PayloadOne

Thank you for contributing. This document covers everything you need to add a new provider adapter, write tests, and get CI passing.

---

## Adding a New Payment Provider

PayloadOne is designed so that adding a new provider requires **zero changes to core pipeline code**. All provider-specific logic lives in an isolated adapter module.

### Step 1 — Create the adapter module

Create `payloadone/providers/yourprovider.py` implementing `BaseProvider`:

```python
import hashlib
import hmac
import json
from typing import Any

from payloadone.exceptions import NormalisationError
from payloadone.interfaces.provider import BaseProvider
from payloadone.models.enums import EventType, Provider
from payloadone.models.event import UnifiedEvent

_EVENT_TYPE_MAP: dict[str, EventType] = {
    "payment.successful": EventType.PAYMENT_SUCCESS,
    # add all event strings your provider emits
}

class YourProvider(BaseProvider):
    def verify_signature(
        self, payload: bytes, headers: dict[str, str], secret_key: str
    ) -> bool:
        """
        MUST use hmac.compare_digest — never raise, return False on any failure.
        MUST use time-constant comparison to prevent timing attacks.
        """
        try:
            received = {k.lower(): v for k, v in headers.items()}.get("x-your-sig-header", "")
            if not received:
                return False
            expected = hmac.new(
                secret_key.encode(), msg=payload, digestmod=hashlib.sha256
            ).hexdigest()
            return hmac.compare_digest(expected, received)
        except Exception:
            return False

    def extract_reference(self, payload: bytes) -> str:
        try:
            return json.loads(payload)["data"]["reference"]
        except (json.JSONDecodeError, KeyError) as exc:
            raise NormalisationError(f"Missing reference: {exc}") from exc

    def normalise(self, payload: bytes) -> UnifiedEvent:
        try:
            raw: dict[str, Any] = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise NormalisationError(f"Invalid JSON: {exc}") from exc

        try:
            data = raw["data"]
            event_type = _EVENT_TYPE_MAP.get(raw["event"])
            if event_type is None:
                raise NormalisationError(f"Unknown event type: {raw['event']}")

            return UnifiedEvent(
                provider=Provider.YOURPROVIDER,
                event_type=event_type,
                reference=data["reference"],
                amount_in_lowest_unit=int(data["amount"]),  # ensure int, never float
                currency=data["currency"],
                customer_email=data["customer"]["email"],
                customer_name=data["customer"].get("name"),
                metadata=data.get("metadata") or {},
                raw_payload=raw,
            )
        except NormalisationError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise NormalisationError(f"Normalisation failed: {exc}") from exc
```

### Step 2 — Add the Provider enum value

In `payloadone/models/enums.py`:

```python
class Provider(str, Enum):
    PAYSTACK = "paystack"
    FLUTTERWAVE = "flutterwave"
    YOURPROVIDER = "yourprovider"   # add this
```

### Step 3 — Register the adapter

In `payloadone/core/manager.py`, add to `_DEFAULT_PROVIDER_REGISTRY`:

```python
from payloadone.providers.yourprovider import YourProvider

_DEFAULT_PROVIDER_REGISTRY: dict[Provider, type[BaseProvider]] = {
    Provider.PAYSTACK: PaystackProvider,
    Provider.FLUTTERWAVE: FlutterwaveProvider,
    Provider.YOURPROVIDER: YourProvider,   # add this
}
```

That is the **only** change to existing code. The pipeline, idempotency system, and dispatcher are untouched.

### Step 4 — Write tests

Create `tests/unit/test_yourprovider.py`. At minimum, cover:

- Valid signature passes `verify_signature`
- Invalid signature returns `False` (does not raise)
- Missing signature header returns `False`
- Tampered payload returns `False`
- `normalise()` maps all event types correctly
- `amount_in_lowest_unit` is always an `int`
- `raw_payload` is preserved unmodified
- Unknown event type raises `NormalisationError`
- Invalid JSON raises `NormalisationError`

### Step 5 — Update the README

Add a configuration table for the new provider under the "Provider Configuration Reference" section.

---

## Development Setup

```bash
# Clone and install
git clone https://github.com/your-org/payloadone
cd payloadone
poetry install --with dev

# Run the full test suite
poetry run pytest

# Lint
poetry run ruff check payloadone/

# Type check
poetry run mypy payloadone/
```

## Code Standards

- All public methods must have type annotations and docstrings.
- No global mutable state anywhere.
- Exceptions must propagate with descriptive messages — no silent swallowing.
- Money amounts must always be `int` (kobo/cents), never `float`.
- Signature verification must use `hmac.compare_digest` — no string equality (`==`).
- New code must maintain ≥ 90% test coverage (`pytest-cov` enforces this in CI).

## Pull Request Checklist

- [ ] Adapter implements all three `BaseProvider` methods
- [ ] `Provider` enum updated
- [ ] `_DEFAULT_PROVIDER_REGISTRY` updated
- [ ] Tests cover valid/invalid signatures, all event type mappings, edge cases
- [ ] `README.md` updated with provider configuration table
- [ ] `poetry run pytest` passes with ≥ 90% coverage
- [ ] `poetry run ruff check payloadone/` passes
- [ ] `poetry run mypy payloadone/` passes