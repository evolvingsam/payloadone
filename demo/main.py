import hashlib
import hmac
import logging
import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from payloadone import PayloadOneConfig, WebhookManager
from payloadone.adapters.fastapi import install_exception_handlers, process_webhook
from payloadone.models.event import UnifiedEvent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="PayloadOne Demo",
    description="Live demo of the PayloadOne webhook SDK.",
)

config = PayloadOneConfig(
    secret_keys={
        "paystack": os.environ["PAYSTACK_SECRET_KEY"],
        "flutterwave": os.environ["FLUTTERWAVE_SECRET_HASH"],
    },
    idempotency_backend="redis",
    redis_url=os.environ["REDIS_URL"],
    idempotency_ttl_seconds=3600,
)

manager = WebhookManager(config=config)
install_exception_handlers(app)

# ── Pre-registered demo handlers ──────────────────────────────────────────────

received_events: list[dict] = []  # in-memory log, visible via /events


@manager.on("payment.success")
async def on_payment_success(event: UnifiedEvent) -> None:
    logger.info("payment.success — ref=%s amount=%s", event.reference, event.amount_in_lowest_unit)
    received_events.append(
        {
            "event_type": event.event_type.value,
            "provider": event.provider.value,
            "reference": event.reference,
            "amount_in_lowest_unit": event.amount_in_lowest_unit,
            "currency": event.currency,
            "customer_email": event.customer_email,
        }
    )


@manager.on("payment.failed")
async def on_payment_failed(event: UnifiedEvent) -> None:
    logger.warning("payment.failed — ref=%s", event.reference)
    received_events.append(
        {
            "event_type": event.event_type.value,
            "provider": event.provider.value,
            "reference": event.reference,
        }
    )


@manager.on("transfer.success")
async def on_transfer_success(event: UnifiedEvent) -> None:
    logger.info("transfer.success — ref=%s", event.reference)
    received_events.append(
        {
            "event_type": event.event_type.value,
            "provider": event.provider.value,
            "reference": event.reference,
        }
    )


# ── Routes ────────────────────────────────────────────────────────────────────


@app.post("/webhooks/{provider}")
async def webhook(provider: str, request: Request):
    return await process_webhook(manager, provider, request)


@app.get("/events")
async def list_events():
    """Returns the last 50 events received in this session."""
    return JSONResponse({"events": received_events[-50:]})


@app.delete("/events")
async def clear_events():
    """Clear the in-memory event log."""
    received_events.clear()
    return JSONResponse({"status": "cleared"})


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/dev/sign/paystack")
async def sign_paystack(request: Request):
    """
    Test helper — signs a payload with the demo's Paystack key.
    Returns the x-paystack-signature header value.
    Only available in demo mode.
    """
    body = await request.body()
    sig = hmac.new(
        os.environ["PAYSTACK_SECRET_KEY"].encode(),
        msg=body,
        digestmod=hashlib.sha512,
    ).hexdigest()
    return {"x-paystack-signature": sig}


@app.get("/")
async def root():
    return {
        "name": "PayloadOne demo",
        "webhook_endpoints": {
            "paystack": "/webhooks/paystack",
            "flutterwave": "/webhooks/flutterwave",
        },
        "view_events": "/events",
        "docs": "/docs",
    }


if __name__ == "__main__":
    import os

    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
