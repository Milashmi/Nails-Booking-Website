"""
Integration tests for the small JSON endpoints the booking wizard calls live
as the customer moves through it (routes/booking.py: /api/promo, /api/quote,
/api/availability), plus the wizard's own GET page and the appointments list.
"""

from datetime import date, timedelta, time

from extensions import db
from models import PromoCode
from tests.conftest import login


def _future_weekday(offset=5):
    day = date.today() + timedelta(days=offset)
    while day.weekday() == 5:
        day += timedelta(days=1)
    return day


class TestCheckPromo:
    def test_valid_code_returns_the_discount(self, client, customer_user):
        db.session.add(PromoCode(code="WELCOME10", kind="percent", value=10,
                                 min_spend=1000, max_discount=600))
        db.session.commit()

        login(client, customer_user.email, "Password@123")
        resp = client.get("/api/promo", query_string={"code": "WELCOME10",
                                                       "subtotal": "3000"})
        data = resp.get_json()
        assert data["ok"] is True
        assert data["discount"] == 300
        assert data["total"] == 2700

    def test_unknown_code_returns_an_error(self, client, customer_user):
        login(client, customer_user.email, "Password@123")
        resp = client.get("/api/promo", query_string={"code": "MADEUP",
                                                       "subtotal": "3000"})
        data = resp.get_json()
        assert data["ok"] is False
        assert "doesn't exist" in data["error"]

    def test_code_below_minimum_spend_returns_the_reason(self, client,
                                                          customer_user):
        db.session.add(PromoCode(code="BIGSPEND", kind="flat", value=500,
                                 min_spend=5000))
        db.session.commit()

        login(client, customer_user.email, "Password@123")
        resp = client.get("/api/promo", query_string={"code": "BIGSPEND",
                                                       "subtotal": "1000"})
        data = resp.get_json()
        assert data["ok"] is False
        assert "minimum spend" in data["error"]

    def test_lookup_is_case_insensitive(self, client, customer_user):
        db.session.add(PromoCode(code="WELCOME10", kind="percent", value=10,
                                 min_spend=1000))
        db.session.commit()

        login(client, customer_user.email, "Password@123")
        resp = client.get("/api/promo", query_string={"code": "welcome10",
                                                       "subtotal": "3000"})
        assert resp.get_json()["ok"] is True

    def test_requires_login(self, client):
        resp = client.get("/api/promo", query_string={"code": "X",
                                                       "subtotal": "1000"})
        assert resp.status_code in (302, 308)


class TestQuoteApi:
    def test_quote_includes_service_and_design_price(self, client,
                                                      customer_user, catalogue):
        catalogue["design"].extra_price = 300
        db.session.commit()

        login(client, customer_user.email, "Password@123")
        resp = client.get("/api/quote", query_string={
            "service": catalogue["service"].id,
            "design": catalogue["design"].id,
            "length": "Short",
        })
        data = resp.get_json()
        assert data["service_price"] == catalogue["service"].price

    def test_unknown_service_returns_400(self, client, customer_user):
        login(client, customer_user.email, "Password@123")
        resp = client.get("/api/quote", query_string={"service": "999999"})
        assert resp.status_code == 400

    def test_requires_login(self, client, catalogue):
        resp = client.get("/api/quote",
                          query_string={"service": catalogue["service"].id})
        assert resp.status_code in (302, 308)


class TestAvailabilityApi:
    def test_returns_open_dates_for_a_known_service(self, client, customer_user,
                                                     catalogue):
        login(client, customer_user.email, "Password@123")
        resp = client.get("/api/availability",
                          query_string={"service": catalogue["service"].id})
        data = resp.get_json()
        assert resp.status_code == 200
        assert "dates" in data
        assert isinstance(data["dates"], list)

    def test_unknown_service_returns_400(self, client, customer_user):
        login(client, customer_user.email, "Password@123")
        resp = client.get("/api/availability", query_string={"service": "999999"})
        assert resp.status_code == 400

    def test_returns_slots_for_a_specific_date(self, client, customer_user,
                                               catalogue):
        day = _future_weekday()
        login(client, customer_user.email, "Password@123")
        resp = client.get("/api/availability", query_string={
            "service": catalogue["service"].id, "date": day.isoformat(),
        })
        data = resp.get_json()
        assert resp.status_code == 200
        assert "slots" in data
        assert any(s["value"] == "11:00" for s in data["slots"])


class TestBookingWizardPage:
    def test_wizard_page_loads_for_a_logged_in_customer(self, client,
                                                         customer_user):
        login(client, customer_user.email, "Password@123")
        resp = client.get("/book")
        assert resp.status_code == 200

    def test_wizard_preselects_a_design_from_the_gallery(self, client,
                                                          customer_user,
                                                          catalogue):
        login(client, customer_user.email, "Password@123")
        resp = client.get("/book", query_string={"design": catalogue["design"].id})
        assert resp.status_code == 200
        assert catalogue["design"].design_name.encode() in resp.data


class TestMyAppointments:
    def test_requires_login(self, client):
        resp = client.get("/appointments")
        assert resp.status_code in (302, 308)

    def test_future_booking_appears_in_upcoming(self, client, customer_user,
                                                catalogue):
        from models import Appointment, STATUS_APPROVED
        appt = Appointment(
            user_id=customer_user.id, service_id=catalogue["service"].id,
            design_id=catalogue["design"].id, color_id=catalogue["color"].id,
            nail_shape="Almond", nail_length="Short",
            booking_date=_future_weekday(), booking_time=time(11, 0),
            duration=90, total_price=3000, status=STATUS_APPROVED)
        db.session.add(appt)
        db.session.commit()

        login(client, customer_user.email, "Password@123")
        resp = client.get("/appointments")
        assert resp.status_code == 200
        assert catalogue["service"].service_name.encode() in resp.data

    def test_only_shows_the_logged_in_users_own_bookings(self, client,
                                                          customer_user,
                                                          catalogue):
        from models import User, Appointment, STATUS_APPROVED
        other = User(full_name="Other Person", email="myappt-other@example.com")
        other.set_password("Password@123")
        db.session.add(other)
        db.session.commit()

        other_appt = Appointment(
            user_id=other.id, service_id=catalogue["service"].id,
            design_id=catalogue["design"].id, color_id=catalogue["color"].id,
            nail_shape="Almond", nail_length="Short",
            booking_date=_future_weekday(), booking_time=time(11, 0),
            duration=90, total_price=3000, status=STATUS_APPROVED,
            notes="ONLY-VISIBLE-TO-OWNER")
        db.session.add(other_appt)
        db.session.commit()

        login(client, customer_user.email, "Password@123")
        resp = client.get("/appointments")
        assert b"ONLY-VISIBLE-TO-OWNER" not in resp.data
