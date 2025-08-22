from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import razorpay
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import serial
import time
from dotenv import load_dotenv
import httpx    


# Load environment variables from .env file
load_dotenv()

app = FastAPI()

# Allow all origins or specify the frontend origin explicitly
origins = [os.getenv("VITE_FRONTEND_URL"),"http://localhost:5173"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Get Razorpay credentials
razorpay_key_id = os.getenv("RAZORPAY_KEY_ID")
razorpay_secret_key = os.getenv("RAZORPAY_SECRET_KEY")

# Debug: Print credentials (remove in production)
print(f"Razorpay Key ID: {'Set' if razorpay_key_id else 'NOT SET'}")
print(f"Razorpay Secret Key: {'Set' if razorpay_secret_key else 'NOT SET'}")

if not razorpay_key_id or not razorpay_secret_key:
    print("WARNING: Razorpay credentials not found in environment variables!")
    print("Please set RAZORPAY_KEY_ID and RAZORPAY_SECRET_KEY")

razorpay_client = razorpay.Client(auth=(razorpay_key_id, razorpay_secret_key))

try:
    arduino = serial.Serial(port=os.getenv("ARDUINO_PORT", "COM7"), baudrate=9600, timeout=1)
    time.sleep(2)
    print(f"Arduino connected successfully on {os.getenv('ARDUINO_PORT', 'COM7')}")
except Exception as e:
    print(f"Arduino connection failed: {e}")
    arduino = None

def Blink(number):
    if arduino:
        command = f'{number}\n'
        arduino.write(command.encode())

@app.post('/create-order')
async def create_order(request: Request):
    try:
        # Check if Razorpay credentials are set
        if not razorpay_key_id or not razorpay_secret_key:
            return JSONResponse(
                {"error": "Razorpay credentials not configured. Please set RAZORPAY_KEY_ID and RAZORPAY_SECRET_KEY"}, 
                status_code=500
            )
        
        data = await request.json()
        amount = data.get("amount")
        
        if not amount:
            return JSONResponse({"error": "Amount is required"}, status_code=400)
        
        print(f"Creating order for amount: {amount}")
        
        order = razorpay_client.order.create({
            "amount": amount,
            "currency": "INR",
            "payment_capture": 1
        })
        
        print(f"Order created successfully: {order}")
        return JSONResponse(order)
    except Exception as e:
        print(f"Error creating order: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post('/verify-payment')
async def verify_payment(request: Request):
    try:
        data = await request.json()
        payment_id = data.get("razorpay_payment_id")
        order_id = data.get("razorpay_order_id")
        signature = data.get("razorpay_signature")
        print(signature)
        if os.getenv("FLASK_ENV") == "development1":
            print("Test payment detected. Skipping signature verification.")
            return {"message": "Payment verification successful!"}
        params = {
            'razorpay_order_id': order_id,
            'razorpay_payment_id': payment_id,
            'razorpay_signature': signature
        }
        razorpay_client.utility.verify_payment_signature(params)
        return {"message": "Payment verification successful!"}
    except Exception as e:
        print(f"Error: {e}")
        return JSONResponse({"message": "Payment verification failed!"}, status_code=400)

@app.post('/low-stock-alert')
async def send_mail(request: Request):
    data = await request.json()
    machineID = data.get("machineID")
    Remaining = data.get("Remaining")
    smtp_server = os.getenv("SMTP_SERVER", 'smtp.gmail.com')
    smtp_port = int(os.getenv("SMTP_PORT", 587))
    sender_email = os.getenv("SENDER_EMAIL")
    sender_password = os.getenv("SENDER_PASSWORD")
    receiver_email = os.getenv("RECEIVER_EMAIL")
    subject = 'Refill needed'
    body = f'Pads count is too low in machine {machineID} \n Pads Left: {Remaining}'
    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = receiver_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))
    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, receiver_email, msg.as_string())
        s = "Email sent successfully!"
    except Exception as e:
        print(f"Error: {e}")
        s = str(e)
    finally:
        server.quit()
    return {"message": s}

@app.post('/dispense')
async def dispense(request: Request):
    try:
        data = await request.json()
        quantity = data.get('number', 1)

        if quantity < 1 or quantity > 5:
            return JSONResponse({"error": "Invalid quantity. Must be between 1 and 5"}, status_code=400)

        esp32_ip = "http://192.168.94.105"  # replace with your actual IP
        duration = quantity  # 1 item = 1 second of rotation, adjust logic as needed

        async with httpx.AsyncClient() as client:
            response = await client.get(f"{esp32_ip}/forward", params={"n": duration}, timeout=10.0)

        if response.status_code == 200:
            return {"status": "success", "message": f"Dispensed for {duration} second(s)"}
        else:
            return JSONResponse({"error": "ESP32 failed to respond properly"}, status_code=500)

    except Exception as e:
        print(f"Error in dispense: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post('/blink')
async def blink(request: Request):
    data = await request.json()
    count = data.get('number', 0)
    if count:
        Blink(count)
        return {"status": "ok", "message": f"Blinked {count} times"}
    else:
        return JSONResponse({"status": "error", "message": "Invalid input"}, status_code=400)

@app.get('/hardware-status')
async def get_hardware_status():
    try:
        if arduino:
            arduino.write(b'STATUS\n')
            arduino.timeout = 2
            response = arduino.readline().decode().strip()
            
            if response.startswith('RESPONSE:STATUS:'):
                parts = response.split(':')[1].split(',')
                return {
                    "machine_id": parts[0],
                    "location": parts[1],
                    "stock": int(parts[2]),
                    "is_dispensing": parts[3] == "1",
                    "hardware_connected": True
                }
            else:
                return {"hardware_connected": False, "error": "No response from hardware"}
        else:
            return {"hardware_connected": False, "error": "Hardware not connected"}
            
    except Exception as e:
        print(f"Error getting hardware status: {e}")
        return {"hardware_connected": False, "error": str(e)}

@app.get('/hardware-stock')
async def get_hardware_stock():
    try:
        if arduino:
            arduino.write(b'STOCK\n')
            arduino.timeout = 2
            response = arduino.readline().decode().strip()
            
            if response.startswith('RESPONSE:STOCK:'):
                stock = int(response.split(':')[1])
                return {"stock": stock, "hardware_connected": True}
            else:
                return {"hardware_connected": False, "error": "No response from hardware"}
        else:
            return {"hardware_connected": False, "error": "Hardware not connected"}
            
    except Exception as e:
        print(f"Error getting hardware stock: {e}")
        return {"hardware_connected": False, "error": str(e)}

# To run: uvicorn main:app --reload
