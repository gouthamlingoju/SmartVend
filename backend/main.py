from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from typing import Optional
import secrets
import razorpay
import uvicorn
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import supabase as db
from config import FRONTEND_URL,RAZORPAY_KEY_ID,RAZORPAY_SECRET_KEY,DISPLAY_CODE_TTL_MINUTES,SENDER_EMAIL,SENDER_PASSWORD,RECEIVER_EMAIL,SMTP_SERVER,SMTP_PORT
# Load environment variables

app = FastAPI(title="SmartVend Cloud Backend")


@app.on_event("startup")
async def startup_event():
    # initialize DB pool if DATABASE_URL provided
    try:
        await db.init_pool()
        if db.pool:
            print("✅ DB pool initialized")
    except Exception as e:
        print("DB pool init error:", e)


@app.on_event("shutdown")
async def shutdown_event():
    try:
        await db.close_pool()
    except Exception:
        pass

# ============ CORS ============
origins = [FRONTEND_URL, "http://localhost:5173"]
# filter out None / empty
origins = [o for o in origins if o]
app.add_middleware(
  CORSMiddleware,
  allow_origins=origins,
  allow_credentials=True,
  allow_methods=["*"],
  allow_headers=["*"],
)

# ============ Razorpay Setup ============
razorpay_client = None
if RAZORPAY_KEY_ID and RAZORPAY_SECRET_KEY:
    razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_SECRET_KEY))
else:
    print("⚠️ WARNING: Razorpay credentials missing! Payment endpoints will return errors.")

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

    expected_key = m.get('api_key')
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
    return {"message": f"Machine {machine_id} registered", "status": "ok", "display_code": res.get('display_code'), "display_code_expires_at": res.get('display_code_expires_at')}

@app.get("/api/machine/{machine_id}/status")
async def get_machine_status(machine_id: str, authorization: Optional[str] = Header(None)):
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
        raise HTTPException(status_code=401, detail="Invalid credentials or machine not found")
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
    if res.get('error'):
        if res['error'] == 'no_lock':
            raise HTTPException(status_code=409, detail='No active lock to unlock')
        if res['error'] == 'not_owner':
            raise HTTPException(status_code=403, detail='Lock not owned by this client')
    return {'status': 'unlocked', 'new_display_code': res.get('new_display_code')}

@app.post("/api/machine/{machine_id}/confirm")
async def confirm_dispense(machine_id: str, request: Request, authorization: Optional[str] = Header(None)):
    """ESP32 confirms dispensing success"""
    # verify API key
    await verify_api_key(machine_id, authorization)
    data = await request.json()
    dispensed = int(data.get("dispensed", 0))
    transaction_id = data.get("transaction_id")

    if not db.pool:
        raise HTTPException(status_code=500, detail="Database not configured")

    res = await db.confirm_dispense_db(machine_id, transaction_id, dispensed)
    if res.get('error'):
        return JSONResponse({'message': 'confirm_failed', 'error': res['error']}, status_code=400)
    return {'status': 'confirmed', 'dispensed': dispensed, 'new_display_code': res.get('new_display_code')}

@app.post("/api/machine/{machine_id}/report-error")
async def report_error(machine_id: str, request: Request, authorization: Optional[str] = Header(None)):
    """ESP32 sends timeout or failure reports"""
    await verify_api_key(machine_id, authorization)
    data = await request.json()
    err = data.get("error")
    print(f"⚠️ Error from machine {machine_id}: {err}")
    # Optionally, we could write this to an events table. For now just ack.
    return {"message": "Error logged"}


# In DB-backed mode display codes and lock expiry are managed in the database.


# ============ Frontend → ESP32 Dispense Trigger ============
@app.post("/api/machine/{machine_id}/dispense")
async def trigger_dispense(machine_id: str, request: Request):
    """Frontend (React) calls this after payment verification"""
    # Deprecated/legacy endpoint. Use /api/machine/{machine_id}/trigger-dispense (server-verified) instead.
    return JSONResponse({"error": "use /api/machine/{machine_id}/trigger-dispense (server-side)"}, status_code=400)


