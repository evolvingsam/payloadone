"""Enumerations for provider identifiers and normalised event types."""

from enum import Enum


class Provider(str, Enum):
    """Supported webhook provider identifiers."""

    PAYSTACK = "paystack"
    FLUTTERWAVE = "flutterwave"


class EventType(str, Enum):
    """Normalised event types emitted by PayloadOne regardless of provider."""

    PAYMENT_SUCCESS = "payment.success"
    PAYMENT_FAILED = "payment.failed"
    REFUND_PROCESSED = "refund.processed"
    CHARGE_DISPUTE_CREATE = "charge.dispute.create"
    TRANSFER_SUCCESS = "transfer.success"
    TRANSFER_FAILED = "transfer.failed"