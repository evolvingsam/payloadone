# PayloadOne

**Secure, normalised, idempotent webhook processing for Paystack and Flutterwave.**

PayloadOne sits between incoming payment webhook requests and your business logic, solving the three most dangerous webhook integration failure modes before a single line of your code runs:

| Problem | PayloadOne's Solution |
|---|---|
| Insecure signature validation | Automatic HMAC-SHA512 (Paystack) and secret-hash (Flutterwave) verification using time-constant comparison |
| Provider payload fragmentation | A single `UnifiedEvent` model regardless of source |
| No idempotency guarantee | An atomic Redis or PostgreSQL ledger that guarantees exactly-once processing |

---
## Live Demo & Docs

Try PayloadOne instantly — no setup or cloning required.

- **Documentation & live testing guide** → https://payloadone-docs-ac0db7a9.quikdb.net
- **Demo API** → https://payloadone-ac0db7a9.quikdb.net
- **Interactive API explorer** → https://payloadone-ac0db7a9.quikdb.net/docs
- **Live event log** → https://payloadone-ac0db7a9.quikdb.net/events

Send a real webhook, watch it get verified, deduplicated, and normalised in seconds.

## Installation

```bash
# With Redis backend (recommended)
pip install "payloadone[redis]"

# With PostgreSQL backend
pip install "payloadone[postgres]"

# With FastAPI integration
pip install "payloadone[redis,fastapi]"

# Everything
pip install "payloadone[all]"
```

Requires Python 3.11+.

---

## Quickstart (FastAPI)

```python
from fastapi import FastAPI, Request
from payloadone import WebhookManager, PayloadOneConfig
from payloadone.models.event import UnifiedEvent
from payloadone.adapters.fastapi import install_exception_handlers, process_webhook

app = FastAPI()

config = PayloadOneConfig(
    secret_keys={
        "paystack": "your-paystack-secret-key",
        "flutterwave": "your-flutterwave-secret-hash",
    },
    idempotency_backend="redis",
    redis_url="redis://localhost:6379",
)

manager = WebhookManager(config=config)
install_exception_handlers(app)   # maps exceptions to HTTP 401 / 400 / 422


@manager.on("payment.success")
async def handle_payment(event: UnifiedEvent) -> None:
    await credit_user_wallet(event.reference, event.amount_in_lowest_unit)


@manager.on("transfer.success")
async def handle_transfer(event: UnifiedEvent) -> None:
    await mark_transfer_complete(event.reference)


@app.post("/webhooks/{provider}")
async def webhook(provider: str, request: Request):
    return await process_webhook(manager, provider, request)
```

Point your Paystack and Flutterwave dashboards at:
```
https://yourapi.com/webhooks/paystack
https://yourapi.com/webhooks/flutterwave
```

---

## Quickstart (Flask)

```python
from flask import Flask
from payloadone import WebhookManager, PayloadOneConfig
from payloadone.adapters.flask import process_webhook_sync

app = Flask(__name__)
manager = WebhookManager(config=config)  # same config as above

@manager.on("payment.success")
async def handle_payment(event):
    await credit_wallet(event.reference, event.amount_in_lowest_unit)

@app.post("/webhooks/<provider>")
def webhook(provider: str):
    return process_webhook_sync(manager, provider)
```

---

## The UnifiedEvent Model

Every verified, deduplicated payload is normalised into a single `UnifiedEvent`:

```python
class UnifiedEvent(BaseModel):
    provider: Provider              # "paystack" | "flutterwave"
    event_type: EventType           # "payment.success" | "payment.failed" | ...
    reference: str                  # Unique transaction reference
    amount_in_lowest_unit: int      # Kobo (NGN) or cents (USD) — always int, never float
    currency: str                   # "NGN" | "USD" | ...
    customer_email: EmailStr
    customer_name: str | None
    metadata: dict[str, Any]        # Passthrough checkout metadata
    raw_payload: dict[str, Any]     # Original unmodified payload
    provider_event_id: str | None   # Provider's own event ID
```

---

## Provider Configuration Reference

### Paystack

| Setting | Value |
|---|---|
| Secret key | Found in Paystack Dashboard → Settings → API Keys |
| Signature algorithm | HMAC-SHA512 |
| Signature header | `x-paystack-signature` |
| Webhook URL | `https://yourapi.com/webhooks/paystack` |

Supported events: `charge.success`, `charge.failed`, `refund.processed`, `transfer.success`, `transfer.failed`

### Flutterwave

| Setting | Value |
|---|---|
| Secret hash | Set in Flutterwave Dashboard → Settings → Webhooks → Secret Hash |
| Verification method | Time-constant header comparison |
| Signature header | `verif-hash` |
| Webhook URL | `https://yourapi.com/webhooks/flutterwave` |

Supported events: `charge.completed` (successful/failed), `transfer.completed` (SUCCESSFUL/FAILED)

---

## Idempotency Backends

### Redis (Recommended)

```python
config = PayloadOneConfig(
    secret_keys={"paystack": "sk_live_..."},
    idempotency_backend="redis",
    redis_url="redis://localhost:6379/0",
    idempotency_ttl_seconds=86400,  # 24 hours
)
```

### PostgreSQL

```python
from payloadone.idempotency.postgres_backend import PostgresIdempotencyBackend

backend = await PostgresIdempotencyBackend.from_dsn(
    dsn="postgresql://user:pass@localhost/mydb",
    ttl_seconds=86400,
)

manager = WebhookManager(config=config, idempotency_backend=backend)
```

Run this DDL once:
```sql
CREATE TABLE IF NOT EXISTS payloadone_idempotency (
    provider        TEXT        NOT NULL,
    reference       TEXT        NOT NULL,
    processed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (provider, reference)
);
```

---

## Event Types

| EventType | Value |
|---|---|
| `EventType.PAYMENT_SUCCESS` | `"payment.success"` |
| `EventType.PAYMENT_FAILED` | `"payment.failed"` |
| `EventType.REFUND_PROCESSED` | `"refund.processed"` |
| `EventType.TRANSFER_SUCCESS` | `"transfer.success"` |
| `EventType.TRANSFER_FAILED` | `"transfer.failed"` |
| `EventType.CHARGE_DISPUTE_CREATE` | `"charge.dispute.create"` |

---

## Running the Tests

```bash
# Install dev dependencies
poetry install --with dev

# Run the full test suite with coverage
poetry run pytest

# Run only unit tests
poetry run pytest tests/unit/

# Run linting
poetry run ruff check payloadone/

# Run type checking
poetry run mypy payloadone/
```

---

## License

MIT