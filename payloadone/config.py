"""
Configuration model for PayloadOne.

All configuration is injected at initialisation. Nothing is read from
environment variables implicitly — the caller controls the config surface.
"""

from dataclasses import dataclass, field

from .exceptions import MisconfigurationError


@dataclass
class PayloadOneConfig:
    """
    Immutable configuration for a WebhookManager instance.

    Args:
        secret_keys: Mapping of provider name → secret key/hash.
            Must contain keys for every provider you intend to receive webhooks from.
            Example: {"paystack": "sk_live_...", "flutterwave": "FLWSECK_TEST-..."}

        idempotency_backend: Storage backend for the idempotency ledger.
            Accepted values: "redis" | "postgres". Defaults to "redis".

        redis_url: Redis connection URL. Required when idempotency_backend is "redis".
            Example: "redis://localhost:6379/0"

        postgres_dsn: PostgreSQL DSN. Required when idempotency_backend is "postgres".
            Example: "postgresql://user:pass@localhost/dbname"

        idempotency_ttl_seconds: How long to retain a processed reference in the ledger
            before it can be re-processed. Defaults to 86400 (24 hours).
    """

    secret_keys: dict[str, str]
    idempotency_backend: str = "redis"
    redis_url: str | None = None
    postgres_dsn: str | None = None
    idempotency_ttl_seconds: int = field(default=86400)

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        """
        Eagerly validate configuration at construction time.

        Raises MisconfigurationError with a precise message on any violation
        so the developer knows exactly what to fix before the server starts.
        """
        if not self.secret_keys:
            raise MisconfigurationError(
                "PayloadOneConfig.secret_keys must not be empty. "
                "Provide at least one provider → secret mapping, "
                "e.g. {'paystack': 'sk_live_...'}."
            )

        for provider, key in self.secret_keys.items():
            if not isinstance(key, str) or not key.strip():
                raise MisconfigurationError(
                    f"Secret key for provider '{provider}' is empty or not a string. "
                    "All secret keys must be non-empty strings."
                )

        valid_backends = {"redis", "postgres"}
        if self.idempotency_backend not in valid_backends:
            raise MisconfigurationError(
                f"idempotency_backend must be one of {valid_backends!r}, "
                f"got '{self.idempotency_backend}'."
            )

        if self.idempotency_backend == "redis" and not self.redis_url:
            raise MisconfigurationError(
                "idempotency_backend is 'redis' but redis_url is not set. "
                "Provide a Redis connection URL, e.g. 'redis://localhost:6379/0'."
            )

        if self.idempotency_backend == "postgres" and not self.postgres_dsn:
            raise MisconfigurationError(
                "idempotency_backend is 'postgres' but postgres_dsn is not set. "
                "Provide a PostgreSQL DSN, e.g. 'postgresql://user:pass@host/db'."
            )

        if self.idempotency_ttl_seconds <= 0:
            raise MisconfigurationError(
                f"idempotency_ttl_seconds must be a positive integer, "
                f"got {self.idempotency_ttl_seconds}."
            )
