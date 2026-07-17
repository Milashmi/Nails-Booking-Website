"""
Integration tests for routes/main.py — the public pages anyone can browse
without an account: home, about, services, gallery, colours, reviews and
the contact form.
"""

from datetime import date, timedelta, time

from extensions import db
from models import Appointment, Review


class TestHome:
    def test_home_page_loads(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_home_shows_active_services_only(self, client):
        """A distinctive name is used here (not the shared 'Gel-X' catalogue
        fixture) because 'Gel-X' also appears in the site's static meta
        description on every page, which would make this assertion pass
        regardless of whether the filtering actually works."""
        from models import Service
        hidden = Service(service_name="Zzz Retired Test Service", price=100,
                         duration=30, is_active=False, sort_order=99)
        db.session.add(hidden)
        db.session.commit()

        resp = client.get("/")
        assert b"Zzz Retired Test Service" not in resp.data

    def test_home_shows_stats(self, client):
        resp = client.get("/")
        assert b"designs" in resp.data.lower() or b"clients" in resp.data.lower()


class TestAbout:
    def test_about_page_loads(self, client):
        resp = client.get("/about")
        assert resp.status_code == 200

    def test_about_reflects_completed_bookings_count(self, client, customer_user,
                                                      catalogue):
        appt = Appointment(
            user_id=customer_user.id, service_id=catalogue["service"].id,
            design_id=catalogue["design"].id, color_id=catalogue["color"].id,
            nail_shape="Almond", nail_length="Short",
            booking_date=date.today() - timedelta(days=1), booking_time=time(11, 0),
            duration=90, total_price=3000, status="completed")
        db.session.add(appt)
        db.session.commit()

        resp = client.get("/about")
        assert resp.status_code == 200
        assert b'data-count="1">0</span>+' in resp.data


class TestServices:
    def test_services_page_loads(self, client):
        resp = client.get("/services")
        assert resp.status_code == 200

    def test_services_lists_active_service(self, client, catalogue):
        resp = client.get("/services")
        assert catalogue["service"].service_name.encode() in resp.data

    def test_services_hides_retired_service(self, client):
        from models import Service
        retired = Service(service_name="Zzz Retired Service", price=100,
                          duration=30, is_active=False, sort_order=99)
        db.session.add(retired)
        db.session.commit()

        resp = client.get("/services")
        assert b"Zzz Retired Service" not in resp.data
