"""
PostgreSQL-backed idempotency ledger.

Uses ``INSERT ... ON CONFLICT DO NOTHING`` to atomically detect and
prevent duplicate processing of the same webhook reference.

Requires the ``asyncpg`` package: pip install payloadone[postgres]

Table DDL (run once during application setup):

    CREATE TABLE IF NOT EXISTS payloadone_idempotency (
        provider        TEXT        NOT NULL,
        reference       TEXT        NOT NULL,
        processed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY (provider, reference)
    );
"""

from datetime import UTC, datetime

from ..exceptions import IdempotencyBackendError
from ..interfaces.idempotency import BaseIdempotencyBackend

try:
    import asyncpg  # type: ignore[import]
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "The PostgreSQL idempotency backend requires the 'asyncpg' package. "
        "Install it with: pip install payloadone[postgres]"
    ) from exc

_INSERT_SQL = """
    INSERT INTO payloadone_idempotency (provider, reference, processed_at)
    VALUES ($1, $2, $3)
    ON CONFLICT (provider, reference) DO NOTHING
    RETURNING reference
"""

_CLEANUP_SQL = """
    DELETE FROM payloadone_idempotency
    WHERE processed_at < NOW() - INTERVAL '1 second' * $1
"""


class PostgresIdempotencyBackend(BaseIdempotencyBackend):
    """
    Idempotency backend backed by PostgreSQL.

    Atomicity guarantee: ``INSERT ... ON CONFLICT DO NOTHING RETURNING``
    is a single atomic statement. If two concurrent requests race to insert
    the same (provider, reference) pair, exactly one INSERT succeeds and
    returns a row; the other returns no row — reliably identifying the
    second as a duplicate.

    Connection management: this class accepts an already-initialised
    ``asyncpg.Pool``. Lifecycle management (pool creation and closure)
    is the caller's responsibility.
    """

    def __init__(self, pool: "asyncpg.Pool", ttl_seconds: int = 86400) -> None:
        """
        Args:
            pool: An active ``asyncpg`` connection pool.
            ttl_seconds: Retention period for processed references.
                         Used only during explicit ``cleanup()`` calls;
                         PostgreSQL does not expire rows automatically.
        """
        self._pool = pool
        self._ttl = ttl_seconds

    @classmethod
    async def from_dsn(
        cls,
        dsn: str,
        ttl_seconds: int = 86400,
        **pool_kwargs: object,
    ) -> "PostgresIdempotencyBackend":
        """
        Convenience factory: create a connection pool from a DSN string.

        Args:
            dsn: PostgreSQL DSN, e.g. 'postgresql://user:pass@host/db'.
            ttl_seconds: Retention period for processed references.
            **pool_kwargs: Additional keyword arguments forwarded to
                           ``asyncpg.create_pool``.

        Returns:
            A fully initialised ``PostgresIdempotencyBackend``.
        """
        pool = await asyncpg.create_pool(dsn, **pool_kwargs)
        return cls(pool=pool, ttl_seconds=ttl_seconds)

    async def is_duplicate(self, reference: str, provider: str) -> bool:
        """
        Atomically insert and check for a duplicate reference.

        Returns:
            ``True`` if the reference already existed (duplicate),
            ``False`` if this is the first occurrence.

        Raises:
            IdempotencyBackendError: If the database operation fails.
        """
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    _INSERT_SQL,
                    provider,
                    reference,
                    datetime.now(UTC),
                )
                # INSERT returned a row → new record, not a duplicate.
                # INSERT returned None → ON CONFLICT fired → duplicate.
                return row is None
        except Exception as exc:
            raise IdempotencyBackendError(
                f"PostgreSQL idempotency check failed for reference '{reference}': {exc}"
            ) from exc

    async def mark_processed(self, reference: str, provider: str) -> None:
        """
        No-op for the PostgreSQL backend.

        The atomic INSERT in ``is_duplicate`` already persists the record.
        No further write is required.
        """

    async def cleanup(self) -> None:
        """
        Delete expired idempotency records older than ``ttl_seconds``.

        PostgreSQL does not expire rows automatically. Call this periodically
        (e.g. via a cron job or background task) to prevent unbounded growth.
        """
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(_CLEANUP_SQL, self._ttl)
        except Exception as exc:
            raise IdempotencyBackendError(
                f"PostgreSQL idempotency cleanup failed: {exc}"
            ) from exc

    async def close(self) -> None:
        """Close the underlying connection pool."""
        await self._pool.close()