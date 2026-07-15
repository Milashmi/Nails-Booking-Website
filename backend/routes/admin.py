"""
routes/admin.py
---------------
The salon owner's dashboard. Everything on the site can be run from here:

  - see the numbers (users, bookings, services, today's diary, takings)
  - approve / reject / complete / cancel bookings, and verify the payment
    screenshot + transaction code attached to each one
  - add, edit and remove services, designs and colours
  - close off dates the studio will not open
  - view and remove customers, and hide or delete reviews

The FIRST account registered becomes the admin (see auth.register); the seeded
owner account is admin@eleanoranails.com.
"""

import re
import secrets
from datetime import datetime, date, timedelta
from functools import wraps

from flask import (Blueprint, render_template, redirect, url_for, request,
                   flash, abort)
from flask_login import login_required, current_user
from sqlalchemy import func

from extensions import db
from models import (User, Service, Design, Color, Appointment, Payment, Review,
                    BlockedDate, PromoCode, Notification, notify,
                    STATUS_PENDING, STATUS_APPROVED, STATUS_COMPLETED,
                    STATUS_CANCELLED, SLOT_HOLDING_STATUSES)
from utils import save_image, delete_upload, slot_is_free

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def admin_required(f):
    """Allow only the logged-in salon owner; everyone else gets a 403."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------- dashboard

@admin_bp.route("/")
@login_required
@admin_required
def dashboard():
    today = date.today()

    earned = (db.session.query(func.coalesce(func.sum(Appointment.total_price), 0))
              .filter(Appointment.status == STATUS_COMPLETED).scalar())

    stats = {
        "users": User.query.filter_by(role="customer").count(),
        "bookings": Appointment.query.count(),
        "services": Service.query.filter_by(is_active=True).count(),
        "designs": Design.query.filter_by(is_active=True).count(),
        "today": Appointment.query.filter(
            Appointment.booking_date == today,
            Appointment.status.in_(SLOT_HOLDING_STATUSES)).count(),
        "pending": Appointment.query.filter_by(status=STATUS_PENDING).count(),
        "earned": int(earned or 0),
    }

    # The queue that actually needs the owner's attention.
    pending = (Appointment.query.filter_by(status=STATUS_PENDING)
               .order_by(Appointment.booking_date, Appointment.booking_time).all())

    todays = (Appointment.query.filter(
        Appointment.booking_date == today,
        Appointment.status.in_(SLOT_HOLDING_STATUSES))
        .order_by(Appointment.booking_time).all())

    upcoming = (Appointment.query.filter(
        Appointment.booking_date > today,
        Appointment.status == STATUS_APPROVED)
        .order_by(Appointment.booking_date, Appointment.booking_time)
        .limit(10).all())

    # Bookings per day for the last fortnight — drives the little bar chart.
    chart = []
    for offset in range(13, -1, -1):
        day = today - timedelta(days=offset)
        count = Appointment.query.filter(Appointment.booking_date == day).count()
        chart.append({"label": day.strftime("%d %b"), "value": count})

    return render_template("admin/dashboard.html", stats=stats, pending=pending,
                           todays=todays, upcoming=upcoming, chart=chart)


# ------------------------------------------------------------ appointments

@admin_bp.route("/appointments")
@login_required
@admin_required
def appointments():
    status = request.args.get("status", "").strip()
    query = Appointment.query
    if status in (STATUS_PENDING, STATUS_APPROVED, STATUS_COMPLETED,
                  STATUS_CANCELLED):
        query = query.filter_by(status=status)

    rows = query.order_by(Appointment.booking_date.desc(),
                          Appointment.booking_time.desc()).all()

    counts = {
        "all": Appointment.query.count(),
        STATUS_PENDING: Appointment.query.filter_by(status=STATUS_PENDING).count(),
        STATUS_APPROVED: Appointment.query.filter_by(status=STATUS_APPROVED).count(),
        STATUS_COMPLETED: Appointment.query.filter_by(status=STATUS_COMPLETED).count(),
        STATUS_CANCELLED: Appointment.query.filter_by(status=STATUS_CANCELLED).count(),
    }

    return render_template("admin/appointments.html", appointments=rows,
                           active=status or "all", counts=counts)


@admin_bp.route("/appointments/<int:appointment_id>/approve", methods=["POST"])
@login_required
@admin_required
def approve(appointment_id):
    """
    Confirm a booking. This is the moment the slot is actually held, so we
    re-check that nothing else has been approved into it in the meantime.
    """
    appt = Appointment.query.get_or_404(appointment_id)

    if not slot_is_free(appt.booking_date, appt.booking_time, appt.duration,
                        exclude_id=appt.id):
        flash("That slot is already taken by another confirmed booking. Ask the "
              "client to pick a different time, or cancel the other one first.",
              "error")
        return redirect(request.referrer or url_for("admin.appointments"))

    appt.status = STATUS_APPROVED

    # Approving a booking accepts the advance it came with.
    payment = appt.payment
    if payment and payment.status == "pending":
        payment.status = "verified"
        payment.verified_at = datetime.utcnow()

    balance = payment.balance if payment else 0
    notify(appt.user_id, "approved",
           "Your booking is confirmed",
           f"Your {appt.service.service_name} on "
           f"{appt.booking_date.strftime('%A %d %B')} at "
           f"{appt.booking_time.strftime('%I:%M %p').lstrip('0')} is confirmed. "
           + (f"Rs. {balance:,} is due at the studio." if balance
              else "Nothing left to pay.")
           + " See you then!",
           appointment=appt)

    db.session.commit()
    flash(f"Booking #{appt.id} is confirmed, the client has been notified.",
          "success")
    return redirect(request.referrer or url_for("admin.appointments"))


@admin_bp.route("/appointments/<int:appointment_id>/complete", methods=["POST"])
@login_required
@admin_required
def complete(appointment_id):
    appt = Appointment.query.get_or_404(appointment_id)
    appt.status = STATUS_COMPLETED

    # The visit happened, so the balance has been settled at the studio.
    if appt.payment:
        appt.payment.status = "settled"
        appt.payment.balance = 0
        appt.payment.verified_at = appt.payment.verified_at or datetime.utcnow()

    notify(appt.user_id, "completed",
           "Thanks for visiting!",
           f"Hope you love your {appt.service.service_name}. If you have a "
           "moment, we'd really appreciate a review.",
           appointment=appt)

    db.session.commit()
    flash(f"Booking #{appt.id} marked as completed.", "success")
    return redirect(request.referrer or url_for("admin.appointments"))


@admin_bp.route("/appointments/<int:appointment_id>/cancel", methods=["POST"])
@login_required
@admin_required
def cancel(appointment_id):
    appt = Appointment.query.get_or_404(appointment_id)
    appt.status = STATUS_CANCELLED
    appt.admin_note = request.form.get("reason", "").strip()[:300]

    # When the STUDIO cancels, the client is not at fault — so the whole advance
    # goes back, not half of it. The 50% rule only applies when they cancel.
    payment = appt.payment
    refund = 0
    if payment and payment.status in ("verified", "settled"):
        refund = payment.amount or 0
        payment.refund_due = refund
        payment.refund_paid = False

    notify(appt.user_id, "cancelled",
           "Your booking was cancelled",
           (appt.admin_note or "We're very sorry, we've had to cancel this "
                               "appointment.")
           + (f" Your full Rs. {refund:,} advance will be refunded."
              if refund else ""),
           appointment=appt)

    db.session.commit()
    flash(f"Booking #{appt.id} cancelled, the slot is free again, and the "
          "client has been notified."
          + (f" A full Rs. {refund:,} refund is owed." if refund else ""),
          "success")
    return redirect(request.referrer or url_for("admin.appointments"))


@admin_bp.route("/appointments/<int:appointment_id>/payment", methods=["POST"])
@login_required
@admin_required
def review_payment(appointment_id):
    """Accept or reject the transaction code + screenshot a client sent in."""
    appt = Appointment.query.get_or_404(appointment_id)
    if not appt.payment:
        flash("There is no payment attached to that booking.", "error")
        return redirect(request.referrer or url_for("admin.appointments"))

    decision = request.form.get("decision", "")
    payment = appt.payment

    if decision == "verify":
        payment.status = "verified"
        payment.verified_at = datetime.utcnow()
        flash("Advance verified. Approve the booking to hold the slot.",
              "success")

    elif decision == "reject":
        payment.status = "rejected"
        payment.verified_at = None
        reason = request.form.get("reason", "").strip()[:300]
        appt.admin_note = reason or ("We couldn't match that transaction. Please "
                                     "send the correct code and screenshot.")

        notify(appt.user_id, "rejected",
               "There's a problem with your payment",
               appt.admin_note + " Your slot is still held for now, please "
                                 "re-send your receipt from My Appointments.",
               appointment=appt)

        flash("Payment rejected, the client has been asked for a new "
              "screenshot.", "success")

    elif decision == "refunded":
        # The owner has actually sent the money back.
        payment.refund_paid = True
        notify(appt.user_id, "refund",
               f"Your Rs. {payment.refund_due:,} refund has been sent",
               "It should reach your eSewa shortly. Sorry it didn't work out, "
               "we'd love to see you another time.",
               appointment=appt)
        flash(f"Marked as refunded (Rs. {payment.refund_due:,}).", "success")

    else:
        flash("Unknown decision.", "error")
        return redirect(request.referrer or url_for("admin.appointments"))

    db.session.commit()
    return redirect(request.referrer or url_for("admin.appointments"))


# ---------------------------------------------------------------- services

@admin_bp.route("/services", methods=["GET", "POST"])
@login_required
@admin_required
def services():
    if request.method == "POST":
        name = request.form.get("service_name", "").strip()
        price = request.form.get("price", type=int)
        duration = request.form.get("duration", type=int)

        if not name or not price or not duration:
            flash("A service needs a name, a price and a duration.", "error")
            return redirect(url_for("admin.services"))

        image = save_image(request.files.get("image"))
        service = Service(
            service_name=name,
            description=request.form.get("description", "").strip()[:400],
            price=price,
            duration=duration,
            image=image or "",
            is_upload=bool(image),      # it went to /static/uploads
            sort_order=Service.query.count(),
        )
        db.session.add(service)
        db.session.commit()
        flash(f"'{name}' added to the menu.", "success")
        return redirect(url_for("admin.services"))

    rows = Service.query.order_by(Service.sort_order, Service.id).all()
    # An uploaded service image lives in /uploads, a seeded one in /designs.
    return render_template("admin/services.html", services=rows)


@admin_bp.route("/services/<int:service_id>/edit", methods=["POST"])
@login_required
@admin_required
def edit_service(service_id):
    service = Service.query.get_or_404(service_id)

    service.service_name = request.form.get("service_name",
                                            service.service_name).strip()
    service.description = request.form.get("description", "").strip()[:400]
    service.price = request.form.get("price", type=int) or service.price
    service.duration = request.form.get("duration", type=int) or service.duration
    service.is_active = bool(request.form.get("is_active"))

    image = save_image(request.files.get("image"))
    if image:
        if service.is_upload:
            delete_upload(service.image)   # replace the old upload on disk
        service.image = image
        service.is_upload = True

    db.session.commit()
    flash(f"'{service.service_name}' updated.", "success")
    return redirect(url_for("admin.services"))


@admin_bp.route("/services/<int:service_id>/delete", methods=["POST"])
@login_required
@admin_required
def delete_service(service_id):
    service = Service.query.get_or_404(service_id)

    # Deleting a service outright would orphan every booking that used it, so
    # once it has history we retire it instead of destroying the record.
    if service.appointments:
        service.is_active = False
        db.session.commit()
        flash(f"'{service.service_name}' has bookings against it, so it has been "
              "retired rather than deleted. It no longer appears on the site.",
              "success")
        return redirect(url_for("admin.services"))

    db.session.delete(service)
    db.session.commit()
    flash("Service deleted.", "success")
    return redirect(url_for("admin.services"))


# ---------------------------------------------------------------- designs

@admin_bp.route("/designs", methods=["GET", "POST"])
@login_required
@admin_required
def designs():
    if request.method == "POST":
        name = request.form.get("design_name", "").strip()
        category = request.form.get("category", "").strip() or "Minimalist"

        image = save_image(request.files.get("image"))
        if not name or not image:
            flash("A design needs a name and an image.", "error")
            return redirect(url_for("admin.designs"))

        db.session.add(Design(
            design_name=name,
            category=category,
            image=image,
            is_upload=True,                       # it lives in /static/uploads
            extra_price=request.form.get("extra_price", type=int) or 0,
            service_id=request.form.get("service_id", type=int) or None,
        ))
        db.session.commit()
        flash(f"'{name}' added to the gallery.", "success")
        return redirect(url_for("admin.designs"))

    rows = Design.query.order_by(Design.id.desc()).all()
    services = Service.query.order_by(Service.sort_order).all()
    categories = ["French", "Chrome", "Ombre", "Glitter", "Floral", "Marble",
                  "Luxury", "Minimalist"]
    return render_template("admin/designs.html", designs=rows, services=services,
                           categories=categories)


@admin_bp.route("/designs/<int:design_id>/edit", methods=["POST"])
@login_required
@admin_required
def edit_design(design_id):
    design = Design.query.get_or_404(design_id)

    design.design_name = request.form.get("design_name",
                                          design.design_name).strip()
    design.category = request.form.get("category", design.category).strip()
    design.extra_price = request.form.get("extra_price", type=int) or 0
    design.service_id = request.form.get("service_id", type=int) or None
    design.is_active = bool(request.form.get("is_active"))

    image = save_image(request.files.get("image"))
    if image:
        if design.is_upload:
            delete_upload(design.image)   # replace the old upload on disk
        design.image = image
        design.is_upload = True

    db.session.commit()
    flash(f"'{design.design_name}' updated.", "success")
    return redirect(url_for("admin.designs"))


@admin_bp.route("/designs/<int:design_id>/delete", methods=["POST"])
@login_required
@admin_required
def delete_design(design_id):
    design = Design.query.get_or_404(design_id)

    if design.appointments:
        design.is_active = False
        db.session.commit()
        flash(f"'{design.design_name}' has bookings against it, so it has been "
              "hidden rather than deleted.", "success")
        return redirect(url_for("admin.designs"))

    if design.is_upload:
        delete_upload(design.image)
    db.session.delete(design)
    db.session.commit()
    flash("Design deleted.", "success")
    return redirect(url_for("admin.designs"))


# ---------------------------------------------------------------- colours

@admin_bp.route("/colors", methods=["GET", "POST"])
@login_required
@admin_required
def colors():
    if request.method == "POST":
        name = request.form.get("color_name", "").strip()
        hex_code = request.form.get("hex_code", "").strip()

        if not name or not hex_code.startswith("#") or len(hex_code) != 7:
            flash("A colour needs a name and a hex code like #e8b4b8.", "error")
            return redirect(url_for("admin.colors"))

        db.session.add(Color(color_name=name, hex_code=hex_code))
        db.session.commit()
        flash(f"'{name}' added to the palette.", "success")
        return redirect(url_for("admin.colors"))

    rows = Color.query.order_by(Color.id).all()
    return render_template("admin/colors.html", colors=rows)


@admin_bp.route("/colors/<int:color_id>/edit", methods=["POST"])
@login_required
@admin_required
def edit_color(color_id):
    color = Color.query.get_or_404(color_id)
    color.color_name = request.form.get("color_name", color.color_name).strip()

    hex_code = request.form.get("hex_code", "").strip()
    if hex_code.startswith("#") and len(hex_code) == 7:
        color.hex_code = hex_code
    color.is_active = bool(request.form.get("is_active"))

    db.session.commit()
    flash("Colour updated.", "success")
    return redirect(url_for("admin.colors"))


@admin_bp.route("/colors/<int:color_id>/delete", methods=["POST"])
@login_required
@admin_required
def delete_color(color_id):
    color = Color.query.get_or_404(color_id)
    # Appointments reference colours with ON DELETE SET NULL, so removing one
    # cannot break an existing booking — it just loses that colour name.
    db.session.delete(color)
    db.session.commit()
    flash("Colour removed from the palette.", "success")
    return redirect(url_for("admin.colors"))


# ------------------------------------------------------------- closed days

@admin_bp.route("/schedule", methods=["GET", "POST"])
@login_required
@admin_required
def schedule():
    """Close off dates the studio will not open (holidays, personal leave)."""
    if request.method == "POST":
        try:
            day = date.fromisoformat(request.form.get("date", ""))
        except ValueError:
            flash("Please choose a valid date.", "error")
            return redirect(url_for("admin.schedule"))

        if BlockedDate.query.filter_by(date=day).first():
            flash("That date is already closed.", "info")
            return redirect(url_for("admin.schedule"))

        db.session.add(BlockedDate(
            date=day,
            reason=request.form.get("reason", "").strip()[:120]))
        db.session.commit()
        flash(f"{day.strftime('%d %b %Y')} is now closed, it will disappear "
              "from the booking calendar.", "success")
        return redirect(url_for("admin.schedule"))

    blocked = (BlockedDate.query.filter(BlockedDate.date >= date.today())
               .order_by(BlockedDate.date).all())

    # Anything already booked on a day the owner is about to close.
    clashes = {
        b.date: Appointment.query.filter(
            Appointment.booking_date == b.date,
            Appointment.status.in_(SLOT_HOLDING_STATUSES)).count()
        for b in blocked
    }

    return render_template("admin/schedule.html", blocked=blocked,
                           clashes=clashes, today=date.today().isoformat())


@admin_bp.route("/schedule/<int:blocked_id>/delete", methods=["POST"])
@login_required
@admin_required
def unblock_date(blocked_id):
    row = BlockedDate.query.get_or_404(blocked_id)
    db.session.delete(row)
    db.session.commit()
    flash("That date is open for bookings again.", "success")
    return redirect(url_for("admin.schedule"))


# ---------------------------------------------------------------- users

@admin_bp.route("/users")
@login_required
@admin_required
def users():
    query_text = request.args.get("q", "").strip()
    rows = User.query
    if query_text:
        like = f"%{query_text}%"
        rows = rows.filter(db.or_(User.full_name.ilike(like),
                                  User.email.ilike(like),
                                  User.phone.ilike(like)))
    rows = rows.order_by(User.created_at.desc()).all()

    # How many bookings each customer has made, for the table.
    counts = dict(db.session.query(Appointment.user_id,
                                   func.count(Appointment.id))
                  .group_by(Appointment.user_id).all())

    return render_template("admin/users.html", users=rows, counts=counts,
                           q=query_text)


@admin_bp.route("/users/<int:user_id>/delete", methods=["POST"])
@login_required
@admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash("You can't delete your own account.", "error")
        return redirect(url_for("admin.users"))

    # The ORM cascade takes their appointments, payments and reviews with them.
    db.session.delete(user)
    db.session.commit()
    flash("Customer deleted.", "success")
    return redirect(url_for("admin.users"))


# ---------------------------------------------------------------- reviews

@admin_bp.route("/reviews")
@login_required
@admin_required
def reviews():
    rows = Review.query.order_by(Review.created_at.desc()).all()
    return render_template("admin/reviews.html", reviews=rows)


@admin_bp.route("/reviews/<int:review_id>/toggle", methods=["POST"])
@login_required
@admin_required
def toggle_review(review_id):
    review = Review.query.get_or_404(review_id)
    review.is_visible = not review.is_visible
    db.session.commit()
    flash("Review shown on the site." if review.is_visible
          else "Review hidden from the site.", "success")
    return redirect(url_for("admin.reviews"))


@admin_bp.route("/reviews/<int:review_id>/delete", methods=["POST"])
@login_required
@admin_required
def delete_review(review_id):
    review = Review.query.get_or_404(review_id)
    db.session.delete(review)
    db.session.commit()
    flash("Review deleted.", "success")
    return redirect(url_for("admin.reviews"))


# ------------------------------------------------------------ promo codes

CODE_RE = re.compile(r"^[A-Z0-9_-]{4,24}$")


def _generate_code(prefix="ELE"):
    """A short, unambiguous code. No O/0 or I/1 — people mistype those."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    while True:
        code = prefix + "".join(secrets.choice(alphabet) for _ in range(5))
        if not PromoCode.query.filter_by(code=code).first():
            return code


