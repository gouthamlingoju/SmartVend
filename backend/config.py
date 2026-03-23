from dotenv import load_dotenv
import os

# from pathlib import Path
# load_dotenv(Path(__file__).resolve().parent.parent / '.env')

load_dotenv()
    
# Supabase configuration
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')

# Razorpay configuration
RAZORPAY_KEY_ID= os.getenv('RAZORPAY_KEY_ID')
RAZORPAY_SECRET_KEY= os.getenv('RAZORPAY_SECRET_KEY')
# FIX: architecture_review.md — "Payment Reconciliation"
RAZORPAY_WEBHOOK_SECRET = os.getenv('RAZORPAY_WEBHOOK_SECRET')
ADMIN_PASSWORD=os.getenv('ADMIN_PASSWORD')
# SMTP Configuration for Email Alerts
SMTP_SERVER = os.getenv('SMTP_SERVER')
SMTP_PORT = os.getenv('SMTP_PORT')
SENDER_EMAIL = os.getenv('SENDER_EMAIL')
SENDER_PASSWORD = os.getenv('SENDER_PASSWORD')
RECEIVER_EMAIL = os.getenv('RECEIVER_EMAIL')

# Hardware / Business Variables
DISPLAY_CODE_TTL_MINUTES = os.getenv('DISPLAY_CODE_TTL_MINUTES')

# v3.0 Session Configuration
SESSION_TTL_SECONDS = int(os.getenv('SESSION_TTL_SECONDS', '60'))     # QR rotation interval
CLAIM_TTL_SECONDS = int(os.getenv('CLAIM_TTL_SECONDS', '300'))       # 5 min payment window
MOTOR_TIMEOUT_SECONDS = int(os.getenv('MOTOR_TIMEOUT_SECONDS', '120'))  # 2 min motor max

# Pricing (paise)
PRICE_PER_UNIT_PAISA = int(os.getenv('PRICE_PER_UNIT_PAISA', '100'))  # default ₹1.00

FRONTEND_URL = os.getenv('FRONTEND_URL')
# Optional Redis URL for cross-worker WebSocket coordination (e.g. redis://localhost:6379)
REDIS_URL = os.getenv('REDIS_URL')
