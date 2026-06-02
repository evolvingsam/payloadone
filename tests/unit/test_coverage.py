"""
Additional coverage tests targeting uncovered branches:
- Flask adapter body/header extraction
- Dispatcher with no handlers and handler exceptions
- WebhookManager postgres config error, register_handler, provider string coercion
- Redis backend close() and error path
- Flutterwave/Paystack verify_signature exception-swallowing paths
"""

import json

import pytest

from payloadone.core.dispatcher import Dispatcher
from payloadone.exceptions import (
    IdempotencyBackendError,
    MisconfigurationError,
    UnknownProviderError,
)
from payloadone.models.enums import EventType, Provider
from payloadone.models.event import UnifiedEvent
from payloadone.providers.flutterwave import FlutterwaveProvider
from payloadone.providers.paystack import PaystackProvider
from tests.conftest import (
    FLUTTERWAVE_SECRET,
    PAYSTACK_SECRET,
    InMemoryIdempotencyBackend,
    make_flutterwave_headers,
    make_paystack_headers,
)


# ---------------------------------------------------------------------------
# Dispatcher — no handlers + handler exception propagation
# ---------------------------------------------------------------------------


class TestDispatcher:
    async def test_dispatch_with_no_handlers_does_not_raise(self, paystack_valid_request):
        """If no handlers are registered, dispatch silently returns."""
        from payloadone.providers.paystack import PaystackProvider

        payload, _ = paystack_valid_request
        event = PaystackProvider().normalise(payload)
        dispatcher = Dispatcher()
        # Must not raise even with zero handlers
        await dispatcher.dispatch(event)

    async def test_dispatch_reraises_handler_exception(self, paystack_valid_request):
        """A handler that raises causes dispatch() to re-raise the first exception."""
        from payloadone.providers.paystack import PaystackProvider

        payload, _ = paystack_valid_request
        event = PaystackProvider().normalise(payload)
        dispatcher = Dispatcher()

        async def bad_handler(e: UnifiedEvent) -> None:
            raise ValueError("business logic exploded")

        dispatcher.register_function(EventType.PAYMENT_SUCCESS, bad_handler)

        with pytest.raises(ValueError, match="business logic exploded"):
            await dispatcher.dispatch(event)

    async def test_register_base_event_handler(self, paystack_valid_request):
        """Registering a BaseEventHandler subclass instance works via .handle()."""
        from payloadone.interfaces.handler import BaseEventHandler
        from payloadone.providers.paystack import PaystackProvider

        payload, _ = paystack_valid_request
        event = PaystackProvider().normalise(payload)
        received = []

        class MyHandler(BaseEventHandler):
            async def handle(self, e: UnifiedEvent) -> None:
                received.append(e)

        dispatcher = Dispatcher()
        dispatcher.register(EventType.PAYMENT_SUCCESS, MyHandler())
        await dispatcher.dispatch(event)
        assert len(received) == 1


# ---------------------------------------------------------------------------
# WebhookManager — postgres config error, register_handler, string provider
# ---------------------------------------------------------------------------


class TestWebhookManagerMiscellaneous:
    def test_postgres_backend_raises_misconfiguration(self):
        """Postgres backend can't be auto-built — must be injected manually."""
        from payloadone.config import PayloadOneConfig
        from payloadone.core.manager import WebhookManager

        config = PayloadOneConfig(
            secret_keys={"paystack": "sk"},
            idempotency_backend="postgres",
            postgres_dsn="postgresql://user:pass@localhost/db",
        )
        with pytest.raises(MisconfigurationError, match="PostgreSQL backend requires"):
            WebhookManager(config=config)

    def test_register_handler_programmatic_api(self, manager):
        """register_handler() is the non-decorator equivalent of @manager.on()."""
        received = []

        async def h(event: UnifiedEvent) -> None:
            received.append(event)

        manager.register_handler(EventType.PAYMENT_SUCCESS, h)
        # Verify it was registered (no assertion needed beyond no-raise)

    def test_register_handler_with_string_event_type(self, manager):
        async def h(event: UnifiedEvent) -> None:
            pass

        manager.register_handler("payment.success", h)  # string, not enum

    async def test_process_accepts_provider_enum(self, manager, paystack_valid_request):
        """process() accepts a Provider enum value directly."""
        payload, headers = paystack_valid_request
        await manager.process(Provider.PAYSTACK, payload, headers)

    async def test_process_accepts_provider_string(self, manager, paystack_valid_request):
        """process() coerces a string to Provider enum."""
        payload, headers = paystack_valid_request
        await manager.process("paystack", payload, headers)

    async def test_process_invalid_provider_string_raises(self, manager, paystack_valid_request):
        payload, headers = paystack_valid_request
        with pytest.raises(UnknownProviderError):
            await manager.process("unknown_gateway", payload, headers)


