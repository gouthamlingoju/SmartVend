"""
SmartVend v3.0 — Cloud Backend
================================
Session-based QR vending system.
ESP32 connects via WebSocket → gets session token → renders QR on OLED.
User scans QR → claims session → pays → dispenses.

Phase 1: Backend session system (this file).
"""

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
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse
from pydantic import BaseModel, Field, constr

from auth import AuthHandler
import database as db
import session_db
from config import (
    ADMIN_PASSWORD,
    CLAIM_TTL_SECONDS,
    DISPLAY_CODE_TTL_MINUTES,
    FRONTEND_URL,
    MOTOR_TIMEOUT_SECONDS,
    PRICE_PER_UNIT_PAISA,
    RAZORPAY_KEY_ID,
    RAZORPAY_SECRET_KEY,
    RAZORPAY_WEBHOOK_SECRET,
    RECEIVER_EMAIL,
    REDIS_URL,
    SENDER_EMAIL,
    SENDER_PASSWORD,
    SESSION_TTL_SECONDS,
    SMTP_PORT,
    SMTP_SERVER,
)
from services import machine_service, payment_service

# Rate Limiting
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# ──────────────────────────────────────────────
#  Globals
# ──────────────────────────────────────────────

pending_http_commands: Dict[str, List[Dict[str, Any]]] = {}

# In-memory map of connected ESP32s: machine_id → WebSocket
connected_machines: dict = {}
redis_client = None
redis_listener_task = None
session_sweeper_task = None
REDIS_CHANNEL = "ws:commands"


# ──────────────────────────────────────────────
#  Lifespan
# ──────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start/stop resources in a Render-friendly way."""
    global redis_client, redis_listener_task, session_sweeper_task
    try:
        await db.init_pool()
        if db.pool:
            print("✅ DB pool initialized")
    except Exception as e:
        print("❌ DB pool init error:", e)

    try:
        if REDIS_URL:
            redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)
            redis_listener_task = asyncio.create_task(
                _redis_pubsub_listener(redis_client)
            )
            print("✅ Redis pubsub listener started")
    except Exception as e:
        print("⚠️ Redis init error:", e)

    try:
        session_sweeper_task = asyncio.create_task(_session_expiry_sweeper())
        print("✅ Session expiry sweeper started")
    except Exception as e:
        print("❌ Session sweeper start error:", e)

    try:
        yield
    finally:
        for task in [session_sweeper_task, redis_listener_task]:
            if task:
                task.cancel()
                with contextlib.suppress(Exception):
                    await task
        if redis_client:
            with contextlib.suppress(Exception):
                await redis_client.close()
        with contextlib.suppress(Exception):
            await db.close_pool()


# ──────────────────────────────────────────────
#  App Setup
# ──────────────────────────────────────────────

app = FastAPI(title="SmartVend Cloud Backend v3.0", lifespan=lifespan)

# Auth
auth_handler = AuthHandler()
ADMIN_PASSWORD_HASH = auth_handler.get_password_hash(ADMIN_PASSWORD)

# CORS
origins = [o for o in [FRONTEND_URL, "http://localhost:5173", "http://localhost:5174"] if o]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate Limiting
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        {"error": "Too many requests. Please slow down."},
        status_code=429,
    )


# Razorpay
razorpay_client = None
if RAZORPAY_KEY_ID and RAZORPAY_SECRET_KEY:
    razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_SECRET_KEY))
else:
    print("⚠️ Razorpay credentials missing; payment endpoints will return errors.")


# ──────────────────────────────────────────────
#  Helper: Send WS + Redis
# ──────────────────────────────────────────────

async def _send_to_machine(machine_id: str, payload: dict, store_pending: bool = True):
    """Send a message to an ESP32 via WebSocket + Redis. Best-effort."""
    if store_pending:
        pending_http_commands.setdefault(machine_id, []).append(payload)
    
    # Local WebSocket
    ws = connected_machines.get(machine_id)
    if ws:
        try:
            await ws.send_text(json.dumps(payload))
        except Exception as e:
            print(f"WS send failed for {machine_id}: {e}")

    # Redis cross-worker
    if redis_client:
        try:
            await redis_client.publish(
                REDIS_CHANNEL,
                json.dumps({"machine_id": machine_id, "payload": payload}),
            )
        except Exception as e:
            print(f"Redis publish failed: {e}")


