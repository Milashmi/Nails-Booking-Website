"""
routes/booking.py
-----------------
The heart of the site: the 9-step booking wizard, plus everything a customer
does with a booking afterwards.

  Step 1  service        Step 4  nail shape     Step 7  time
  Step 2  design         Step 5  nail length    Step 8  summary
  Step 3  colours        Step 6  date           Step 9  payment + confirm

How a booking is held
---------------------
A new booking is saved as *pending*. A pending booking does NOT reserve the
slot — only an approved one does (see utils.available_slots). That means two
people may request 14:00 on the same day, and the slot goes to whichever one
the admin approves first; the other is told the slot has gone. Nothing is
promised to a customer until the salon has looked at it.

Payment
-------
Pre-pay: the customer scans the studio QR, transfers the deposit, and must give
a non-empty transaction code AND upload a screenshot. The admin eyeballs both
before approving.
Post-pay: nothing to upload; the customer settles up at the studio and the
admin marks it paid afterwards.
"""

from datetime import datetime, date, time

from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, jsonify, abort, current_app)
from flask_login import login_required, current_user

from extensions import db, limiter
from models import (Service, Design, Color, Appointment, Payment, Review,
                    PromoCode, Notification, notify,
                    NAIL_SHAPES, NAIL_LENGTHS,
                    STATUS_PENDING, STATUS_APPROVED, STATUS_COMPLETED,
                    STATUS_CANCELLED)
from utils import (save_image, delete_upload, available_slots, open_dates,
                   slot_is_free, quote_price, find_promo, refund_due,
                   read_payment_screenshot, screenshot_already_used)

booking_bp = Blueprint("booking", __name__)


def _get_or_none(model, id_value):
    """db.session.get(), but tolerant of a missing id. Several lookups here
    are for genuinely optional fields (secondary/accent colour, a design not
    chosen yet on the live quote) -- calling .get() with None directly
    triggers a SAWarning ('fully NULL primary key') that SQLAlchemy says may
    become a hard error in a future release."""
    return db.session.get(model, id_value) if id_value else None


def _catalogue():
    """Everything the wizard needs to render its steps."""
    return {
        "services": (Service.query.filter_by(is_active=True)
                     .order_by(Service.sort_order, Service.price).all()),
        "designs": (Design.query.filter_by(is_active=True)
                    .order_by(Design.id).all()),
        "colors": Color.query.filter_by(is_active=True).order_by(Color.id).all(),
        "shapes": NAIL_SHAPES,
        "lengths": NAIL_LENGTHS,
    }


@booking_bp.route("/book")
@login_required
def book():
    """The wizard itself. Everything is on one page; JS walks through the steps."""
    data = _catalogue()

    categories = sorted({d.category for d in data["designs"]})

    # The wizard may be opened from a service card or a gallery tile, in which
    # case that choice is pre-selected.
    preselect_service = request.args.get("service", type=int)
    preselect_design = request.args.get("design", type=int)

    return render_template(
        "book.html",
        categories=categories,
        preselect_service=preselect_service,
        preselect_design=preselect_design,
        deposit=current_app.config["DEPOSIT_AMOUNT"],
        **data,
    )


@booking_bp.route("/api/availability")
@login_required
def availability():
    """
    Which dates and times are still open for a service.

    The date picker calls this so a full (or closed, or blocked) day is simply
    never offered — the customer cannot even click it.

    ?service=<id>            -> every open date for that service
    ?service=<id>&date=<iso> -> the free start times on that date
    &exclude=<appointment id> -> ignore this booking's own slot (rescheduling)
    """
    service = _get_or_none(Service, request.args.get("service", type=int))
    if not service:
        return jsonify({"error": "Unknown service."}), 400

    exclude_id = request.args.get("exclude", type=int)
    if exclude_id:
        # You may only reschedule around your own appointment.
        own = _get_or_none(Appointment, exclude_id)
        if not own or (own.user_id != current_user.id and not current_user.is_admin):
            exclude_id = None

    day_text = request.args.get("date", "").strip()
    if not day_text:
        return jsonify({"dates": open_dates(service.duration,
                                            exclude_id=exclude_id)})

    try:
        day = date.fromisoformat(day_text)
    except ValueError:
        return jsonify({"error": "Bad date."}), 400

    slots = available_slots(day, service.duration, exclude_id=exclude_id)
    return jsonify({
        "date": day.isoformat(),
        "slots": [{"value": s.strftime("%H:%M"),
                   "label": s.strftime("%I:%M %p").lstrip("0")} for s in slots],
    })


