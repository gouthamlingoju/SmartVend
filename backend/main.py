import asyncio
import contextlib
import json
import os
import secrets
import smtplib
from contextlib import asynccontextmanager
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional, Set

import razorpay
import redis.asyncio as aioredis
import uvicorn
from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from services.email_service import send_email_async
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, constr

from auth import AuthHandler
import database as db
from config import (
    ADMIN_PASSWORD,
    DISPLAY_CODE_TTL_MINUTES,
    FRONTEND_URL,
    PRICE_PER_UNIT_PAISA,
    RAZORPAY_KEY_ID,
    RAZORPAY_SECRET_KEY,
    RAZORPAY_WEBHOOK_SECRET,
    RECEIVER_EMAIL,
    REDIS_URL,
    SENDER_EMAIL,
    SENDER_PASSWORD,
    SMTP_PORT,
    SMTP_SERVER,
)
from services import machine_service, payment_service

# FIX: architecture_review.md — "Rate Limiting"
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Load environment variables

pending_http_commands: Dict[str, List[Dict[str, Any]]] = {}

# FIX: architecture_review.md — "Idempotency"
# In-memory set of already-processed transaction IDs to prevent duplicate dispenses.
# NOTE: For multi-worker deployments, replace with Redis SET or DB lookup.
_processed_transactions: Set[str] = set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start/stop resources in a Render-friendly way."""
    global redis_client, redis_listener_task, lock_sweeper_task
    try:
        await db.init_pool()
        if db.pool:
            print("DB pool initialized")
    except Exception as e:
        print("DB pool init error:", e)

    try:
        if REDIS_URL:
            redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)
            redis_listener_task = asyncio.create_task(
                _redis_pubsub_listener(redis_client)
            )
            print("Redis pubsub listener started")
    except Exception as e:
        print("Redis init error:", e)

    try:
        lock_sweeper_task = asyncio.create_task(_lock_expiry_sweeper())
        print("Lock expiry sweeper started")
    except Exception as e:
        print("Lock sweeper start error:", e)

    try:
        yield
    finally:
        try:
            if lock_sweeper_task:
                lock_sweeper_task.cancel()
                with contextlib.suppress(Exception):
                    await lock_sweeper_task
        except Exception:
            pass
        try:
            if redis_listener_task:
                redis_listener_task.cancel()
                with contextlib.suppress(Exception):
                    await redis_listener_task
        except Exception:
            pass
        try:
            if redis_client:
                with contextlib.suppress(Exception):
                    await redis_client.close()
        except Exception:
            pass
        try:
            await db.close_pool()
        except Exception:
            pass


app = FastAPI(title="SmartVend Cloud Backend", lifespan=lifespan)

# Initialize auth handler
auth_handler = AuthHandler()
# For demo purposes - in production, use a secure password and store hashed
ADMIN_PASSWORD_HASH = auth_handler.get_password_hash(ADMIN_PASSWORD)

# In-memory map of connected machines: machine_id -> WebSocket
# When an ESP32 connects it should send a first message: { "type": "register", "machine_id": "<id>" }
connected_machines: dict = {}
redis_client = None
redis_listener_task = None
lock_sweeper_task = None
REDIS_CHANNEL = "ws:commands"


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for ESP32 devices.
    Protocol (JSON messages):
      - {"type":"register", "machine_id":"...", "api_key":"..."}
      - {"type":"status", "value":"active|locked|unlocked"}
      - {"type":"fetch_display"}
      - server responses: {"type":"display_code","value":"1234"} or {"type":"command","action":"dispense","duration":1}
    """
    await websocket.accept()
    machine_id = None
    heartbeat_task = None

    async def heartbeat():
        """Send periodic pings to keep connection alive"""
        try:
            while True:
                await asyncio.sleep(30)  # Send heartbeat every 30 seconds
                await websocket.send_text(json.dumps({"type": "ping"}))
        except Exception:
            pass  # Task will be cancelled on disconnect

    try:
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=75)
            except asyncio.TimeoutError:
                # keep-alive on idle
                try:
                    await websocket.send_text(json.dumps({"type": "ping"}))
                except Exception:
                    break
                continue
            try:
                msg = json.loads(data)
            except Exception:
                print("Invalid WS JSON:", data)
                continue

            mtype = msg.get("type")

            # Registration message binds this WebSocket to a machine_id
            if mtype == "register":
                machine_id = msg.get("machine_id")
                api_key = msg.get("api_key")
                if machine_id:
                    # Remove old connection if exists
                    if machine_id in connected_machines:
                        try:
                            await connected_machines[machine_id].close()
                        except Exception:
                            pass
                    connected_machines[machine_id] = websocket
                    # Start heartbeat for this connection
                    heartbeat_task = asyncio.create_task(heartbeat())
                    print(f"WebSocket: registered machine {machine_id}")
                    # Optionally upsert machine record in DB (keeps server in sync)
                    try:
                        if db.pool:
                            await db.upsert_machine(
                                machine_id, api_key or "none", DISPLAY_CODE_TTL_MINUTES
                            )
                    except Exception as e:
                        print("DB upsert during WS register failed:", e)

            elif mtype == "status":
                # status updates from device; simply log for now and optionally update DB
                value = msg.get("value")
                print(f"WS status from {machine_id}: {value}")
                # update DB heartbeat / last_seen
                try:
                    if machine_id and db.pool:
                        await db.set_machine_last_seen(machine_id)
                        if value == "active":
                            await db.update_machine_status(machine_id, "active")
                except Exception as e:
                    print(f"Error updating machine status for {machine_id}: {e}")

            elif mtype == "fetch_display":
                # Device asks for its current display code; check DB and refresh if expired
                if not machine_id:
                    await websocket.send_text(
                        json.dumps({"type": "error", "error": "not_registered"})
                    )
                    continue
                try:
                    if db.pool:
                        info = await db.get_or_refresh_display_code(machine_id)
                        if info and info.get("display_code"):
                            payload = {
                                "type": "display_code",
                                "value": info.get("display_code"),
                            }
                            await websocket.send_text(json.dumps(payload))
                            print(f"Sent display_code to {machine_id}")
                        else:
                            await websocket.send_text(
                                json.dumps({"type": "display_code", "value": "----"})
                            )
                    else:
                        await websocket.send_text(
                            json.dumps({"type": "display_code", "value": "----"})
                        )
                except Exception as e:
                    print("Error responding to fetch_display:", e)

            else:
                # Unknown message type — log and continue
                print("WS unknown message:", msg)

    except WebSocketDisconnect:
        print("WebSocket disconnected", machine_id)
        if machine_id and connected_machines.get(machine_id) is websocket:
            connected_machines.pop(machine_id, None)
            try:
                if db.pool:
                    await db.update_machine_status(machine_id, "offline")
            except Exception as e:
                print(f"Error updating machine status to offline for {machine_id}: {e}")
    except Exception as e:
        print("WebSocket error:", e)
        if machine_id and connected_machines.get(machine_id) is websocket:
            connected_machines.pop(machine_id, None)


