"""
models.py
---------
Database tables described as Python classes (SQLAlchemy ORM).

Tables:
  - User        : customer / admin accounts, hashed passwords, optional TOTP 2FA
  - Service     : the four treatments (Overlay, Gel Extension, Gel-X, Acrylic)
  - Design      : the nail-art gallery (image + category)
  - Color       : the polish palette customers pick from
  - Appointment : a booking — service + design + colours + shape + length + slot
  - Payment     : the transfer proof attached to an appointment (pre or post pay)
  - Review      : a star rating + comment left after a completed appointment
  - BlockedDate : a day the admin has closed off (holiday, personal leave)
"""

from datetime import datetime, timedelta, time, date

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from extensions import db, login_manager


# ---------------------------------------------------------------- users

class User(UserMixin, db.Model):
    """A customer (or, when role == 'admin', the salon owner)."""
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)

    # We never store the raw password, only a salted hash.
    password_hash = db.Column(db.String(255), nullable=False)

    phone = db.Column(db.String(20), default="")
    avatar = db.Column(db.String(255), default="")   # filename in /static/uploads

    # "customer" or "admin". The first account created becomes the admin.
    role = db.Column(db.String(20), default="customer", nullable=False, index=True)

    # --- TOTP two-factor authentication fields ---
    totp_secret = db.Column(db.String(32), default="")     # base32 shared secret
    totp_enabled = db.Column(db.Boolean, default=False)    # is 2FA turned on?

    # --- Brute-force protection ---
    # Consecutive failed login / 2FA attempts. After too many the account is
    # locked until `locked_until`, which stops rapid password / TOTP guessing.
    failed_attempts = db.Column(db.Integer, default=0)
    locked_until = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    appointments = db.relationship("Appointment", backref="user", lazy=True,
                                   cascade="all, delete-orphan")
    reviews = db.relationship("Review", backref="user", lazy=True,
                              cascade="all, delete-orphan")

    # ---- Convenience ----
    @property
    def is_admin(self):
        return self.role == "admin"

    @property
    def first_name(self):
        return (self.full_name or "").split(" ")[0]

    @property
    def initials(self):
        parts = [p for p in (self.full_name or "").split(" ") if p]
        return "".join(p[0].upper() for p in parts[:2]) or "?"

    # ---- Password helpers ----
    def set_password(self, raw_password):
        """Hash and store a new password."""
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password):
        """Return True if the given password matches the stored hash."""
        return check_password_hash(self.password_hash, raw_password)

    # ---- Brute-force lockout helpers ----
    def is_locked(self):
        """True if the account is currently temporarily locked."""
        return self.locked_until is not None and self.locked_until > datetime.utcnow()

    def lock_seconds_left(self):
        """How many seconds until the lock expires (0 if not locked)."""
        if not self.is_locked():
            return 0
        return int((self.locked_until - datetime.utcnow()).total_seconds())

    def register_failure(self, max_attempts=5, lock_minutes=15):
        """
        Record one failed attempt. Once `max_attempts` consecutive failures are
        reached, lock the account for `lock_minutes` minutes.
        """
        self.failed_attempts = (self.failed_attempts or 0) + 1
        if self.failed_attempts >= max_attempts:
            self.locked_until = datetime.utcnow() + timedelta(minutes=lock_minutes)
            self.failed_attempts = 0   # reset the counter for the next window

    def reset_failures(self):
        """Clear the failure counter and any lock (called on a successful login)."""
        self.failed_attempts = 0
        self.locked_until = None

    def __repr__(self):
        return f"<User {self.email}>"


# ------------------------------------------------------------- catalogue

