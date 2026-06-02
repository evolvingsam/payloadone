"""
Integration tests for the full WebhookManager pipeline.

Covers:
- Full happy path: verify → deduplicate → normalise → handler invoked
- Duplicate detection: handler is NOT invoked on repeat delivery
- Signature failure: HTTP 401, no downstream code runs
- FastAPI adapter extraction
- Flask adapter extraction
"""

import json

import pytest

from payloadone.exceptions import SignatureVerificationError, UnknownProviderError
from payloadone.models.enums import EventType
from payloadone.models.event import UnifiedEvent
from tests.conftest import (
    PAYSTACK_SECRET,
    make_flutterwave_headers,
    make_paystack_headers,
)


# ---------------------------------------------------------------------------
# Full pipeline — happy path
# ---------------------------------------------------------------------------


class TestPipelineHappyPath:
    async def test_paystack_payment_success_invokes_handler(
        self,
        manager,
        paystack_valid_request,
    ):
        payload, headers = paystack_valid_request
        received_events: list[UnifiedEvent] = []

        @manager.on("payment.success")
        async def capture(event: UnifiedEvent) -> None:
            received_events.append(event)

        await manager.process("paystack", payload, headers)

        assert len(received_events) == 1
        assert received_events[0].reference == "txn_paystack_001"
        assert received_events[0].amount_in_lowest_unit == 5000

    async def test_flutterwave_payment_success_invokes_handler(
        self,
        manager,
        flutterwave_valid_request,
    ):
        payload, headers = flutterwave_valid_request
        received_events: list[UnifiedEvent] = []

        @manager.on("payment.success")
        async def capture(event: UnifiedEvent) -> None:
            received_events.append(event)

        await manager.process("flutterwave", payload, headers)

        assert len(received_events) == 1
        assert received_events[0].reference == "txn_flw_001"

    async def test_handler_receives_correct_event_type(
        self,
        manager,
        paystack_valid_request,
    ):
        payload, headers = paystack_valid_request
        captured: list[UnifiedEvent] = []

        @manager.on(EventType.PAYMENT_SUCCESS)
        async def h(event: UnifiedEvent) -> None:
            captured.append(event)

        await manager.process("paystack", payload, headers)
        assert captured[0].event_type == EventType.PAYMENT_SUCCESS


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------


class TestDuplicateDetection:
    async def test_duplicate_does_not_invoke_handler(
        self,
        manager,
        paystack_valid_request,
    ):
        payload, headers = paystack_valid_request
        call_count = 0

        @manager.on("payment.success")
        async def counter(event: UnifiedEvent) -> None:
            nonlocal call_count
            call_count += 1

        # First delivery — should process
        await manager.process("paystack", payload, headers)
        assert call_count == 1

        # Second delivery (gateway retry) — should be silently deduplicated
        await manager.process("paystack", payload, headers)
        assert call_count == 1  # still 1, not 2

    async def test_duplicate_returns_without_error(
        self,
        manager,
        paystack_valid_request,
    ):
        """A duplicate delivery must not raise — gateway expects 200."""
        payload, headers = paystack_valid_request

        await manager.process("paystack", payload, headers)
        # This must not raise any exception
        await manager.process("paystack", payload, headers)


# ---------------------------------------------------------------------------
# Signature failure
# ---------------------------------------------------------------------------