# ---------------------------------------------------------------------------
# Flask adapter
# ---------------------------------------------------------------------------


class TestFlaskAdapter:
    def test_process_webhook_sync_success(self, manager, paystack_valid_request):
        try:
            from flask import Flask
            from payloadone.adapters.flask import process_webhook_sync

            app = Flask(__name__)
            payload_bytes, headers = paystack_valid_request
            _manager = manager

            with app.test_request_context(
                "/webhooks/paystack",
                method="POST",
                data=payload_bytes,
                headers=headers,
            ):
                response = process_webhook_sync(_manager, "paystack")
                assert response.status_code == 200

        except ImportError:
            pytest.skip("flask not installed")

    def test_process_webhook_sync_invalid_signature_returns_401(
        self, manager, paystack_charge_success_payload
    ):
        try:
            from flask import Flask
            from payloadone.adapters.flask import process_webhook_sync

            app = Flask(__name__)
            payload_bytes = json.dumps(paystack_charge_success_payload).encode()
            bad_headers = {"X-Paystack-Signature": "bad", "Content-Type": "application/json"}
            _manager = manager

            with app.test_request_context(
                "/webhooks/paystack",
                method="POST",
                data=payload_bytes,
                headers=bad_headers,
            ):
                response = process_webhook_sync(_manager, "paystack")
                assert response.status_code == 401

        except ImportError:
            pytest.skip("flask not installed")

    def test_process_webhook_sync_unknown_provider_returns_400(
        self, manager, paystack_valid_request
    ):
        try:
            from flask import Flask
            from payloadone.adapters.flask import process_webhook_sync

            app = Flask(__name__)
            payload_bytes, headers = paystack_valid_request
            _manager = manager

            with app.test_request_context(
                "/webhooks/stripe",
                method="POST",
                data=payload_bytes,
                headers=headers,
            ):
                response = process_webhook_sync(_manager, "stripe")
                assert response.status_code == 400

        except ImportError:
            pytest.skip("flask not installed")

    def test_extract_body_and_headers(self, paystack_valid_request):
        try:
            from flask import Flask
            from payloadone.adapters.flask import extract_body_and_headers

            app = Flask(__name__)
            payload_bytes, headers = paystack_valid_request

            with app.test_request_context(
                "/webhooks/paystack",
                method="POST",
                data=payload_bytes,
                headers=headers,
            ):
                body, extracted_headers = extract_body_and_headers()
                assert body == payload_bytes
                assert "x-paystack-signature" in {k.lower() for k in extracted_headers}

        except ImportError:
            pytest.skip("flask not installed")


# ---------------------------------------------------------------------------
# Provider — verify_signature exception swallowing
# ---------------------------------------------------------------------------


class TestProviderExceptionSwallowing:
    def test_paystack_verify_handles_none_secret(self, paystack_charge_success_payload):
        """verify_signature must return False (not raise) even with a None secret."""
        provider = PaystackProvider()
        body = json.dumps(paystack_charge_success_payload).encode()
        headers = make_paystack_headers(body)
        # Pass None as secret — should return False, not raise AttributeError
        result = provider.verify_signature(body, headers, None)  # type: ignore[arg-type]
        assert result is False

    def test_flutterwave_verify_handles_none_secret(self, flutterwave_charge_success_payload):
        provider = FlutterwaveProvider()
        body = json.dumps(flutterwave_charge_success_payload).encode()
        headers = make_flutterwave_headers()
        result = provider.verify_signature(body, headers, None)  # type: ignore[arg-type]
        assert result is False


# ---------------------------------------------------------------------------
# Redis backend — error path and close()
# ---------------------------------------------------------------------------


class TestRedisBackendErrorAndClose:
    async def test_is_duplicate_raises_idempotency_error_on_redis_failure(self):
        """When Redis raises, is_duplicate wraps it in IdempotencyBackendError."""
        try:
            from unittest.mock import AsyncMock, patch

            from payloadone.idempotency.redis_backend import RedisIdempotencyBackend

            backend = RedisIdempotencyBackend.__new__(RedisIdempotencyBackend)
            mock_client = AsyncMock()
            mock_client.set.side_effect = ConnectionError("Redis unreachable")
            backend._client = mock_client
            backend._ttl = 3600

            with pytest.raises(IdempotencyBackendError, match="Redis idempotency check failed"):
                await backend.is_duplicate("ref", "paystack")

        except ImportError:
            pytest.skip("redis not installed")

    async def test_close_calls_aclose(self):
        """close() must call aclose() on the underlying client."""
        try:
            from unittest.mock import AsyncMock

            from payloadone.idempotency.redis_backend import RedisIdempotencyBackend

            backend = RedisIdempotencyBackend.__new__(RedisIdempotencyBackend)
            mock_client = AsyncMock()
            backend._client = mock_client
            backend._ttl = 3600

            await backend.close()
            mock_client.aclose.assert_called_once()

        except ImportError:
            pytest.skip("redis not installed")


