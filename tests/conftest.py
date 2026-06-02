"""
Shared pytest fixtures for the PayloadOne test suite.

Provides:
- Raw payload bytes for Paystack and Flutterwave
- Pre-signed payload factories
- A stub idempotency backend for integration tests
- A pre-configured WebhookManager with fakeredis
"""

import hashlib
import hmac
import json

import pytest

from payloadone.config import PayloadOneConfig
from payloadone.core.manager import WebhookManager
from payloadone.interfaces.idempotency import BaseIdempotencyBackend

# ---------------------------------------------------------------------------
# Secret keys used in tests
# ---------------------------------------------------------------------------

PAYSTACK_SECRET = "test-paystack-secret-key"
FLUTTERWAVE_SECRET = "test-flutterwave-secret-hash"

# ---------------------------------------------------------------------------
# Raw payload fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def paystack_charge_success_payload() -> dict:
    return {
        "event": "charge.success",
        "data": {
            "id": 123456,
            "reference": "txn_paystack_001",
            "amount": 5000,
            "currency": "NGN",
            "status": "success",
            "customer": {
                "email": "user@example.com",
                "first_name": "Amaka",
                "last_name": "Okafor",
            },
            "metadata": {"order_id": "order_999"},
        },
    }


@pytest.fixture()
def paystack_charge_failed_payload() -> dict:
    return {
        "event": "charge.failed",
        "data": {
            "id": 123457,
            "reference": "txn_paystack_002",
            "amount": 2000,
            "currency": "NGN",
            "status": "failed",
            "customer": {
                "email": "user2@example.com",
                "first_name": "Emeka",
                "last_name": "Eze",
            },
            "metadata": {},
        },
    }


@pytest.fixture()
def flutterwave_charge_success_payload() -> dict:
    return {
        "event": "charge.completed",
        "data": {
            "id": 987654,
            "tx_ref": "txn_flw_001",
            "amount": 50.00,
            "currency": "NGN",
            "status": "successful",
            "customer": {
                "email": "customer@example.com",
                "name": "Ngozi Adeyemi",
            },
            "meta": {"product": "premium"},
        },
    }


@pytest.fixture()
def flutterwave_charge_failed_payload() -> dict:
    return {
        "event": "charge.completed",
        "data": {
            "id": 987655,
            "tx_ref": "txn_flw_002",
            "amount": 100.00,
            "currency": "NGN",
            "status": "failed",
            "customer": {
                "email": "customer2@example.com",
                "name": "Chidi Okeke",
            },
            "meta": {},
        },
    }


# ---------------------------------------------------------------------------
# Signed payload factories
# ---------------------------------------------------------------------------


def make_paystack_headers(payload_bytes: bytes, secret: str = PAYSTACK_SECRET) -> dict:
    """Generate a valid Paystack signature header for the given payload."""
    sig = hmac.new(
        secret.encode("utf-8"),
        msg=payload_bytes,
        digestmod=hashlib.sha512,
    ).hexdigest()
    return {"x-paystack-signature": sig, "content-type": "application/json"}


def make_flutterwave_headers(secret: str = FLUTTERWAVE_SECRET) -> dict:
    """Generate a valid Flutterwave verif-hash header."""
    return {"verif-hash": secret, "content-type": "application/json"}


@pytest.fixture()
def paystack_valid_request(paystack_charge_success_payload) -> tuple[bytes, dict]:
    """Returns (payload_bytes, headers) with a valid Paystack signature."""
    body = json.dumps(paystack_charge_success_payload).encode()
    return body, make_paystack_headers(body)


@pytest.fixture()
def flutterwave_valid_request(flutterwave_charge_success_payload) -> tuple[bytes, dict]:
    """Returns (payload_bytes, headers) with a valid Flutterwave hash."""
    body = json.dumps(flutterwave_charge_success_payload).encode()
    return body, make_flutterwave_headers()


# ---------------------------------------------------------------------------
# Stub idempotency backend
# ---------------------------------------------------------------------------


class InMemoryIdempotencyBackend(BaseIdempotencyBackend):
    """Simple in-memory idempotency backend for unit and integration tests."""

    def __init__(self) -> None:
        self._seen: set[str] = set()

    async def is_duplicate(self, reference: str, provider: str) -> bool:
        key = f"{provider}:{reference}"
        if key in self._seen:
            return True
        self._seen.add(key)
        return False

    async def mark_processed(self, reference: str, provider: str) -> None:
        pass  # Already marked in is_duplicate for this stub.

    def reset(self) -> None:
        self._seen.clear()


@pytest.fixture()
def in_memory_backend() -> InMemoryIdempotencyBackend:
    return InMemoryIdempotencyBackend()


# ---------------------------------------------------------------------------
# Pre-configured WebhookManager
# ---------------------------------------------------------------------------


@pytest.fixture()
def manager_config() -> PayloadOneConfig:
    return PayloadOneConfig(
        secret_keys={
            "paystack": PAYSTACK_SECRET,
            "flutterwave": FLUTTERWAVE_SECRET,
        },
        idempotency_backend="redis",
        redis_url="redis://localhost:6379",
        idempotency_ttl_seconds=3600,
    )


@pytest.fixture()
def manager(manager_config, in_memory_backend) -> WebhookManager:
    """A WebhookManager with in-memory idempotency — no Redis required."""
    return WebhookManager(
        config=manager_config,
        idempotency_backend=in_memory_backend,
    )