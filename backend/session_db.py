"""
SmartVend v3.0 — Session Database Layer
=======================================
All session lifecycle operations using Supabase client.
Each function is async-safe (runs blocking supabase calls in threads).

Session States: active → in_progress → dispensing → completed
                  ↓            ↓
                expired      expired
"""

import asyncio
import secrets
import string
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from config import SUPABASE_KEY, SUPABASE_URL

# Reuse supabase client from database.py
import database as db


# ──────────────────────────────────────────────
#  Configuration
# ──────────────────────────────────────────────

SESSION_TTL_SECONDS = 60       # QR rotation interval (how long before QR refreshes)
CLAIM_TTL_SECONDS = 300        # 5 minutes to complete payment after scanning
MOTOR_TIMEOUT_SECONDS = 120    # 2 minutes max for dispensing


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _generate_session_token(length: int = 6) -> str:
    """Generate a URL-safe token for QR codes.
    6-char base62 = 62^6 = 56.8 billion combinations.
    Extremely short so it easily fits under the Version 2 QR boundary (32 bytes).
    """
    alphabet = string.ascii_letters + string.digits  # base62
    return ''.join(secrets.choice(alphabet) for _ in range(length))


# ──────────────────────────────────────────────
#  Session CRUD
# ──────────────────────────────────────────────

async def create_session(machine_id: str, ttl_seconds: int = SESSION_TTL_SECONDS) -> Optional[Dict]:
    """Create a new ACTIVE session for a machine.
    
    Returns: { id, session_token, machine_id, status, expires_at, created_at }
    Returns None on failure (e.g., unique constraint violation = session already exists).
    """
    if not db.supabase:
        return None

    token = _generate_session_token()
    expires_at = (_now() + timedelta(seconds=ttl_seconds)).isoformat()

    payload = {
        "session_token": token,
        "machine_id": machine_id,
        "status": "active",
        "expires_at": expires_at,
    }

    def _insert():
        return db.supabase.table("sessions").insert(payload).execute()

    try:
        res = await asyncio.to_thread(lambda: db._retry_supabase_query(_insert))
        data = db._res_data(res)
        if isinstance(data, list) and data:
            return data[0]
        return data
    except Exception as e:
        error_str = str(e).lower()
        if "unique" in error_str or "duplicate" in error_str:
            # Partial unique index violation: there's already an active session for this machine
            # This is expected — caller should expire the old one first
            print(f"Session create conflict for {machine_id}: active session already exists")
            return None
        print(f"Session create error for {machine_id}: {e}")
        return None


async def get_session_by_token(session_token: str) -> Optional[Dict]:
    """Look up a session by its token. Returns the full row or None."""
    if not db.supabase:
        return None

    def _query():
        res = (
            db.supabase.table("sessions")
            .select("*")
            .eq("session_token", session_token)
            .execute()
        )
        if not res.data:
            return None
        return res.data[0]

    try:
        return await asyncio.to_thread(lambda: db._retry_supabase_query(_query))
    except Exception as e:
        print(f"Session lookup error for token {session_token[:4]}...: {e}")
        return None


