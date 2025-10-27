from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from typing import Optional
import hashlib
import secrets
from datetime import timedelta
import razorpay
import os
import uvicorn
from dotenv import load_dotenv
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

# Load environment variables
load_dotenv()

app = FastAPI(title="SmartVend Cloud Backend")

# ============ CORS ============
origins = [os.getenv("VITE_FRONTEND_URL"), "http://localhost:5173"]
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
razorpay_key_id = os.getenv("RAZORPAY_KEY_ID")
razorpay_secret_key = os.getenv("RAZORPAY_SECRET_KEY")
razorpay_client = None
if razorpay_key_id and razorpay_secret_key:
    razorpay_client = razorpay.Client(auth=(razorpay_key_id, razorpay_secret_key))
else:
    print("⚠️ WARNING: Razorpay credentials missing! Payment endpoints will return errors.")

# ============ In-Memory Machine Store ============
# In production, use Supabase/Postgres. This in-memory store is for local testing
# and will be migrated to Supabase later.
DISPLAY_CODE_TTL_MINUTES = int(os.getenv("DISPLAY_CODE_TTL_MINUTES", "10"))  # chosen: 10 minutes

# machines holds machine-visible state (what ESP32 reads)
machines = {
    "M001": {
        "api_key": "sv_m1_3h5k9d",
        "status": "idle",
        "display_code": "MV-1001",
        "display_code_expires_at": None,
        "quantity": 0,
        "last_seen": None,
    },
    "M002": {
        "api_key": "sv_m2_7x9k2b",
        "status": "idle",
        "display_code": "MV-2001",
        "display_code_expires_at": None,
        "quantity": 0,
        "last_seen": None,
    }
}

# locks holds active locks per machine. Structure:
# { machine_id: { locked_by, access_code_hash, locked_at, expires_at, status, transaction_id } }
locks = {}

# transactions store payment/dispense metadata (in-memory for now)
transactions = {}

# ============ Auth Helper ============
def verify_api_key(machine_id: str, authorization: Optional[str]):
    if machine_id not in machines:
        raise HTTPException(status_code=404, detail="Machine not registered")

    expected_key = machines[machine_id]["api_key"]
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    provided = authorization.split(" ")[1].strip()
    # constant-time compare to avoid timing attacks
    if not secrets.compare_digest(provided, expected_key):
        raise HTTPException(status_code=401, detail="Invalid API key")

 # ============ ESP32 Communication APIs ============
@app.post("/api/machine/register")
async def register_machine(request: Request):
    """ESP32 calls this once on boot"""
    data = await request.json()
    machine_id = data.get("machine_id")
    if not machine_id:
        raise HTTPException(status_code=400, detail="Missing machine_id")

    if machine_id not in machines:
        machines[machine_id] = {
            "api_key": data.get("api_key", "none"),
            "status": "idle",
            "display_code": generate_display_code(),
            "display_code_expires_at": (datetime.utcnow() + timedelta(minutes=DISPLAY_CODE_TTL_MINUTES)).isoformat() + "Z",
            "quantity": 0,
            "last_seen": datetime.now().isoformat(),
        }
    else:
        machines[machine_id]["last_seen"] = datetime.now().isoformat()

    return {"message": f"Machine {machine_id} registered", "status": "ok"}

@app.get("/api/machine/{machine_id}/status")
async def get_machine_status(machine_id: str, authorization: Optional[str] = Header(None)):
    """ESP32 polls this every few seconds"""
    verify_api_key(machine_id, authorization)

    m = machines[machine_id]
    m["last_seen"] = datetime.now().isoformat()

    # determine lock info if any
    lock = locks.get(machine_id)
    locked = False
    locked_by = None
    expires_at = None
    if lock and lock.get("status") == "locked":
        locked = True
        locked_by = lock.get("locked_by")
        expires_at = lock.get("expires_at")

    return {
        "machine_id": machine_id,
        "status": m["status"],
        "display_code": m.get("display_code"),
        "display_code_expires_at": m.get("display_code_expires_at"),
        "locked": locked,
        "locked_by": locked_by,
        "expires_at": expires_at,
        "quantity": m["quantity"],
        "server_time": datetime.utcnow().isoformat() + "Z",
    }


@app.get("/api/machine/{machine_id}/public-status")
async def get_machine_public_status(machine_id: str, client_id: Optional[str] = None):
    """Public status for frontend use. Does NOT require machine API key.
    If client_id provided, locked_by is revealed only when it matches.
    """
    # print("machine ID",machine_id)
    if machine_id not in machines:
        raise HTTPException(status_code=404, detail="Machine not found")

    m = machines[machine_id]
    lock = locks.get(machine_id)
    locked = False
    locked_by = None
    expires_at = None
    if lock and lock.get("status") == "locked":
        locked = True
        expires_at = lock.get("expires_at")
        if client_id and lock.get("locked_by") == client_id:
            locked_by = lock.get("locked_by")

    return {
        "machine_id": machine_id,
        "status": m.get("status"),
        "display_code": m.get("display_code"),
        "display_code_expires_at": m.get("display_code_expires_at"),
        "locked": locked,
        "locked_by": locked_by,
        "expires_at": expires_at,
        "quantity": m.get("quantity"),
        "server_time": datetime.utcnow().isoformat() + "Z",
    }