class Service(db.Model):
    """One of the treatments on the menu."""
    __tablename__ = "services"

    id = db.Column(db.Integer, primary_key=True)
    service_name = db.Column(db.String(80), nullable=False)
    description = db.Column(db.String(400), default="")
    price = db.Column(db.Integer, nullable=False)        # rupees, whole numbers
    duration = db.Column(db.Integer, nullable=False)     # minutes (used for slots)
    image = db.Column(db.String(255), default="")
    # A seeded service uses a photo from /static/designs; one the admin created
    # uploaded its own picture to /static/uploads.
    is_upload = db.Column(db.Boolean, default=False)

    is_active = db.Column(db.Boolean, default=True, index=True)
    sort_order = db.Column(db.Integer, default=0)

    appointments = db.relationship("Appointment", backref="service", lazy=True)
    designs = db.relationship("Design", backref="service", lazy=True)

    @property
    def image_url_path(self):
        """Which static sub-folder this image lives in."""
        if not self.image:
            return ""
        return f"uploads/{self.image}" if self.is_upload else f"designs/{self.image}"

    @property
    def duration_label(self):
        """'90 mins' or '1h 30m' style label for the cards."""
        h, m = divmod(self.duration, 60)
        if h and m:
            return f"{h}h {m}m"
        if h:
            return f"{h}h"
        return f"{m} mins"

    def __repr__(self):
        return f"<Service {self.service_name}>"


class Design(db.Model):
    """A nail-art design in the gallery."""
    __tablename__ = "designs"

    id = db.Column(db.Integer, primary_key=True)
    design_name = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(40), default="Minimalist", index=True)
    image = db.Column(db.String(255), nullable=False)

    # Seeded designs live in /static/designs; admin uploads land in /static/uploads.
    is_upload = db.Column(db.Boolean, default=False)

    # Designs suit a particular service best (optional).
    service_id = db.Column(db.Integer,
                           db.ForeignKey("services.id", ondelete="SET NULL"),
                           nullable=True)

    # A small surcharge for the more intricate art (Rs.). Added to the service price.
    extra_price = db.Column(db.Integer, default=0)

    is_active = db.Column(db.Boolean, default=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    appointments = db.relationship("Appointment", backref="design", lazy=True)

    @property
    def image_url_path(self):
        """Which static sub-folder this image lives in."""
        return f"uploads/{self.image}" if self.is_upload else f"designs/{self.image}"

    def __repr__(self):
        return f"<Design {self.design_name}>"


class Color(db.Model):
    """A polish colour customers can choose."""
    __tablename__ = "colors"

    id = db.Column(db.Integer, primary_key=True)
    color_name = db.Column(db.String(40), nullable=False)
    hex_code = db.Column(db.String(7), nullable=False)   # e.g. "#e8b4b8"
    is_active = db.Column(db.Boolean, default=True, index=True)

    def __repr__(self):
        return f"<Color {self.color_name}>"


class BlockedDate(db.Model):
    """A single date the admin has closed the studio."""
    __tablename__ = "blocked_dates"

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, unique=True, nullable=False, index=True)
    reason = db.Column(db.String(120), default="")


# ----------------------------------------------------------- appointments

# The nail shapes and lengths on offer. Kept here so the booking form, the
# validator and the admin dashboard all read from one list.
NAIL_SHAPES = ["Square", "Coffin", "Almond", "Oval", "Stiletto"]

# Longer nails take more product and time, so they carry a small surcharge.
NAIL_LENGTHS = {
    "Short": 0,
    "Medium": 200,
    "Long": 400,
    "Extra Long": 700,
}

# The lifecycle of a booking.
STATUS_PENDING = "pending"       # waiting for the admin to verify + approve
STATUS_APPROVED = "approved"     # confirmed; this slot is now held
STATUS_COMPLETED = "completed"   # the client has been served
STATUS_CANCELLED = "cancelled"   # cancelled by the client or the admin

# Only an approved (or completed) booking actually holds a time slot — a
# pending request does not block anyone else from asking for the same time.
SLOT_HOLDING_STATUSES = (STATUS_APPROVED, STATUS_COMPLETED)