async def get_active_session_for_machine(machine_id: str) -> Optional[Dict]:
    """Get the current active/in_progress/dispensing session for a machine."""
    if not db.supabase:
        return None

    def _query():
        res = (
            db.supabase.table("sessions")
            .select("*")
            .eq("machine_id", machine_id)
            .in_("status", ["active", "in_progress", "dispensing"])
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if not res.data:
            return None
        return res.data[0]

    try:
        return await asyncio.to_thread(lambda: db._retry_supabase_query(_query))
    except Exception as e:
        print(f"Active session lookup error for {machine_id}: {e}")
        return None


async def claim_session(session_token: str, client_id: str) -> Dict:
    """Atomically claim an ACTIVE session → IN_PROGRESS.
    
    Returns:
        Success: { "status": "claimed", "session": {...}, "machine_id": "..." }
        Already claimed by same user: { "status": "already_claimed", "session": {...} }
        Already claimed by other: { "error": "already_claimed" }
        Expired/invalid: { "error": "expired_or_invalid" }
    """
    if not db.supabase:
        return {"error": "database_unavailable"}

    # First, fetch the session to understand its current state
    session = await get_session_by_token(session_token)
    
    if not session:
        return {"error": "session_not_found"}

    current_status = session.get("status")
    session_id = session.get("id")
    machine_id = session.get("machine_id")

    # Case 1: Session is already in_progress — check if same user (resume) or different (reject)
    if current_status == "in_progress":
        if session.get("claimed_by") == client_id:
            # Same user resuming (e.g., page reload)
            return {
                "status": "already_claimed",
                "session": session,
                "machine_id": machine_id,
            }
        else:
            return {"error": "already_claimed"}

    # Case 2: Session is completed/expired/dispensing → dead
    if current_status in ("completed", "expired", "dispensing"):
        return {"error": "expired_or_invalid"}

    # Case 3: Session is active → check if not expired by time
    expires_at = session.get("expires_at")
    if expires_at and _now().isoformat() > expires_at:
        return {"error": "expired_or_invalid"}

    # Case 4: Atomic claim — UPDATE WHERE status='active' (race-safe)
    now_iso = _now().isoformat()
    claim_expires = (_now() + timedelta(seconds=CLAIM_TTL_SECONDS)).isoformat()

    def _atomic_claim():
        res = (
            db.supabase.table("sessions")
            .update({
                "status": "in_progress",
                "claimed_by": client_id,
                "claimed_at": now_iso,
                "expires_at": claim_expires,  # Extend TTL to claim duration
            })
            .eq("session_token", session_token)
            .eq("status", "active")  # CRITICAL: only claim if still active
            .execute()
        )
        return res

    try:
        res = await asyncio.to_thread(lambda: db._retry_supabase_query(_atomic_claim))
        data = db._res_data(res)

        if not data or (isinstance(data, list) and len(data) == 0):
            # No rows updated → someone else got it first (race condition lost)
            return {"error": "already_claimed"}

        claimed_session = data[0] if isinstance(data, list) else data

        # Update machine status to 'in_use'
        await db.update_machine_status(machine_id, "in_use")

        # Log the claim event
        await log_event(
            machine_id=machine_id,
            session_id=session_id,
            event_type="session_claimed",
            client_id=client_id,
        )

        return {
            "status": "claimed",
            "session": claimed_session,
            "machine_id": machine_id,
        }

    except Exception as e:
        print(f"Session claim error: {e}")
        return {"error": "claim_failed"}


async def get_session_status(session_token: str, client_id: Optional[str] = None) -> Dict:
    """Get session status for frontend (resume on reload).
    
    Returns session info. If client_id provided, indicates whether this user owns the session.
    """
    session = await get_session_by_token(session_token)
    if not session:
        return {"error": "session_not_found"}

    result = {
        "session_token": session.get("session_token"),
        "machine_id": session.get("machine_id"),
        "status": session.get("status"),
        "expires_at": session.get("expires_at"),
        "created_at": session.get("created_at"),
    }

    if client_id:
        result["is_owner"] = session.get("claimed_by") == client_id

    # Check if expired by time (sweeper may not have caught it yet)
    if session.get("status") in ("active", "in_progress"):
        expires_at = session.get("expires_at")
        if expires_at and _now().isoformat() > expires_at:
            result["status"] = "expired"
            result["expired_by_time"] = True

    return result


async def cancel_session(session_token: str, client_id: str) -> Dict:
    """Explicitly cancel a session. Only the owner can cancel.
    Releases reserved stock if an order was created.
    
    Returns: { "status": "cancelled" } or { "error": "..." }
    """
    session = await get_session_by_token(session_token)
    if not session:
        return {"error": "session_not_found"}

    if session.get("status") not in ("in_progress",):
        return {"error": "cannot_cancel", "detail": f"Session is {session.get('status')}"}

    if session.get("claimed_by") != client_id:
        return {"error": "not_owner"}

    session_id = session.get("id")
    machine_id = session.get("machine_id")

    # Expire the session
    def _expire():
        return (
            db.supabase.table("sessions")
            .update({
                "status": "expired",
                "completed_at": _now().isoformat(),
            })
            .eq("id", session_id)
            .eq("status", "in_progress")  # Only if still in_progress
            .execute()
        )

    try:
        res = await asyncio.to_thread(lambda: db._retry_supabase_query(_expire))
        data = db._res_data(res)
        if not data or (isinstance(data, list) and len(data) == 0):
            return {"error": "cancel_failed", "detail": "Session state changed"}

        # Release reserved stock if any orders exist for this session
        await _release_reserved_stock(session_id, machine_id)

        # Reset machine to idle
        await db.update_machine_status(machine_id, "idle")

        # Log event
        await log_event(
            machine_id=machine_id,
            session_id=session_id,
            event_type="session_cancelled",
            client_id=client_id,
        )

        return {"status": "cancelled", "machine_id": machine_id}

    except Exception as e:
        print(f"Session cancel error: {e}")
        return {"error": "cancel_failed"}


async def update_session_status(
    session_id: str, new_status: str, extra_fields: Optional[Dict] = None
) -> Optional[Dict]:
    """Update session status with optional extra fields."""
    if not db.supabase:
        return None

    update_data = {"status": new_status}
    if new_status == "completed":
        update_data["completed_at"] = _now().isoformat()
    if extra_fields:
        update_data.update(extra_fields)

    def _update():
        return (
            db.supabase.table("sessions")
            .update(update_data)
            .eq("id", session_id)
            .execute()
        )

    try:
        res = await asyncio.to_thread(lambda: db._retry_supabase_query(_update))
        data = db._res_data(res)
        if isinstance(data, list) and data:
            return data[0]
        return data
    except Exception as e:
        print(f"Session status update error: {e}")
        return None


# ──────────────────────────────────────────────
#  Orders (Razorpay ↔ Session mapping)
# ──────────────────────────────────────────────

async def create_order_record(
    order_id: str,
    session_id: str,
    machine_id: str,
    client_id: str,
    quantity: int,
    amount: int,
) -> Optional[Dict]:
    """Store the Razorpay order → session mapping for webhook reconciliation."""
    if not db.supabase:
        return None

    payload = {
        "order_id": order_id,
        "session_id": session_id,
        "machine_id": machine_id,
        "client_id": client_id,
        "quantity": quantity,
        "amount": amount,
        "reserved_stock": True,
    }

    def _insert():
        return db.supabase.table("orders").insert(payload).execute()

    try:
        res = await asyncio.to_thread(lambda: db._retry_supabase_query(_insert))
        data = db._res_data(res)
        if isinstance(data, list) and data:
            return data[0]
        return data
    except Exception as e:
        print(f"Order record create error: {e}")
        return None


async def get_order_by_id(order_id: str) -> Optional[Dict]:
    """Look up an order by Razorpay order_id."""
    if not db.supabase:
        return None

    def _query():
        res = (
            db.supabase.table("orders")
            .select("*")
            .eq("order_id", order_id)
            .execute()
        )
        if not res.data:
            return None
        return res.data[0]

    try:
        return await asyncio.to_thread(lambda: db._retry_supabase_query(_query))
    except Exception as e:
        print(f"Order lookup error for {order_id}: {e}")
        return None


# ──────────────────────────────────────────────
#  Idempotency (replaces in-memory set)
# ──────────────────────────────────────────────

async def check_transaction_exists_for_order(order_id: str) -> bool:
    """Check if a transaction already exists for this order_id.
    Uses the orders → transactions link via session_id.
    Replaces the in-memory _processed_transactions set.
    """
    if not db.supabase:
        return False

    order = await get_order_by_id(order_id)
    if not order:
        return False

    session_id = order.get("session_id")
    if not session_id:
        return False

    def _query():
        res = (
            db.supabase.table("transactions")
            .select("id")
            .eq("machine_id", order.get("machine_id"))
            .execute()
        )
        # Check if any transaction exists for this machine with 'paid' or 'completed' status
        return bool(res.data)

    try:
        return await asyncio.to_thread(lambda: db._retry_supabase_query(_query))
    except Exception:
        return False


# ──────────────────────────────────────────────
#  Stock Management
# ──────────────────────────────────────────────

async def reserve_stock_atomic(machine_id: str, quantity: int) -> Dict:
    """Atomically decrement stock. Returns success/failure.
    
    Uses SELECT → CHECK → UPDATE pattern (Supabase doesn't support
    UPDATE ... WHERE current_stock >= quantity RETURNING natively via REST).
    """
    if not db.supabase:
        return {"error": "database_unavailable"}

    def _get_stock():
        res = (
            db.supabase.table("machines")
            .select("current_stock")
            .eq("machine_id", machine_id)
            .single()
            .execute()
        )
        return db._res_data(res)

    try:
        machine = await asyncio.to_thread(lambda: db._retry_supabase_query(_get_stock))
        if not machine:
            return {"error": "machine_not_found"}

        current_stock = machine.get("current_stock") or 0
        if current_stock < quantity:
            return {"error": "insufficient_stock", "available": current_stock}

        new_stock = current_stock - quantity

        def _update():
            return (
                db.supabase.table("machines")
                .update({"current_stock": new_stock})
                .eq("machine_id", machine_id)
                .execute()
            )

        await asyncio.to_thread(lambda: db._retry_supabase_query(_update))
        return {"status": "reserved", "remaining": new_stock}

    except Exception as e:
        print(f"Stock reservation error for {machine_id}: {e}")
        return {"error": "reservation_failed"}


async def release_stock(machine_id: str, quantity: int) -> bool:
    """Release previously reserved stock (on cancel/expiry). Best-effort."""
    if not db.supabase:
        return False

    def _get_stock():
        res = (
            db.supabase.table("machines")
            .select("current_stock")
            .eq("machine_id", machine_id)
            .single()
            .execute()
        )
        return db._res_data(res)

    try:
        machine = await asyncio.to_thread(lambda: db._retry_supabase_query(_get_stock))
        if not machine:
            return False

        current_stock = machine.get("current_stock") or 0
        new_stock = current_stock + quantity

        def _update():
            return (
                db.supabase.table("machines")
                .update({"current_stock": new_stock})
                .eq("machine_id", machine_id)
                .execute()
            )

        await asyncio.to_thread(lambda: db._retry_supabase_query(_update))
        return True

    except Exception as e:
        print(f"Stock release error for {machine_id}: {e}")
        return False


async def _release_reserved_stock(session_id: str, machine_id: str):
    """Release stock for all orders associated with a session."""
    if not db.supabase:
        return

    def _get_orders():
        res = (
            db.supabase.table("orders")
            .select("quantity, reserved_stock")
            .eq("session_id", session_id)
            .eq("reserved_stock", True)
            .execute()
        )
        return res.data if res.data else []

    try:
        orders = await asyncio.to_thread(lambda: db._retry_supabase_query(_get_orders))
        total_qty = sum(o.get("quantity", 0) for o in orders)
        if total_qty > 0:
            await release_stock(machine_id, total_qty)
            # Mark orders as stock released
            def _mark_released():
                return (
                    db.supabase.table("orders")
                    .update({"reserved_stock": False})
                    .eq("session_id", session_id)
                    .execute()
                )
            await asyncio.to_thread(lambda: db._retry_supabase_query(_mark_released))
    except Exception as e:
        print(f"Stock release error for session {session_id}: {e}")


# ──────────────────────────────────────────────
#  Session Expiry Sweeper
# ──────────────────────────────────────────────

async def expire_stale_sessions() -> List[Dict]:
    """Find and expire all sessions past their expires_at.
    
    Returns list of { machine_id, old_status, session_id } for each expired session.
    The caller should then create new sessions for these machines and notify ESP32s.
    """
    if not db.supabase:
        return []

    now_iso = _now().isoformat()

    def _find_expired():
        res = (
            db.supabase.table("sessions")
            .select("id, machine_id, status, session_token")
            .in_("status", ["active", "in_progress"])
            .lt("expires_at", now_iso)
            .execute()
        )
        return res.data if res.data else []

    try:
        expired = await asyncio.to_thread(lambda: db._retry_supabase_query(_find_expired))
        if not expired:
            return []

        results = []
        for session in expired:
            session_id = session["id"]
            machine_id = session["machine_id"]
            old_status = session["status"]

            # Expire the session
            def _make_expire(sid):
                def _expire():
                    return (
                        db.supabase.table("sessions")
                        .update({
                            "status": "expired",
                            "completed_at": now_iso,
                        })
                        .eq("id", sid)
                        .in_("status", ["active", "in_progress"])
                        .execute()
                    )
                return _expire

            res = await asyncio.to_thread(
                lambda sid=session_id: db._retry_supabase_query(_make_expire(sid))
            )
            data = db._res_data(res)
            if not data or (isinstance(data, list) and len(data) == 0):
                continue  # Already expired by another worker

            # If was in_progress, release any reserved stock
            if old_status == "in_progress":
                await _release_reserved_stock(session_id, machine_id)

            # Reset machine to idle
            await db.update_machine_status(machine_id, "idle")

            # Log event
            await log_event(
                machine_id=machine_id,
                session_id=session_id,
                event_type="session_expired",
                payload={"old_status": old_status},
            )

            results.append({
                "machine_id": machine_id,
                "old_status": old_status,
                "session_id": session_id,
            })

        return results

    except Exception as e:
        print(f"Session expiry sweeper error: {e}")
        return []


async def expire_and_renew_sessions() -> List[Tuple[str, Dict]]:
    """Expire stale sessions AND create new ones for each machine.
    
    Returns: List of (machine_id, new_session) tuples.
    The caller uses this to send new QR URLs to ESP32 devices.
    """
    expired = await expire_stale_sessions()
    renewed = []

    for item in expired:
        machine_id = item["machine_id"]
        new_session = await create_session(machine_id)
        if new_session:
            renewed.append((machine_id, new_session))
        else:
            print(f"Failed to create renewal session for {machine_id}")

    return renewed


# ──────────────────────────────────────────────
#  Dispense Flow
# ──────────────────────────────────────────────

async def trigger_dispense_session(
    session_token: str,
    client_id: str,
    quantity: int,
    transaction_id: str,
    amount: int,
) -> Dict:
    """Validate session ownership and transition to DISPENSING.
    Creates the transaction record. Returns dispense command details.
    
    Returns:
        Success: { "status": "ok", "session": {...}, "machine_id": "..." }
        Error: { "error": "..." }
    """
    session = await get_session_by_token(session_token)
    if not session:
        return {"error": "session_not_found"}

    if session.get("status") != "in_progress":
        return {"error": "invalid_state", "detail": f"Session is {session.get('status')}"}

    if session.get("claimed_by") != client_id:
        return {"error": "not_owner"}

    # Check expiry
    expires_at = session.get("expires_at")
    if expires_at and _now().isoformat() > expires_at:
        return {"error": "session_expired"}

    session_id = session.get("id")
    machine_id = session.get("machine_id")

    # DB-level idempotency check: does a transaction already exist for this session?
    import uuid
    try:
        tx_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, str(transaction_id)))
    except Exception:
        tx_uuid = str(uuid.uuid4())

    def _check_existing_tx():
        res = (
            db.supabase.table("transactions")
            .select("id")
            .eq("id", tx_uuid)
            .execute()
        )
        return bool(res.data)

    try:
        exists = await asyncio.to_thread(lambda: db._retry_supabase_query(_check_existing_tx))
        if exists:
            return {"error": "already_processed", "status": "duplicate"}
    except Exception:
        pass

    # Create transaction row
    tx_payload = {
        "id": tx_uuid,
        "machine_id": machine_id,
        "client_id": client_id,
        "amount": amount,
        "quantity": quantity,
        "payment_status": "paid",
        "created_at": _now().isoformat(),
    }

    def _insert_tx():
        return db.supabase.table("transactions").insert(tx_payload).execute()

    try:
        await asyncio.to_thread(lambda: db._retry_supabase_query(_insert_tx))
    except Exception as e:
        error_str = str(e).lower()
        if "duplicate" in error_str or "unique" in error_str:
            return {"error": "already_processed", "status": "duplicate"}
        print(f"Transaction insert error: {e}")
        return {"error": "transaction_failed"}

    # Transition session to DISPENSING
    dispense_expires = (_now() + timedelta(seconds=MOTOR_TIMEOUT_SECONDS)).isoformat()
    await update_session_status(session_id, "dispensing", {"expires_at": dispense_expires})

    # Update machine status
    await db.update_machine_status(machine_id, "dispensing")

    # Log event
    await log_event(
        machine_id=machine_id,
        session_id=session_id,
        event_type="dispense_triggered",
        client_id=client_id,
        payload={"transaction_id": transaction_id, "quantity": quantity},
    )

    return {
        "status": "ok",
        "session": session,
        "machine_id": machine_id,
        "transaction_id": transaction_id,
    }


