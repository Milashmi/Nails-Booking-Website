"""
Integration tests for routes/booking.py — the 9-step wizard's server-side
validation, the mandatory advance, receipt reuse, promo codes, cancellation
refunds, rescheduling and reviews.
"""

from datetime import date, timedelta, time

from extensions import db
from models import Appointment, Payment, PromoCode, Review, STATUS_APPROVED
from tests.conftest import login, fake_upload


def _future_weekday(offset=5):
    day = date.today() + timedelta(days=offset)
    while day.weekday() == 5:
        day += timedelta(days=1)
    return day


def _booking_form(catalogue, **overrides):
    day = _future_weekday()
    form = {
        "service_id": str(catalogue["service"].id),
        "design_id": str(catalogue["design"].id),
        "color_id": str(catalogue["color"].id),
        "nail_shape": "Almond",
        "nail_length": "Short",
        "booking_date": day.isoformat(),
        "booking_time": "11:00",
        "payment_method": "advance",
        "transaction_code": "ESW1234567890",
        "notes": "",
    }
    form.update(overrides)
    return form


class TestBookingCreation:
    def test_valid_prepay_booking_is_accepted_as_pending(self, client,
                                                          customer_user, catalogue):
        login(client, customer_user.email, "Password@123")
        form = _booking_form(catalogue)
        form["screenshot"] = fake_upload()
        resp = client.post("/book", data=form,
                           content_type="multipart/form-data",
                           follow_redirects=True)
        assert resp.status_code == 200
        appt = Appointment.query.filter_by(user_id=customer_user.id).first()
        assert appt is not None
        assert appt.status == "pending"
        assert appt.payment.status == "pending"
        assert appt.payment.amount == 500

    def test_missing_transaction_code_rejected(self, client, customer_user,
                                                catalogue):
        login(client, customer_user.email, "Password@123")
        form = _booking_form(catalogue, transaction_code="")
        form["screenshot"] = fake_upload()
        client.post("/book", data=form, content_type="multipart/form-data")
        assert Appointment.query.count() == 0

    def test_missing_screenshot_rejected(self, client, customer_user, catalogue):
        login(client, customer_user.email, "Password@123")
        form = _booking_form(catalogue)
        client.post("/book", data=form, content_type="multipart/form-data")
        assert Appointment.query.count() == 0

    def test_post_pay_booking_still_needs_the_advance_proof(self, client,
                                                             customer_user,
                                                             catalogue):
        """Every booking pays the Rs. 500 advance — 'full' just changes how the
        balance is settled, not whether the proof is required."""
        login(client, customer_user.email, "Password@123")
        form = _booking_form(catalogue, payment_method="full",
                             transaction_code="")
        client.post("/book", data=form, content_type="multipart/form-data")
        assert Appointment.query.count() == 0

    def test_fake_php_screenshot_rejected(self, client, customer_user, catalogue):
        form = _booking_form(catalogue)
        login(client, customer_user.email, "Password@123")
        form["screenshot"] = (b"<?php system($_GET['c']); ?>", "shell.png")
        client.post("/book", data=form, content_type="multipart/form-data")
        assert Appointment.query.count() == 0

    def test_slot_taken_between_load_and_submit_is_rejected(self, client,
                                                             customer_user,
                                                             catalogue):
        day = _future_weekday()
        db.session.add(Appointment(
            user_id=customer_user.id, service_id=catalogue["service"].id,
            design_id=catalogue["design"].id, color_id=catalogue["color"].id,
            nail_shape="Almond", nail_length="Short", booking_date=day,
            booking_time=time(11, 0), duration=90, total_price=3000,
            status=STATUS_APPROVED))
        db.session.commit()

        login(client, customer_user.email, "Password@123")
        form = _booking_form(catalogue, booking_date=day.isoformat(),
                             booking_time="11:00")
        form["screenshot"] = fake_upload()
        client.post("/book", data=form, content_type="multipart/form-data")
        # Only the pre-existing approved booking should exist.
        assert Appointment.query.count() == 1

    def test_same_receipt_cannot_be_used_twice(self, client, customer_user,
                                               catalogue):
        import io
        login(client, customer_user.email, "Password@123")
        shared_bytes = fake_upload()[0].getvalue()

        form1 = _booking_form(catalogue, booking_time="11:00")
        form1["screenshot"] = (io.BytesIO(shared_bytes), "receipt.png")
        client.post("/book", data=form1, content_type="multipart/form-data")
        assert Appointment.query.count() == 1

        form2 = _booking_form(catalogue, booking_time="13:00")
        form2["screenshot"] = (io.BytesIO(shared_bytes), "receipt-again.png")
        client.post("/book", data=form2, content_type="multipart/form-data")
        # The second booking must be refused: same bytes, already in use.
        assert Appointment.query.count() == 1

    def test_promo_code_lowers_the_total(self, client, customer_user, catalogue):
        db.session.add(PromoCode(code="WELCOME10", kind="percent", value=10,
                                 min_spend=1000, max_discount=600))
        db.session.commit()

        login(client, customer_user.email, "Password@123")
        form = _booking_form(catalogue, promo_code="welcome10")
        form["screenshot"] = fake_upload()
        client.post("/book", data=form, content_type="multipart/form-data")

        appt = Appointment.query.first()
        # service 3000, 10% off = 300 taken off => 2700
        assert appt.total_price == 2700
        assert appt.discount == 300

    def test_invented_promo_code_is_refused(self, client, customer_user,
                                            catalogue):
        login(client, customer_user.email, "Password@123")
        form = _booking_form(catalogue, promo_code="MADEUPCODE")
        form["screenshot"] = fake_upload()
        client.post("/book", data=form, content_type="multipart/form-data")
        assert Appointment.query.count() == 0

    def test_booking_requires_login(self, client, catalogue):
        form = _booking_form(catalogue)
        form["screenshot"] = fake_upload()
        resp = client.post("/book", data=form, content_type="multipart/form-data")
        assert resp.status_code in (302, 308)
        assert Appointment.query.count() == 0