class Appointment(db.Model):
    """A booking made through the 9-step wizard."""
    __tablename__ = "appointments"

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False,
                        index=True)
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"), nullable=False)
    design_id = db.Column(db.Integer,
                          db.ForeignKey("designs.id", ondelete="SET NULL"),
                          nullable=True)

    # Three optional colour picks (base is required by the form).
    color_id = db.Column(db.Integer, db.ForeignKey("colors.id", ondelete="SET NULL"),
                         nullable=True)
    secondary_color_id = db.Column(
        db.Integer, db.ForeignKey("colors.id", ondelete="SET NULL"), nullable=True)
    accent_color_id = db.Column(
        db.Integer, db.ForeignKey("colors.id", ondelete="SET NULL"), nullable=True)

    nail_shape = db.Column(db.String(20), nullable=False)
    nail_length = db.Column(db.String(20), nullable=False)

    booking_date = db.Column(db.Date, nullable=False, index=True)
    booking_time = db.Column(db.Time, nullable=False)
    # Copied from the service at booking time so later price edits don't move
    # the goalposts on an existing booking.
    duration = db.Column(db.Integer, nullable=False, default=90)  # minutes
    total_price = db.Column(db.Integer, nullable=False)

    notes = db.Column(db.String(500), default="")
    status = db.Column(db.String(20), default=STATUS_PENDING, nullable=False,
                       index=True)
    admin_note = db.Column(db.String(300), default="")   # reason for a rejection

    # A promo code applied at booking time. The discount is stored alongside it
    # so that editing (or deleting) the code later cannot silently reprice a
    # booking that has already been made.
    promo_id = db.Column(db.Integer,
                         db.ForeignKey("promo_codes.id", ondelete="SET NULL"),
                         nullable=True)
    discount = db.Column(db.Integer, default=0)     # rupees taken off

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    # Explicit foreign_keys: three separate FKs point at the colors table.
    base_color = db.relationship("Color", foreign_keys=[color_id])
    secondary_color = db.relationship("Color", foreign_keys=[secondary_color_id])
    accent_color = db.relationship("Color", foreign_keys=[accent_color_id])

    payment = db.relationship("Payment", backref="appointment", uselist=False,
                              cascade="all, delete-orphan")
    review = db.relationship("Review", backref="appointment", uselist=False,
                             cascade="all, delete-orphan")
    promo = db.relationship("PromoCode", foreign_keys=[promo_id])

    # ---- Derived helpers ----
    @property
    def start_dt(self):
        return datetime.combine(self.booking_date, self.booking_time)

    @property
    def end_dt(self):
        return self.start_dt + timedelta(minutes=self.duration or 90)

    @property
    def is_upcoming(self):
        return (self.start_dt >= datetime.now()
                and self.status in (STATUS_PENDING, STATUS_APPROVED))

    @property
    def can_cancel(self):
        """Clients may cancel up until the appointment starts."""
        return (self.status in (STATUS_PENDING, STATUS_APPROVED)
                and self.start_dt > datetime.now())

    @property
    def can_reschedule(self):
        """Rescheduling is allowed up to 24 hours before the slot."""
        return (self.status in (STATUS_PENDING, STATUS_APPROVED)
                and self.start_dt > datetime.now() + timedelta(hours=24))

    @property
    def can_review(self):
        return self.status == STATUS_COMPLETED and self.review is None

    @property
    def status_label(self):
        return {
            STATUS_PENDING: "Awaiting approval",
            STATUS_APPROVED: "Confirmed",
            STATUS_COMPLETED: "Completed",
            STATUS_CANCELLED: "Cancelled",
        }.get(self.status, self.status.title())

    def __repr__(self):
        return f"<Appointment {self.id} {self.booking_date} {self.booking_time}>"