async def _redis_pubsub_listener(rclient):
    """Background task that listens for published WS commands and forwards to local sockets."""
    pubsub = None
    try:
        pubsub = rclient.pubsub()
        await pubsub.subscribe(REDIS_CHANNEL)
        print(f"Subscribed to redis channel {REDIS_CHANNEL}")
        while True:
            try:
                msg = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if not msg:
                    await asyncio.sleep(0.01)
                    continue
                data = msg.get("data")
                if not data:
                    continue
                if isinstance(data, (bytes, bytearray)):
                    data = data.decode()
                try:
                    obj = json.loads(data)
                except Exception:
                    print("Invalid redis WS payload:", data)
                    continue
                machine = obj.get("machine_id")
                payload = obj.get("payload")
                if machine and payload:
                    ws = connected_machines.get(machine)
                    if ws:
                        try:
                            await ws.send_text(json.dumps(payload))
                            print(f"Forwarded redis payload to {machine}")
                        except Exception as e:
                            print("Error forwarding to ws client:", e)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                # loop continues on transient errors
                print("Redis pubsub listener error:", e)
                await asyncio.sleep(1)
    finally:
        try:
            if pubsub:
                await pubsub.unsubscribe(REDIS_CHANNEL)
        except Exception:
            pass


class TelemetryPayload(BaseModel):
    proto: int = Field(1, ge=1, le=1)
    device_id: constr(strip_whitespace=True, min_length=1)
    status: Optional[str] = None
    rssi: Optional[int] = Field(None, ge=-120, le=0)
    battery: Optional[float] = Field(None, ge=0, le=100)
    ts: Optional[datetime] = None
    metadata: Optional[Dict[str, Any]] = None


