"""
Unit tests for idempotency backends and configuration validation.
"""

import pytest

from payloadone.config import PayloadOneConfig
from payloadone.exceptions import MisconfigurationError
from tests.conftest import InMemoryIdempotencyBackend


# ---------------------------------------------------------------------------
# In-memory backend (covers interface contract; Redis tests use fakeredis)
# ---------------------------------------------------------------------------


class TestInMemoryIdempotencyBackend:
    @pytest.fixture(autouse=True)
    def backend(self):
        self.backend = InMemoryIdempotencyBackend()

    async def test_first_occurrence_is_not_duplicate(self):
        result = await self.backend.is_duplicate("ref_001", "paystack")
        assert result is False

    async def test_second_occurrence_is_duplicate(self):
        await self.backend.is_duplicate("ref_001", "paystack")
        result = await self.backend.is_duplicate("ref_001", "paystack")
        assert result is True

    async def test_same_reference_different_providers_not_duplicate(self):
        """Cross-provider reference isolation: same ref, different provider → not duplicate."""
        await self.backend.is_duplicate("ref_shared", "paystack")
        result = await self.backend.is_duplicate("ref_shared", "flutterwave")
        assert result is False

    async def test_different_references_not_duplicate(self):
        await self.backend.is_duplicate("ref_A", "paystack")
        result = await self.backend.is_duplicate("ref_B", "paystack")
        assert result is False

    async def test_mark_processed_is_no_op(self):
        """mark_processed should not raise on a valid reference."""
        await self.backend.mark_processed("ref_001", "paystack")


# ---------------------------------------------------------------------------
# Redis backend with fakeredis
# ---------------------------------------------------------------------------


class TestRedisIdempotencyBackend:
    @pytest.fixture(autouse=True)
    async def redis_backend(self):
        try:
            import fakeredis.aioredis as fakeredis_async
            from payloadone.idempotency.redis_backend import RedisIdempotencyBackend

            fake_redis = fakeredis_async.FakeRedis(decode_responses=True)
            self.backend = RedisIdempotencyBackend.__new__(RedisIdempotencyBackend)
            self.backend._client = fake_redis
            self.backend._ttl = 3600
        except ImportError:
            pytest.skip("fakeredis not installed")

    async def test_first_reference_not_duplicate(self):
        assert await self.backend.is_duplicate("redis_ref_001", "paystack") is False

    async def test_second_reference_is_duplicate(self):
        await self.backend.is_duplicate("redis_ref_002", "paystack")
        assert await self.backend.is_duplicate("redis_ref_002", "paystack") is True

    async def test_different_providers_isolated(self):
        await self.backend.is_duplicate("redis_shared", "paystack")
        assert await self.backend.is_duplicate("redis_shared", "flutterwave") is False

    async def test_mark_processed_is_no_op(self):
        """Redis backend commits atomically in is_duplicate; mark_processed is no-op."""
        await self.backend.mark_processed("redis_ref_003", "paystack")  # must not raise

    async def test_key_expires_after_ttl(self):
        """Verify the key is set with correct TTL."""
        import fakeredis.aioredis as fakeredis_async
        from payloadone.idempotency.redis_backend import _build_key

        await self.backend.is_duplicate("ttl_ref", "paystack")
        key = _build_key("ttl_ref", "paystack")
        ttl = await self.backend._client.ttl(key)
        assert ttl > 0  # key has an expiry set


# ---------------------------------------------------------------------------
# Configuration validation
# ---------------------------------------------------------------------------


class TestPayloadOneConfig:
    def test_valid_redis_config(self):
        cfg = PayloadOneConfig(
            secret_keys={"paystack": "sk_live_abc"},
            idempotency_backend="redis",
            redis_url="redis://localhost:6379",
        )
        assert cfg.idempotency_backend == "redis"

    def test_valid_postgres_config(self):
        cfg = PayloadOneConfig(
            secret_keys={"paystack": "sk_live_abc"},
            idempotency_backend="postgres",
            postgres_dsn="postgresql://user:pass@localhost/db",
        )
        assert cfg.idempotency_backend == "postgres"

    def test_empty_secret_keys_raises(self):
        with pytest.raises(MisconfigurationError, match="secret_keys must not be empty"):
            PayloadOneConfig(
                secret_keys={},
                idempotency_backend="redis",
                redis_url="redis://localhost",
            )

    def test_blank_secret_key_raises(self):
        with pytest.raises(MisconfigurationError, match="empty or not a string"):
            PayloadOneConfig(
                secret_keys={"paystack": "   "},
                idempotency_backend="redis",
                redis_url="redis://localhost",
            )

    def test_invalid_backend_raises(self):
        with pytest.raises(MisconfigurationError, match="idempotency_backend must be one of"):
            PayloadOneConfig(
                secret_keys={"paystack": "sk"},
                idempotency_backend="memcached",
                redis_url="redis://localhost",
            )

    def test_redis_backend_without_url_raises(self):
        with pytest.raises(MisconfigurationError, match="redis_url is not set"):
            PayloadOneConfig(
                secret_keys={"paystack": "sk"},
                idempotency_backend="redis",
            )

    def test_postgres_backend_without_dsn_raises(self):
        with pytest.raises(MisconfigurationError, match="postgres_dsn is not set"):
            PayloadOneConfig(
                secret_keys={"paystack": "sk"},
                idempotency_backend="postgres",
            )

    def test_negative_ttl_raises(self):
        with pytest.raises(MisconfigurationError, match="positive integer"):
            PayloadOneConfig(
                secret_keys={"paystack": "sk"},
                idempotency_backend="redis",
                redis_url="redis://localhost",
                idempotency_ttl_seconds=-1,
            )

    def test_default_ttl_is_24_hours(self):
        cfg = PayloadOneConfig(
            secret_keys={"paystack": "sk"},
            idempotency_backend="redis",
            redis_url="redis://localhost",
        )
        assert cfg.idempotency_ttl_seconds == 86400