class Payment(db.Model):
    """
    The advance a client transferred to hold their slot.

    EVERY booking now pays the same Rs. 500 advance up front, whichever way they
    settle the balance:

      method == "advance"  -> advance now, the balance settled at the studio
      method == "full"     -> advance now, and they intend to pay the rest by
                              transfer as well (the admin records it on the day)

    Either way a transaction code and a screenshot are required, and the admin
    checks both before the booking is confirmed.
    """
    __tablename__ = "payments"

    id = db.Column(db.Integer, primary_key=True)
    appointment_id = db.Column(db.Integer,
                               db.ForeignKey("appointments.id", ondelete="CASCADE"),
                               nullable=False, unique=True)

    method = db.Column(db.String(20), nullable=False)      # advance / full
    amount = db.Column(db.Integer, nullable=False, default=0)   # what they sent
    balance = db.Column(db.Integer, default=0)                  # left to pay

    transaction_code = db.Column(db.String(60), default="")
    screenshot = db.Column(db.String(255), default="")     # filename in /static/uploads

    # pending -> verified / rejected. 'settled' once the balance is paid too.
    status = db.Column(db.String(20), default="pending", nullable=False, index=True)
    verified_at = db.Column(db.DateTime, nullable=True)

    # ---- what the OCR made of the screenshot ----
    # We read the image on upload and look for the studio's eSewa number, the
    # amount, and a word meaning "success". The result is advisory: it is shown
    # to the admin to speed up their check, never used to auto-approve money.
    ocr_checked = db.Column(db.Boolean, default=False)
    ocr_number_ok = db.Column(db.Boolean, default=False)   # right eSewa number?
    ocr_amount_ok = db.Column(db.Boolean, default=False)   # right amount?
    ocr_success_ok = db.Column(db.Boolean, default=False)  # says "successful"?
    ocr_note = db.Column(db.String(200), default="")       # what we found / missed

    # ---- refunds ----
    refund_due = db.Column(db.Integer, default=0)          # owed after a cancel
    refund_paid = db.Column(db.Boolean, default=False)     # the studio sent it

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def status_label(self):
        return {
            "pending": "Awaiting verification",
            "verified": "Advance verified",
            "rejected": "Payment rejected",
            "settled": "Paid in full",
        }.get(self.status, self.status.title())

    @property
    def ocr_all_ok(self):
        """True only if every automated check on the screenshot passed."""
        return (self.ocr_checked and self.ocr_number_ok
                and self.ocr_amount_ok and self.ocr_success_ok)

    @property
    def ocr_flags(self):
        """The checks that FAILED — what the admin should look at closely."""
        if not self.ocr_checked:
            return []
        problems = []
        if not self.ocr_number_ok:
            problems.append("eSewa number not found")
        if not self.ocr_amount_ok:
            problems.append("amount not found")
        if not self.ocr_success_ok:
            problems.append("no 'successful' confirmation")
        return problems