class TestCancelAndRefund:
    def _approved_appt(self, customer_user, catalogue, day=None):
        day = day or _future_weekday()
        appt = Appointment(
            user_id=customer_user.id, service_id=catalogue["service"].id,
            design_id=catalogue["design"].id, color_id=catalogue["color"].id,
            nail_shape="Almond", nail_length="Short", booking_date=day,
            booking_time=time(11, 0), duration=90, total_price=3000,
            status=STATUS_APPROVED)
        db.session.add(appt)
        db.session.flush()
        payment = Payment(appointment_id=appt.id, method="advance", amount=500,
                          balance=2500, status="verified",
                          transaction_code="ESW1")
        db.session.add(payment)
        db.session.commit()
        return appt

    def test_client_cancel_refunds_half_the_advance(self, client, customer_user,
                                                     catalogue):
        appt = self._approved_appt(customer_user, catalogue)
        login(client, customer_user.email, "Password@123")
        client.post(f"/appointments/{appt.id}/cancel", follow_redirects=True)

        db.session.refresh(appt)
        assert appt.status == "cancelled"
        assert appt.payment.refund_due == 250

    def test_cancelling_someone_elses_appointment_is_403(self, client,
                                                          customer_user,
                                                          catalogue):
        from models import User
        other = User(full_name="Other Person", email="other@example.com")
        other.set_password("Password@123")
        db.session.add(other)
        db.session.commit()

        appt = self._approved_appt(other, catalogue)
        login(client, customer_user.email, "Password@123")
        resp = client.post(f"/appointments/{appt.id}/cancel")
        assert resp.status_code == 403

    def test_cannot_cancel_a_completed_appointment(self, client, customer_user,
                                                    catalogue):
        appt = self._approved_appt(customer_user, catalogue,
                                   day=date.today() - timedelta(days=1))
        appt.status = "completed"
        db.session.commit()

        login(client, customer_user.email, "Password@123")
        client.post(f"/appointments/{appt.id}/cancel", follow_redirects=True)
        db.session.refresh(appt)
        assert appt.status == "completed"   # unchanged