class TestSignatureFailure:
    async def test_invalid_paystack_signature_raises(
        self,
        manager,
        paystack_charge_success_payload,
    ):
        payload = json.dumps(paystack_charge_success_payload).encode()
        bad_headers = {"x-paystack-signature": "invalidsig", "content-type": "application/json"}

        with pytest.raises(SignatureVerificationError):
            await manager.process("paystack", payload, bad_headers)

    async def test_missing_signature_header_raises(
        self,
        manager,
        paystack_charge_success_payload,
    ):
        payload = json.dumps(paystack_charge_success_payload).encode()
        with pytest.raises(SignatureVerificationError):
            await manager.process("paystack", payload, {})

    async def test_handler_not_invoked_after_signature_failure(
        self,
        manager,
        paystack_charge_success_payload,
    ):
        payload = json.dumps(paystack_charge_success_payload).encode()
        bad_headers = {"x-paystack-signature": "bad"}
        called = False

        @manager.on("payment.success")
        async def h(event: UnifiedEvent) -> None:
            nonlocal called
            called = True

        with pytest.raises(SignatureVerificationError):
            await manager.process("paystack", payload, bad_headers)

        assert called is False

    async def test_invalid_flutterwave_hash_raises(
        self,
        manager,
        flutterwave_charge_success_payload,
    ):
        payload = json.dumps(flutterwave_charge_success_payload).encode()
        bad_headers = {"verif-hash": "wrong-hash"}
        with pytest.raises(SignatureVerificationError):
            await manager.process("flutterwave", payload, bad_headers)


# ---------------------------------------------------------------------------
# Unknown provider
# ---------------------------------------------------------------------------


class TestUnknownProvider:
    async def test_unknown_provider_string_raises(
        self,
        manager,
        paystack_valid_request,
    ):
        payload, headers = paystack_valid_request
        with pytest.raises(UnknownProviderError):
            await manager.process("stripe", payload, headers)


# ---------------------------------------------------------------------------
# @manager.on decorator
# ---------------------------------------------------------------------------


class TestManagerOnDecorator:
    def test_invalid_event_type_string_raises(self, manager):
        from payloadone.exceptions import MisconfigurationError

        with pytest.raises(MisconfigurationError, match="not a valid EventType"):
            @manager.on("not.a.real.event")
            async def h(event: UnifiedEvent) -> None:
                pass

    def test_enum_value_accepted(self, manager):
        """Registering with an EventType enum should not raise."""
        @manager.on(EventType.TRANSFER_SUCCESS)
        async def h(event: UnifiedEvent) -> None:
            pass


# ---------------------------------------------------------------------------
# Framework adapter: FastAPI header extraction
# ---------------------------------------------------------------------------


class TestFastAPIAdapter:
    async def test_process_webhook_helper(self, manager, paystack_valid_request):
        """FastAPI process_webhook helper returns 200 on valid request."""
        try:
            from fastapi import FastAPI, Request
            from fastapi.testclient import TestClient

            from payloadone.adapters.fastapi import install_exception_handlers, process_webhook

            _manager = manager
            app = FastAPI()
            install_exception_handlers(app)

            payload_bytes, headers = paystack_valid_request

            @app.post("/webhooks/{provider}")
            async def webhook(provider: str, request: Request):
                return await process_webhook(_manager, provider, request)

            client = TestClient(app, raise_server_exceptions=False)
            response = client.post(
                "/webhooks/paystack",
                content=payload_bytes,
                headers=headers,
            )
            assert response.status_code == 200

        except ImportError:
            pytest.skip("fastapi not installed")

    async def test_invalid_signature_returns_401(self, manager, paystack_charge_success_payload):
        """FastAPI adapter maps SignatureVerificationError to 401."""
        try:
            from fastapi import FastAPI, Request
            from fastapi.testclient import TestClient

            from payloadone.adapters.fastapi import install_exception_handlers, process_webhook

            _manager = manager
            app = FastAPI()
            install_exception_handlers(app)

            payload_bytes = json.dumps(paystack_charge_success_payload).encode()
            bad_headers = {"x-paystack-signature": "bad", "content-type": "application/json"}

            @app.post("/webhooks/{provider}")
            async def webhook(provider: str, request: Request):
                return await process_webhook(_manager, provider, request)

            client = TestClient(app, raise_server_exceptions=False)
            response = client.post(
                "/webhooks/paystack",
                content=payload_bytes,
                headers=bad_headers,
            )
            assert response.status_code == 401

        except ImportError:
            pytest.skip("fastapi not installed")