@app.post("/api/machine/{machine_id}/unlock")
async def unlock_by_client(machine_id: str, request: Request):
    """Allow the client who locked the machine to manually unlock it before TTL."""
    if machine_id not in machines:
        raise HTTPException(status_code=404, detail="Machine not found")

    data = await request.json()
    client_id = data.get("client_id")
    if not client_id:
        raise HTTPException(status_code=400, detail="client_id required")

    lk = locks.get(machine_id)
    if not lk or lk.get("status") != "locked":
        raise HTTPException(status_code=409, detail="No active lock to unlock")

    if lk.get("locked_by") != client_id:
        raise HTTPException(status_code=403, detail="Lock not owned by this client")

    # perform unlock: mark lock expired/cleared and rotate display code
    lk["status"] = "expired"
    machines[machine_id]["status"] = "idle"
    machines[machine_id]["display_code"] = generate_display_code()
    machines[machine_id]["display_code_expires_at"] = (datetime.utcnow() + timedelta(minutes=DISPLAY_CODE_TTL_MINUTES)).isoformat() + "Z"
    try:
        del locks[machine_id]
    except KeyError:
        pass

    return {"status": "unlocked", "new_display_code": machines[machine_id]["display_code"], "expires_at": machines[machine_id]["display_code_expires_at"]}

@app.post("/api/machine/{machine_id}/confirm")
async def confirm_dispense(machine_id: str, request: Request, authorization: Optional[str] = Header(None)):
    """ESP32 confirms dispensing success"""
    verify_api_key(machine_id, authorization)

    data = await request.json()
    dispensed = int(data.get("dispensed", 0))
    access_code = data.get("access_code")
    transaction_id = data.get("transaction_id")

    # idempotency: if transaction_id provided and already completed, return success
    if transaction_id and transaction_id in transactions:
        tx = transactions[transaction_id]
        if tx.get("completed_at"):
            return {"status": "confirmed", "dispensed": tx.get("dispensed", dispensed)}

    # mark machine idle, clear lock and set new display code
    machines[machine_id]["status"] = "idle"
    machines[machine_id]["display_code"] = generate_display_code()
    machines[machine_id]["display_code_expires_at"] = (datetime.utcnow() + timedelta(minutes=DISPLAY_CODE_TTL_MINUTES)).isoformat() + "Z"
    machines[machine_id]["last_seen"] = datetime.now().isoformat()

    # update transactions if we have a transaction_id
    if transaction_id:
        tx = transactions.get(transaction_id, {})
        tx["completed_at"] = datetime.utcnow().isoformat() + "Z"
        tx["dispensed"] = dispensed
        transactions[transaction_id] = tx

    # clear lock
    if machine_id in locks:
        try:
            del locks[machine_id]
        except KeyError:
            pass

    print(f"✅ Machine {machine_id} confirmed dispense: {dispensed} items (transaction={transaction_id})")
    return {"status": "confirmed", "dispensed": dispensed}

@app.post("/api/machine/{machine_id}/report-error")
async def report_error(machine_id: str, request: Request, authorization: Optional[str] = Header(None)):
    """ESP32 sends timeout or failure reports"""
    verify_api_key(machine_id, authorization)

    data = await request.json()
    err = data.get("error")
    print(f"⚠️ Error from machine {machine_id}: {err}")

    machines[machine_id]["status"] = "idle"
    return {"message": "Error logged"}


def generate_display_code():
    # MV-XXXXXXXX (8 uppercase alnum)
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    code = "MV-" + "".join(secrets.choice(alphabet) for _ in range(8))
    return code


def hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def expire_locks_if_needed():
    # simple sweep to expire locks past their TTL
    now = datetime.utcnow()
    expired = []
    for mid, lk in list(locks.items()):
        exp = lk.get("expires_at")
        if exp:
            # parse isoformat
            try:
                exp_dt = datetime.fromisoformat(exp.replace("Z", ""))
            except Exception:
                continue
            if exp_dt < now:
                expired.append(mid)
    for mid in expired:
        locks[mid]["status"] = "expired"
        machines[mid]["status"] = "idle"
        # rotate display code
        machines[mid]["display_code"] = generate_display_code()
        machines[mid]["display_code_expires_at"] = (datetime.utcnow() + timedelta(minutes=DISPLAY_CODE_TTL_MINUTES)).isoformat() + "Z"


# Initialize display codes for all machines at startup to ensure randomness
for mid, m in machines.items():
    if not m.get("display_code"):
        m["display_code"] = generate_display_code()
    if not m.get("display_code_expires_at"):
        m["display_code_expires_at"] = (datetime.utcnow() + timedelta(minutes=DISPLAY_CODE_TTL_MINUTES)).isoformat() + "Z"


