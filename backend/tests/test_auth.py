"""
Integration tests for routes/auth.py, driven through the Flask test client
exactly the way a browser would: real HTTP verbs, real form bodies, real
cookies for session state.
"""

import pyotp

from extensions import db
from models import User
from tests.conftest import login


REG_FORM = {
    "full_name": "Sabina Karki",
    "email": "sabina.karki@example.com",
    "phone": "+977 9801234567",
    "password": "Password@123",
    "confirm": "Password@123",
}


class TestRegister:
    def test_register_creates_account(self, client):
        resp = client.post("/register", data=REG_FORM, follow_redirects=True)
        assert resp.status_code == 200
        assert User.query.filter_by(email="sabina.karki@example.com").first()

    def test_first_account_ever_becomes_admin(self, client):
        client.post("/register", data=REG_FORM, follow_redirects=True)
        user = User.query.filter_by(email="sabina.karki@example.com").first()
        assert user.role == "admin"

    def test_second_account_is_a_customer(self, client):
        client.post("/register", data=REG_FORM, follow_redirects=True)
        second = dict(REG_FORM, email="second@example.com")
        client.post("/register", data=second, follow_redirects=True)
        user = User.query.filter_by(email="second@example.com").first()
        assert user.role == "customer"

    def test_duplicate_email_is_rejected(self, client):
        client.post("/register", data=REG_FORM, follow_redirects=True)
        resp = client.post("/register", data=REG_FORM, follow_redirects=True)
        assert User.query.filter_by(email="sabina.karki@example.com").count() == 1
        assert b"already exists" in resp.data

    def test_short_password_is_rejected(self, client):
        bad = dict(REG_FORM, password="short", confirm="short")
        client.post("/register", data=bad, follow_redirects=True)
        assert User.query.filter_by(email="sabina.karki@example.com").first() is None

    def test_mismatched_passwords_rejected(self, client):
        bad = dict(REG_FORM, confirm="Different@123")
        client.post("/register", data=bad, follow_redirects=True)
        assert User.query.filter_by(email="sabina.karki@example.com").first() is None

    def test_invalid_email_rejected(self, client):
        bad = dict(REG_FORM, email="not-an-email")
        client.post("/register", data=bad, follow_redirects=True)
        assert User.query.filter_by(email="not-an-email").first() is None


class TestLogin:
    def test_correct_credentials_log_in(self, client, customer_user):
        resp = login(client, "customer@example.com", "Password@123")
        assert resp.status_code == 200
        assert b"Welcome back" in resp.data or resp.request.path != "/login"

    def test_wrong_password_rejected(self, client, customer_user):
        resp = login(client, "customer@example.com", "WrongPassword")
        assert b"match an account" in resp.data

    def test_unknown_email_same_message_as_wrong_password(self, client,
                                                           customer_user):
        """User enumeration guard: both failures must read identically."""
        wrong_pw = login(client, "customer@example.com", "WrongPassword")
        unknown = login(client, "nosuchuser@example.com", "whatever")
        assert b"match an account" in wrong_pw.data
        assert b"match an account" in unknown.data

    def test_five_failed_logins_lock_the_account(self, client, customer_user):
        for _ in range(5):
            login(client, "customer@example.com", "WrongPassword")
        resp = login(client, "customer@example.com", "Password@123")
        assert b"locked" in resp.data

    def test_logout_requires_login(self, client):
        resp = client.get("/logout")
        assert resp.status_code in (302, 308)   # redirected to login


class TestTwoFactor:
    def _enable_2fa(self, client, user):
        """Log in, then walk through the setup flow, returning the raw secret."""
        login(client, user.email, "Password@123")
        client.get("/profile/2fa/setup")
        with client.session_transaction() as sess:
            secret = sess["setup_totp_secret"]
        code = pyotp.TOTP(secret).now()
        client.post("/profile/2fa/setup", data={"code": code})
        return secret

    def test_setup_requires_a_correct_live_code(self, client, customer_user):
        login(client, customer_user.email, "Password@123")
        client.get("/profile/2fa/setup")
        client.post("/profile/2fa/setup", data={"code": "000000"})
        db.session.refresh(customer_user)
        assert customer_user.totp_enabled is False

    def test_setup_with_correct_code_enables_2fa(self, client, customer_user):
        self._enable_2fa(client, customer_user)
        db.session.refresh(customer_user)
        assert customer_user.totp_enabled is True

    def test_login_then_demands_the_code(self, client, customer_user):
        secret = self._enable_2fa(client, customer_user)
        client.get("/logout")

        resp = login(client, customer_user.email, "Password@123")
        assert b"code" in resp.data.lower()

        # Not authenticated yet — /appointments should still bounce us.
        appt_resp = client.get("/appointments")
        assert appt_resp.status_code in (302, 308)

        code = pyotp.TOTP(secret).now()
        final = client.post("/login/2fa", data={"code": code},
                            follow_redirects=True)
        assert final.status_code == 200

    def test_wrong_2fa_code_at_login_is_refused(self, client, customer_user):
        self._enable_2fa(client, customer_user)
        client.get("/logout")
        login(client, customer_user.email, "Password@123")
        resp = client.post("/login/2fa", data={"code": "000000"})
        assert b"not correct" in resp.data

    def test_disable_requires_current_password(self, client, customer_user):
        self._enable_2fa(client, customer_user)
        client.post("/profile/2fa/disable", data={"password": "WrongPassword"})
        db.session.refresh(customer_user)
        assert customer_user.totp_enabled is True

        client.post("/profile/2fa/disable", data={"password": "Password@123"})
        db.session.refresh(customer_user)
        assert customer_user.totp_enabled is False


class TestProfile:
    def test_profile_requires_login(self, client):
        resp = client.get("/profile")
        assert resp.status_code in (302, 308)

    def test_update_name_and_phone(self, client, customer_user):
        login(client, customer_user.email, "Password@123")
        client.post("/profile", data={"full_name": "Sabina Updated",
                                      "phone": "+977 9811111111"})
        db.session.refresh(customer_user)
        assert customer_user.full_name == "Sabina Updated"

    def test_change_password_requires_correct_current_password(self, client,
                                                                customer_user):
        login(client, customer_user.email, "Password@123")
        client.post("/profile/password", data={
            "current_password": "WrongOne",
            "new_password": "NewPassword@123",
            "confirm_password": "NewPassword@123",
        })
        db.session.refresh(customer_user)
        assert customer_user.check_password("Password@123")

    def test_change_password_success(self, client, customer_user):
        login(client, customer_user.email, "Password@123")
        client.post("/profile/password", data={
            "current_password": "Password@123",
            "new_password": "NewPassword@123",
            "confirm_password": "NewPassword@123",
        })
        db.session.refresh(customer_user)
        assert customer_user.check_password("NewPassword@123")