@booking_bp.route("/api/quote")
@login_required
def quote():
    """Live price for the summary step, as the customer changes their picks."""
    service = _get_or_none(Service, request.args.get("service", type=int))
    design = _get_or_none(Design, request.args.get("design", type=int))
    length = request.args.get("length", "Short")

    if not service:
        return jsonify({"error": "Unknown service."}), 400

    return jsonify({
        "service_price": service.price,
        "design_extra": (design.extra_price if design else 0),
        "length_extra": NAIL_LENGTHS.get(length, 0),
        "total": quote_price(service, design, length),
        "duration": service.duration,
        "deposit": current_app.config["DEPOSIT_AMOUNT"],
    })


@booking_bp.route("/api/promo")
@login_required
@limiter.limit("30 per hour")     # stop anyone grinding through guessed codes
def check_promo():
    """
    Check a promo code against the current subtotal, and say what it is worth.

    The wizard calls this as the customer types. The server works out the
    discount itself — the browser is never trusted to say what a code is worth.
    """
    promo = find_promo(request.args.get("code", ""))
    subtotal = request.args.get("subtotal", type=int) or 0

    if not promo:
        return jsonify({"ok": False, "error": "That code doesn't exist."})

    problem = promo.why_not(subtotal)
    if problem:
        return jsonify({"ok": False, "error": problem})

    discount = promo.discount_on(subtotal)
    if discount <= 0:
        return jsonify({"ok": False, "error": "That code takes nothing off this "
                                              "booking."})

    return jsonify({
        "ok": True,
        "code": promo.code,
        "label": promo.label,
        "description": promo.description,
        "discount": discount,
        "total": subtotal - discount,
    })


