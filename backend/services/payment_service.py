# FIX: architecture_review.md — "Backend Service Layer"
# Extracted payment-related orchestration logic from main.py routes.

import json
import hmac
import hashlib
from typing import Any, Dict, List, Optional

import database as db


async def create_order(
    razorpay_client,
    quantity: int,
    price_per_unit_paisa: int,
    machine_id: Optional[str] = None,
):
    """Create a Razorpay order. Returns the order dict.

    FIX: architecture_review.md — "Stock Reservation"
    Checks stock availability before creating the order.
    """
    # Stock availability check (Fix 2.2)
    if machine_id:
        stock_ok = await db.check_stock_available(machine_id, quantity)
        if not stock_ok:
            return {"error": "insufficient_stock"}

    amount = quantity * price_per_unit_paisa
    order = razorpay_client.order.create(
        {"amount": amount, "currency": "INR", "payment_capture": 1}
    )
    order["unit_price_paise"] = price_per_unit_paisa
    order["quantity"] = quantity
    return order


def verify_payment_signature(razorpay_client, payment_data: dict):
    """Verify Razorpay payment signature. Returns True on success, raises on failure."""
    params = {
        "razorpay_order_id": payment_data.get("razorpay_order_id"),
        "razorpay_payment_id": payment_data.get("razorpay_payment_id"),
        "razorpay_signature": payment_data.get("razorpay_signature"),
    }
    razorpay_client.utility.verify_payment_signature(params)
    return True


async def trigger_dispense(
    machine_id: str,
    client_id: str,
    access_code: str,
    quantity: int,
    transaction_id: str,
    price_per_unit_paisa: int,
    connected_machines: dict,
    pending_http_commands: Dict[str, List[Dict[str, Any]]],
    redis_client,
    redis_channel: str,
):
    """Validate lock, record transaction, and send dispense command to device."""
    amount = quantity * price_per_unit_paisa

    res = await db.trigger_dispense_db(
        machine_id, client_id, access_code, quantity, transaction_id, amount
    )
    if res.get("error"):
        return res

    # Send dispense command via WS/Redis
    payload = {
        "type": "command",
        "action": "dispense",
        "duration": quantity,
        "transaction_id": transaction_id,
    }
    try:
        pending_http_commands.setdefault(machine_id, []).append(payload)
        ws = connected_machines.get(machine_id)
        if ws:
            try:
                await ws.send_text(json.dumps(payload))
            except Exception as e:
                print(f"Local WS send failed for {machine_id}:", e)
        if redis_client:
            try:
                await redis_client.publish(
                    redis_channel,
                    json.dumps({"machine_id": machine_id, "payload": payload}),
                )
            except Exception as e:
                print("Redis publish failed:", e)
    except Exception as e:
        print(f"Failed to send WS command to {machine_id}:", e)

    return {"status": "ok"}


# FIX: architecture_review.md — "Payment Reconciliation"
def verify_webhook_signature(
    request_body: bytes,
    signature: str,
    webhook_secret: str,
) -> bool:
    """Verify Razorpay webhook signature using HMAC-SHA256."""
    if not webhook_secret or not signature:
        return False
    expected = hmac.new(
        webhook_secret.encode("utf-8"),
        request_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
