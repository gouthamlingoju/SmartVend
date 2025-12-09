from config import SUPABASE_KEY, SUPABASE_URL, DISPLAY_CODE_TTL_MINUTES
from supabase import create_client, Client
import asyncio
import secrets
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional
import uuid
import time


# Create a synchronous supabase client (blocking). We'll call it from async wrappers.
supabase: Client = None
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Pool flag used by main.py to detect DB availability
pool = bool(supabase)


async def init_pool():
    """Initialize any connection/pool resources. For Supabase client this is a no-op
    but the API in `main.py` expects an async callable.
    """
    global pool
    # already created above; still expose as async
    pool = bool(supabase)
    return


async def close_pool():
    # supabase-py doesn't expose a close; keep interface
    return


def _res_data(res):
    # supabase client may return an object with .data/.error or a dict
    if res is None:
        return None
    if hasattr(res, "data"):
        return res.data
    if isinstance(res, dict):
        return res.get("data")
    # fallback
    return None


def _res_error(res):
    if res is None:
        return None
    if hasattr(res, "error"):
        return res.error
    if isinstance(res, dict):
        return res.get("error")
    return None


def _now():
    return datetime.now(timezone.utc)


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _retry_supabase_query(query_func, max_retries=3, delay=0.5):
    """Retry a Supabase query function with exponential backoff on connection errors."""
    for attempt in range(max_retries):
        try:
            return query_func()
        except Exception as e:
            error_str = str(e).lower()
            # Only retry on connection/protocol errors
            is_retryable = any(
                err in error_str
                for err in [
                    "connectionterminated",
                    "remoteprotocolerror",
                    "connection",
                    "network",
                    "protocol",
                ]
            )

            if not is_retryable or attempt == max_retries - 1:
                # Non-retryable error or final attempt - re-raise
                raise

            # Exponential backoff with jitter
            wait_time = delay * (2**attempt) + (secrets.randbelow(100) / 1000)
            print(
                f"Supabase connection error (attempt {attempt + 1}/{max_retries}), retrying in {wait_time:.2f}s: {e}"
            )
            time.sleep(wait_time)

    # Should never reach here, but just in case
    return query_func()


async def get_machine_by_id(machine_id: str):
    def _query():
        res = (
            supabase.table("machines")
            .select("*")
            .eq("machine_id", machine_id)
            .execute()
        )
        if not res.data:  # no machine found
            return None
        return res.data[0]  # return first matching record

    return await asyncio.to_thread(lambda: _retry_supabase_query(_query))


async def upsert_machine(machine_id: str, api_key: str, ttl_minutes: Optional[int]):
    """Create or update a machine row and generate a display code when registering.
    Returns the upserted row.
    """
    if not supabase:
        return None

    ttl = (
        int(ttl_minutes)
        if ttl_minutes
        else int(DISPLAY_CODE_TTL_MINUTES)
        if DISPLAY_CODE_TTL_MINUTES
        else 10
    )
    display_code = f"{secrets.randbelow(900000) + 100000}"  # 6-digit
    expires_at = (_now() + timedelta(minutes=ttl)).isoformat()

    payload = {
        "machine_id": machine_id,
        "api_key": api_key,
        "display_code": display_code,
        "display_code_expires_at": expires_at,
        "last_seen_at": _now().isoformat(),
    }

    def _upsert():
        return supabase.table("machines").upsert(payload).execute()

    res = await asyncio.to_thread(lambda: _retry_supabase_query(_upsert))
    data = _res_data(res)
    # upsert returns list of rows; return the first
    if isinstance(data, list) and data:
        row = data[0]
    else:
        row = data
    return row