class CommandResponse(BaseModel):
    commands: List[Dict[str, Any]]
    count: int


# ============ CORS ============
# FIX: architecture_review.md — "CORS Scoping"
# Removed wildcard "*" — only allow known frontend origins.
origins = [FRONTEND_URL, "http://localhost:5174"]
# filter out None / empty
origins = [o for o in origins if o]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# FIX: architecture_review.md — "Rate Limiting"
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        {"error": "Too many requests. Please slow down."},
        status_code=429,
    )


@app.get("/health")
async def health_check():
    return {"status": "ok"}


# FIX: architecture_review.md — "Unify Frontend Data Access"
# New endpoint so the frontend fetches machines via backend, not direct Supabase.
@app.get("/api/machines")
async def list_machines():
    """Return all machines. Public endpoint for the frontend machine-list view."""
    if not db.pool:
        raise HTTPException(status_code=500, detail="Database not configured")
    machines = await db.get_all_machines()
    # Apply out_of_stock derivation server-side (was previously done client-side)
    for m in machines:
        if m.get("status") == "working" and (m.get("current_stock") or 0) <= 0:
            m["status"] = "out_of_stock"
    return machines


# FIX: architecture_review.md — "Rate Limiting"
@app.post("/api/admin/login")
@limiter.limit("5/minute")
async def admin_login(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    password = data.get("password")
    if not password:
        raise HTTPException(status_code=400, detail="Password is required")

    if not auth_handler.verify_password(password, ADMIN_PASSWORD_HASH):
        raise HTTPException(status_code=401, detail="Invalid password")

    token = auth_handler.encode_token("admin")
    
    # Send login alert email in background
    subject = "SmartVend Admin Login Alert"
    body = f"An admin logged in at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}."
    background_tasks.add_task(send_email_async, subject, body)

    return {"token": token}


@app.get("/api/admin/verify")
def verify_token(user_id=Depends(auth_handler.auth_wrapper)):
    return {"status": "valid", "user_id": user_id}


@app.post("/api/machine/{machine_id}/update-stock")
async def update_machine_stock(
    machine_id: str, request: Request, user_id=Depends(auth_handler.auth_wrapper)):
    """Update machine stock levels after refill. Requires admin authentication."""
    if not db.pool:
        raise HTTPException(status_code=500, detail="Database not configured")

    data = await request.json()
    new_stock = data.get("stock")

    if new_stock is None:
        raise HTTPException(status_code=400, detail="New stock level required")

    try:
        new_stock = int(new_stock)
        if new_stock < 0:
            raise ValueError("Stock cannot be negative")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Update stock in database
    result = await db.update_machine_stock(machine_id, new_stock)
    if result is None:
        raise HTTPException(status_code=500, detail="Failed to update stock")

    # Notify connected device (if present) and publish via Redis for other workers
    payload = {"type": "stock_update", "stock": new_stock}
    try:
        ws = connected_machines.get(machine_id)
        if ws:
            try:
                await ws.send_text(json.dumps(payload))
                print(f"Sent stock_update WS to {machine_id}")
            except Exception as e:
                print("Failed to send WS stock_update to local client:", e)

        # publish to redis so other workers can forward
        if redis_client:
            try:
                await redis_client.publish(
                    REDIS_CHANNEL,
                    json.dumps({"machine_id": machine_id, "payload": payload}),
                )
            except Exception as e:
                print("Failed to publish stock_update to redis:", e)
    except Exception:
        pass

    return {"status": "success", "current_stock": new_stock}


# ============ Razorpay Setup ============
razorpay_client = None
if RAZORPAY_KEY_ID and RAZORPAY_SECRET_KEY:
    razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_SECRET_KEY))
