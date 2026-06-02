"""
Unit tests for Paystack and Flutterwave provider adapters.

Covers:
- Valid and invalid signature verification
- Missing signature headers
- Payload normalisation correctness
- Amount lowest-unit conversion
- Raw payload preservation
- Event type mapping
"""

import hashlib
import hmac
import json

import pytest

from payloadone.exceptions import NormalisationError
from payloadone.models.enums import EventType, Provider
from payloadone.providers.flutterwave import FlutterwaveProvider
from payloadone.providers.paystack import PaystackProvider
from tests.conftest import (
    FLUTTERWAVE_SECRET,
    PAYSTACK_SECRET,
    make_flutterwave_headers,
    make_paystack_headers,
)

# ---------------------------------------------------------------------------
# Paystack — Signature Verification
# ---------------------------------------------------------------------------


class TestPaystackSignatureVerification:
    def setup_method(self):
        self.provider = PaystackProvider()

    def test_valid_signature_passes(self, paystack_charge_success_payload):
        body = json.dumps(paystack_charge_success_payload).encode()
        headers = make_paystack_headers(body)
        assert self.provider.verify_signature(body, headers, PAYSTACK_SECRET) is True

    def test_invalid_signature_fails(self, paystack_charge_success_payload):
        body = json.dumps(paystack_charge_success_payload).encode()
        headers = {"x-paystack-signature": "deadbeef" * 16}
        assert self.provider.verify_signature(body, headers, PAYSTACK_SECRET) is False

    def test_missing_signature_header_fails(self, paystack_charge_success_payload):
        body = json.dumps(paystack_charge_success_payload).encode()
        assert self.provider.verify_signature(body, {}, PAYSTACK_SECRET) is False

    def test_wrong_secret_fails(self, paystack_charge_success_payload):
        body = json.dumps(paystack_charge_success_payload).encode()
        headers = make_paystack_headers(body, secret="wrong-secret")
        assert self.provider.verify_signature(body, headers, PAYSTACK_SECRET) is False

    def test_tampered_payload_fails(self, paystack_charge_success_payload):
        body = json.dumps(paystack_charge_success_payload).encode()
        headers = make_paystack_headers(body)
        # Tamper the payload after signing
        tampered = body + b"extra"
        assert self.provider.verify_signature(tampered, headers, PAYSTACK_SECRET) is False

    def test_header_case_insensitive(self, paystack_charge_success_payload):
        """Header lookup must be case-insensitive for framework compatibility."""
        body = json.dumps(paystack_charge_success_payload).encode()
        sig = hmac.new(
            PAYSTACK_SECRET.encode(), msg=body, digestmod=hashlib.sha512
        ).hexdigest()
        headers = {"X-Paystack-Signature": sig}  # different casing
        assert self.provider.verify_signature(body, headers, PAYSTACK_SECRET) is True


# ---------------------------------------------------------------------------
# Paystack — Normalisation
# ---------------------------------------------------------------------------


class TestPaystackNormalisation:
    def setup_method(self):
        self.provider = PaystackProvider()

    def test_charge_success_normalises_correctly(self, paystack_charge_success_payload):
        body = json.dumps(paystack_charge_success_payload).encode()
        event = self.provider.normalise(body)

        assert event.provider == Provider.PAYSTACK
        assert event.event_type == EventType.PAYMENT_SUCCESS
        assert event.reference == "txn_paystack_001"
        assert event.amount_in_lowest_unit == 5000  # already in kobo
        assert event.currency == "NGN"
        assert event.customer_email == "user@example.com"
        assert event.customer_name == "Amaka Okafor"

    def test_charge_failed_maps_to_payment_failed(self, paystack_charge_failed_payload):
        body = json.dumps(paystack_charge_failed_payload).encode()
        event = self.provider.normalise(body)
        assert event.event_type == EventType.PAYMENT_FAILED

    def test_amount_is_integer_not_float(self, paystack_charge_success_payload):
        body = json.dumps(paystack_charge_success_payload).encode()
        event = self.provider.normalise(body)
        assert isinstance(event.amount_in_lowest_unit, int)

    def test_raw_payload_preserved_unmodified(self, paystack_charge_success_payload):
        body = json.dumps(paystack_charge_success_payload).encode()
        event = self.provider.normalise(body)
        assert event.raw_payload == paystack_charge_success_payload

    def test_metadata_extracted(self, paystack_charge_success_payload):
        body = json.dumps(paystack_charge_success_payload).encode()
        event = self.provider.normalise(body)
        assert event.metadata == {"order_id": "order_999"}

    def test_missing_reference_raises_normalisation_error(self):
        payload = json.dumps({"event": "charge.success", "data": {}}).encode()
        with pytest.raises(NormalisationError, match="reference"):
            self.provider.extract_reference(payload)

    def test_unknown_event_type_raises_normalisation_error(self):
        payload = {
            "event": "unknown.event",
            "data": {
                "reference": "ref",
                "amount": 100,
                "currency": "NGN",
                "customer": {"email": "a@b.com"},
            },
        }
        with pytest.raises(NormalisationError, match="no normalised mapping"):
            self.provider.normalise(json.dumps(payload).encode())

    def test_invalid_json_raises_normalisation_error(self):
        with pytest.raises(NormalisationError, match="not valid JSON"):
            self.provider.normalise(b"not json at all")