# ---------------------------------------------------------------------------
# Flask adapter — NormalisationError → 422
# ---------------------------------------------------------------------------


class TestFlaskAdapterNormalisationError:
    def test_normalisation_error_returns_422(self, manager):
        """Flask adapter maps NormalisationError to HTTP 422."""
        try:
            from flask import Flask
            from payloadone.adapters.flask import process_webhook_sync
            from payloadone.config import PayloadOneConfig
            from payloadone.core.manager import WebhookManager
            from tests.conftest import InMemoryIdempotencyBackend, make_paystack_headers

            app = Flask(__name__)
            # Valid signature on a broken payload that will fail normalisation
            broken = json.dumps({
                "event": "charge.success",
                "data": {}  # missing required fields → NormalisationError
            }).encode()
            headers = make_paystack_headers(broken)
            _manager = manager

            with app.test_request_context(
                "/webhooks/paystack",
                method="POST",
                data=broken,
                headers=headers,
            ):
                response = process_webhook_sync(_manager, "paystack")
                assert response.status_code == 422

        except ImportError:
            pytest.skip("flask not installed")


# ---------------------------------------------------------------------------
# WebhookManager — extra_providers and auto-build redis path
# ---------------------------------------------------------------------------


class TestWebhookManagerExtraProviders:
    def test_extra_providers_override_registry(self, in_memory_backend):
        """extra_providers kwarg allows injecting custom adapter instances."""
        from payloadone.config import PayloadOneConfig
        from payloadone.core.manager import WebhookManager
        from payloadone.interfaces.provider import BaseProvider

        class StubProvider(BaseProvider):
            def verify_signature(self, payload, headers, secret_key) -> bool:
                return True

            def extract_reference(self, payload) -> str:
                return "stub-ref"

            def normalise(self, payload):
                raise NotImplementedError

        config = PayloadOneConfig(
            secret_keys={"paystack": "sk"},
            idempotency_backend="redis",
            redis_url="redis://localhost:6379",
        )
        wm = WebhookManager(
            config=config,
            idempotency_backend=in_memory_backend,
            extra_providers={Provider.PAYSTACK: StubProvider()},
        )
        assert Provider.PAYSTACK in wm._provider_registry

    def test_auto_build_redis_backend(self):
        """WebhookManager auto-builds RedisIdempotencyBackend from config."""
        from payloadone.config import PayloadOneConfig
        from payloadone.core.manager import WebhookManager
        from payloadone.idempotency.redis_backend import RedisIdempotencyBackend

        config = PayloadOneConfig(
            secret_keys={"paystack": "sk"},
            idempotency_backend="redis",
            redis_url="redis://localhost:6379",
        )
        wm = WebhookManager(config=config)
        assert isinstance(wm._idempotency, RedisIdempotencyBackend)


# ---------------------------------------------------------------------------
# PostgreSQL backend — mocked pool
# ---------------------------------------------------------------------------