@booking_bp.route("/book", methods=["POST"])
@login_required
@limiter.limit("15 per hour")     # a real person does not book 15 times an hour
def create():
    """Validate the whole wizard server-side, then save the booking as pending."""
    form = request.form

    service = _get_or_none(Service, form.get("service_id", type=int))
    design = _get_or_none(Design, form.get("design_id", type=int))
    shape = form.get("nail_shape", "")
    length = form.get("nail_length", "")
    method = form.get("payment_method", "")

    errors = []

    # ---- the picks ----
    if not service or not service.is_active:
        errors.append("Please choose a service.")
    if not design or not design.is_active:
        errors.append("Please choose a design.")
    if shape not in NAIL_SHAPES:
        errors.append("Please choose a nail shape.")
    if length not in NAIL_LENGTHS:
        errors.append("Please choose a nail length.")

    base_color = _get_or_none(Color, form.get("color_id", type=int))
    if not base_color:
        errors.append("Please choose at least a base colour.")
    secondary = _get_or_none(Color, form.get("secondary_color_id", type=int))
    accent = _get_or_none(Color, form.get("accent_color_id", type=int))

    # ---- the slot ----
    booking_date = None
    booking_time = None
    try:
        booking_date = date.fromisoformat(form.get("booking_date", ""))
        hour, minute = form.get("booking_time", "").split(":")
        booking_time = time(int(hour), int(minute))
    except (ValueError, TypeError):
        errors.append("Please choose a date and a time.")

    if service and booking_date and booking_time:
        if booking_date < date.today():
            errors.append("That date is in the past.")
        elif not slot_is_free(booking_date, booking_time, service.duration):
            # Someone else's booking was approved into this slot while the
            # customer was filling the form in.
            errors.append("Sorry, that slot was taken while you were booking. "
                          "Please pick another time.")

    # ---- the payment ----
    # EVERY booking now pays the same Rs. 500 advance. The only choice is how
    # the balance is settled, so the transaction code and the screenshot are
    # always required — there is no route through this form that skips them.
    deposit = current_app.config["DEPOSIT_AMOUNT"]

    if method not in ("advance", "full"):
        errors.append("Please choose how you'd like to settle the balance.")

    transaction_code = form.get("transaction_code", "").strip()
    if not transaction_code:
        errors.append("Please enter the transaction code from your transfer.")
    elif len(transaction_code) < 4:
        errors.append("That transaction code looks too short.")

    screenshot_name = None
    upload = request.files.get("screenshot")
    if not upload or not upload.filename:
        errors.append("Please upload a screenshot of your payment.")
    else:
        screenshot_name = save_image(upload)
        if not screenshot_name:
            errors.append("That screenshot could not be read. Please upload a "
                          "PNG or JPG image under 5 MB.")

    # ---- the promo code (optional) ----
    subtotal = quote_price(service, design, length) if service else 0
    promo = find_promo(form.get("promo_code", ""))
    discount = 0

    if form.get("promo_code", "").strip() and not promo:
        errors.append("That promo code doesn't exist.")
    elif promo:
        problem = promo.why_not(subtotal)
        if problem:
            errors.append(problem)
        else:
            # The server works out the discount itself. Whatever the browser
            # claimed the code was worth is irrelevant.
            discount = promo.discount_on(subtotal)

    if errors:
        # Don't leave an orphan file on disk if the rest of the form failed.
        if screenshot_name:
            delete_upload(screenshot_name)
        for message in errors:
            flash(message, "error")
        return redirect(url_for("booking.book",
                                service=(service.id if service else None)))

    # ---- the same receipt cannot be used twice ----
    if screenshot_already_used(screenshot_name):
        delete_upload(screenshot_name)
        flash("That screenshot has already been used on another booking. Please "
              "upload the receipt for this transfer.", "error")
        return redirect(url_for("booking.book", service=service.id))

    total = max(0, subtotal - discount)

    # ---- save it ----
    appt = Appointment(
        user_id=current_user.id,
        service_id=service.id,
        design_id=design.id,
        color_id=base_color.id,
        secondary_color_id=(secondary.id if secondary else None),
        accent_color_id=(accent.id if accent else None),
        nail_shape=shape,
        nail_length=length,
        booking_date=booking_date,
        booking_time=booking_time,
        duration=service.duration,
        total_price=total,
        promo_id=(promo.id if promo and discount else None),
        discount=discount,
        notes=form.get("notes", "").strip()[:500],
        status=STATUS_PENDING,
    )
    db.session.add(appt)
    db.session.flush()   # we need the id for the payment row

    # ---- read the receipt ----
    # Advisory only: it tells the client if something looks off, and tells the
    # owner where to look. It never approves or rejects the money by itself.
    ocr = read_payment_screenshot(screenshot_name, deposit)

    payment = Payment(
        appointment_id=appt.id,
        method=method,
        amount=deposit,                  # always the advance
        balance=max(0, total - deposit),  # what is left to settle
        transaction_code=transaction_code,
        screenshot=screenshot_name,
        status="pending",
        ocr_checked=ocr["checked"],
        ocr_number_ok=ocr["number_ok"],
        ocr_amount_ok=ocr["amount_ok"],
        ocr_success_ok=ocr["success_ok"],
        ocr_note=ocr["note"],
    )
    db.session.add(payment)

    if promo and discount:
        promo.used_count = (promo.used_count or 0) + 1

    db.session.commit()

    # Tell the client honestly what the automated read made of their receipt.
    if ocr["checked"] and not payment.ocr_all_ok:
        flash("We couldn't automatically confirm your receipt "
              f"({ocr['note']}). Your booking is still in, Eleanora will check "
              "the screenshot herself.", "warning")

    if discount:
        flash(f"Promo code {promo.code} applied, Rs. {discount:,} off.",
              "success")

    flash("Your booking request is in! It stays pending until Eleanora verifies "
          "your payment, you'll be notified the moment she does.", "success")
    return redirect(url_for("booking.my_appointments"))


# ---------------- my appointments ----------------

