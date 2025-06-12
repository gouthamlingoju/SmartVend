from flask import Flask, request, jsonify
import razorpay
import os
from flask_cors import CORS
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import serial
import time


app = Flask(__name__)



def Blink(number):
    command = f'{number}\n'
    arduino.write(command.encode())

# Allow all origins or specify the frontend origin explicitly
CORS(app, resources={r"/*": {"origins": "http://localhost:5173"}})

razorpay_client = razorpay.Client(auth=(os.getenv("RAZORPAY_KEY_ID"), os.getenv("RAZORPAY_SECRET_KEY")))

@app.route('/create-order', methods=['POST'])
def create_order():
    try:
        data = request.json
        amount = data.get("amount")  # Amount in paise (100 INR = 10000 paise)

        order = razorpay_client.order.create({
            "amount": amount,
            "currency": "INR",
            "payment_capture": 1
        })

        return jsonify(order)
    except Exception as e:
        print(f"Error creating order: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/verify-payment', methods=['POST'])
def verify_payment():
    try:
        data = request.json
        payment_id = data.get("razorpay_payment_id")
        order_id = data.get("razorpay_order_id")
        signature = data.get("razorpay_signature")
        print(signature)
        # Check if it's a test payment and bypass signature verification
        if os.getenv("FLASK_ENV") == "development1":  # Assuming you're using environment variables to detect the environment
            print("Test payment detected. Skipping signature verification.")
            # Simulate successful payment verification
            return jsonify({"message": "Payment verification successful!"})

        # Otherwise, verify the payment signature using Razorpay's SDK
        params = {
            'razorpay_order_id': order_id,
            'razorpay_payment_id': payment_id,
            'razorpay_signature': signature
        }

        
        # Verify the payment signature
        razorpay_client.utility.verify_payment_signature(params)

        
        # Return a success message to the frontend
        return jsonify({"message": "Payment verification successful!"})

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"message": "Payment verification failed!"}), 400

@app.route('/low-stock-alert', methods=['POST'])
def send_mail():
    data= request.json
    machineID=data.get("machineID")
    Remaining=data.get("Remaining")
    # Setup the server and port
    smtp_server = 'smtp.gmail.com'
    smtp_port = 587  # For TLS

    # Sender email and password (Use App Password for Gmail if 2FA is enabled)
    sender_email = 'vnrvjietenglish@gmail.com'
    sender_password = 'awngnzzpdcgmiety'

    # Receiver email
    receiver_email = 'gouthamlingoju@gmail.com'

    # Create the email content
    subject = 'Refill needed'
    body = f'Pads count is too low in machine {machineID} \n Pads Left: {Remaining}'

    # Set up the MIME
    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = receiver_email
    msg['Subject'] = subject

    # Attach the email body to the message
    msg.attach(MIMEText(body, 'plain'))  # or 'html' for HTML emails

    # Send email using the smtplib
    try:
        # Connect to Gmail's SMTP server
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()  # Secure the connection

        # Log in to the server
        server.login(sender_email, sender_password)

        # Send the email
        server.sendmail(sender_email, receiver_email, msg.as_string())

        s="Email sent successfully!"

    except Exception as e:
        print(f"Error: {e}")

    finally:
        server.quit()
    return jsonify({"message": s})


@app.route('/blink', methods=['POST'])
def blink():
    data = request.get_json()
    count = data.get('number', 0)
    if count:
        Blink(count)
        return {"status": "ok", "message": f"Blinked {count} times"}
    else:
        return {"status": "error", "message": "Invalid input"}, 400

if __name__ == "__main__":
    try:
        arduino = serial.Serial(port='COM7', baudrate=9600, timeout=1)
        time.sleep(2)
        print("Arduino connected successfully on COM7")
    except Exception as e:
        print(f"Arduino connection failed: {e}")
    # 🔧 THIS LINE FIXES THE ISSUE:
    app.run(debug=True, use_reloader=False)