else:
    print("WARNING: Razorpay credentials missing; payment endpoints will return errors.")

# Use Supabase/Postgres as the single source of truth. In-memory stores removed.


# ============ Auth Helper ============
async def verify_api_key(machine_id: str, authorization: Optional[str]):
    """Verify the provided machine API key against the DB. Raises HTTPException on failure."""
    if not db.pool:
        raise HTTPException(status_code=500, detail="Database not configured")

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    provided = authorization.split(" ")[1].strip()
    m = await db.get_machine_by_id(machine_id)
    if not m:
        raise HTTPException(status_code=404, detail="Machine not registered")

    expected_key = m.get("api_key")
    if not expected_key or not secrets.compare_digest(provided, expected_key):
        raise HTTPException(status_code=401, detail="Invalid API key")


# ============ ESP32 Communication APIs ============
@app.post("/api/machine/register")
async def register_machine(request: Request):
    """ESP32 calls this once on boot"""
    data = await request.json()
    machine_id = data.get("machine_id")
    if not machine_id:
        raise HTTPException(status_code=400, detail="Missing machine_id")
    # DB-only mode: require database and upsert machine record
    if not db.pool:
        raise HTTPException(status_code=500, detail="Database not configured")

    api_key = data.get("api_key", "none")
    res = await db.upsert_machine(machine_id, api_key, DISPLAY_CODE_TTL_MINUTES)
    if not res:
        raise HTTPException(status_code=500, detail="Failed to upsert machine")
    return {
        "message": f"Machine {machine_id} registered",
        "status": "ok",
        "display_code": res.get("display_code"),
        "display_code_expires_at": res.get("display_code_expires_at"),
    }


@app.get("/api/machine/{machine_id}/status")
async def get_machine_status(
    machine_id: str, authorization: Optional[str] = Header(None)):
    """ESP32 polls this every few seconds"""
    # DB-backed: validate API key and return machine status
    if not db.pool:
        raise HTTPException(status_code=500, detail="Database not configured")

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    provided = authorization.split(" ")[1].strip()
    status = await db.get_machine_status_for_esp32(machine_id, provided)
    if not status:
        # either machine not found or API key mismatch
        raise HTTPException(
            status_code=401, detail="Invalid credentials or machine not found"
        )
    return status


@app.get("/api/machine/{machine_id}/public-status")
async def get_machine_public_status(machine_id: str, client_id: Optional[str] = None):
    """Public status for frontend use. Does NOT require machine API key.
    If client_id provided, locked_by is revealed only when it matches.
    """
    if not db.pool:
        raise HTTPException(status_code=500, detail="Database not configured")
    s = await db.get_public_status(machine_id, client_id)
    if not s:
        raise HTTPException(status_code=404, detail="Machine not found")
    return s