@booking_bp.route("/appointments")
@login_required
def my_appointments():
    rows = (Appointment.query.filter_by(user_id=current_user.id)
            .order_by(Appointment.booking_date.desc(),
                      Appointment.booking_time.desc()).all())

    upcoming = [a for a in rows if a.is_upcoming]
    upcoming.sort(key=lambda a: a.start_dt)          # soonest first
    history = [a for a in rows if not a.is_upcoming]

    return render_template("appointments.html", upcoming=upcoming,
                           history=history,
                           deposit=current_app.config["DEPOSIT_AMOUNT"])


def _own_appointment(appointment_id):
    """Fetch an appointment, but only if it belongs to the person asking."""
    appt = Appointment.query.get_or_404(appointment_id)
    if appt.user_id != current_user.id:
        abort(403)
    return appt


@booking_bp.route("/appointments/<int:appointment_id>/cancel", methods=["POST"])
@login_required
def cancel(appointment_id):
    appt = _own_appointment(appointment_id)
    if not appt.can_cancel:
        flash("That appointment can no longer be cancelled.", "error")
        return redirect(url_for("booking.my_appointments"))

    appt.status = STATUS_CANCELLED

    # Half the verified advance comes back; the studio keeps the other half,
    # because the slot was held and other clients were turned away from it.
    refund = refund_due(appt.payment)
    if refund:
        appt.payment.refund_due = refund
        appt.payment.refund_paid = False

        notify(current_user.id, "refund",
               f"Refund of Rs. {refund:,} on the way",
               f"You cancelled your {appt.service.service_name} on "
               f"{appt.booking_date.strftime('%d %b')}. Half of your Rs. "
               f"{appt.payment.amount:,} advance (Rs. {refund:,}) will be sent "
               "back to your eSewa within 3 working days.",
               appointment=appt)

    db.session.commit()

    if refund:
        flash(f"Your appointment has been cancelled. Rs. {refund:,} of your "
              f"Rs. {appt.payment.amount:,} advance will be refunded, the "
              "other half is retained, as the slot was held for you.", "success")
    else:
        flash("Your appointment has been cancelled.", "success")

    return redirect(url_for("booking.my_appointments"))


@booking_bp.route("/appointments/<int:appointment_id>/reschedule",
                  methods=["GET", "POST"])
@login_required
def reschedule(appointment_id):
    """Move an appointment to a different free slot (up to 24h before)."""
    appt = _own_appointment(appointment_id)
    if not appt.can_reschedule:
        flash("Appointments can only be moved up to 24 hours beforehand. "
              "Please call us instead.", "error")
        return redirect(url_for("booking.my_appointments"))

    if request.method == "POST":
        try:
            new_date = date.fromisoformat(request.form.get("booking_date", ""))
            hour, minute = request.form.get("booking_time", "").split(":")
            new_time = time(int(hour), int(minute))
        except (ValueError, TypeError):
            flash("Please choose a new date and time.", "error")
            return redirect(url_for("booking.reschedule",
                                    appointment_id=appt.id))

        if not slot_is_free(new_date, new_time, appt.duration,
                            exclude_id=appt.id):
            flash("Sorry, that slot has just been taken. Please pick another.",
                  "error")
            return redirect(url_for("booking.reschedule",
                                    appointment_id=appt.id))

        appt.booking_date = new_date
        appt.booking_time = new_time
        # Moving a confirmed booking sends it back for approval, so the salon
        # always knows about the change.
        appt.status = STATUS_PENDING
        db.session.commit()

        flash("Your appointment has been moved. It's waiting on Eleanora to "
              "confirm the new time.", "success")
        return redirect(url_for("booking.my_appointments"))

    return render_template("reschedule.html", appt=appt)


@booking_bp.route("/appointments/<int:appointment_id>/review", methods=["POST"])
@login_required
def leave_review(appointment_id):
    """Rate a completed appointment."""
    appt = _own_appointment(appointment_id)
    if not appt.can_review:
        flash("You can only review an appointment once it is completed.", "error")
        return redirect(url_for("booking.my_appointments"))

    rating = request.form.get("rating", type=int)
    comment = request.form.get("comment", "").strip()[:600]

    if rating not in (1, 2, 3, 4, 5):
        flash("Please choose a rating from 1 to 5 stars.", "error")
        return redirect(url_for("booking.my_appointments"))

    db.session.add(Review(user_id=current_user.id, appointment_id=appt.id,
                          rating=rating, comment=comment))
    db.session.commit()
    flash("Thank you for the review!", "success")
    return redirect(url_for("booking.my_appointments"))


