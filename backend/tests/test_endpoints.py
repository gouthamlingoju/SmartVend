import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import sys, os
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import database as db
from main import app



@pytest.fixture(autouse=True)
def enable_db_pool(monkeypatch):
    # Ensure handlers that check db.pool treat DB as configured
    monkeypatch.setattr(db, "pool", True)


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