@app.post("/api/machine/{machine_id}/unlock")
async def unlock_by_client(machine_id: str, request: Request):
    """Allow the client who locked the machine to manually unlock it before TTL."""
    if not db.pool:
        raise HTTPException(status_code=500, detail="Database not configured")
    data = await request.json()
    client_id = data.get("client_id")
    if not client_id:
        raise HTTPException(status_code=400, detail="client_id required")

    res = await db.unlock_by_client_db(machine_id, client_id)
    if res.get("error"):
        if res["error"] == "no_lock":
            raise HTTPException(status_code=409, detail="No active lock to unlock")
        if res["error"] == "not_owner":
            raise HTTPException(status_code=403, detail="Lock not owned by this client")
    # notify device via WS and redis
    try:
        payload = {"type": "unlock"}
        pending_http_commands.setdefault(machine_id, []).append(payload)
        ws = connected_machines.get(machine_id)
        if ws:
            try:
                await ws.send_text(json.dumps(payload))
                # also push fresh display code to device
                if res.get("new_display_code"):
                    await ws.send_text(
                        json.dumps(
                            {
                                "type": "display_code",
                                "value": res.get("new_display_code"),
                            }
                        )
                    )
            except Exception:
                pass
        if redis_client:
            try:
                await redis_client.publish(
                    REDIS_CHANNEL,
                    json.dumps({"machine_id": machine_id, "payload": payload}),
                )
            except Exception:
                pass
    except Exception:
        pass
    return {"status": "unlocked", "new_display_code": res.get("new_display_code")}


@app.post("/api/machine/{machine_id}/confirm")
async def confirm_dispense(
    machine_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    authorization: Optional[str] = Header(None),
):
    """ESP32 confirms dispensing success"""
    # verify API key
    await verify_api_key(machine_id, authorization)
    data = await request.json()
    dispensed = int(data.get("dispensed", 0))
    transaction_id = data.get("transaction_id")

    if not db.pool:
        raise HTTPException(status_code=500, detail="Database not configured")

    res = await db.confirm_dispense_db(machine_id, transaction_id, dispensed)
    if res.get("error"):
        return JSONResponse(
            {"message": "confirm_failed", "error": res["error"]}, status_code=400
        )

    if res.get("low_stock_triggered"):
        subject = f"Low Stock Alert - {machine_id}"
        remaining = res.get("remaining_stock", 0)
        body = f"Machine {machine_id} stock just crossed the low-threshold.\nRemaining stock: {remaining}."
        background_tasks.add_task(send_email_async, subject, body)
        print(f"Low stock alert queued automatically for {machine_id} (remaining: {remaining})")

    # notify device to unlock
    try:
        payload = {"type": "unlock"}
        ws = connected_machines.get(machine_id)
        if ws:
            try:
                await ws.send_text(json.dumps(payload))
                # also push fresh display code to device
                if res.get("new_display_code"):
                    await ws.send_text(
                        json.dumps(
                            {
                                "type": "display_code",
                                "value": res.get("new_display_code"),
                            }
                        )
                    )
            except Exception:
                pass
        if redis_client:
            try:
                await redis_client.publish(
                    REDIS_CHANNEL,
                    json.dumps({"machine_id": machine_id, "payload": payload}),
                )
            except Exception:
                pass
    except Exception:
        pass

    return {
        "status": "confirmed",
        "dispensed": dispensed,
        "new_display_code": res.get("new_display_code"),
    }


@app.post("/api/machine/{machine_id}/report-error")
async def report_error(
    machine_id: str, request: Request, authorization: Optional[str] = Header(None)
):
    """ESP32 sends timeout or failure reports"""
    await verify_api_key(machine_id, authorization)
    data = await request.json()
    err = data.get("error")
    print(f"Error from machine {machine_id}: {err}")
    # Optionally, we could write this to an events table. For now just ack.
    return {"message": "Error logged"}


# In DB-backed mode display codes and lock expiry are managed in the database.


# ============ Frontend → ESP32 Dispense Trigger ============
@app.post("/api/machine/{machine_id}/dispense")
async def trigger_dispense(machine_id: str, request: Request):
    """Frontend (React) calls this after payment verification"""
    # Deprecated/legacy endpoint. Use /api/machine/{machine_id}/trigger-dispense (server-verified) instead.
    return JSONResponse(
        {"error": "use /api/machine/{machine_id}/trigger-dispense (server-side)"},
        status_code=400,
    )


