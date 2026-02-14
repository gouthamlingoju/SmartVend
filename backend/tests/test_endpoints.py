import json
import hmac
import hashlib
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

import sys, os
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import database as db
import main as main_module
from main import app


@pytest.fixture(autouse=True)
def enable_db_pool(monkeypatch):
    # Ensure handlers that check db.pool treat DB as configured
    monkeypatch.setattr(db, "pool", True)


@pytest.fixture(autouse=True)
def clear_processed_transactions():
    """Clear idempotency state between tests."""
    main_module._processed_transactions.clear()
    yield
    main_module._processed_transactions.clear()


def iso_future():
    return (datetime.now(timezone.utc)).isoformat()


def test_public_status_endpoint(monkeypatch):
    async def fake_get_public_status(machine_id, client_id=None):
        return {
            "machine_id": machine_id,
            "status": "idle",
            "current_stock": 12,
            "display_code_expires_at": iso_future(),
            "locked": False,
            "server_time": iso_future(),
        }

    monkeypatch.setattr(db, "get_public_status", fake_get_public_status)

    client = TestClient(app)
    res = client.get("/api/machine/test-machine/public-status")
    assert res.status_code == 200
    body = res.json()
    assert body["machine_id"] == "test-machine"
    assert "current_stock" in body


def test_lock_by_code(monkeypatch):
    async def fake_lock_by_code(client_id, code, ttl_minutes=None):
        return {"machine_id": "m1", "status": "locked", "expires_at": iso_future()}

    monkeypatch.setattr(db, "lock_by_code", fake_lock_by_code)

    client = TestClient(app)
    res = client.post("/api/lock-by-code", json={"client_id": "c1", "code": "123456"})
    assert res.status_code == 200
    data = res.json()
    assert data.get("status") == "locked"


def test_unlock_by_client(monkeypatch):
    async def fake_unlock_by_client_db(machine_id, client_id):
        return {"new_display_code": "999999"}

    monkeypatch.setattr(db, "unlock_by_client_db", fake_unlock_by_client_db)

    client = TestClient(app)
    res = client.post("/api/machine/m1/unlock", json={"client_id": "c1"})
    assert res.status_code == 200
    body = res.json()
    assert body.get("new_display_code") == "999999"


def test_trigger_dispense_validated(monkeypatch):
    async def fake_trigger_dispense_db(machine_id, client_id, access_code, quantity, transaction_id, amount):
        return {"status": "ok"}

    monkeypatch.setattr(db, "trigger_dispense_db", fake_trigger_dispense_db)

    client = TestClient(app)
    payload = {
        "client_id": "c1",
        "access_code": "abc123",
        "quantity": 1,
        "transaction_id": "tx1",
        "amount": 500,
    }
    res = client.post("/api/machine/m1/trigger-dispense", json=payload)
    assert res.status_code == 200
    assert res.json().get("status") == "dispatch_sent"


# ============ New tests for architecture review fixes ============


# FIX: architecture_review.md — "Unify Frontend Data Access"
def test_get_machines_endpoint(monkeypatch):
    """Test that GET /api/machines returns the machine list from DB
    and applies the out_of_stock derivation server-side."""

    async def fake_get_all_machines():
        return [
            {"machine_id": "m1", "location": "Block A", "status": "working", "current_stock": 10},
            {"machine_id": "m2", "location": "Block B", "status": "working", "current_stock": 0},
            {"machine_id": "m3", "location": "Block C", "status": "idle", "current_stock": 5},
        ]

    monkeypatch.setattr(db, "get_all_machines", fake_get_all_machines)

    client = TestClient(app)
    res = client.get("/api/machines")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 3
    # Machine 1: working + stock > 0 → stays "working"
    assert data[0]["status"] == "working"
    # Machine 2: working + stock 0 → derived to "out_of_stock"
    assert data[1]["status"] == "out_of_stock"
    # Machine 3: idle (not "working") → left unchanged
    assert data[2]["status"] == "idle"