async def complete_session(
    machine_id: str, transaction_id: str, dispensed: int
) -> Dict:
    """Complete a dispensing session: mark transaction done, complete session,
    create new session, handle low stock alert.
    
    Returns: { "status": "completed", "new_session": {...}, "low_stock": bool }
    """
    session = await get_active_session_for_machine(machine_id)
    if not session:
        return {"error": "no_active_session"}

    if session.get("status") != "dispensing":
        return {"error": "not_dispensing", "detail": f"Session is {session.get('status')}"}

    session_id = session.get("id")

    # Update transaction
    import uuid
    try:
        tx_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, str(transaction_id)))
    except Exception:
        tx_uuid = str(uuid.uuid4())

    def _update_tx():
        return (
            db.supabase.table("transactions")
            .update({
                "dispensed": dispensed,
                "payment_status": "completed",
                "completed_at": _now().isoformat(),
            })
            .eq("id", tx_uuid)
            .execute()
        )

    try:
        await asyncio.to_thread(lambda: db._retry_supabase_query(_update_tx))
    except Exception as e:
        print(f"Transaction update error: {e}")

    # Complete the session
    await update_session_status(session_id, "completed")

    # Check low stock
    low_stock = False
    remaining = 0

    def _get_stock():
        res = (
            db.supabase.table("machines")
            .select("current_stock")
            .eq("machine_id", machine_id)
            .single()
            .execute()
        )
        return db._res_data(res)

    try:
        machine = await asyncio.to_thread(lambda: db._retry_supabase_query(_get_stock))
        if machine:
            remaining = machine.get("current_stock") or 0
            if remaining <= 5:
                low_stock = True
    except Exception:
        pass

    # Reset machine to idle
    if remaining <= 0:
        await db.update_machine_status(machine_id, "Unavailable")
    else:
        await db.update_machine_status(machine_id, "idle")

    # Create new session for this machine
    new_session = await create_session(machine_id)

    # Log event
    await log_event(
        machine_id=machine_id,
        session_id=session_id,
        event_type="session_completed",
        payload={
            "transaction_id": transaction_id,
            "dispensed": dispensed,
            "remaining_stock": remaining,
        },
    )

    return {
        "status": "completed",
        "new_session": new_session,
        "low_stock": low_stock,
        "remaining_stock": remaining,
    }