async def get_machine_status_for_esp32(machine_id: str, provided_key: str):
    """Return status info for machine if API key matches, otherwise None."""
    m = await get_machine_by_id(machine_id)
    if not m:
        return {"status": "no_machine_found"}

    expected = m.get("api_key")
    if not expected or not secrets.compare_digest(str(expected), str(provided_key)):
        return None

    # Build status object
    # include basic machine fields and current lock if any
    def _lock_query():
        res = supabase.table("locks").select("*").eq("machine_id", machine_id).execute()
        if not res.data:  # no rows returned
            return None
        return res.data[0]  # return the first record

    lock = await asyncio.to_thread(lambda: _retry_supabase_query(_lock_query))
    # Continue and return machine status even without a lock
    # This ensures ESP32 always gets display_code

    status = {
        "machine_id": m.get("machine_id"),
        "status": m.get("status"),
        "current_stock": m.get("current_stock"),
        "display_code": m.get("display_code"),
        "display_code_expires_at": m.get("display_code_expires_at"),
        "locked": bool(lock and lock.get("status") == "locked"),
        "locked_by": lock.get("locked_by") if lock else None,
        "lock_expires_at": lock.get("expires_at") if lock else None,
    }
    return status


async def get_public_status(machine_id: str, client_id: Optional[str] = None):
    """Return public view of machine status. Only reveal locked_by when it matches client_id."""
    m = await get_machine_by_id(machine_id)
    if not m:
        return {"status": "no_machine_found"}

    def _lock_query():
        res = supabase.table("locks").select("*").eq("machine_id", machine_id).execute()
        if not res.data:  # no rows returned
            return None
        return res.data[0]  # return the first record

    lock = await asyncio.to_thread(lambda: _retry_supabase_query(_lock_query))
    is_locked = bool(
        lock
        and lock.get("status") == "locked"
        and lock.get("expires_at")
        and _now().isoformat() < lock.get("expires_at")
    )
    locked_by = None
    if is_locked:
        if client_id and client_id == lock.get("locked_by"):
            locked_by = lock.get("locked_by")
    out = {
        "machine_id": m.get("machine_id"),
        "status": m.get("status"),
        "current_stock": m.get("current_stock"),
        "display_code_expires_at": m.get("display_code_expires_at"),
        "locked": is_locked,
        "locked_by": locked_by,
        "expires_at": lock.get("expires_at") if lock else None,
        "server_time": _now().isoformat(),
    }
    return out


async def unlock_by_client_db(machine_id: str, client_id: str):
    """Unlock machine if owned by client_id. Returns dict with possible error or new_display_code."""

    # fetch lock
    def _get_lock():
        query = (
            supabase.table("locks").select("*").eq("machine_id", machine_id).execute()
        )
        data = query.data
        if not data:
            return None  # or handle appropriately
        return data[0]  # first record if multiple found

    res = await asyncio.to_thread(lambda: _retry_supabase_query(_get_lock))
    lock = res
    if not lock or lock.get("status") != "locked":
        return {"error": "no_lock"}
    if lock.get("locked_by") != client_id:
        return {"error": "not_owner"}

    # delete lock
    def _delete_lock():
        return supabase.table("locks").delete().eq("machine_id", machine_id).execute()

    await asyncio.to_thread(lambda: _retry_supabase_query(_delete_lock))

    # generate new display code
    ttl = int(DISPLAY_CODE_TTL_MINUTES) if DISPLAY_CODE_TTL_MINUTES else 10
    display_code = f"{secrets.randbelow(900000) + 100000}"
    expires_at = (_now() + timedelta(minutes=ttl)).isoformat()

    def _update_machine():
        return (
            supabase.table("machines")
            .update(
                {
                    "display_code": display_code,
                    "display_code_expires_at": expires_at,
                    "status": "idle",
                }
            )
            .eq("machine_id", machine_id)
            .execute()
        )

    await asyncio.to_thread(lambda: _retry_supabase_query(_update_machine))
    return {"new_display_code": display_code}


