"""
Integration tests for routes/admin.py — access control, the approve/reject
workflow, slot-holding on approval, and a sample of the CRUD screens.
"""

from datetime import date, timedelta, time

from extensions import db
from models import (Appointment, Payment, Service, Color, PromoCode,
                    STATUS_PENDING, STATUS_APPROVED)
from tests.conftest import login, fake_upload
from utils import available_slots


def _future_weekday(offset=5):
    day = date.today() + timedelta(days=offset)
    while day.weekday() == 5:
        day += timedelta(days=1)
    return day


def _pending_appt(customer_user, catalogue, day=None):
    day = day or _future_weekday()
    appt = Appointment(
        user_id=customer_user.id, service_id=catalogue["service"].id,
        design_id=catalogue["design"].id, color_id=catalogue["color"].id,
        nail_shape="Almond", nail_length="Short", booking_date=day,
        booking_time=time(11, 0), duration=90, total_price=3000,
        status=STATUS_PENDING)
    db.session.add(appt)
    db.session.flush()
    payment = Payment(appointment_id=appt.id, method="advance", amount=500,
                      balance=2500, status="pending",
                      transaction_code="ESW1234567890")
    db.session.add(payment)
    db.session.commit()
    return appt


class TestAccessControl:
    def test_anonymous_is_redirected_from_admin_dashboard(self, client):
        resp = client.get("/admin/")
        assert resp.status_code in (302, 308)

    def test_customer_gets_403_from_admin_dashboard(self, client, customer_user):
        login(client, customer_user.email, "Password@123")
        resp = client.get("/admin/")
        assert resp.status_code == 403

    def test_customer_gets_403_from_admin_appointments(self, client,
                                                        customer_user):
        login(client, customer_user.email, "Password@123")
        resp = client.get("/admin/appointments")
        assert resp.status_code == 403

    def test_admin_can_reach_dashboard(self, client, admin_user):
        login(client, admin_user.email, "Admin@123")
        resp = client.get("/admin/")
        assert resp.status_code == 200

    def test_anonymous_cannot_reach_booking_wizard(self, client):
        resp = client.get("/book")
        assert resp.status_code in (302, 308)

    def test_anonymous_cannot_reach_availability_api(self, client):
        resp = client.get("/api/availability?service=1")
        assert resp.status_code in (302, 308)


class TestApprovalAndSlotHolding:
    def test_approve_confirms_booking_and_verifies_payment(self, client,
                                                            admin_user,
                                                            customer_user,
                                                            catalogue):
        appt = _pending_appt(customer_user, catalogue)
        login(client, admin_user.email, "Admin@123")
        client.post(f"/admin/appointments/{appt.id}/approve",
                   follow_redirects=True)

        db.session.refresh(appt)
        assert appt.status == "approved"
        assert appt.payment.status == "verified"

    def test_approved_slot_disappears_from_everyone_elses_calendar(
            self, client, admin_user, customer_user, catalogue, app):
        appt = _pending_appt(customer_user, catalogue)
        with app.app_context():
            before = time(11, 0) in available_slots(appt.booking_date, 90)
        assert before is True   # pending booking does not hold the slot yet

        login(client, admin_user.email, "Admin@123")
        client.post(f"/admin/appointments/{appt.id}/approve")

        with app.app_context():
            after = time(11, 0) in available_slots(appt.booking_date, 90)
        assert after is False

    def test_two_pending_requests_same_slot_second_approval_is_refused(
            self, client, admin_user, catalogue):
        from models import User
        day = _future_weekday()

        alice = User(full_name="Alice", email="alice@example.com")
        alice.set_password("Password@123")
        bob = User(full_name="Bob", email="bob@example.com")
        bob.set_password("Password@123")
        db.session.add_all([alice, bob])
        db.session.commit()

        appt_a = _pending_appt(alice, catalogue, day=day)
        appt_b = _pending_appt(bob, catalogue, day=day)   # same 11:00 slot

        login(client, admin_user.email, "Admin@123")
        client.post(f"/admin/appointments/{appt_a.id}/approve")
        client.post(f"/admin/appointments/{appt_b.id}/approve")

        db.session.refresh(appt_a)
        db.session.refresh(appt_b)
        assert appt_a.status == "approved"
        assert appt_b.status == "pending"   # refused — the slot was taken

    def test_reject_payment_notifies_client(self, client, admin_user,
                                            customer_user, catalogue):
        from models import Notification
        appt = _pending_appt(customer_user, catalogue)
        login(client, admin_user.email, "Admin@123")
        client.post(f"/admin/appointments/{appt.id}/payment",
                   data={"decision": "reject", "reason": "Code doesn't match."})

        db.session.refresh(appt)
        assert appt.payment.status == "rejected"
        note = Notification.query.filter_by(user_id=customer_user.id,
                                            kind="rejected").first()
        assert note is not None

    def test_studio_cancel_refunds_the_whole_advance(self, client, admin_user,
                                                      customer_user, catalogue):
        appt = _pending_appt(customer_user, catalogue)
        appt.status = STATUS_APPROVED
        appt.payment.status = "verified"
        db.session.commit()

        login(client, admin_user.email, "Admin@123")
        client.post(f"/admin/appointments/{appt.id}/cancel",
                   data={"reason": "Owner unavailable."})

        db.session.refresh(appt)
        assert appt.status == "cancelled"
        assert appt.payment.refund_due == 500   # the WHOLE advance, not half