# ══════════════════════════════════════════════
#  WEBSOCKET — ESP32 Connection
# ══════════════════════════════════════════════

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for ESP32 devices.
    
    v3.0 Protocol:
    ESP32 → Server:
      - {"type": "register", "machine_id": "M001", "api_key": "sv_001mmsg"}
      - {"type": "pong"}
      - {"type": "confirm", "transaction_id": "...", "dispensed": 2}
    
    Server → ESP32:
      - {"type": "session", "token": "xK9mBq2P", "url": "https://..."}
      - {"type": "claimed", "name": "Goutham"}
      - {"type": "new_session", "token": "pR7nWm4K", "url": "https://..."}
      - {"type": "command", "action": "dispense", "duration": 2, "transaction_id": "..."}
      - {"type": "ping"}
    """
    await websocket.accept()
    machine_id = None
    heartbeat_task = None

    async def heartbeat():
        """Send periodic pings to keep connection alive."""
        try:
            while True:
                await asyncio.sleep(30)
                await websocket.send_text(json.dumps({"type": "ping"}))
        except Exception:
            pass

    try:
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=75)
            except asyncio.TimeoutError:
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

            # ── REGISTER ──
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
                    
                    # Start heartbeat
                    if heartbeat_task:
                        heartbeat_task.cancel()
                    heartbeat_task = asyncio.create_task(heartbeat())
                    print(f"🔌 WS: registered machine {machine_id}")
                    
                    # v3.0: Register machine + create session + send QR URL
                    try:
                        if db.pool:
                            session_info = await session_db.register_machine_session(
                                machine_id, api_key or "none"
                            )
                            if session_info and not session_info.get("error"):
                                # Send session to ESP32 for QR generation
                                await websocket.send_text(json.dumps({
                                    "type": "session",
                                    "token": session_info["session_token"],
                                    "url": session_info["url"],
                                    "expires_at": session_info["expires_at"],
                                }))
                                print(f"📱 Sent session to {machine_id}: {session_info['session_token']}")
                            else:
                                print(f"⚠️ Session creation failed for {machine_id}: {session_info}")
                                await websocket.send_text(json.dumps({
                                    "type": "error",
                                    "error": "session_creation_failed",
                                }))
                    except Exception as e:
                        print(f"❌ Session setup during WS register failed: {e}")

            # ── PONG (response to our ping) ──
            elif mtype == "pong":
                if machine_id and db.pool:
                    try:
                        await db.set_machine_last_seen(machine_id)
                    except Exception:
                        pass

            # ── STATUS (legacy, kept for backward compat) ──
            elif mtype == "status":
                value = msg.get("value")
                print(f"WS status from {machine_id}: {value}")
                try:
                    if machine_id and db.pool:
                        await db.set_machine_last_seen(machine_id)
                except Exception as e:
                    print(f"Error updating machine status for {machine_id}: {e}")

            # ── FETCH_DISPLAY (legacy, kept for backward compat) ──
            elif mtype == "fetch_display":
                # v3.0: Send current session URL instead of display code
                if not machine_id:
                    await websocket.send_text(
                        json.dumps({"type": "error", "error": "not_registered"})
                    )
                    continue
                try:
                    if db.pool:
                        session = await session_db.get_active_session_for_machine(machine_id)
                        if session:
                            base_url = FRONTEND_URL or "https://smartvend.onrender.com"
                            token = session.get("session_token")
                            url = f"{base_url}/s/{token}"
                            await websocket.send_text(json.dumps({
                                "type": "session",
                                "token": token,
                                "url": url,
                                "expires_at": session.get("expires_at"),
                            }))
                        else:
                            # No active session — create one
                            new_session = await session_db.create_session(machine_id)
                            if new_session:
                                base_url = FRONTEND_URL or "https://smartvend.onrender.com"
                                token = new_session.get("session_token")
                                url = f"{base_url}/s/{token}"
                                await websocket.send_text(json.dumps({
                                    "type": "session",
                                    "token": token,
                                    "url": url,
                                    "expires_at": new_session.get("expires_at"),
                                }))
                            else:
                                await websocket.send_text(json.dumps({
                                    "type": "error",
                                    "error": "no_session",
                                }))
                except Exception as e:
                    print("Error responding to fetch_display:", e)

            else:
                print("WS unknown message:", msg)

    except WebSocketDisconnect:
        print(f"🔌 WebSocket disconnected: {machine_id}")
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
    finally:
        if heartbeat_task:
            heartbeat_task.cancel()


# ──────────────────────────────────────────────
#  Redis PubSub Listener
# ──────────────────────────────────────────────

async def _redis_pubsub_listener(rclient):
    """Background task: forward Redis messages to local WebSocket connections."""
    pubsub = None
    try:
        pubsub = rclient.pubsub()
        await pubsub.subscribe(REDIS_CHANNEL)
        print(f"📡 Subscribed to redis channel {REDIS_CHANNEL}")
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
                    continue
                machine = obj.get("machine_id")
                payload = obj.get("payload")
                if machine and payload:
                    ws = connected_machines.get(machine)
                    if ws:
                        try:
                            await ws.send_text(json.dumps(payload))
                        except Exception as e:
                            print("Error forwarding to ws client:", e)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print("Redis pubsub listener error:", e)
                await asyncio.sleep(1)
    finally:
        if pubsub:
            with contextlib.suppress(Exception):
                await pubsub.unsubscribe(REDIS_CHANNEL)


# ══════════════════════════════════════════════
#  v3.0 SESSION ENDPOINTS
# ══════════════════════════════════════════════

@app.get("/s/{token}")
async def short_link_redirect(token: str):
    """Short URL redirection for ESP32 QR codes to minimize length.
    Maps /s/TOKEN straight to the frontend /vend/M001/TOKEN route.
    """
    if not db.pool:
        raise HTTPException(status_code=500, detail="Database not configured")
    session = await session_db.get_session_by_token(token)
    if not session:
        return HTMLResponse("<h1>Session expired or invalid.</h1><p>Please scan the new QR code on the machine.</p>", 404)
    
    machine_id = session.get("machine_id")
    base_url = FRONTEND_URL or "https://smartvend.onrender.com"
    return RedirectResponse(f"{base_url}/vend/{machine_id}/{token}")

@app.post("/api/session/claim")
@limiter.limit("15/minute")
async def claim_session(request: Request):
    """Claim an active session after QR scan.
    
    Body: { "session_token": "xK9mBq2P", "client_id": "abc123", "name": "Goutham" }
    
    Returns:
      200: { "status": "claimed", "machine_id": "M001", "expires_at": "..." }
      200: { "status": "already_claimed", ... }  (same user resuming)
      409: { "error": "already_claimed" }  (different user)
      410: { "error": "expired_or_invalid" }
    """
    if not db.pool:
        raise HTTPException(status_code=500, detail="Database not configured")

    data = await request.json()
    session_token = data.get("session_token")
    client_id = data.get("client_id")
    user_name = data.get("name", "User")

    if not session_token or not client_id:
        raise HTTPException(status_code=400, detail="session_token and client_id required")

    result = await session_db.claim_session(session_token, client_id)

    if result.get("error"):
        error = result["error"]
        if error == "already_claimed":
            return JSONResponse(
                {"error": "already_claimed", "message": "This session is already in use. Please wait for a new QR."},
                status_code=409,
            )
        if error in ("expired_or_invalid", "session_not_found"):
            return JSONResponse(
                {"error": "expired_or_invalid", "message": "This QR code has expired. Please scan the new QR on the machine."},
                status_code=410,
            )
        if error == "database_unavailable":
            raise HTTPException(status_code=500, detail="Database not available")
        return JSONResponse({"error": error}, status_code=400)

    machine_id = result.get("machine_id")
    session = result.get("session", {})

    # Send "claimed" notification to ESP32 → OLED switches from QR to "In Use"
    if result.get("status") == "claimed":
        await _send_to_machine(machine_id, {
            "type": "claimed",
            "claimed_by_name": user_name,
        }, store_pending=True)

    return {
        "status": result.get("status"),
        "machine_id": machine_id,
        "session_token": session.get("session_token"),
        "expires_at": session.get("expires_at"),
        "is_owner": True,
    }


@app.get("/api/session/status")
async def get_session_status(session_token: str, client_id: Optional[str] = None):
    """Check session status (for frontend reload/resume).
    
    Query: ?session_token=xK9mBq2P&client_id=abc123
    """
    if not db.pool:
        raise HTTPException(status_code=500, detail="Database not configured")

    if not session_token:
        raise HTTPException(status_code=400, detail="session_token required")

    result = await session_db.get_session_status(session_token, client_id)

    if result.get("error"):
        if result["error"] == "session_not_found":
            return JSONResponse(
                {"error": "session_not_found", "message": "Session not found. Please scan a new QR."},
                status_code=404,
            )
        return JSONResponse({"error": result["error"]}, status_code=400)

    return result


@app.post("/api/session/cancel")
async def cancel_session(request: Request):
    """Explicitly cancel a session (user decides not to pay).
    
    Body: { "session_token": "xK9mBq2P", "client_id": "abc123" }
    """
    if not db.pool:
        raise HTTPException(status_code=500, detail="Database not configured")

    data = await request.json()
    session_token = data.get("session_token")
    client_id = data.get("client_id")

    if not session_token or not client_id:
        raise HTTPException(status_code=400, detail="session_token and client_id required")

    result = await session_db.cancel_session(session_token, client_id)

    if result.get("error"):
        error = result["error"]
        if error == "not_owner":
            raise HTTPException(status_code=403, detail="You don't own this session")
        if error == "session_not_found":
            raise HTTPException(status_code=404, detail="Session not found")
        return JSONResponse({"error": error, "detail": result.get("detail")}, status_code=400)

    machine_id = result.get("machine_id")

    # Create new session for the machine and notify ESP32
    if machine_id:
        new_session = await session_db.create_session(machine_id)
        if new_session:
            base_url = FRONTEND_URL or "https://smartvend.onrender.com"
            token = new_session.get("session_token")
            url = f"{base_url}/s/{token}"
            await _send_to_machine(machine_id, {
                "type": "new_session",
                "token": token,
                "url": url,
                "expires_at": new_session.get("expires_at"),
            })

    return {"status": "cancelled"}


@app.post("/api/session/trigger-dispense")
async def session_trigger_dispense(request: Request):
    """Trigger dispense after payment verification.
    
    Body: {
        "session_token": "xK9mBq2P",
        "client_id": "abc123",
        "quantity": 2,
        "transaction_id": "txn_xxx"
    }
    """
    if not db.pool:
        raise HTTPException(status_code=500, detail="Database not configured")

    data = await request.json()
    session_token = data.get("session_token")
    client_id = data.get("client_id")
    quantity = int(data.get("quantity", 1))
    transaction_id = data.get("transaction_id")

    if not all([session_token, client_id, transaction_id]):
        raise HTTPException(
            status_code=400,
            detail="session_token, client_id, and transaction_id required"
        )

    amount = quantity * PRICE_PER_UNIT_PAISA

    result = await session_db.trigger_dispense_session(
        session_token, client_id, quantity, transaction_id, amount
    )

    if result.get("error"):
        error = result["error"]
        if error == "not_owner":
            raise HTTPException(status_code=403, detail="Session not owned by this client")
        if error == "session_not_found":
            raise HTTPException(status_code=404, detail="Session not found")
        if error in ("already_processed", "duplicate"):
            return JSONResponse(
                {"error": "Transaction already processed", "status": "duplicate"},
                status_code=409,
            )
        if error == "session_expired":
            return JSONResponse(
                {"error": "Session expired", "message": "Your session has expired. Payment was not charged."},
                status_code=410,
            )
        if error == "invalid_state":
            return JSONResponse(
                {"error": error, "detail": result.get("detail")},
                status_code=409,
            )
        return JSONResponse({"error": error}, status_code=400)

    machine_id = result.get("machine_id")

    # Send dispense command to ESP32
    await _send_to_machine(machine_id, {
        "type": "command",
        "action": "dispense",
        "duration": quantity,
        "transaction_id": transaction_id,
    })

    return {"status": "dispatch_sent", "machine_id": machine_id}


# ══════════════════════════════════════════════
#  HEALTH & UTILITIES
# ══════════════════════════════════════════════

@app.get("/health")
async def health_check():
    return {"status": "ok", "version": "3.0"}


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


# ══════════════════════════════════════════════
#  MACHINE MANAGEMENT ENDPOINTS
# ══════════════════════════════════════════════

@app.get("/api/machines")
async def list_machines():
    """Return all machines. Public endpoint for frontend machine-list view."""
    if not db.pool:
        raise HTTPException(status_code=500, detail="Database not configured")
    machines = await db.get_all_machines()
    for m in machines:
        if m.get("status") == "idle" and (m.get("current_stock") or 0) <= 0:
            m["status"] = "out_of_stock"
    return machines


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

    subject = "SmartVend Admin Login Alert"
    body = f"An admin logged in at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}."
    background_tasks.add_task(send_email_async, subject, body)

    return {"token": token}


@app.get("/api/admin/verify")
def verify_token(user_id=Depends(auth_handler.auth_wrapper)):
    return {"status": "valid", "user_id": user_id}


@app.post("/api/machine/{machine_id}/update-stock")
async def update_machine_stock(
    machine_id: str, request: Request, user_id=Depends(auth_handler.auth_wrapper)
):
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

    result = await db.update_machine_stock(machine_id, new_stock)
    if result is None:
        raise HTTPException(status_code=500, detail="Failed to update stock")

    # Notify device
    await _send_to_machine(machine_id, {"type": "stock_update", "stock": new_stock}, store_pending=False)

    return {"status": "success", "current_stock": new_stock}


# ══════════════════════════════════════════════
#  ESP32 COMMUNICATION (kept from v2, updated)
# ══════════════════════════════════════════════

async def verify_api_key(machine_id: str, authorization: Optional[str]):
    """Verify the provided machine API key against the DB."""
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


@app.post("/api/machine/register")
async def register_machine(request: Request):
    """ESP32 calls this once on boot (HTTP fallback for WebSocket registration)."""
    data = await request.json()
    machine_id = data.get("machine_id")
    if not machine_id:
        raise HTTPException(status_code=400, detail="Missing machine_id")
    if not db.pool:
        raise HTTPException(status_code=500, detail="Database not configured")

    api_key = data.get("api_key", "none")
    
    # v3.0: Use session registration
    session_info = await session_db.register_machine_session(machine_id, api_key)
    if not session_info or session_info.get("error"):
        raise HTTPException(status_code=500, detail="Failed to register machine")

    return {
        "message": f"Machine {machine_id} registered",
        "status": "ok",
        "session_token": session_info.get("session_token"),
        "url": session_info.get("url"),
        "expires_at": session_info.get("expires_at"),
    }


@app.get("/api/machine/{machine_id}/status")
async def get_machine_status(
    machine_id: str, authorization: Optional[str] = Header(None)
):
    """ESP32 polls this every few seconds."""
    if not db.pool:
        raise HTTPException(status_code=500, detail="Database not configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    provided = authorization.split(" ")[1].strip()
    status = await db.get_machine_status_for_esp32(machine_id, provided)
    if not status:
        raise HTTPException(
            status_code=401, detail="Invalid credentials or machine not found"
        )
    return status


@app.get("/api/machine/{machine_id}/public-status")
async def get_machine_public_status(machine_id: str, client_id: Optional[str] = None):
    """Public status for frontend use."""
    if not db.pool:
        raise HTTPException(status_code=500, detail="Database not configured")
    s = await db.get_public_status(machine_id, client_id)
    if not s:
        raise HTTPException(status_code=404, detail="Machine not found")
    return s


@app.post("/api/machine/{machine_id}/confirm")
async def confirm_dispense(
    machine_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    authorization: Optional[str] = Header(None),
):
    """ESP32 confirms dispensing success. v3.0: completes session + creates new one."""
    await verify_api_key(machine_id, authorization)
    data = await request.json()
    dispensed = int(data.get("dispensed", 0))
    transaction_id = data.get("transaction_id")

    if not db.pool:
        raise HTTPException(status_code=500, detail="Database not configured")

    # v3.0: Complete the session and create a new one
    result = await session_db.complete_session(machine_id, transaction_id, dispensed)

    if result.get("error"):
        # Fallback to legacy confirm if session system fails
        res = await db.confirm_dispense_db(machine_id, transaction_id, dispensed)
        if res.get("error"):
            return JSONResponse(
                {"message": "confirm_failed", "error": res["error"]}, status_code=400
            )
        return {"status": "confirmed", "dispensed": dispensed}

    # Low stock alert
    if result.get("low_stock"):
        subject = f"Low Stock Alert - {machine_id}"
        remaining = result.get("remaining_stock", 0)
        body = f"Machine {machine_id} stock is low.\nRemaining stock: {remaining}."
        background_tasks.add_task(send_email_async, subject, body)
        print(f"📧 Low stock alert queued for {machine_id} (remaining: {remaining})")

    # Send new session to ESP32 for fresh QR
    new_session = result.get("new_session")
    if new_session:
        base_url = FRONTEND_URL or "https://smartvend.onrender.com"
        token = new_session.get("session_token")
        url = f"{base_url}/vend/{machine_id}/{token}"
        await _send_to_machine(machine_id, {
            "type": "new_session",
            "token": token,
            "url": url,
            "expires_at": new_session.get("expires_at"),
        })

    return {
        "status": "confirmed",
        "dispensed": dispensed,
        "new_session_token": new_session.get("session_token") if new_session else None,
    }


@app.post("/api/machine/{machine_id}/report-error")
async def report_error(
    machine_id: str, request: Request, authorization: Optional[str] = Header(None)
):
    """ESP32 sends timeout or failure reports."""
    await verify_api_key(machine_id, authorization)
    data = await request.json()
    err = data.get("error")
    print(f"⚠️ Error from machine {machine_id}: {err}")

    # Log to events table
    try:
        await session_db.log_event(
            machine_id=machine_id,
            event_type="machine_error",
            payload={"error": err},
        )
    except Exception:
        pass

    return {"message": "Error logged"}


# ══════════════════════════════════════════════
#  PAYMENT ENDPOINTS
# ══════════════════════════════════════════════

@app.post("/create-order")
async def create_order(request: Request):
    """Create Razorpay order with atomic stock reservation + order↔session mapping."""
    if not razorpay_client:
        return JSONResponse({"error": "Razorpay not configured"}, status_code=500)
    try:
        data = await request.json()
        quantity = int(data.get("quantity", 1))
        if quantity <= 0:
            return JSONResponse({"error": "Quantity must be positive"}, status_code=400)

        machine_id = data.get("machine_id")
        session_token = data.get("session_token")
        client_id = data.get("client_id")

        # v3.0: Validate session ownership before creating order
        if session_token and client_id:
            session = await session_db.get_session_by_token(session_token)
            if not session:
                return JSONResponse({"error": "Session not found"}, status_code=404)
            if session.get("status") != "in_progress":
                return JSONResponse(
                    {"error": f"Session is {session.get('status')}, not in_progress"},
                    status_code=409,
                )
            if session.get("claimed_by") != client_id:
                return JSONResponse({"error": "Session not owned by this client"}, status_code=403)

        # Atomic stock reservation
        if machine_id:
            reserve_result = await session_db.reserve_stock_atomic(machine_id, quantity)
            if reserve_result.get("error"):
                return JSONResponse(
                    {"error": reserve_result["error"], "available": reserve_result.get("available")},
                    status_code=409,
                )

        amount = quantity * PRICE_PER_UNIT_PAISA
        order = razorpay_client.order.create(
            {"amount": amount, "currency": "INR", "payment_capture": 1}
        )
        order["unit_price_paise"] = PRICE_PER_UNIT_PAISA
        order["quantity"] = quantity

        # v3.0: Store order ↔ session mapping for webhook reconciliation
        if session_token and session:
            await session_db.create_order_record(
                order_id=order["id"],
                session_id=session["id"],
                machine_id=machine_id or session.get("machine_id"),
                client_id=client_id or "",
                quantity=quantity,
                amount=amount,
            )

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
        params = {
            "razorpay_order_id": data.get("razorpay_order_id"),
            "razorpay_payment_id": data.get("razorpay_payment_id"),
            "razorpay_signature": data.get("razorpay_signature"),
        }
        razorpay_client.utility.verify_payment_signature(params)
        return {"message": "Payment verified"}
    except Exception as e:
        print(f"Payment verification failed: {e}")
        return JSONResponse(
            {"message": "Verification failed", "error": str(e)},
            status_code=400,
        )


@app.post("/low-stock-alert")
async def send_mail(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    machineID = data.get("machineID")
    remaining = data.get("Remaining")

    subject = f"Low Stock Alert - {machineID}"
    body = f"Machine {machineID} is running low.\nRemaining pads: {remaining}"

    background_tasks.add_task(send_email_async, subject, body)
    print(f"📧 Low stock alert queued for {machineID}")
    return {"message": "Email queued"}


# ══════════════════════════════════════════════
#  RAZORPAY WEBHOOK (v3.0: auto-dispense)
# ══════════════════════════════════════════════

@app.post("/api/razorpay-webhook")
async def razorpay_webhook(request: Request):
    """Handle Razorpay webhook for payment reconciliation.
    
    v3.0: When payment is captured but frontend never called trigger-dispense
    (tab closed, network failure), this webhook auto-dispenses.
    """
    body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")

    if not RAZORPAY_WEBHOOK_SECRET:
        print("⚠️ RAZORPAY_WEBHOOK_SECRET not configured, skipping webhook")
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
                f"🔔 WEBHOOK: payment.captured — order={order_id} payment={payment_id} amount={amount}"
            )

            # v3.0: Check if order exists in our orders table
            if order_id:
                order = await session_db.get_order_by_id(order_id)
                if order:
                    session_id = order.get("session_id")
                    machine_id = order.get("machine_id")
                    client_id = order.get("client_id")
                    quantity = order.get("quantity")

                    # Check: does a transaction already exist for this session?
                    # If not, auto-trigger dispense (the safety net)
                    session = await session_db.get_active_session_for_machine(machine_id)
                    if session and session.get("status") == "in_progress":
                        print(f"🔄 WEBHOOK: Auto-triggering dispense for order {order_id}")
                        
                        # Create a synthetic transaction_id for the webhook-triggered dispense
                        tx_id = f"webhook_{order_id}"
                        result = await session_db.trigger_dispense_session(
                            session.get("session_token"),
                            client_id,
                            quantity,
                            tx_id,
                            amount or (quantity * PRICE_PER_UNIT_PAISA),
                        )

                        if result.get("status") == "ok":
                            # Send dispense command to ESP32
                            await _send_to_machine(machine_id, {
                                "type": "command",
                                "action": "dispense",
                                "duration": quantity,
                                "transaction_id": tx_id,
                            })
                            print(f"✅ WEBHOOK: Dispense command sent for order {order_id}")
                        elif result.get("error") in ("already_processed", "duplicate"):
                            print(f"ℹ️ WEBHOOK: Order {order_id} already processed")
                        else:
                            print(f"❌ WEBHOOK: Dispense failed for order {order_id}: {result}")
                    elif session and session.get("status") == "dispensing":
                        print(f"ℹ️ WEBHOOK: Order {order_id} already being dispensed")
                    else:
                        print(f"⚠️ WEBHOOK: No active session for machine {machine_id}, order {order_id}")
                        await session_db.log_event(
                            machine_id=machine_id,
                            event_type="webhook_orphan_payment",
                            payload={"order_id": order_id, "amount": amount},
                        )
                else:
                    print(f"⚠️ WEBHOOK: No order record found for {order_id}")
        else:
            print(f"🔔 WEBHOOK: Received event '{event_type}', no action taken.")

        return JSONResponse({"status": "ok"})
    except Exception as e:
        print(f"❌ WEBHOOK error: {e}")
        return JSONResponse({"error": "Processing failed"}, status_code=500)


# ══════════════════════════════════════════════
#  DEVICE HTTP FALLBACK ENDPOINTS
# ══════════════════════════════════════════════

@app.post("/device/telemetry")
async def ingest_telemetry(payload: TelemetryPayload):
    """HTTP fallback when WS is unavailable."""
    device_id = payload.device_id
    if db.pool:
        try:
            await db.set_machine_last_seen(device_id)
        except Exception as e:
            print(f"Telemetry update error for {device_id}: {e}")
    return {"status": "ok", "proto": payload.proto}


@app.get("/device/commands/{device_id}", response_model=CommandResponse)
async def get_device_commands(device_id: str):
    """HTTP polling fallback for ESP32 when WS is unavailable."""
    cmds = pending_http_commands.pop(device_id, [])
    return CommandResponse(commands=cmds, count=len(cmds))


# ══════════════════════════════════════════════
#  SESSION EXPIRY SWEEPER (v3.0 — replaces lock sweeper)
# ══════════════════════════════════════════════

async def _session_expiry_sweeper():
    """Periodically expire stale sessions and create new ones.
    
    v3.0: Queries DB directly for all expired sessions (not just connected machines).
    This ensures sessions expire even if the ESP32 is connected to a different worker.
    """
    while True:
        try:
            await asyncio.sleep(5)  # Check every 5 seconds
            
            if not db.pool:
                continue

            # Expire stale sessions and get list of machines that need new sessions
            renewed = await session_db.expire_and_renew_sessions()

            for machine_id, new_session in renewed:
                base_url = FRONTEND_URL or "https://smartvend.onrender.com"
                token = new_session.get("session_token")
                url = f"{base_url}/vend/{machine_id}/{token}"

                # Send new QR to ESP32
                await _send_to_machine(machine_id, {
                    "type": "new_session",
                    "token": token,
                    "url": url,
                    "expires_at": new_session.get("expires_at"),
                })

                print(f"🔄 Sweeper: renewed session for {machine_id} → {token}")

        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"Session sweeper error: {e}")
            await asyncio.sleep(2)


# ══════════════════════════════════════════════
#  DEPRECATED ENDPOINTS (kept for backward compat, Phase 3 removal)
# ══════════════════════════════════════════════

@app.post("/api/lock-by-code")
@limiter.limit("10/minute")
async def lock_by_code_deprecated(request: Request):
    """DEPRECATED: Use /api/session/claim instead.
    Kept for backward compatibility during v2→v3 transition.
    """
    return JSONResponse(
        {
            "error": "deprecated",
            "message": "This endpoint is deprecated. Use /api/session/claim with QR scan instead.",
            "migration": "v3.0 uses QR codes on OLED. Scan the QR code on the machine to claim a session.",
        },
        status_code=410,
    )


@app.post("/api/machine/{machine_id}/unlock")
async def unlock_deprecated(machine_id: str, request: Request):
    """DEPRECATED: Sessions auto-expire or use /api/session/cancel."""
    return JSONResponse(
        {
            "error": "deprecated",
            "message": "Use /api/session/cancel to cancel a session, or wait for auto-expiry.",
        },
        status_code=410,
    )


@app.post("/api/machine/{machine_id}/dispense")
async def trigger_dispense_deprecated(machine_id: str, request: Request):
    """DEPRECATED: Use /api/session/trigger-dispense."""
    return JSONResponse(
        {"error": "deprecated", "message": "Use /api/session/trigger-dispense"},
        status_code=410,
    )


@app.post("/api/machine/{machine_id}/trigger-dispense")
async def trigger_dispense_legacy(machine_id: str, request: Request):
    """DEPRECATED: Use /api/session/trigger-dispense (session-based)."""
    return JSONResponse(
        {"error": "deprecated", "message": "Use /api/session/trigger-dispense with session_token"},
        status_code=410,
    )


# ══════════════════════════════════════════════
#  RUN SERVER
# ══════════════════════════════════════════════

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8002"))
    reload_enabled = os.getenv("RELOAD", "").lower() == "true"
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=reload_enabled,
    )