# FIX: architecture_review.md — "Rate Limiting"
@app.post("/api/lock-by-code")
@limiter.limit("10/minute")
async def lock_by_code(request: Request):
    """Frontend posts { client_id, code } to lock the machine atomically (in-memory simplified)
    This stores access_code_hash in locks and sets machine status to 'locked'.
    """
    if not db.pool:
        return JSONResponse(
            {"error": "Database not configured. Locking requires Supabase/Postgres."},
            status_code=500,
        )

    data = await request.json()
    client_id = data.get("client_id")
    code = data.get("code")
    if not client_id or not code:
        raise HTTPException(status_code=400, detail="client_id and code required")

    res = await db.lock_by_code(client_id, code, DISPLAY_CODE_TTL_MINUTES)
    if res is None:
        raise HTTPException(status_code=500, detail="Lock failed")
    if res.get("error"):
        if res["error"] == "code_not_found":
            raise HTTPException(status_code=400, detail="Code not found or expired")
        if res["error"] == "busy":
            # fetch lock info for machine
            status = await db.get_public_status(res.get("machine_id"))
            return JSONResponse(
                {
                    "status": "busy",
                    "message": "Machine is already locked by another user",
                    "locked_by": status.get("locked_by"),
                    "locked_until": status.get("expires_at"),
                },
                status_code=409,
            )
        raise HTTPException(status_code=400, detail=res.get("error"))

    # notify device to lock for the duration
    try:
        machine_id = res.get("machine_id")
        payload = {"type": "lock", "expires_at": res.get("expires_at")}
        if machine_id:
            pending_http_commands.setdefault(machine_id, []).append(payload)
        ws = connected_machines.get(machine_id)
        if ws:
            try:
                await ws.send_text(json.dumps(payload))
                print(f"Sent lock WS to {machine_id}")
            except Exception as e:
                print("Failed to send WS lock:", e)
        if redis_client and machine_id:
            try:
                await redis_client.publish(
                    REDIS_CHANNEL,
                    json.dumps({"machine_id": machine_id, "payload": payload}),
                )
            except Exception as e:
                print("Failed to publish lock to redis:", e)
    except Exception:
        pass
    return JSONResponse(res)


@app.post("/api/machine/{machine_id}/trigger-dispense")
async def trigger_dispense_validated(machine_id: str, request: Request):
    """Called by backend after payment verification to instruct machine to dispense.
    Validates the lock, client and access_code hash before changing machine state.
    Body: { client_id, access_code, quantity, transaction_id }
    """
    if not db.pool:
        return JSONResponse(
            {
                "error": "Database not configured. Trigger-dispense requires Supabase/Postgres."
            },
            status_code=500,
        )

    data = await request.json()
    client_id = data.get("client_id")
    access_code = data.get("access_code")
    quantity = int(data.get("quantity", 1))
    transaction_id = data.get("transaction_id")

    if not client_id or not access_code or not transaction_id:
        raise HTTPException(
            status_code=400, detail="client_id, access_code and transaction_id required"
        )

    # FIX: architecture_review.md — "Idempotency"
    # Reject duplicate dispense requests for the same transaction_id.
    if transaction_id in _processed_transactions:
        return JSONResponse(
            {"error": "Transaction already processed", "status": "duplicate"},
            status_code=409,
        )
    _processed_transactions.add(transaction_id)

    amount = quantity * PRICE_PER_UNIT_PAISA  # calculate server-side

    res = await db.trigger_dispense_db(
        machine_id, client_id, access_code, quantity, transaction_id, amount
    )
    if res.get("error"):
        err = res["error"]
        if err == "no_lock" or err == "expired":
            raise HTTPException(
                status_code=409, detail="No active lock or lock expired"
            )
        if err == "not_owner":
            raise HTTPException(status_code=403, detail="Lock not owned by this client")
        if err == "access_mismatch":
            raise HTTPException(status_code=403, detail="Access code mismatch")
        return JSONResponse({"error": err}, status_code=400)

    # If the machine is connected over WebSocket, send a dispense command (best-effort)
    try:
        payload = {
            "type": "command",
            "action": "dispense",
            "duration": quantity,
            "transaction_id": transaction_id,
        }
        pending_http_commands.setdefault(machine_id, []).append(payload)
        # Attempt local delivery
        ws = connected_machines.get(machine_id)
        if ws:
            try:
                await ws.send_text(json.dumps(payload))
                print(
                    f"Sent dispense command to {machine_id} (quantity={quantity}) via WebSocket"
                )
            except Exception as e:
                print(f"Local WS send failed for {machine_id}:", e)

        # Publish to Redis so other workers can forward to their connected sockets (best-effort)
        try:
            if redis_client:
                await redis_client.publish(
                    REDIS_CHANNEL,
                    json.dumps({"machine_id": machine_id, "payload": payload}),
                )
        except Exception as e:
            print("Redis publish failed:", e)
    except Exception as e:
        print(f"Failed to send WS command to {machine_id}:", e)

    return JSONResponse({"status": "dispatch_sent"})


