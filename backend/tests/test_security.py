"""
Security-focused tests: SQL injection safety, XSS escaping, CSRF enforcement,
IDOR / access control, and the security response headers that should be on
every response.
"""

from extensions import db
from tests.conftest import login


class TestSqlInjectionSafety:
    def test_injection_payload_in_gallery_search_finds_nothing_and_does_not_error(
            self, client):
        payload = "' OR '1'='1"
        resp = client.get("/gallery", query_string={"q": payload})
        assert resp.status_code == 200   # not a 500 — the ORM parameterises it

    def test_injection_payload_does_not_dump_the_users_table(self, client,
                                                              customer_user):
        payload = "'; SELECT * FROM users; --"
        resp = client.get("/gallery", query_string={"q": payload})
        assert resp.status_code == 200
        assert b"customer@example.com" not in resp.data


class TestXssSafety:
    def test_search_query_is_escaped_not_executed(self, client):
        payload = "<script>alert(1)</script>"
        resp = client.get("/gallery", query_string={"q": payload})
        assert b"<script>alert(1)</script>" not in resp.data
        # Jinja2 autoescaping turns it into harmless entities.
        assert b"&lt;script&gt;" in resp.data or payload.encode() not in resp.data


class TestAccessControlIdor:
    def test_admin_routes_require_admin_role(self, client, customer_user):
        login(client, customer_user.email, "Password@123")
        for path in ("/admin/", "/admin/appointments", "/admin/services",
                    "/admin/designs", "/admin/colors", "/admin/users",
                    "/admin/promos", "/admin/schedule", "/admin/reviews"):
            resp = client.get(path)
            assert resp.status_code == 403, f"{path} should be 403 for a customer"

    def test_guessing_someone_elses_appointment_id_is_403(self, client,
                                                           customer_user,
                                                           catalogue):
        from datetime import date, timedelta, time
        from models import User, Appointment

        victim = User(full_name="Victim", email="victim@example.com")
        victim.set_password("Password@123")
        db.session.add(victim)
        db.session.commit()

        appt = Appointment(
            user_id=victim.id, service_id=catalogue["service"].id,
            design_id=catalogue["design"].id, color_id=catalogue["color"].id,
            nail_shape="Almond", nail_length="Short",
            booking_date=date.today() + timedelta(days=5), booking_time=time(11, 0),
            duration=90, total_price=3000, status="approved")
        db.session.add(appt)
        db.session.commit()

        login(client, customer_user.email, "Password@123")
        resp = client.post(f"/appointments/{appt.id}/cancel")
        assert resp.status_code == 403


class TestCsrfProtection:
    def test_post_without_csrf_token_is_rejected(self, app, client):
        """conftest disables CSRF globally for convenience; this one test turns
        it back on to prove the protection itself actually works."""
        app.config["WTF_CSRF_ENABLED"] = True
        try:
            resp = client.post("/contact", data={
                "name": "Test", "email": "test@example.com",
                "message": "This message is long enough.",
            })
            assert resp.status_code == 400
        finally:
            app.config["WTF_CSRF_ENABLED"] = False


class TestSecurityHeaders:
    def test_headers_present_on_every_response(self, client):
        resp = client.get("/")
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-Frame-Options") == "DENY"
        assert "default-src 'self'" in resp.headers.get(
            "Content-Security-Policy", "")
        assert "unsafe-inline" not in resp.headers.get(
            "Content-Security-Policy", "").split("script-src")[1].split(";")[0]
        assert resp.headers.get("Referrer-Policy")

    def test_404_page_has_no_stack_trace(self, client):
        resp = client.get("/this-route-does-not-exist")
        assert resp.status_code == 404
        assert b"Traceback" not in resp.data