@booking_bp.route("/appointments/<int:appointment_id>/pay", methods=["POST"])
@login_required
@limiter.limit("20 per hour")
def submit_payment(appointment_id):
    """
    Re-send the transfer proof — used when the admin rejected the first
    screenshot and the client needs to upload a better one.
    """
    appt = _own_appointment(appointment_id)
    if appt.status in (STATUS_COMPLETED, STATUS_CANCELLED):
        flash("That appointment is closed.", "error")
        return redirect(url_for("booking.my_appointments"))

    transaction_code = request.form.get("transaction_code", "").strip()
    if not transaction_code:
        flash("Please enter the transaction code from your transfer.", "error")
        return redirect(url_for("booking.my_appointments"))

    upload = request.files.get("screenshot")
    if not upload or not upload.filename:
        flash("Please upload a screenshot of your payment.", "error")
        return redirect(url_for("booking.my_appointments"))

    screenshot_name = save_image(upload)
    if not screenshot_name:
        flash("That screenshot could not be read. Please upload a PNG or JPG "
              "image under 5 MB.", "error")
        return redirect(url_for("booking.my_appointments"))

    payment = appt.payment
    if not payment:
        payment = Payment(appointment_id=appt.id, method="advance")
        db.session.add(payment)
        db.session.flush()

    # The same receipt must not be recycled onto another booking.
    if screenshot_already_used(screenshot_name, exclude_payment_id=payment.id):
        delete_upload(screenshot_name)
        flash("That screenshot has already been used on another booking.",
              "error")
        return redirect(url_for("booking.my_appointments"))

    deposit = current_app.config["DEPOSIT_AMOUNT"]

    if payment.screenshot:
        delete_upload(payment.screenshot)   # drop the rejected one

    payment.amount = deposit
    payment.balance = max(0, (appt.total_price or 0) - deposit)
    payment.transaction_code = transaction_code
    payment.screenshot = screenshot_name
    payment.status = "pending"       # back in the queue for the admin to check
    payment.verified_at = None

    ocr = read_payment_screenshot(screenshot_name, deposit)
    payment.ocr_checked = ocr["checked"]
    payment.ocr_number_ok = ocr["number_ok"]
    payment.ocr_amount_ok = ocr["amount_ok"]
    payment.ocr_success_ok = ocr["success_ok"]
    payment.ocr_note = ocr["note"]

    # A rejected booking goes back into the queue for another look.
    if appt.status == STATUS_PENDING:
        appt.admin_note = ""

    db.session.commit()

    if ocr["checked"] and not payment.ocr_all_ok:
        flash(f"We still couldn't confirm the receipt automatically "
              f"({ocr['note']}). Eleanora will check it herself.", "warning")

    flash("Payment proof received, Eleanora will verify it shortly.", "success")
    return redirect(url_for("booking.my_appointments"))


# ---------------- notifications ----------------

@booking_bp.route("/notifications")
@login_required
def notifications():
    """
    The client's bell: has my booking been confirmed or not? This is the answer
    to the only question a waiting customer actually has.
    """
    rows = (Notification.query.filter_by(user_id=current_user.id)
            .order_by(Notification.created_at.desc()).limit(50).all())

    # Opening the page marks them read.
    unread = [n for n in rows if not n.is_read]
    for note in unread:
        note.is_read = True
    if unread:
        db.session.commit()

    return render_template("notifications.html", notifications=rows)


@booking_bp.route("/notifications/read-all", methods=["POST"])
@login_required
def read_all_notifications():
    (Notification.query
     .filter_by(user_id=current_user.id, is_read=False)
     .update({"is_read": True}))
    db.session.commit()
    return redirect(url_for("booking.notifications"))
