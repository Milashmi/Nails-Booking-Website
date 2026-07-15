"""
utils.py
--------
Helpers shared across the route files:
  - saving uploaded images safely (payment screenshots, design uploads, avatars)
  - TOTP / QR helpers for two-factor authentication
  - the availability engine: which slots (and which whole days) are still free
"""

import io
import os
import re
import base64
import hashlib
import secrets
from datetime import datetime, timedelta, date, time

import pyotp
import qrcode
from PIL import Image
from werkzeug.utils import secure_filename
from flask import current_app

from extensions import db
from models import (Appointment, BlockedDate, Service, Payment,
                    SLOT_HOLDING_STATUSES)


# ---------------- uploads ----------------

def allowed_file(filename):
    """True if the filename has an allowed image extension."""
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower()
        in current_app.config["ALLOWED_EXTENSIONS"]
    )


def save_image(file_storage, max_side=1600):
    """
    Save an uploaded image to the uploads folder and return its filename.

    Steps taken for safety:
      - reject anything that is not a whitelisted image type
      - generate a random filename so users cannot overwrite each other's files
        or guess paths
      - re-encode the image with Pillow, which strips any smuggled payload and
        shrinks very large photos down to a sane size

    Returns the saved filename, or None if no valid file was provided.
    """
    if not file_storage or file_storage.filename == "":
        return None

    if not allowed_file(file_storage.filename):
        return None

    # Keep the original extension but discard the original (untrusted) name.
    ext = secure_filename(file_storage.filename).rsplit(".", 1)[1].lower()
    if ext == "jpg":
        ext = "jpeg"
    random_name = f"{secrets.token_hex(16)}.{ext}"
    save_path = os.path.join(current_app.config["UPLOAD_FOLDER"], random_name)

    try:
        img = Image.open(file_storage.stream)
        img = img.convert("RGBA") if ext == "png" else img.convert("RGB")
        img.thumbnail((max_side, max_side))   # scale down, keeping aspect ratio
        img.save(save_path)
    except Exception:
        # If Pillow cannot read it, it was not a real image.
        return None

    return random_name


def delete_upload(filename):
    """Remove an uploaded file from disk (ignore if it is already gone)."""
    if not filename:
        return
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], filename)
    try:
        os.remove(path)
    except OSError:
        pass


# ---------------- reading the payment screenshot ----------------
#
# When a client uploads their eSewa receipt we try to actually READ it, and
# check three things: that it went to the studio's number, that it was for the
# right amount, and that it says the transfer succeeded. That stops people
# uploading a screenshot of their lunch, or last month's receipt, or a transfer
# to somebody else.
#
# Two rules govern this code:
#
#   1. It is ADVISORY, never authoritative. OCR misreads real receipts — a dark
#      theme, a cropped screenshot, an odd font. So a failed check WARNS the
#      client and FLAGS it for the owner; it never rejects the money outright,
#      and it never approves it either. A human still decides.
#
#   2. It is OPTIONAL. If the Tesseract engine is not installed on this machine
#      — which it will not be, on most — everything below quietly turns itself
#      off and the site behaves exactly as it did before. Nothing crashes.

def _ocr_engine():
    """
    Return a usable pytesseract module, or None if OCR is not available here.
    Cached on the app so we only pay for the check once.
    """
    if "_ocr" in current_app.extensions:
        return current_app.extensions["_ocr"]

    engine = None
    try:
        import pytesseract

        cmd = current_app.config.get("TESSERACT_CMD", "")
        if cmd and os.path.exists(cmd):
            pytesseract.pytesseract.tesseract_cmd = cmd

        # Prove it actually runs before we rely on it.
        pytesseract.get_tesseract_version()
        engine = pytesseract
    except Exception:
        # No pytesseract, no engine binary, or it refuses to start. Either way
        # we carry on without OCR rather than taking the site down.
        current_app.logger.info(
            "Tesseract OCR not available — payment screenshots will not be "
            "read automatically. The admin still verifies them by eye.")

    current_app.extensions["_ocr"] = engine
    return engine


def _digits(text):
    """Every run of digits in the text, as a single searchable string."""
    return re.sub(r"[^0-9]", "", text or "")


