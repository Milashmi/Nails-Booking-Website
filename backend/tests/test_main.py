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
