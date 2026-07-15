"""
config.py
---------
Central configuration for the Eleanora Nails app.

Every setting lives in one place so it is easy to change things (like the
database password) without hunting through the code.

Values can be overridden with environment variables (see .env.example),
which keeps secrets out of the source code.
"""

import os
from datetime import timedelta

# Absolute path of the backend folder (this file's directory).
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# The frontend folder sits next to the backend folder.
FRONTEND_DIR = os.path.join(os.path.dirname(BASE_DIR), "frontend")


class Config:
    # --- Secret key: signs session cookies and CSRF tokens ---
    # In production this MUST be a long random value kept secret.
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-to-a-long-random-string")

    # --- MySQL connection settings ---
    # Change these to match your local MySQL install.
    # Password is commonly "root" or "kali" on lab machines.
    DB_USER = os.environ.get("DB_USER", "root")
    DB_PASSWORD = os.environ.get("DB_PASSWORD", "kali")   # try "root" if kali fails
    DB_HOST = os.environ.get("DB_HOST", "localhost")
    DB_PORT = os.environ.get("DB_PORT", "3306")
    DB_NAME = os.environ.get("DB_NAME", "eleanora_nails")

    # SQLAlchemy connection string for MySQL using the PyMySQL driver.
    SQLALCHEMY_DATABASE_URI = (
        f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
        "?charset=utf8mb4"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False  # silence noisy warning / save memory

    # --- Where Jinja templates and static assets live (in ../frontend) ---
    TEMPLATE_FOLDER = os.path.join(FRONTEND_DIR, "templates")
    STATIC_FOLDER = os.path.join(FRONTEND_DIR, "static")

    # --- Image upload settings ---
    UPLOAD_FOLDER = os.path.join(FRONTEND_DIR, "static", "uploads")
    DESIGN_FOLDER = os.path.join(FRONTEND_DIR, "static", "designs")
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5 MB max upload to avoid abuse

    # --- Session / cookie security hardening ---
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)   # auto-logout after 7 days
    SESSION_COOKIE_HTTPONLY = True    # JS cannot read the cookie -> blocks XSS theft
    SESSION_COOKIE_SAMESITE = "Lax"   # basic CSRF defence for the cookie
    # Set to True when serving over HTTPS in production.
    SESSION_COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "0") == "1"

    # Issuer name shown inside the authenticator app for 2FA.
    TOTP_ISSUER = "Eleanora Nails"

    # Per-IP rate limiting is ON by default and should stay on in production —
    # it is what stops password guessing and booking-spam from one machine.
    # The test suite drives hundreds of requests from a single IP, so it sets
    # RATELIMIT_ENABLED=0 to get out of its own way.
    RATELIMIT_ENABLED = os.environ.get("RATELIMIT_ENABLED", "1") != "0"

    # ---------------- Salon / business settings ----------------
    SALON_NAME = "Eleanora Nails"
    SALON_TAGLINE = "Nails that speak elegance"
    SALON_PHONE = "+977 9847495064"     # the same number as the eSewa QR
    SALON_EMAIL = "mizumilamgade@gmail.com"
    # Home-based studio — the exact address is shared after a booking is approved.
    SALON_AREA = "Ghattekulo, Dillibazar"
    SALON_ADDRESS = "Home Studio · Ghattekulo, Dillibazar, Kathmandu, Nepal"
    SALON_MAP_EMBED = (
        "https://www.google.com/maps?q=Ghattekulo,Dillibazar,Kathmandu&output=embed"
    )
    # The eSewa account the payment QR pays into.
    SALON_ESEWA = "9847495064"
    SALON_ESEWA_NAME = "Mizumi Lamgade"

    # --- Booking window (a home studio: one client at a time) ---
    OPEN_HOUR = 10          # first appointment starts at 10:00
    CLOSE_HOUR = 18         # last appointment must END by 18:00
    SLOT_MINUTES = 30       # slots are offered on the half hour
    BOOKING_DAYS_AHEAD = 45  # how far into the future customers may book
    # Weekday numbers the studio is closed (Monday=0 ... Sunday=6).
    CLOSED_WEEKDAYS = {5}   # closed on Saturdays (public holiday in Nepal)

    # ---- Money ----
    # EVERY booking now takes the same Rs. 500 advance up front. It is what makes
    # a slot worth holding: without it, a no-show costs the studio a whole
    # afternoon and nothing else. The rest is settled at the studio.
    DEPOSIT_AMOUNT = 500

    # If a client cancels, half the advance comes back and the studio keeps the
    # other half — the slot was held for them and turned other people away.
    REFUND_PERCENT = 50

    # Where the OCR engine lives. If it is not installed the app still runs;
    # screenshot reading is simply skipped (see utils.read_payment_screenshot).
    TESSERACT_CMD = os.environ.get(
        "TESSERACT_CMD", r"C:\Program Files\Tesseract-OCR\tesseract.exe")