def read_payment_screenshot(filename, expected_amount):
    """
    Read an uploaded eSewa receipt and check it looks genuine.

    Returns a dict the caller stores on the Payment row:
        checked     did OCR actually run?
        number_ok   does the studio's eSewa number appear?
        amount_ok   does the expected amount appear?
        success_ok  does it say the transfer succeeded?
        note        a short human summary
    """
    blank = {"checked": False, "number_ok": False, "amount_ok": False,
             "success_ok": False, "note": ""}

    engine = _ocr_engine()
    if not engine or not filename:
        return blank

    path = os.path.join(current_app.config["UPLOAD_FOLDER"], filename)
    if not os.path.exists(path):
        return blank

    try:
        img = Image.open(path)
        # Receipts are small text on a plain background: greyscale and a good
        # upscale give Tesseract a much better chance than the raw phone image.
        img = img.convert("L")
        if img.width < 1000:
            scale = 1000 / img.width
            img = img.resize((1000, int(img.height * scale)), Image.LANCZOS)

        text = engine.image_to_string(img)
    except Exception as exc:
        current_app.logger.warning("OCR failed on %s: %s", filename, exc)
        return blank

    low = text.lower()
    seen_digits = _digits(text)

    # 1. Did it go to the studio's eSewa number?
    esewa = _digits(current_app.config.get("SALON_ESEWA", ""))
    number_ok = bool(esewa) and esewa in seen_digits

    # 2. Was it for the right amount? eSewa writes it a few ways
    #    ("Rs. 500", "500.00", "NPR 500"), so match the bare number too.
    amount = int(expected_amount or 0)
    amount_ok = False
    if amount:
        patterns = [
            rf"\b{amount}\b",
            rf"\b{amount}\.00\b",
            rf"\b{amount:,}\b",          # 1,500
            rf"\b{amount:,}\.00\b",
        ]
        amount_ok = any(re.search(p, text) for p in patterns)

    # 3. Does it actually say the transfer went through?
    success_ok = any(word in low for word in (
        "success", "successful", "completed", "complete", "paid",
        "transaction successful", "payment successful",
    ))

    problems = []
    if not number_ok:
        problems.append("eSewa number not found")
    if not amount_ok:
        problems.append(f"Rs. {amount} not found")
    if not success_ok:
        problems.append("no success confirmation")

    note = "All checks passed." if not problems else "; ".join(problems)

    return {
        "checked": True,
        "number_ok": number_ok,
        "amount_ok": amount_ok,
        "success_ok": success_ok,
        "note": note[:200],
    }


# ---------------- TOTP 2FA helpers ----------------

def new_totp_secret():
    """Create a fresh random base32 secret for a new 2FA setup."""
    return pyotp.random_base32()


def totp_uri(secret, label):
    """Build the otpauth:// URI that authenticator apps understand."""
    issuer = current_app.config["TOTP_ISSUER"]
    return pyotp.TOTP(secret).provisioning_uri(name=label, issuer_name=issuer)


def totp_qr_data_uri(secret, label):
    """
    Render the provisioning URI as a QR code and return it as a base64 data URI
    so it can be dropped straight into an <img src="..."> tag.
    """
    qr_img = qrcode.make(totp_uri(secret, label))

    buffer = io.BytesIO()
    qr_img.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def verify_totp(secret, code):
    """True if the 6-digit code matches the secret (allowing slight clock drift)."""
    if not secret or not code:
        return False
    return pyotp.TOTP(secret).verify(code.strip(), valid_window=1)


# ---------------- availability engine ----------------
#
# The studio is home-based: Eleanora serves one client at a time. So a slot is
# free only if the whole appointment (start .. start + duration) overlaps no
# other *approved* booking. Pending requests deliberately do NOT hold a slot —
# two people may ask for 14:00, and whoever the admin approves first gets it.