@app.post("/api/lock-by-code")
async def lock_by_code(request: Request):
    """Frontend posts { client_id, code } to lock the machine atomically (in-memory simplified)
    This stores access_code_hash in locks and sets machine status to 'locked'.
    """
    if not db.pool:
        return JSONResponse({"error": "Database not configured. Locking requires Supabase/Postgres."}, status_code=500)

    data = await request.json()
    client_id = data.get("client_id")
    code = data.get("code")
    if not client_id or not code:
        raise HTTPException(status_code=400, detail="client_id and code required")

    res = await db.lock_by_code(client_id, code, DISPLAY_CODE_TTL_MINUTES)
    if res is None:
        raise HTTPException(status_code=500, detail="Lock failed")
    if res.get('error'):
        if res['error'] == 'code_not_found':
            raise HTTPException(status_code=400, detail='Code not found or expired')
        if res['error'] == 'busy':
            # fetch lock info for machine
            status = await db.get_public_status(res.get('machine_id'))
            return JSONResponse({
                "status": "busy",
                "message": "Machine is already locked by another user",
                "locked_by": status.get('locked_by'),
                "locked_until": status.get('expires_at')
            }, status_code=409)
        raise HTTPException(status_code=400, detail=res.get('error'))

    return JSONResponse(res)


@app.post("/api/machine/{machine_id}/trigger-dispense")
async def trigger_dispense_validated(machine_id: str, request: Request):
    """Called by backend after payment verification to instruct machine to dispense.
    Validates the lock, client and access_code hash before changing machine state.
    Body: { client_id, access_code, quantity, transaction_id, amount }
    """
    if not db.pool:
        return JSONResponse({"error": "Database not configured. Trigger-dispense requires Supabase/Postgres."}, status_code=500)

    data = await request.json()
    client_id = data.get("client_id")
    access_code = data.get("access_code")
    quantity = int(data.get("quantity", 1))
    transaction_id = data.get("transaction_id")
    amount = data.get("amount")

    if not client_id or not access_code or not transaction_id:
        raise HTTPException(status_code=400, detail="client_id, access_code and transaction_id required")

    res = await db.trigger_dispense_db(machine_id, client_id, access_code, quantity, transaction_id, amount)
    if res.get('error'):
        err = res['error']
        if err == 'no_lock' or err == 'expired':
            raise HTTPException(status_code=409, detail='No active lock or lock expired')
        if err == 'not_owner':
            raise HTTPException(status_code=403, detail='Lock not owned by this client')
        if err == 'access_mismatch':
            raise HTTPException(status_code=403, detail='Access code mismatch')
        return JSONResponse({'error': err}, status_code=400)

    return JSONResponse({'status': 'dispatch_sent'})

# ============ Payment and Alert Routes (from your existing code) ============
@app.post('/create-order')
async def create_order(request: Request):
    if not razorpay_client:
        return JSONResponse({"error": "Razorpay not configured"}, status_code=500)
    try:
        data = await request.json()
        amount = data.get("amount")
        if not amount:
            return JSONResponse({"error": "Amount required"}, status_code=400)
        order = razorpay_client.order.create({
            "amount": amount,
            "currency": "INR",
            "payment_capture": 1
        })
        return JSONResponse(order)
    except Exception as e:
        print(f"Error creating order: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post('/verify-payment')
async def verify_payment(request: Request):
    if not razorpay_client:
        return JSONResponse({"message": "Razorpay not configured"}, status_code=500)
    try:
        data = await request.json()
        params = {
            'razorpay_order_id': data.get("razorpay_order_id"),
            'razorpay_payment_id': data.get("razorpay_payment_id"),
            'razorpay_signature': data.get("razorpay_signature")
        }
        razorpay_client.utility.verify_payment_signature(params)
        return {"message": "Payment verified"}
    except Exception as e:
        return JSONResponse({"message": "Verification failed", "error": str(e)}, status_code=400)

@app.post('/low-stock-alert')
async def send_mail(request: Request):
    data = await request.json()
    machineID = data.get("machineID")
    remaining = data.get("Remaining")

    sender = SENDER_EMAIL
    password = SENDER_PASSWORD
    receiver = RECEIVER_EMAIL
    smtp_server = SMTP_SERVER
    smtp_port = int(SMTP_PORT)

    subject = f"Low Stock Alert - {machineID}"
    body = f"Machine {machineID} is running low.\nRemaining pads: {remaining}"

    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = receiver
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender, password)
            server.send_message(msg)
        print(f"📧 Low stock alert sent for {machineID}")
        return {"message": "Email sent"}
    except Exception as e:
        print("Email error:", e)
        return JSONResponse({"error": str(e)}, status_code=500)

# ============ Run Server ============
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8002)
