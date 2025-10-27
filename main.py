from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from typing import Optional
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
# In production, use Firebase/Supabase or PostgreSQL.
machines = {
    "M1": {
        "api_key": "sv_m1_3h5k9d",
        "status": "idle",
        "code": "MV-1001",
        "quantity": 0,
        "last_seen": None,
    },
    "M2": {
        "api_key": "sv_m2_7x9k2b",
        "status": "idle",
        "code": "MV-2001",
        "quantity": 0,
        "last_seen": None,
    }
}

# ============ Auth Helper ============
def verify_api_key(machine_id: str, authorization: Optional[str]):
    if machine_id not in machines:
        raise HTTPException(status_code=404, detail="Machine not registered")

    expected_key = machines[machine_id]["api_key"]
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    provided = authorization.split(" ")[1].strip()
    if provided != expected_key:
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
            "code": "MV-" + str(datetime.now().strftime("%H%M")),
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
    return {
        "machine_id": machine_id,
        "status": m["status"],
        "code": m["code"],
        "quantity": m["quantity"],
    }

@app.post("/api/machine/{machine_id}/confirm")
async def confirm_dispense(machine_id: str, request: Request, authorization: Optional[str] = Header(None)):
    """ESP32 confirms dispensing success"""
    verify_api_key(machine_id, authorization)

    data = await request.json()
    dispensed = data.get("dispensed", 0)
    code = data.get("code")

    machines[machine_id]["status"] = "idle"
    machines[machine_id]["code"] = f"MV-{datetime.now().strftime('%H%M')}"
    machines[machine_id]["last_seen"] = datetime.now().isoformat()

    print(f"✅ Machine {machine_id} confirmed dispense: {dispensed} items (code={code})")
    return {"message": "Confirmed", "dispensed": dispensed}

@app.post("/api/machine/{machine_id}/report-error")
async def report_error(machine_id: str, request: Request, authorization: Optional[str] = Header(None)):
    """ESP32 sends timeout or failure reports"""
    verify_api_key(machine_id, authorization)

    data = await request.json()
    err = data.get("error")
    print(f"⚠️ Error from machine {machine_id}: {err}")

    machines[machine_id]["status"] = "idle"
    return {"message": "Error logged"}

# ============ Frontend → ESP32 Dispense Trigger ============
@app.post("/api/machine/{machine_id}/dispense")
async def trigger_dispense(machine_id: str, request: Request):
    """Frontend (React) calls this after payment verification"""
    if machine_id not in machines:
        raise HTTPException(status_code=404, detail="Machine not found")

    data = await request.json()
    quantity = int(data.get("quantity", 1))
    code = data.get("code", machines[machine_id]["code"])

    machines[machine_id]["status"] = "dispense"
    machines[machine_id]["quantity"] = quantity
    machines[machine_id]["code"] = code
    print(f"🚀 Dispense command sent to {machine_id}: {quantity} items")

    return {"message": f"Dispense command sent to {machine_id}", "status": "ok"}

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