@app.post("/device/telemetry")
async def ingest_telemetry(payload: TelemetryPayload):
    """HTTP fallback when WS is unavailable; best-effort status update."""
    device_id = payload.device_id
    if db.pool:
        try:
            await db.set_machine_last_seen(device_id)
            if payload.status in {"active", "idle", "locked"}:
                await db.update_machine_status(device_id, payload.status)
        except Exception as e:
            print(f"Telemetry update error for {device_id}: {e}")
    return {"status": "ok", "proto": payload.proto}


@app.get("/device/commands/{device_id}", response_model=CommandResponse)
async def get_device_commands(device_id: str):
    """HTTP polling fallback for ESP32 when WS is unavailable."""
    cmds = pending_http_commands.pop(device_id, [])
    return CommandResponse(commands=cmds, count=len(cmds))


async def _lock_expiry_sweeper():
    """Periodically checks for expired locks and unlocks machines, rotates display codes,
    and notifies devices via websocket/redis.
    """
    while True:
        try:
            await asyncio.sleep(2)
            # naive approach: get all machines that might have locks and attempt expiry
            # If needed, optimize by querying locks table for expired rows via RPC.
            # Here we iterate connected machines as a lightweight heuristic.
            for machine_id in list(connected_machines.keys()):
                try:
                    res = await db.expire_lock_and_rotate_code(machine_id)
                    if res:
                        payload = {"type": "unlock"}
                        pending_http_commands.setdefault(machine_id, []).append(
                            payload
                        )
                        ws = connected_machines.get(machine_id)
                        if ws:
                            try:
                                await ws.send_text(json.dumps(payload))
                                # push fresh display code after expiry
                                if res.get("new_display_code"):
                                    await ws.send_text(
                                        json.dumps(
                                            {
                                                "type": "display_code",
                                                "value": res.get("new_display_code"),
                                            }
                                        )
                                    )
                            except Exception:
                                pass
                        if redis_client:
                            try:
                                await redis_client.publish(
                                    REDIS_CHANNEL,
                                    json.dumps(
                                        {"machine_id": machine_id, "payload": payload}
                                    ),
                                )
                            except Exception:
                                pass
                except Exception:
                    pass
        except asyncio.CancelledError:
            break
        except Exception:
            await asyncio.sleep(1)