class TestServiceCRUD:
    def test_admin_can_add_a_service(self, client, admin_user):
        login(client, admin_user.email, "Admin@123")
        client.post("/admin/services", data={
            "service_name": "Nail Art Add-on", "price": "500",
            "duration": "30", "description": "Extra detailing.",
        }, content_type="multipart/form-data")
        assert Service.query.filter_by(service_name="Nail Art Add-on").first()

    def test_service_with_bookings_is_retired_not_deleted(self, client,
                                                           admin_user,
                                                           customer_user,
                                                           catalogue):
        _pending_appt(customer_user, catalogue)
        login(client, admin_user.email, "Admin@123")
        client.post(f"/admin/services/{catalogue['service'].id}/delete")

        service = db.session.get(Service, catalogue["service"].id)
        assert service is not None            # not deleted
        assert service.is_active is False     # retired instead

    def test_service_without_bookings_is_deleted(self, client, admin_user,
                                                  catalogue):
        login(client, admin_user.email, "Admin@123")
        client.post(f"/admin/services/{catalogue['service'].id}/delete")
        assert db.session.get(Service, catalogue["service"].id) is None


class TestColorCRUD:
    def test_admin_can_add_a_color(self, client, admin_user):
        login(client, admin_user.email, "Admin@123")
        client.post("/admin/colors", data={"color_name": "Mint",
                                           "hex_code": "#a8d8c9"})
        assert Color.query.filter_by(color_name="Mint").first()

    def test_admin_can_deactivate_a_color(self, client, admin_user, catalogue):
        login(client, admin_user.email, "Admin@123")
        client.post(f"/admin/colors/{catalogue['color'].id}/edit", data={
            "color_name": catalogue["color"].color_name,
            "hex_code": catalogue["color"].hex_code,
            # is_active omitted entirely -> the checkbox reads as unchecked.
        })
        db.session.refresh(catalogue["color"])
        assert catalogue["color"].is_active is False


class TestScheduleAndBlockedDates:
    def test_admin_can_close_a_date(self, client, admin_user):
        from utils import is_studio_open
        day = _future_weekday()
        login(client, admin_user.email, "Admin@123")
        client.post("/admin/schedule", data={"date": day.isoformat(),
                                              "reason": "Family event"})
        assert not is_studio_open(day)


class TestPromoCRUD:
    def test_admin_can_create_a_promo_code(self, client, admin_user):
        login(client, admin_user.email, "Admin@123")
        client.post("/admin/promos", data={
            "code": "TESTCODE10", "kind": "percent", "value": "10",
            "description": "Test code",
        })
        assert PromoCode.query.filter_by(code="TESTCODE10").first()

    def test_toggling_a_promo_switches_it_off(self, client, admin_user):
        promo = PromoCode(code="TOGGLEME", kind="flat", value=100)
        db.session.add(promo)
        db.session.commit()

        login(client, admin_user.email, "Admin@123")
        client.post(f"/admin/promos/{promo.id}/toggle")
        db.session.refresh(promo)
        assert promo.is_active is False


