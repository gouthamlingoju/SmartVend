from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import razorpay
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv
import uvicorn


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

if not razorpay_key_id or not razorpay_secret_key:
    print("WARNING: Razorpay credentials not found in environment variables!")
    print("Please set RAZORPAY_KEY_ID and RAZORPAY_SECRET_KEY")

razorpay_client = razorpay.Client(auth=(razorpay_key_id, razorpay_secret_key))

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
        pass
    except Exception as e:
        print(f"Error in dispense: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8002, reload=True)