async def confirm_dispense_db(machine_id: str, transaction_id: str, dispensed: int):
    """Mark transaction as completed and clear lock; return new display code.
    Returns {'error': ...} on failure or {'new_display_code': ...} on success.
    """
    # fetch transaction
    # Convert external transaction_id to deterministic UUIDv5 used as primary key
    try:
        tx_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, str(transaction_id)))
    except Exception:
        tx_uuid = str(uuid.uuid4())

    def _get_tx():
        return (
            supabase.table("transactions")
            .select("*")
            .eq("id", tx_uuid)
            .single()
            .execute()
        )

    res = await asyncio.to_thread(lambda: _retry_supabase_query(_get_tx))
    tx = _res_data(res)
    if not tx:
        return {"error": "tx_not_found"}

    # update transaction
    def _update_tx():
        return (
            supabase.table("transactions")
            .update(
                {
                    "dispensed": dispensed,
                    "payment_status": "completed",
                    "completed_at": _now().isoformat(),
                }
            )
            .eq("id", tx_uuid)
            .execute()
        )

    await asyncio.to_thread(lambda: _retry_supabase_query(_update_tx))

    # decrement machine stock by dispensed quantity (non-negative)
    try:

        def _get_machine():
            return (
                supabase.table("machines")
                .select("current_stock")
                .eq("machine_id", machine_id)
                .single()
                .execute()
            )

        mres = await asyncio.to_thread(lambda: _retry_supabase_query(_get_machine))

        mdata = _res_data(mres)
        if mdata is not None and isinstance(mdata, dict):
            current = int(mdata.get("current_stock") or 0)
            new_stock = max(0, current - int(dispensed or 0))
            print("Newstockkk   ", new_stock)

            def _update_stock():
                # Update status to 'Unavailable' if stock reaches 0
                update_data = {"current_stock": new_stock}
                if new_stock <= 0:
                    update_data["status"] = "Unavailable"
                return (
                    supabase.table("machines")
                    .update(update_data)
                    .eq("machine_id", machine_id)
                    .execute()
                )

            await asyncio.to_thread(lambda: _retry_supabase_query(_update_stock))
    except Exception as e:
        # best-effort; log and continue
        print(f"Stock decrement error for {machine_id}: {e}")

    # clear lock for machine
    def _delete_lock():
        return supabase.table("locks").delete().eq("machine_id", machine_id).execute()

    await asyncio.to_thread(lambda: _retry_supabase_query(_delete_lock))

    # new display code
    ttl = int(DISPLAY_CODE_TTL_MINUTES) if DISPLAY_CODE_TTL_MINUTES else 10
    display_code = f"{secrets.randbelow(900000) + 100000}"
    expires_at = (_now() + timedelta(minutes=ttl)).isoformat()

    def _update_machine():
        return (
            supabase.table("machines")
            .update(
                {
                    "display_code": display_code,
                    "display_code_expires_at": expires_at,
                    "status": "idle",
                }
            )
            .eq("machine_id", machine_id)
            .execute()
        )

    await asyncio.to_thread(lambda: _retry_supabase_query(_update_machine))
    return {"new_display_code": display_code}


async def lock_by_code(client_id: str, code: str, ttl_minutes: int):
    """Attempt to claim a machine using a display code. Returns None on server error or
    a dict with error or success info.
    """

    # find machine by display_code and not expired
    def _find_machine():
        return supabase.table("machines").select("*").eq("display_code", code).execute()

    res = await asyncio.to_thread(lambda: _retry_supabase_query(_find_machine))
    data = _res_data(res)
    if not data:
        return {"error": "code_not_found"}
    # data may be a list
    machine = data[0] if isinstance(data, list) else data

    # check expiry
    exp = machine.get("display_code_expires_at")
    if not exp or _now().isoformat() > exp:
        return {"error": "code_not_found"}

    machine_id = machine.get("machine_id")

    # check existing lock
    def _get_lock():
        query = (
            supabase.table("locks").select("*").eq("machine_id", machine_id).execute()
        )
        data = query.data
        if not data:
            return None  # or handle appropriately
        return data[0]  # first record if multiple found

    res_lock = await asyncio.to_thread(lambda: _retry_supabase_query(_get_lock))
    lock = res_lock
    if (
        lock
        and lock.get("status") == "locked"
        and lock.get("expires_at")
        and _now().isoformat() < lock.get("expires_at")
    ):
        return {"error": "busy", "machine_id": machine_id}

    # create/update lock
    ttl = (
        int(ttl_minutes)
        if ttl_minutes
        else int(DISPLAY_CODE_TTL_MINUTES)
        if DISPLAY_CODE_TTL_MINUTES
        else 10
    )
    expires_at = (_now() + timedelta(minutes=ttl)).isoformat()
    access_code_hash = _hash_code(code)

    payload = {
        "machine_id": machine_id,
        "locked_by": client_id,
        "access_code_hash": access_code_hash,
        "locked_at": _now().isoformat(),
        "expires_at": expires_at,
        "status": "locked",
    }
    print(payload)

    def _upsert_lock():
        return supabase.table("locks").upsert(payload).execute()

    await asyncio.to_thread(lambda: _retry_supabase_query(_upsert_lock))

    # mark machine as locked
    def _update_machine_locked():
        return (
            supabase.table("machines")
            .update({"status": "locked"})
            .eq("machine_id", machine_id)
            .execute()
        )

    await asyncio.to_thread(lambda: _retry_supabase_query(_update_machine_locked))
    return {"machine_id": machine_id, "status": "locked", "expires_at": expires_at}