class TestAnalytics:
    def test_customer_gets_403(self, client, customer_user):
        login(client, customer_user.email, "Password@123")
        resp = client.get("/admin/analytics")
        assert resp.status_code == 403

    def test_admin_sees_the_analytics_page(self, client, admin_user):
        login(client, admin_user.email, "Admin@123")
        resp = client.get("/admin/analytics")
        assert resp.status_code == 200
        assert b"Top services" in resp.data
        assert b"Most-picked designs" in resp.data

    def test_completed_booking_shows_up_in_top_services(self, client, admin_user,
                                                         customer_user, catalogue):
        appt = Appointment(
            user_id=customer_user.id, service_id=catalogue["service"].id,
            design_id=catalogue["design"].id, color_id=catalogue["color"].id,
            nail_shape="Almond", nail_length="Short",
            booking_date=date.today() - timedelta(days=2), booking_time=time(11, 0),
            duration=90, total_price=3000, status="completed")
        db.session.add(appt)
        db.session.commit()

        login(client, admin_user.email, "Admin@123")
        resp = client.get("/admin/analytics")
        assert catalogue["service"].service_name.encode() in resp.data
        assert b"Rs. 3,000" in resp.data

    def test_pending_booking_is_not_counted_as_revenue(self, client, admin_user,
                                                        customer_user, catalogue):
        """Only completed bookings count as earned revenue -- a pending one
        hasn't been paid out in full and might still be cancelled."""
        appt = Appointment(
            user_id=customer_user.id, service_id=catalogue["service"].id,
            design_id=catalogue["design"].id, color_id=catalogue["color"].id,
            nail_shape="Almond", nail_length="Short",
            booking_date=date.today(), booking_time=time(11, 0),
            duration=90, total_price=3000, status="pending")
        db.session.add(appt)
        db.session.commit()

        login(client, admin_user.email, "Admin@123")
        resp = client.get("/admin/analytics")
        # Nothing completed yet, so the top-services table should be empty.
        assert b"Nothing completed yet" in resp.data


class TestCsvExport:
    def test_customer_gets_403_on_appointments_export(self, client, customer_user):
        login(client, customer_user.email, "Password@123")
        assert client.get("/admin/export/appointments.csv").status_code == 403

    def test_customer_gets_403_on_customers_export(self, client, customer_user):
        login(client, customer_user.email, "Password@123")
        assert client.get("/admin/export/customers.csv").status_code == 403

    def test_appointments_csv_has_expected_columns_and_rows(
            self, client, admin_user, customer_user, catalogue):
        appt = Appointment(
            user_id=customer_user.id, service_id=catalogue["service"].id,
            design_id=catalogue["design"].id, color_id=catalogue["color"].id,
            nail_shape="Almond", nail_length="Short",
            booking_date=date.today() + timedelta(days=5), booking_time=time(11, 0),
            duration=90, total_price=3000, status="pending")
        db.session.add(appt)
        db.session.commit()

        login(client, admin_user.email, "Admin@123")
        resp = client.get("/admin/export/appointments.csv")
        assert resp.status_code == 200
        assert resp.headers["Content-Type"].startswith("text/csv")
        assert "attachment" in resp.headers["Content-Disposition"]

        lines = resp.data.decode().splitlines()
        assert lines[0] == ("ID,Customer,Email,Service,Design,Date,Time,Status,"
                            "Total (Rs.),Booked on")
        assert any(customer_user.email in line for line in lines[1:])

    def test_customers_csv_has_expected_columns_and_rows(self, client, admin_user,
                                                          customer_user):
        login(client, admin_user.email, "Admin@123")
        resp = client.get("/admin/export/customers.csv")
        assert resp.status_code == 200
        assert resp.headers["Content-Type"].startswith("text/csv")

        lines = resp.data.decode().splitlines()
        assert lines[0] == "ID,Name,Email,Phone,Bookings,2FA enabled,Joined"
        assert any(customer_user.email in line for line in lines[1:])
        # The admin account itself is not a customer, so it must not appear.
        assert not any(admin_user.email in line for line in lines[1:])
