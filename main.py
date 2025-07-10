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

app = FastAPI()

# Allow all origins or specify the frontend origin explicitly
origins = [os.getenv("VITE_FRONTEND_URL")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

razorpay_client = razorpay.Client(auth=(os.getenv("RAZORPAY_KEY_ID"), os.getenv("RAZORPAY_SECRET_KEY")))

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
        data = await request.json()
        amount = data.get("amount")
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

@app.post('/blink')
async def blink(request: Request):
    data = await request.json()
    count = data.get('number', 0)
    if count:
        Blink(count)
        return {"status": "ok", "message": f"Blinked {count} times"}
    else:
        return JSONResponse({"status": "error", "message": "Invalid input"}, status_code=400)

# To run: uvicorn main:app --reload