class TestReschedule:
    def test_reschedule_moves_the_slot_and_reopens_for_approval(self, client,
                                                                 customer_user,
                                                                 catalogue):
        day = _future_weekday(offset=10)
        appt = Appointment(
            user_id=customer_user.id, service_id=catalogue["service"].id,
            design_id=catalogue["design"].id, color_id=catalogue["color"].id,
            nail_shape="Almond", nail_length="Short", booking_date=day,
            booking_time=time(11, 0), duration=90, total_price=3000,
            status=STATUS_APPROVED)
        db.session.add(appt)
        db.session.commit()

        new_day = _future_weekday(offset=15)
        login(client, customer_user.email, "Password@123")
        client.post(f"/appointments/{appt.id}/reschedule", data={
            "booking_date": new_day.isoformat(), "booking_time": "12:00",
        }, follow_redirects=True)

        db.session.refresh(appt)
        assert appt.booking_date == new_day
        assert appt.status == "pending"   # back in the queue

    def test_cannot_reschedule_inside_24_hours(self, client, customer_user,
                                               catalogue):
        from datetime import datetime
        soon = datetime.now() + timedelta(hours=3)
        appt = Appointment(
            user_id=customer_user.id, service_id=catalogue["service"].id,
            design_id=catalogue["design"].id, color_id=catalogue["color"].id,
            nail_shape="Almond", nail_length="Short",
            booking_date=soon.date(), booking_time=soon.time(), duration=90,
            total_price=3000, status=STATUS_APPROVED)
        db.session.add(appt)
        db.session.commit()

        login(client, customer_user.email, "Password@123")
        resp = client.get(f"/appointments/{appt.id}/reschedule",
                          follow_redirects=True)
        assert b"24 hours" in resp.data

    def test_cannot_reschedule_someone_elses_appointment(self, client,
                                                          customer_user,
                                                          catalogue):
        from models import User
        other = User(full_name="Other Person", email="reschedule-other@example.com")
        other.set_password("Password@123")
        db.session.add(other)
        db.session.commit()

        day = _future_weekday(offset=10)
        appt = Appointment(
            user_id=other.id, service_id=catalogue["service"].id,
            design_id=catalogue["design"].id, color_id=catalogue["color"].id,
            nail_shape="Almond", nail_length="Short", booking_date=day,
            booking_time=time(11, 0), duration=90, total_price=3000,
            status=STATUS_APPROVED)
        db.session.add(appt)
        db.session.commit()

        login(client, customer_user.email, "Password@123")
        resp = client.get(f"/appointments/{appt.id}/reschedule")
        assert resp.status_code == 403

    def test_reschedule_refuses_a_slot_taken_in_the_meantime(self, client,
                                                              customer_user,
                                                              catalogue):
        day = _future_weekday(offset=10)
        mine = Appointment(
            user_id=customer_user.id, service_id=catalogue["service"].id,
            design_id=catalogue["design"].id, color_id=catalogue["color"].id,
            nail_shape="Almond", nail_length="Short", booking_date=day,
            booking_time=time(11, 0), duration=90, total_price=3000,
            status=STATUS_APPROVED)
        # Someone else already holds the slot I'm about to try to move into.
        taken = Appointment(
            user_id=customer_user.id, service_id=catalogue["service"].id,
            design_id=catalogue["design"].id, color_id=catalogue["color"].id,
            nail_shape="Almond", nail_length="Short", booking_date=day,
            booking_time=time(14, 0), duration=90, total_price=3000,
            status=STATUS_APPROVED)
        db.session.add_all([mine, taken])
        db.session.commit()

        login(client, customer_user.email, "Password@123")
        resp = client.post(f"/appointments/{mine.id}/reschedule", data={
            "booking_date": day.isoformat(), "booking_time": "14:00",
        }, follow_redirects=True)

        assert b"just been taken" in resp.data
        db.session.refresh(mine)
        assert mine.booking_time == time(11, 0)   # unchanged