# FIX: architecture_review.md — "Stock Reservation"
def test_create_order_insufficient_stock(monkeypatch):
    """Test that /create-order returns 409 when stock < quantity,
    preventing payment for unavailable items."""

    async def fake_check_stock_available(machine_id, quantity):
        return False  # simulate no stock

    monkeypatch.setattr(db, "check_stock_available", fake_check_stock_available)
    # Need razorpay_client to not be None to get past the first check
    monkeypatch.setattr(main_module, "razorpay_client", MagicMock())

    client = TestClient(app)
    res = client.post("/create-order", json={"quantity": 5, "machine_id": "m1"})
    assert res.status_code == 409
    assert "Insufficient stock" in res.json()["error"]


# FIX: architecture_review.md — "Payment Reconciliation"
def test_razorpay_webhook_invalid_signature(monkeypatch):
    """Test that webhook rejects requests with bad signatures."""

    monkeypatch.setattr(main_module, "RAZORPAY_WEBHOOK_SECRET", "test_secret_key")

    client = TestClient(app)
    body = json.dumps({"event": "payment.captured"}).encode()
    res = client.post(
        "/api/razorpay-webhook",
        content=body,
        headers={"X-Razorpay-Signature": "bad_signature_here"},
    )
    assert res.status_code == 400
    assert res.json()["error"] == "Invalid signature"


# FIX: architecture_review.md — "Payment Reconciliation"
def test_razorpay_webhook_valid_signature(monkeypatch):
    """Test that webhook accepts requests with valid HMAC-SHA256 signatures."""

    secret = "test_webhook_secret"
    monkeypatch.setattr(main_module, "RAZORPAY_WEBHOOK_SECRET", secret)

    body = json.dumps({
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_test123",
                    "order_id": "order_test456",
                    "amount": 10000,
                }
            }
        }
    }).encode()

    # Generate valid HMAC signature
    valid_sig = hmac.new(
        secret.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()

    client = TestClient(app)
    res = client.post(
        "/api/razorpay-webhook",
        content=body,
        headers={"X-Razorpay-Signature": valid_sig},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


# ============ Tests for medium-priority fixes ============


# FIX: architecture_review.md — "Idempotency"
def test_trigger_dispense_idempotency(monkeypatch):
    """Test that calling /trigger-dispense twice with the same transaction_id
    returns 409 on the second call."""
    async def fake_trigger_dispense_db(machine_id, client_id, access_code, quantity, transaction_id, amount):
        return {"status": "ok"}

    monkeypatch.setattr(db, "trigger_dispense_db", fake_trigger_dispense_db)

    client = TestClient(app)
    payload = {
        "client_id": "c1",
        "access_code": "abc123",
        "quantity": 1,
        "transaction_id": "tx_idempotent_test",
    }

    # First call succeeds
    res1 = client.post("/api/machine/m1/trigger-dispense", json=payload)
    assert res1.status_code == 200

    # Second call with same transaction_id is rejected
    res2 = client.post("/api/machine/m1/trigger-dispense", json=payload)
    assert res2.status_code == 409
    assert res2.json()["status"] == "duplicate"


# FIX: architecture_review.md — "CORS Scoping"
def test_cors_no_wildcard():
    """Test that CORS configuration does not include the wildcard '*' origin."""
    # Access the CORS middleware config from the app
    for middleware in app.user_middleware:
        if middleware.cls.__name__ == "CORSMiddleware":
            origins = middleware.kwargs.get("allow_origins", [])
            assert "*" not in origins, "CORS should not allow wildcard '*' origin"
            break
    else:
        pytest.fail("CORSMiddleware not found on the app")


# FIX: architecture_review.md — "Rate Limiting"
def test_admin_login_rate_limiting():
    """Test that /api/admin/login is rate-limited (returns 429 after exceeding limit)."""
    client = TestClient(app)
    # Send 6 requests (limit is 5/minute)
    for i in range(6):
        res = client.post("/api/admin/login", json={"password": "wrong"})

    # The 6th request should be rate-limited
    assert res.status_code == 429
    assert "Too many requests" in res.json()["error"]
