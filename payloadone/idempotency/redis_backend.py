"""
Redis-backed idempotency ledger.

Uses atomic SET NX (set-if-not-exists) with TTL to guarantee that
concurrent delivery of the same webhook reference cannot produce
a double-process race condition.
"""

from typing import cast

from ..exceptions import IdempotencyBackendError
from ..interfaces.idempotency import BaseIdempotencyBackend

try:
    import redis.asyncio as aioredis
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "The Redis idempotency backend requires the 'redis' package. "
        "Install it with: pip install payloadone[redis]"
    ) from exc


def _build_key(reference: str, provider: str) -> str:
    """
    Construct a namespaced Redis key for a given reference and provider.

    Scoping by provider prevents cross-provider reference collisions
    where two different gateways may legitimately reuse the same
    reference string.
    """
    return f"payloadone:idempotency:{provider}:{reference}"


class RedisIdempotencyBackend(BaseIdempotencyBackend):
    """
    Idempotency backend backed by Redis.

    Atomicity guarantee: ``SET key value NX EX ttl`` is a single atomic
    Redis command. If two concurrent requests race to process the same
    reference, exactly one will receive a successful SET (returning True
    from the Redis call), and the other will receive None — reliably
    identifying the second as a duplicate.
    """

    def __init__(self, redis_url: str, ttl_seconds: int = 86400) -> None:
        """
        Args:
            redis_url: Redis connection URL, e.g. 'redis://localhost:6379/0'.
            ttl_seconds: How long a processed reference is retained in Redis
                         before expiry. Defaults to 24 hours.
        """
        self._client: aioredis.Redis = cast(
            aioredis.Redis,
            aioredis.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
            ),
        )
        self._ttl = ttl_seconds

    async def is_duplicate(self, reference: str, provider: str) -> bool:
        """
        Atomically check and reserve a reference in Redis.

        A single ``SET NX EX`` command atomically:
        1. Checks whether the key already exists.
        2. Sets it (with TTL) only if it does not exist.

        Returns:
            ``True`` if the key already existed (duplicate), ``False`` if
            this is the first time the reference has been seen.

        Raises:
            IdempotencyBackendError: If the Redis operation fails.
        """
        key = _build_key(reference, provider)
        try:
            # set() with nx=True returns True on success, None if key existed.
            result = await self._client.set(key, "1", nx=True, ex=self._ttl)
            # result is None → key already existed → duplicate
            return result is None
        except Exception as exc:
            raise IdempotencyBackendError(
                f"Redis idempotency check failed for reference '{reference}': {exc}"
            ) from exc

    async def mark_processed(self, reference: str, provider: str) -> None:
        """
        No-op for the Redis backend.

        The atomic ``SET NX EX`` in ``is_duplicate`` already reserves the key
        with its TTL. There is no separate "commit" step needed; the key
        will expire automatically after ``ttl_seconds``.
        """
        # The reservation was performed atomically in is_duplicate.
        # This method satisfies the interface contract; no further action required.

    async def close(self) -> None:
        """Close the underlying Redis connection pool."""
        await self._client.aclose()