# ============ Payment and Alert Routes (from your existing code) ============
@app.post("/create-order")
async def create_order(request: Request):
    if not razorpay_client:
        return JSONResponse({"error": "Razorpay not configured"}, status_code=500)
    try:
        data = await request.json()
        quantity = int(data.get("quantity", 1))
        if quantity <= 0:
            return JSONResponse({"error": "Quantity must be positive"}, status_code=400)

        # FIX: architecture_review.md — "Stock Reservation"
        # Check stock availability before taking payment to prevent paying for unavailable items.
        machine_id = data.get("machine_id")
        if machine_id:
            stock_ok = await db.check_stock_available(machine_id, quantity)
            if not stock_ok:
                return JSONResponse(
                    {"error": "Insufficient stock for requested quantity"},
                    status_code=409,
                )

        amount = quantity * PRICE_PER_UNIT_PAISA  # amount in paise
        order = razorpay_client.order.create(
            {"amount": amount, "currency": "INR", "payment_capture": 1}
        )
        print("ORDER  ::", order)
        order["unit_price_paise"] = PRICE_PER_UNIT_PAISA
        order["quantity"] = quantity
        return JSONResponse(order)
    except Exception as e:
        print(f"Error creating order: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/verify-payment")
async def verify_payment(request: Request):
    if not razorpay_client:
        return JSONResponse({"message": "Razorpay not configured"}, status_code=500)
    try:
        data = await request.json()
        print(f"Verifying payment with data: {data}")  # Added logging
        params = {
            "razorpay_order_id": data.get("razorpay_order_id"),
            "razorpay_payment_id": data.get("razorpay_payment_id"),
            "razorpay_signature": data.get("razorpay_signature"),
        }
        print(params)
        razorpay_client.utility.verify_payment_signature(params)
        return {"message": "Payment verified"}
    except Exception as e:
        print(f"Payment verification failed: {e}")  # Added logging
        return JSONResponse(
            {"message": "Verification failed", "error": str(e)},
            status_code=400)        


@app.post("/low-stock-alert")
async def send_mail(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    machineID = data.get("machineID")
    remaining = data.get("Remaining")

    subject = f"Low Stock Alert - {machineID}"
    body = f"Machine {machineID} is running low.\nRemaining pads: {remaining}"
    
    background_tasks.add_task(send_email_async, subject, body)
    
    # We log optimistically
    print(f"Low stock alert queued for {machineID}")
    return {"message": "Email queued"}


# FIX: architecture_review.md — "Payment Reconciliation"
# Razorpay webhook for catching paid orders that the client failed to report.
@app.post("/api/razorpay-webhook")
async def razorpay_webhook(request: Request):
    """Handle Razorpay webhook events for payment reconciliation.

    When a payment is captured but the client never called /trigger-dispense
    (e.g., tab closed, network failure), this webhook logs the event for
    manual or automated reconciliation.
    """
    body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")

    if not RAZORPAY_WEBHOOK_SECRET:
        print("WARNING: RAZORPAY_WEBHOOK_SECRET not configured, skipping webhook")
        return JSONResponse({"status": "ignored"}, status_code=200)

    # Verify signature
    if not payment_service.verify_webhook_signature(body, signature, RAZORPAY_WEBHOOK_SECRET):
        return JSONResponse({"error": "Invalid signature"}, status_code=400)

    try:
        event = json.loads(body)
        event_type = event.get("event", "")

        if event_type == "payment.captured":
            payment_entity = event.get("payload", {}).get("payment", {}).get("entity", {})
            order_id = payment_entity.get("order_id")
            payment_id = payment_entity.get("id")
            amount = payment_entity.get("amount")
            print(
                f"WEBHOOK: payment.captured — order={order_id} payment={payment_id} amount={amount}"
            )
            # TODO: Check if a transaction was already recorded for this order_id.
            # If not, flag for manual reconciliation or auto-refund.
        else:
            print(f"WEBHOOK: Received event '{event_type}', no action taken.")

        return JSONResponse({"status": "ok"})
    except Exception as e:
        print(f"WEBHOOK error: {e}")
        return JSONResponse({"error": "Processing failed"}, status_code=500)


# ============ Run Server ============
if __name__ == "__main__":
    port = int(os.getenv("PORT", "8002"))
    reload_enabled = os.getenv("RELOAD", "").lower() == "true"
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=reload_enabled,
    )