async def expire_lock_and_rotate_code(machine_id: str):
    """Expire any active lock for machine_id if past expires_at; rotate display code; set status idle.
    Returns dict with fields or None if no action.
    """
    if not supabase:
        return None

    def _get_lock():
        return (
            supabase.table("locks")
            .select("*")
            .eq("machine_id", machine_id)
            .single()
            .execute()
        )

    res = await asyncio.to_thread(lambda: _retry_supabase_query(_get_lock))
    lock = _res_data(res)
    if not lock or lock.get("status") != "locked":
        return None
    if not lock.get("expires_at") or _now().isoformat() < lock.get("expires_at"):
        return None

    # delete lock
    def _delete_lock():
        return supabase.table("locks").delete().eq("machine_id", machine_id).execute()

    await asyncio.to_thread(lambda: _retry_supabase_query(_delete_lock))

    # rotate code
    ttl = int(DISPLAY_CODE_TTL_MINUTES) if DISPLAY_CODE_TTL_MINUTES else 10
    display_code = f"{secrets.randbelow(900000) + 100000}"
    expires_at = (_now() + timedelta(minutes=ttl)).isoformat()

    def _update_machine():
        return (
            supabase.table("machines")
            .update(
                {
                    "display_code": display_code,
                    "display_code_expires_at": expires_at,
                    "status": "idle",
                }
            )
            .eq("machine_id", machine_id)
            .execute()
        )

    await asyncio.to_thread(lambda: _retry_supabase_query(_update_machine))
    return {"new_display_code": display_code, "display_code_expires_at": expires_at}


async def trigger_dispense_db(
    machine_id: str,
    client_id: str,
    access_code: str,
    quantity: int,
    transaction_id: str,
    amount: int,
):
    """Validate lock and record a transaction. Returns dict with error or success."""

    # fetch lock
    def _get_lock():
        return (
            supabase.table("locks")
            .select("*")
            .eq("machine_id", machine_id)
            .single()
            .execute()
        )

    res = await asyncio.to_thread(lambda: _retry_supabase_query(_get_lock))
    lock = _res_data(res)
    if not lock or lock.get("status") != "locked":
        return {"error": "no_lock"}
    if lock.get("locked_by") != client_id:
        return {"error": "not_owner"}
    if lock.get("expires_at") and _now().isoformat() > lock.get("expires_at"):
        return {"error": "expired"}

    if lock.get("access_code_hash") != _hash_code(access_code):
        return {"error": "access_mismatch"}

    # create transaction row (DB expects UUID in id). Derive stable UUIDv5 from external id
    try:
        tx_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, str(transaction_id)))
    except Exception:
        tx_uuid = str(uuid.uuid4())

    tx_payload = {
        "id": tx_uuid,
        "machine_id": machine_id,
        "client_id": client_id,
        "access_code": access_code,
        "amount": amount,
        "quantity": quantity,
        "payment_status": "paid",
        "created_at": _now().isoformat(),
    }

    def _insert_tx():
        return supabase.table("transactions").insert(tx_payload).execute()

    await asyncio.to_thread(lambda: _retry_supabase_query(_insert_tx))

    # mark lock as consumed (keep row for history)
    def _update_lock():
        return (
            supabase.table("locks")
            .update({"status": "consumed"})
            .eq("machine_id", machine_id)
            .execute()
        )

    await asyncio.to_thread(lambda: _retry_supabase_query(_update_lock))

    # update machine status
    def _update_machine():
        return (
            supabase.table("machines")
            .update({"status": "dispatch_sent"})
            .eq("machine_id", machine_id)
            .execute()
        )

    await asyncio.to_thread(lambda: _retry_supabase_query(_update_machine))

    return {"status": "ok"}