class PromoCode(db.Model):
    """
    A discount code the owner hands out.

    It can take off a flat number of rupees or a percentage, may expire, may be
    limited to a number of uses, and may require a minimum spend.
    """
    __tablename__ = "promo_codes"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(24), unique=True, nullable=False, index=True)
    description = db.Column(db.String(140), default="")

    # "percent" -> `value` is 0-100.   "flat" -> `value` is rupees.
    kind = db.Column(db.String(10), nullable=False, default="percent")
    value = db.Column(db.Integer, nullable=False)

    # A percentage code on a Rs. 5,600 acrylic set could take off a fortune, so
    # the owner can cap what any one booking may claim (0 = no cap).
    max_discount = db.Column(db.Integer, default=0)
    min_spend = db.Column(db.Integer, default=0)

    usage_limit = db.Column(db.Integer, default=0)   # 0 = unlimited
    used_count = db.Column(db.Integer, default=0)

    expires_on = db.Column(db.Date, nullable=True)   # NULL = never expires
    is_active = db.Column(db.Boolean, default=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Appointment.promo already maps this same foreign key, so this side is
    # read-only — otherwise SQLAlchemy has two writers for one column.
    appointments = db.relationship("Appointment",
                                   foreign_keys="Appointment.promo_id",
                                   viewonly=True)

    @property
    def label(self):
        return (f"{self.value}% off" if self.kind == "percent"
                else f"Rs. {self.value} off")

    @property
    def is_expired(self):
        return self.expires_on is not None and self.expires_on < date.today()

    @property
    def is_used_up(self):
        return self.usage_limit > 0 and self.used_count >= self.usage_limit

    @property
    def is_usable(self):
        return self.is_active and not self.is_expired and not self.is_used_up

    def discount_on(self, subtotal):
        """
        What this code takes off a bill of `subtotal`, in rupees.
        Returns 0 if the code cannot be used on this amount.
        """
        if not self.is_usable or subtotal < (self.min_spend or 0):
            return 0

        if self.kind == "percent":
            off = subtotal * self.value // 100
        else:
            off = self.value

        if self.max_discount:
            off = min(off, self.max_discount)

        # Never discount below zero, and never below the advance we must collect.
        return max(0, min(off, subtotal))

    def why_not(self, subtotal):
        """A human explanation of why the code was refused (or None if it's fine)."""
        if not self.is_active:
            return "That code is no longer active."
        if self.is_expired:
            return "That code has expired."
        if self.is_used_up:
            return "That code has been fully claimed."
        if subtotal < (self.min_spend or 0):
            return (f"That code needs a minimum spend of Rs. "
                    f"{self.min_spend:,}.")
        return None

    def __repr__(self):
        return f"<PromoCode {self.code}>"


# The kinds of thing a client gets told about.
NOTIFY_KINDS = {
    "approved":   "Your booking is confirmed",
    "rejected":   "There's a problem with your payment",
    "cancelled":  "Your booking was cancelled",
    "completed":  "Thanks for visiting",
    "reminder":   "Your appointment is coming up",
    "refund":     "Your refund is on its way",
    "promo":      "A discount for you",
}


class Notification(db.Model):
    """
    Something the studio wants a client to know — above all, whether their
    booking was confirmed. This is what turns "I sent the money, now what?"
    into an answer.
    """
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    appointment_id = db.Column(
        db.Integer, db.ForeignKey("appointments.id", ondelete="CASCADE"),
        nullable=True)

    kind = db.Column(db.String(20), nullable=False)   # see NOTIFY_KINDS
    title = db.Column(db.String(120), nullable=False)
    body = db.Column(db.String(400), default="")

    is_read = db.Column(db.Boolean, default=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    appointment = db.relationship("Appointment", foreign_keys=[appointment_id])

    @property
    def tone(self):
        """Which colour the card should be."""
        return {
            "approved": "ok",
            "completed": "ok",
            "refund": "ok",
            "promo": "rose",
            "rejected": "danger",
            "cancelled": "danger",
        }.get(self.kind, "warn")


def notify(user_id, kind, title, body="", appointment=None):
    """Drop a notification in someone's bell. Caller commits."""
    db.session.add(Notification(
        user_id=user_id,
        kind=kind,
        title=title,
        body=body,
        appointment_id=(appointment.id if appointment else None),
    ))


class Review(db.Model):
    """A star rating and comment left by a customer."""
    __tablename__ = "reviews"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    appointment_id = db.Column(
        db.Integer, db.ForeignKey("appointments.id", ondelete="CASCADE"),
        nullable=True, unique=True)

    rating = db.Column(db.Integer, nullable=False)   # 1 - 5
    comment = db.Column(db.String(600), default="")

    # The admin can hide a review from the homepage without deleting it.
    is_visible = db.Column(db.Boolean, default=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    @property
    def stars(self):
        return range(int(self.rating or 0))


# Flask-Login needs a way to load a user from the id stored in the session.
@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))