@admin_bp.route("/promos", methods=["GET", "POST"])
@login_required
@admin_required
def promos():
    if request.method == "POST":
        # The owner can type a code, or let us invent one for her.
        code = request.form.get("code", "").strip().upper()
        if not code:
            code = _generate_code()
        elif not CODE_RE.match(code):
            flash("A code must be 4-24 characters: letters, numbers, - or _.",
                  "error")
            return redirect(url_for("admin.promos"))
        elif PromoCode.query.filter_by(code=code).first():
            flash(f"'{code}' already exists.", "error")
            return redirect(url_for("admin.promos"))

        kind = request.form.get("kind", "percent")
        value = request.form.get("value", type=int) or 0

        if kind not in ("percent", "flat") or value <= 0:
            flash("Please give the discount a value.", "error")
            return redirect(url_for("admin.promos"))
        if kind == "percent" and value > 100:
            flash("A percentage discount cannot be more than 100%.", "error")
            return redirect(url_for("admin.promos"))

        expires = None
        raw_expiry = request.form.get("expires_on", "").strip()
        if raw_expiry:
            try:
                expires = date.fromisoformat(raw_expiry)
            except ValueError:
                flash("That expiry date is not valid.", "error")
                return redirect(url_for("admin.promos"))

        db.session.add(PromoCode(
            code=code,
            description=request.form.get("description", "").strip()[:140],
            kind=kind,
            value=value,
            max_discount=request.form.get("max_discount", type=int) or 0,
            min_spend=request.form.get("min_spend", type=int) or 0,
            usage_limit=request.form.get("usage_limit", type=int) or 0,
            expires_on=expires,
        ))
        db.session.commit()
        flash(f"Promo code {code} is live.", "success")
        return redirect(url_for("admin.promos"))

    rows = PromoCode.query.order_by(PromoCode.created_at.desc()).all()
    return render_template("admin/promos.html", promos=rows,
                           today=date.today().isoformat(),
                           suggested=_generate_code())


@admin_bp.route("/promos/<int:promo_id>/toggle", methods=["POST"])
@login_required
@admin_required
def toggle_promo(promo_id):
    promo = PromoCode.query.get_or_404(promo_id)
    promo.is_active = not promo.is_active
    db.session.commit()
    flash(f"{promo.code} is now {'live' if promo.is_active else 'switched off'}.",
          "success")
    return redirect(url_for("admin.promos"))


@admin_bp.route("/promos/<int:promo_id>/delete", methods=["POST"])
@login_required
@admin_required
def delete_promo(promo_id):
    promo = PromoCode.query.get_or_404(promo_id)

    # Bookings point at the code they used. Deleting it would orphan them, so a
    # code that has been claimed is switched off rather than destroyed — the
    # discount already given is recorded on the booking itself either way.
    if promo.used_count:
        promo.is_active = False
        db.session.commit()
        flash(f"{promo.code} has been used on {promo.used_count} booking(s), so "
              "it has been switched off rather than deleted.", "success")
        return redirect(url_for("admin.promos"))

    db.session.delete(promo)
    db.session.commit()
    flash("Promo code deleted.", "success")
    return redirect(url_for("admin.promos"))