def _slot_grid():
    """Every candidate start time in the working day, e.g. 10:00, 10:30, ..."""
    cfg = current_app.config
    grid = []
    minute = cfg["OPEN_HOUR"] * 60
    end = cfg["CLOSE_HOUR"] * 60
    while minute < end:
        grid.append(time(minute // 60, minute % 60))
        minute += cfg["SLOT_MINUTES"]
    return grid


def is_studio_open(day):
    """False if the studio is closed that weekday or the admin blocked the date."""
    cfg = current_app.config
    if day.weekday() in cfg["CLOSED_WEEKDAYS"]:
        return False
    return BlockedDate.query.filter_by(date=day).first() is None


def booked_intervals(day, exclude_id=None):
    """The (start, end) minute-of-day ranges already held by confirmed bookings."""
    query = Appointment.query.filter(
        Appointment.booking_date == day,
        Appointment.status.in_(SLOT_HOLDING_STATUSES),
    )
    if exclude_id:
        # When rescheduling, an appointment must not collide with itself.
        query = query.filter(Appointment.id != exclude_id)

    spans = []
    for appt in query.all():
        start = appt.booking_time.hour * 60 + appt.booking_time.minute
        spans.append((start, start + (appt.duration or 90)))
    return spans


def available_slots(day, duration, exclude_id=None):
    """
    Every start time on `day` where a `duration`-minute appointment fits:
      - it must finish before closing time
      - it must not overlap an already-confirmed booking
      - if the day is today, it must be at least 2 hours from now (prep time)
    Returns a list of `time` objects.
    """
    if not is_studio_open(day):
        return []

    cfg = current_app.config
    close_minute = cfg["CLOSE_HOUR"] * 60
    taken = booked_intervals(day, exclude_id=exclude_id)

    # Same-day bookings need a little lead time.
    earliest = 0
    if day == date.today():
        now = datetime.now()
        earliest = now.hour * 60 + now.minute + 120

    free = []
    for slot in _slot_grid():
        start = slot.hour * 60 + slot.minute
        end = start + duration

        if start < earliest or end > close_minute:
            continue
        # Two ranges overlap unless one ends before the other starts.
        if any(start < b_end and b_start < end for b_start, b_end in taken):
            continue
        free.append(slot)

    return free


def open_dates(duration, exclude_id=None):
    """
    The dates a customer may still pick, as 'YYYY-MM-DD' strings.

    A date drops out of the list entirely once it is closed, blocked, or has no
    room left for an appointment of this length — so a full day never even
    appears on the calendar.
    """
    cfg = current_app.config
    today = date.today()
    dates = []
    for offset in range(cfg["BOOKING_DAYS_AHEAD"]):
        day = today + timedelta(days=offset)
        if available_slots(day, duration, exclude_id=exclude_id):
            dates.append(day.isoformat())
    return dates


def slot_is_free(day, start, duration, exclude_id=None):
    """Re-check one specific slot at submit time (guards against a stale form)."""
    return start in available_slots(day, duration, exclude_id=exclude_id)


# ---------------- pricing ----------------

def quote_price(service, design, nail_length):
    """
    The subtotal for a booking, BEFORE any discount: the service price, plus a
    surcharge for intricate art, plus a surcharge for longer nails.
    """
    from models import NAIL_LENGTHS

    total = service.price if service else 0
    if design:
        total += design.extra_price or 0
    total += NAIL_LENGTHS.get(nail_length, 0)
    return total


def find_promo(code):
    """Look up a promo code (case-insensitively). None if there is no such code."""
    from models import PromoCode

    code = (code or "").strip().upper()
    if not code:
        return None
    return PromoCode.query.filter(
        db.func.upper(PromoCode.code) == code).first()


def refund_due(payment):
    """
    What comes back to a client who cancels: half of what they actually paid.
    The studio keeps the other half — the slot was held for them, and other
    people were turned away from it.
    """
    if not payment or payment.status not in ("verified", "settled"):
        return 0   # nothing was ever verified, so there is nothing to give back

    percent = current_app.config.get("REFUND_PERCENT", 50)
    return int((payment.amount or 0) * percent / 100)


def screenshot_already_used(filename, exclude_payment_id=None):
    """
    True if this exact receipt is already backing another LIVE booking.

    One transfer buys one slot, so the same receipt must not be recycled onto a
    second booking. We hash the file's bytes rather than trusting the filename
    (which we chose at random anyway), so the same image is caught even under a
    different name.

    Two deliberate exceptions, or this guard would punish honest people:

      * A CANCELLED booking's receipt is fair game again. The client got half
        their money back and the other half was forfeited — that transfer is
        spent, and its screenshot is not evidence for anything any more.
      * A REJECTED payment's own receipt can be re-sent (that is what
        exclude_payment_id is for): the client is usually re-uploading the very
        same image with a clearer transaction code, and blocking that would trap
        them with no way to fix the booking.
    """
    from models import STATUS_CANCELLED

    path = os.path.join(current_app.config["UPLOAD_FOLDER"], filename or "")
    if not os.path.exists(path):
        return False

    with open(path, "rb") as handle:
        digest = hashlib.sha256(handle.read()).hexdigest()

    # Only bookings that are still alive can hold a receipt hostage.
    query = (Payment.query
             .join(Appointment, Payment.appointment_id == Appointment.id)
             .filter(Payment.screenshot != "",
                     Appointment.status != STATUS_CANCELLED))
    if exclude_payment_id:
        query = query.filter(Payment.id != exclude_payment_id)

    folder = current_app.config["UPLOAD_FOLDER"]
    for other in query.all():
        other_path = os.path.join(folder, other.screenshot)
        if not os.path.exists(other_path):
            continue
        with open(other_path, "rb") as handle:
            if hashlib.sha256(handle.read()).hexdigest() == digest:
                return True

    return False