# ──────────────────────────────────────────────
#  ESP32 Registration Helper
# ──────────────────────────────────────────────

async def register_machine_session(machine_id: str, api_key: str) -> Dict:
    """Called when ESP32 registers via WebSocket.
    1. Upsert machine record
    2. Expire any stale session for this machine
    3. Create a fresh active session
    4. Return session info for QR generation
    
    Returns: { "session_token": "...", "url": "...", "expires_at": "..." }
    """
    from config import FRONTEND_URL

    # 1. Upsert machine
    await db.upsert_machine(machine_id, api_key, None)
    await db.update_machine_status(machine_id, "idle")
    await db.set_machine_last_seen(machine_id)

    # 2. Expire any existing active session (ESP32 just rebooted)
    existing = await get_active_session_for_machine(machine_id)
    if existing:
        existing_id = existing.get("id")
        old_status = existing.get("status")

        def _force_expire():
            return (
                db.supabase.table("sessions")
                .update({
                    "status": "expired",
                    "completed_at": _now().isoformat(),
                })
                .eq("id", existing_id)
                .execute()
            )

        try:
            await asyncio.to_thread(lambda: db._retry_supabase_query(_force_expire))
            # Release stock if it was in_progress with orders
            if old_status == "in_progress":
                await _release_reserved_stock(existing_id, machine_id)
        except Exception as e:
            print(f"Force-expire existing session error: {e}")

    # 3. Create new active session
    new_session = await create_session(machine_id)
    if not new_session:
        return {"error": "session_creation_failed"}

    token = new_session.get("session_token")
    base_url = FRONTEND_URL or "https://smartvend.onrender.com"
    url = f"{base_url}/s/{token}"

    # 4. Log event
    await log_event(
        machine_id=machine_id,
        session_id=new_session.get("id"),
        event_type="session_created",
        payload={"trigger": "esp32_register"},
    )

    return {
        "session_token": token,
        "url": url,
        "expires_at": new_session.get("expires_at"),
    }


# ──────────────────────────────────────────────
#  Audit Logging
# ──────────────────────────────────────────────

async def log_event(
    machine_id: str,
    session_id: Optional[str] = None,
    event_type: str = "unknown",
    client_id: Optional[str] = None,
    payload: Optional[Dict] = None,
):
    """Write an event to the events table. Best-effort (never raises)."""
    if not db.supabase:
        return

    event_payload = {
        "machine_id": machine_id,
        "event_type": event_type,
    }
    if session_id:
        event_payload["session_id"] = session_id
    if client_id:
        event_payload["client_id"] = client_id
    if payload:
        event_payload["payload"] = payload

    def _insert():
        return db.supabase.table("events").insert(event_payload).execute()

    try:
        await asyncio.to_thread(lambda: db._retry_supabase_query(_insert))
    except Exception as e:
        # Best-effort: never fail the main operation because of logging
        print(f"Event log error: {e}")