# ============ Frontend → ESP32 Dispense Trigger ============
@app.post("/api/machine/{machine_id}/dispense")
async def trigger_dispense(machine_id: str, request: Request):
    """Frontend (React) calls this after payment verification"""
    if machine_id not in machines:
        raise HTTPException(status_code=404, detail="Machine not found")

    data = await request.json()
    quantity = int(data.get("quantity", 1))
    code = data.get("code", machines[machine_id].get("display_code"))

    machines[machine_id]["status"] = "dispense"
    machines[machine_id]["quantity"] = quantity
    # keep display_code unchanged here; machines should retain display code until confirm
    print(f"🚀 Dispense command sent to {machine_id}: {quantity} items (code={code})")

    return {"message": f"Dispense command sent to {machine_id}", "status": "ok"}


@app.post("/api/lock-by-code")
async def lock_by_code(request: Request):
    """Frontend posts { client_id, code } to lock the machine atomically (in-memory simplified)
    This stores access_code_hash in locks and sets machine status to 'locked'.
    """
    data = await request.json()
    client_id = data.get("client_id")
    code = data.get("code")
    print(client_id,code)
    if not client_id or not code:
        raise HTTPException(status_code=400, detail="client_id and code required")

    # expire any stale locks first
    expire_locks_if_needed()

    # find a machine with matching display_code and idle status
    target_mid = None
    for mid, m in machines.items():
        if m.get("display_code") == code and m.get("status") == "idle":
            target_mid = mid
            break

    if not target_mid:
        # either code invalid or machine busy
        # if a lock exists with this code but expired, it's been rotated by expire_locks_if_needed
        raise HTTPException(status_code=400, detail="Code not found or expired")

    # double-check there's no active lock
    if target_mid in locks and locks[target_mid].get("status") == "locked":
        lk = locks[target_mid]
        return JSONResponse({
            "status": "busy",
            "message": "Machine is already locked by another user",
            "locked_by": lk.get("locked_by"),
            "locked_until": lk.get("expires_at")
        }, status_code=409)

    # create lock with hashed access code
    now = datetime.utcnow()
    expires_at = (now + timedelta(minutes=DISPLAY_CODE_TTL_MINUTES)).isoformat() + "Z"
    locks[target_mid] = {
        "locked_by": client_id,
        "access_code_hash": hash_code(code),
        "locked_at": now.isoformat() + "Z",
        "expires_at": expires_at,
        "status": "locked",
    }
    machines[target_mid]["status"] = "locked"

    return {
        "status": "locked",
        "machine_id": target_mid,
        "access_code": code,
        "expires_at": expires_at,
    }


@app.post("/api/machine/{machine_id}/trigger-dispense")
async def trigger_dispense_validated(machine_id: str, request: Request):
    """Called by backend after payment verification to instruct machine to dispense.
    Validates the lock, client and access_code hash before changing machine state.
    Body: { client_id, access_code, quantity, transaction_id, amount }
    """
    if machine_id not in machines:
        raise HTTPException(status_code=404, detail="Machine not found")

    data = await request.json()
    client_id = data.get("client_id")
    access_code = data.get("access_code")
    quantity = int(data.get("quantity", 1))
    transaction_id = data.get("transaction_id")
    amount = data.get("amount")

    if not client_id or not access_code or not transaction_id:
        raise HTTPException(status_code=400, detail="client_id, access_code and transaction_id required")

    # expire any stale locks
    expire_locks_if_needed()

    lk = locks.get(machine_id)
    if not lk or lk.get("status") != "locked":
        raise HTTPException(status_code=409, detail="No active lock for this machine")

    # check ownership
    if lk.get("locked_by") != client_id:
        raise HTTPException(status_code=403, detail="Lock not owned by this client")

    # check expiry
    try:
        exp_dt = datetime.fromisoformat(lk.get("expires_at").replace("Z", ""))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid lock expires_at")
    if exp_dt < datetime.utcnow():
        lk["status"] = "expired"
        machines[machine_id]["status"] = "idle"
        raise HTTPException(status_code=409, detail="Lock expired")

    # verify access code via hash
    if lk.get("access_code_hash") != hash_code(access_code):
        raise HTTPException(status_code=403, detail="Access code mismatch")

    # all good: update status to dispense and mark lock consumed
    machines[machine_id]["status"] = "dispense"
    machines[machine_id]["quantity"] = quantity
    lk["status"] = "consumed"
    lk["transaction_id"] = transaction_id

    # create transaction record (in-memory)
    transactions[transaction_id] = {
        "id": transaction_id,
        "machine_id": machine_id,
        "client_id": client_id,
        "access_code_hash": lk.get("access_code_hash"),
        "amount": amount,
        "quantity": quantity,
        "payment_status": "paid",
        "created_at": datetime.utcnow().isoformat() + "Z",
    }

    return {"status": "dispatch_sent"}

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

    sender = os.getenv("SENDER_EMAIL")
    password = os.getenv("SENDER_PASSWORD")
    receiver = os.getenv("RECEIVER_EMAIL")
    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", 587))

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