# ---------------------------------------------------------------------------
# Flutterwave — Signature Verification
# ---------------------------------------------------------------------------


class TestFlutterwaveSignatureVerification:
    def setup_method(self):
        self.provider = FlutterwaveProvider()

    def test_valid_hash_passes(self, flutterwave_charge_success_payload):
        body = json.dumps(flutterwave_charge_success_payload).encode()
        headers = make_flutterwave_headers()
        assert self.provider.verify_signature(body, headers, FLUTTERWAVE_SECRET) is True

    def test_invalid_hash_fails(self, flutterwave_charge_success_payload):
        body = json.dumps(flutterwave_charge_success_payload).encode()
        headers = {"verif-hash": "wrong-hash"}
        assert self.provider.verify_signature(body, headers, FLUTTERWAVE_SECRET) is False

    def test_missing_header_fails(self, flutterwave_charge_success_payload):
        body = json.dumps(flutterwave_charge_success_payload).encode()
        assert self.provider.verify_signature(body, {}, FLUTTERWAVE_SECRET) is False

    def test_header_case_insensitive(self, flutterwave_charge_success_payload):
        body = json.dumps(flutterwave_charge_success_payload).encode()
        headers = {"Verif-Hash": FLUTTERWAVE_SECRET}  # different casing
        assert self.provider.verify_signature(body, headers, FLUTTERWAVE_SECRET) is True


# ---------------------------------------------------------------------------
# Flutterwave — Normalisation
# ---------------------------------------------------------------------------


class TestFlutterwaveNormalisation:
    def setup_method(self):
        self.provider = FlutterwaveProvider()

    def test_charge_success_normalises_correctly(self, flutterwave_charge_success_payload):
        body = json.dumps(flutterwave_charge_success_payload).encode()
        event = self.provider.normalise(body)

        assert event.provider == Provider.FLUTTERWAVE
        assert event.event_type == EventType.PAYMENT_SUCCESS
        assert event.reference == "txn_flw_001"
        assert event.currency == "NGN"
        assert event.customer_email == "customer@example.com"
        assert event.customer_name == "Ngozi Adeyemi"

    def test_amount_converted_to_kobo(self, flutterwave_charge_success_payload):
        """50.00 NGN * 100 = 5000 kobo as integer."""
        body = json.dumps(flutterwave_charge_success_payload).encode()
        event = self.provider.normalise(body)
        assert event.amount_in_lowest_unit == 5000
        assert isinstance(event.amount_in_lowest_unit, int)

    def test_amount_conversion_avoids_float_error(self):
        """Floating-point amounts are multiplied by 100 and rounded to int."""
        payload = {
            "event": "charge.completed",
            "data": {
                "id": 1,
                "tx_ref": "ref",
                # 99.99 NGN → 9999 kobo (avoids naive int() truncation of 9998.999...)
                "amount": 99.99,
                "currency": "NGN",
                "status": "successful",
                "customer": {"email": "a@b.com", "name": "Test"},
                "meta": {},
            },
        }
        body = json.dumps(payload).encode()
        event = self.provider.normalise(body)
        assert event.amount_in_lowest_unit == 9999
        assert isinstance(event.amount_in_lowest_unit, int)

    def test_charge_failed_maps_correctly(self, flutterwave_charge_failed_payload):
        body = json.dumps(flutterwave_charge_failed_payload).encode()
        event = self.provider.normalise(body)
        assert event.event_type == EventType.PAYMENT_FAILED

    def test_raw_payload_preserved(self, flutterwave_charge_success_payload):
        body = json.dumps(flutterwave_charge_success_payload).encode()
        event = self.provider.normalise(body)
        assert event.raw_payload == flutterwave_charge_success_payload

    def test_missing_tx_ref_raises_normalisation_error(self):
        payload = json.dumps({"event": "charge.completed", "data": {}}).encode()
        with pytest.raises(NormalisationError, match="tx_ref"):
            self.provider.extract_reference(payload)

    def test_unknown_status_raises_normalisation_error(self):
        payload = {
            "event": "charge.completed",
            "data": {
                "tx_ref": "ref",
                "amount": 100,
                "currency": "NGN",
                "status": "pending",  # not in mapping
                "customer": {"email": "a@b.com", "name": "X"},
                "meta": {},
            },
        }
        with pytest.raises(NormalisationError, match="no normalised mapping"):
            self.provider.normalise(json.dumps(payload).encode())