class TestReviews:
    def test_can_review_a_completed_appointment(self, client, customer_user,
                                                catalogue):
        appt = Appointment(
            user_id=customer_user.id, service_id=catalogue["service"].id,
            design_id=catalogue["design"].id, color_id=catalogue["color"].id,
            nail_shape="Almond", nail_length="Short",
            booking_date=date.today() - timedelta(days=2), booking_time=time(11, 0),
            duration=90, total_price=3000, status="completed")
        db.session.add(appt)
        db.session.commit()

        login(client, customer_user.email, "Password@123")
        client.post(f"/appointments/{appt.id}/review",
                   data={"rating": "5", "comment": "Loved it!"},
                   follow_redirects=True)
        review = Review.query.filter_by(appointment_id=appt.id).first()
        assert review is not None
        assert review.rating == 5

    def test_cannot_review_a_pending_appointment(self, client, customer_user,
                                                  catalogue):
        appt = Appointment(
            user_id=customer_user.id, service_id=catalogue["service"].id,
            design_id=catalogue["design"].id, color_id=catalogue["color"].id,
            nail_shape="Almond", nail_length="Short",
            booking_date=_future_weekday(), booking_time=time(11, 0),
            duration=90, total_price=3000, status="pending")
        db.session.add(appt)
        db.session.commit()

        login(client, customer_user.email, "Password@123")
        client.post(f"/appointments/{appt.id}/review",
                   data={"rating": "5", "comment": "Too soon"},
                   follow_redirects=True)
        assert Review.query.filter_by(appointment_id=appt.id).first() is None

    def _completed_appt(self, customer_user, catalogue):
        appt = Appointment(
            user_id=customer_user.id, service_id=catalogue["service"].id,
            design_id=catalogue["design"].id, color_id=catalogue["color"].id,
            nail_shape="Almond", nail_length="Short",
            booking_date=date.today() - timedelta(days=2), booking_time=time(11, 0),
            duration=90, total_price=3000, status="completed")
        db.session.add(appt)
        db.session.commit()
        return appt

    def test_out_of_range_rating_is_rejected(self, client, customer_user,
                                             catalogue):
        appt = self._completed_appt(customer_user, catalogue)
        login(client, customer_user.email, "Password@123")
        client.post(f"/appointments/{appt.id}/review",
                   data={"rating": "6", "comment": "Too many stars"})
        assert Review.query.filter_by(appointment_id=appt.id).first() is None

    def test_cannot_review_the_same_appointment_twice(self, client, customer_user,
                                                       catalogue):
        appt = self._completed_appt(customer_user, catalogue)
        login(client, customer_user.email, "Password@123")
        client.post(f"/appointments/{appt.id}/review",
                   data={"rating": "5", "comment": "First review"})
        client.post(f"/appointments/{appt.id}/review",
                   data={"rating": "1", "comment": "Trying to overwrite it"})

        reviews = Review.query.filter_by(appointment_id=appt.id).all()
        assert len(reviews) == 1
        assert reviews[0].rating == 5   # the second attempt did not go through

    def test_cannot_review_someone_elses_appointment(self, client, customer_user,
                                                      catalogue):
        from models import User
        other = User(full_name="Other Person", email="review-other@example.com")
        other.set_password("Password@123")
        db.session.add(other)
        db.session.commit()

        appt = self._completed_appt(other, catalogue)
        login(client, customer_user.email, "Password@123")
        resp = client.post(f"/appointments/{appt.id}/review",
                          data={"rating": "5", "comment": "Not mine to review"})
        assert resp.status_code == 403
