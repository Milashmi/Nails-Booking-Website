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


class TestGallery:
    def test_gallery_page_loads(self, client):
        resp = client.get("/gallery")
        assert resp.status_code == 200

    def test_gallery_lists_active_design(self, client, catalogue):
        resp = client.get("/gallery")
        assert catalogue["design"].design_name.encode() in resp.data

    def test_gallery_hides_inactive_design(self, client, catalogue):
        catalogue["design"].is_active = False
        db.session.commit()
        resp = client.get("/gallery")
        assert catalogue["design"].design_name.encode() not in resp.data

    def test_gallery_filters_by_category(self, client, catalogue):
        from models import Design
        other = Design(design_name="Other Category Design", category="Marble",
                       image="x.jpg", extra_price=0,
                       service_id=catalogue["service"].id)
        db.session.add(other)
        db.session.commit()

        resp = client.get("/gallery", query_string={"category": "French"})
        assert catalogue["design"].design_name.encode() in resp.data
        assert b"Other Category Design" not in resp.data

    def test_gallery_search_matches_by_name(self, client, catalogue):
        resp = client.get("/gallery", query_string={"q": "Gold Line"})
        assert catalogue["design"].design_name.encode() in resp.data

    def test_gallery_search_with_no_match_shows_nothing(self, client, catalogue):
        resp = client.get("/gallery", query_string={"q": "Nonexistent Design Xyz"})
        assert catalogue["design"].design_name.encode() not in resp.data


class TestColors:
    def test_colors_page_loads(self, client):
        resp = client.get("/colors")
        assert resp.status_code == 200

    def test_colors_lists_active_color(self, client, catalogue):
        resp = client.get("/colors")
        assert catalogue["color"].color_name.encode() in resp.data

    def test_colors_hides_inactive_color(self, client, catalogue):
        catalogue["color"].is_active = False
        db.session.commit()
        resp = client.get("/colors")
        assert catalogue["color"].color_name.encode() not in resp.data


class TestReviews:
    def _appt(self, customer_user, catalogue):
        appt = Appointment(
            user_id=customer_user.id, service_id=catalogue["service"].id,
            design_id=catalogue["design"].id, color_id=catalogue["color"].id,
            nail_shape="Almond", nail_length="Short",
            booking_date=date.today() - timedelta(days=2), booking_time=time(11, 0),
            duration=90, total_price=3000, status="completed")
        db.session.add(appt)
        db.session.flush()
        return appt

    def test_reviews_page_loads(self, client):
        resp = client.get("/reviews")
        assert resp.status_code == 200

    def test_reviews_shows_a_visible_review(self, client, customer_user, catalogue):
        appt = self._appt(customer_user, catalogue)
        db.session.add(Review(user_id=customer_user.id, appointment_id=appt.id,
                              rating=5, comment="Absolutely loved my set!",
                              is_visible=True))
        db.session.commit()

        resp = client.get("/reviews")
        assert b"Absolutely loved my set" in resp.data

    def test_reviews_hides_an_invisible_review(self, client, customer_user,
                                               catalogue):
        appt = self._appt(customer_user, catalogue)
        db.session.add(Review(user_id=customer_user.id, appointment_id=appt.id,
                              rating=5, comment="Hidden from the public site",
                              is_visible=False))
        db.session.commit()

        resp = client.get("/reviews")
        assert b"Hidden from the public site" not in resp.data


class TestContact:
    def test_contact_page_loads(self, client):
        resp = client.get("/contact")
        assert resp.status_code == 200

    def test_valid_message_is_accepted(self, client):
        resp = client.post("/contact", data={
            "name": "Test Visitor", "email": "visitor@example.com",
            "message": "This message is long enough to pass validation.",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"Thank you" in resp.data

    def test_short_message_is_rejected(self, client):
        resp = client.post("/contact", data={
            "name": "Test Visitor", "email": "visitor@example.com",
            "message": "Too short",
        })
        assert b"at least" in resp.data

    def test_missing_name_is_rejected(self, client):
        resp = client.post("/contact", data={
            "name": "", "email": "visitor@example.com",
            "message": "This message is long enough to pass validation.",
        })
        assert b"at least" in resp.data or b"Please fill in" in resp.data