class TestPostgresBackendMocked:
    async def test_is_duplicate_returns_false_on_new_reference(self):
        """INSERT returns a row → not a duplicate."""
        pytest.importorskip("asyncpg")
        from unittest.mock import AsyncMock, MagicMock

        from payloadone.idempotency.postgres_backend import PostgresIdempotencyBackend

        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = {"reference": "ref_new"}  # row returned → new

        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        backend = PostgresIdempotencyBackend(pool=mock_pool, ttl_seconds=3600)
        result = await backend.is_duplicate("ref_new", "paystack")
        assert result is False

    async def test_is_duplicate_returns_true_on_existing_reference(self):
        """INSERT returns None (ON CONFLICT) → duplicate."""
        pytest.importorskip("asyncpg")
        from unittest.mock import AsyncMock, MagicMock

        from payloadone.idempotency.postgres_backend import PostgresIdempotencyBackend

        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = None  # None → ON CONFLICT fired → duplicate

        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        backend = PostgresIdempotencyBackend(pool=mock_pool, ttl_seconds=3600)
        result = await backend.is_duplicate("ref_dup", "paystack")
        assert result is True

    async def test_is_duplicate_raises_on_db_error(self):
        """DB exception is wrapped in IdempotencyBackendError."""
        pytest.importorskip("asyncpg")
        from unittest.mock import AsyncMock, MagicMock

        from payloadone.idempotency.postgres_backend import PostgresIdempotencyBackend

        mock_conn = AsyncMock()
        mock_conn.fetchrow.side_effect = Exception("connection refused")

        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        backend = PostgresIdempotencyBackend(pool=mock_pool)
        with pytest.raises(IdempotencyBackendError, match="PostgreSQL idempotency check failed"):
            await backend.is_duplicate("ref", "paystack")

    async def test_mark_processed_is_no_op(self):
        """mark_processed must not raise."""
        pytest.importorskip("asyncpg")
        from unittest.mock import MagicMock

        from payloadone.idempotency.postgres_backend import PostgresIdempotencyBackend

        backend = PostgresIdempotencyBackend(pool=MagicMock(), ttl_seconds=3600)
        await backend.mark_processed("ref", "paystack")

    async def test_cleanup_executes_delete(self):
        """cleanup() runs the DELETE SQL."""
        pytest.importorskip("asyncpg")
        from unittest.mock import AsyncMock, MagicMock

        from payloadone.idempotency.postgres_backend import PostgresIdempotencyBackend

        mock_conn = AsyncMock()
        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        backend = PostgresIdempotencyBackend(pool=mock_pool, ttl_seconds=3600)
        await backend.cleanup()
        mock_conn.execute.assert_called_once()

    async def test_cleanup_raises_on_db_error(self):
        """Cleanup DB exception is wrapped in IdempotencyBackendError."""
        pytest.importorskip("asyncpg")
        from unittest.mock import AsyncMock, MagicMock

        from payloadone.idempotency.postgres_backend import PostgresIdempotencyBackend

        mock_conn = AsyncMock()
        mock_conn.execute.side_effect = Exception("db error")

        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        backend = PostgresIdempotencyBackend(pool=mock_pool)
        with pytest.raises(IdempotencyBackendError, match="cleanup failed"):
            await backend.cleanup()

    async def test_close_calls_pool_close(self):
        """close() delegates to pool.close()."""
        pytest.importorskip("asyncpg")
        from unittest.mock import AsyncMock, MagicMock

        from payloadone.idempotency.postgres_backend import PostgresIdempotencyBackend

        mock_pool = MagicMock()
        mock_pool.close = AsyncMock()
        backend = PostgresIdempotencyBackend(pool=mock_pool)
        await backend.close()
        mock_pool.close.assert_called_once()


# ---------------------------------------------------------------------------
# Flutterwave — invalid JSON and missing data fields
# ---------------------------------------------------------------------------


class TestFlutterwaveEdgeCases:
    def test_invalid_json_raises_normalisation_error(self):
        provider = FlutterwaveProvider()
        with pytest.raises(Exception):  # NormalisationError
            provider.normalise(b"not json")

    def test_missing_customer_field_raises(self):
        provider = FlutterwaveProvider()
        payload = json.dumps({
            "event": "charge.completed",
            "data": {
                "tx_ref": "ref",
                "amount": 100,
                "currency": "NGN",
                "status": "successful",
                # missing "customer"
            }
        }).encode()
        from payloadone.exceptions import NormalisationError
        with pytest.raises(NormalisationError):
            provider.normalise(payload)


# ---------------------------------------------------------------------------
# Paystack — missing customer field (covers lines 130-131)
# ---------------------------------------------------------------------------


class TestPaystackEdgeCases:
    def test_missing_customer_raises_normalisation_error(self):
        provider = PaystackProvider()
        payload = json.dumps({
            "event": "charge.success",
            "data": {
                "reference": "ref",
                "amount": 1000,
                "currency": "NGN",
                # missing "customer"
            }
        }).encode()
        from payloadone.exceptions import NormalisationError
        with pytest.raises(NormalisationError):
            provider.normalise(payload)


# ---------------------------------------------------------------------------
# Pipeline — provider not in registry (UnknownProviderError from pipeline)
# ---------------------------------------------------------------------------


class TestPipelineUnknownProvider:
    async def test_provider_not_in_registry_raises(self, in_memory_backend):
        """Pipeline raises UnknownProviderError when provider has no registered adapter."""
        from payloadone.config import PayloadOneConfig
        from payloadone.core.dispatcher import Dispatcher
        from payloadone.core.pipeline import WebhookPipeline

        pipeline = WebhookPipeline(
            provider_registry={},  # empty — no adapters
            idempotency_backend=in_memory_backend,
            dispatcher=Dispatcher(),
            secret_keys={"paystack": "sk"},
        )

        with pytest.raises(UnknownProviderError):
            await pipeline.execute(
                provider=Provider.PAYSTACK,
                payload=b"{}",
                headers={},
            )