async def set_machine_last_seen(machine_id: str):
    """Update the machine's last_seen_at timestamp (best-effort)."""
    if not supabase:
        return None

    def _update():
        return (
            supabase.table("machines")
            .update({"last_seen_at": _now().isoformat()})
            .eq("machine_id", machine_id)
            .execute()
        )

    try:
        res = await asyncio.to_thread(lambda: _retry_supabase_query(_update))
        return _res_data(res)
    except Exception:
        return None


async def update_machine_status(machine_id: str, status: str):
    """Update the machine's status."""
    if not supabase:
        return None

    def _update():
        return (
            supabase.table("machines")
            .update({"status": status})
            .eq("machine_id", machine_id)
            .execute()
        )

    try:
        res = await asyncio.to_thread(lambda: _retry_supabase_query(_update))
        return _res_data(res)
    except Exception:
        return None


async def update_machine_stock(machine_id: str, new_stock: int):
    """Update machine's stock level and last refill timestamp.
    Updates status to 'Unavailable' if stock is 0, otherwise sets status to 'idle' if it was 'Unavailable'."""
    if not supabase:
        return None

    # Check current status if stock is being refilled (new_stock > 0)
    current_status = None
    if new_stock > 0:

        def _get_current_status():
            res = (
                supabase.table("machines")
                .select("status")
                .eq("machine_id", machine_id)
                .single()
                .execute()
            )
            return _res_data(res)

        try:
            current_machine = await asyncio.to_thread(
                lambda: _retry_supabase_query(_get_current_status)
            )
            current_status = current_machine.get("status") if current_machine else None
        except Exception:
            pass

    def _update():
        update_data = {"current_stock": new_stock, "last_refill_at": _now().isoformat()}
        # Update status based on stock level
        if new_stock <= 0:
            update_data["status"] = "Unavailable"
        elif current_status == "Unavailable":
            # If stock is being refilled and machine was unavailable, set it back to idle
            update_data["status"] = "idle"

        return (
            supabase.table("machines")
            .update(update_data)
            .eq("machine_id", machine_id)
            .execute()
        )

    try:
        res = await asyncio.to_thread(lambda: _retry_supabase_query(_update))
        return _res_data(res)
    except Exception as e:
        print(f"Stock update error: {e}")
        return None


async def get_or_refresh_display_code(
    machine_id: str, ttl_minutes: Optional[int] = None
):
    """Return the current display code for the machine. If expired (or missing), generate a new one,
    update the DB and return it. Returns dict: { 'display_code': str, 'display_code_expires_at': iso } or None if machine missing.
    """
    if not supabase:
        return None

    def _get():
        return (
            supabase.table("machines")
            .select("*")
            .eq("machine_id", machine_id)
            .execute()
        )

    res = await asyncio.to_thread(lambda: _retry_supabase_query(_get))
    data = _res_data(res)
    if not data:
        return None
    m = data[0] if isinstance(data, list) else data

    exp = m.get("display_code_expires_at")
    now_iso = _now().isoformat()
    ttl = (
        int(ttl_minutes)
        if ttl_minutes
        else int(DISPLAY_CODE_TTL_MINUTES)
        if DISPLAY_CODE_TTL_MINUTES
        else 10
    )

    if not exp or now_iso > exp:
        # expired -> generate new
        display_code = f"{secrets.randbelow(900000) + 100000}"
        expires_at = (_now() + timedelta(minutes=ttl)).isoformat()

        def _update_machine():
            return (
                supabase.table("machines")
                .update(
                    {
                        "display_code": display_code,
                        "display_code_expires_at": expires_at,
                    }
                )
                .eq("machine_id", machine_id)
                .execute()
            )

        await asyncio.to_thread(lambda: _retry_supabase_query(_update_machine))
        return {"display_code": display_code, "display_code_expires_at": expires_at}
    else:
        return {"display_code": m.get("display_code"), "display_code_expires_at": exp}
