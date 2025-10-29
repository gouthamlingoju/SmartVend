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

# SMTP Configuration for Email Alerts
SMTP_SERVER = os.getenv('SMTP_SERVER')
SMTP_PORT = os.getenv('SMTP_PORT')
SENDER_EMAIL = os.getenv('SENDER_EMAIL')
SENDER_PASSWORD = os.getenv('SENDER_PASSWORD')
RECEIVER_EMAIL = os.getenv('RECEIVER_EMAIL')

# Hardware Variables
DISPLAY_CODE_TTL_MINUTES= os.getenv('DISPLAY_CODE_TTL_MINUTES')

FRONTEND_URL = os.getenv('FRONTEND_URL')
# Optional Redis URL for cross-worker WebSocket coordination (e.g. redis://localhost:6379)
REDIS_URL = os.getenv('REDIS_URL')
