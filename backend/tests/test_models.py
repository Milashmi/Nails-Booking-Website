"""
Unit tests for models.py — password hashing, lockout, appointment lifecycle
helpers, and promo-code math. These don't touch routes at all.
"""

from datetime import datetime, timedelta, date, time

from extensions import db
from models import (User, Appointment, PromoCode, Payment,
                    STATUS_PENDING, STATUS_APPROVED, STATUS_COMPLETED)


class TestUserPassword:
    def test_password_is_hashed_not_stored_raw(self):
        user = User(full_name="A B", email="a@example.com")
        user.set_password("Sup3rSecret!")
        assert user.password_hash != "Sup3rSecret!"
        assert user.check_password("Sup3rSecret!")

    def test_wrong_password_fails(self):
        user = User(full_name="A B", email="a@example.com")
        user.set_password("Sup3rSecret!")
        assert not user.check_password("wrong-password")

    def test_is_admin_property(self):
        assert User(full_name="A", email="a@x.com", role="admin").is_admin
        assert not User(full_name="A", email="a@x.com", role="customer").is_admin

    def test_initials(self):
        user = User(full_name="Aayusha Shrestha", email="a@x.com")
        assert user.initials == "AS"


class TestUserLockout:
    def test_five_failures_lock_the_account(self):
        user = User(full_name="A", email="a@x.com")
        user.set_password("x")
        for _ in range(4):
            user.register_failure()
            assert not user.is_locked()
        user.register_failure()   # 5th failure trips the lock
        assert user.is_locked()
        assert user.lock_seconds_left() > 0

    def test_reset_failures_clears_lock(self):
        user = User(full_name="A", email="a@x.com")
        for _ in range(5):
            user.register_failure()
        assert user.is_locked()
        user.reset_failures()
        assert not user.is_locked()
        assert user.failed_attempts == 0

    def test_lock_expires_after_window(self):
        user = User(full_name="A", email="a@x.com")
        user.locked_until = datetime.utcnow() - timedelta(seconds=1)
        assert not user.is_locked()
        assert user.lock_seconds_left() == 0


class TestAppointmentLifecycle:
    def _appt(self, **overrides):
        base = dict(
            user_id=1, service_id=1, design_id=1, color_id=1,
            nail_shape="Almond", nail_length="Short",
            booking_date=date.today() + timedelta(days=5),
            booking_time=time(12, 0), duration=90, total_price=3000,
            status=STATUS_PENDING,
        )
        base.update(overrides)
        return Appointment(**base)

    def test_start_and_end_dt(self):
        appt = self._appt(booking_date=date(2026, 8, 1), booking_time=time(14, 0),
                          duration=90)
        assert appt.start_dt == datetime(2026, 8, 1, 14, 0)
        assert appt.end_dt == datetime(2026, 8, 1, 15, 30)

    def test_can_cancel_future_pending(self):
        appt = self._appt(status=STATUS_PENDING)
        assert appt.can_cancel

    def test_cannot_cancel_completed(self):
        appt = self._appt(status=STATUS_COMPLETED)
        assert not appt.can_cancel

    def test_cannot_cancel_past_appointment(self):
        appt = self._appt(booking_date=date.today() - timedelta(days=1),
                          status=STATUS_APPROVED)
        assert not appt.can_cancel

    def test_can_reschedule_needs_24h_notice(self):
        soon = self._appt(
            booking_date=date.today(),
            booking_time=(datetime.now() + timedelta(hours=2)).time(),
            status=STATUS_APPROVED)
        far = self._appt(
            booking_date=date.today() + timedelta(days=3),
            status=STATUS_APPROVED)
        assert not soon.can_reschedule
        assert far.can_reschedule

    def test_status_label(self):
        assert self._appt(status=STATUS_PENDING).status_label == "Awaiting approval"
        assert self._appt(status=STATUS_APPROVED).status_label == "Confirmed"


class TestPromoCodeMath:
    """PromoCode's boolean/int columns rely on SQLAlchemy's Python-side
    `default=`, which is only applied on flush -- a bare `PromoCode(...)` that
    never touches the session leaves `is_active` etc. as None. So every promo
    here is added and flushed (no commit needed, no route involved) before
    its math is exercised."""

    def _flushed(self, **kwargs):
        promo = PromoCode(**kwargs)
        db.session.add(promo)
        db.session.flush()
        return promo

    def test_percent_discount(self):
        promo = self._flushed(code="WELCOME10", kind="percent", value=10,
                              min_spend=1500, max_discount=600)
        assert promo.discount_on(3000) == 300

    def test_percent_discount_is_capped(self):
        promo = self._flushed(code="DASHAIN25", kind="percent", value=25,
                              min_spend=2000, max_discount=1000)
        # 25% of 6000 would be 1500, but the cap is 1000.
        assert promo.discount_on(6000) == 1000

    def test_flat_discount(self):
        promo = self._flushed(code="GLOWUP500", kind="flat", value=500,
                              min_spend=3000)
        assert promo.discount_on(4000) == 500

    def test_below_minimum_spend_gives_nothing(self):
        promo = self._flushed(code="WELCOME10", kind="percent", value=10,
                              min_spend=1500)
        assert promo.discount_on(1000) == 0

    def test_expired_code_gives_nothing(self):
        promo = self._flushed(code="OLD", kind="flat", value=500,
                              expires_on=date.today() - timedelta(days=1))
        assert promo.is_expired
        assert promo.discount_on(5000) == 0

    def test_used_up_code_gives_nothing(self):
        promo = self._flushed(code="LIMITED", kind="flat", value=100,
                              usage_limit=5, used_count=5)
        assert promo.is_used_up
        assert promo.discount_on(5000) == 0

    def test_inactive_code_gives_nothing(self):
        promo = self._flushed(code="OFF", kind="flat", value=100,
                              is_active=False)
        assert promo.discount_on(5000) == 0

    def test_why_not_messages(self):
        expired = self._flushed(code="OLD", kind="flat", value=100,
                                expires_on=date.today() - timedelta(days=1))
        assert "expired" in expired.why_not(5000)

        broke = self._flushed(code="X", kind="flat", value=100, min_spend=5000)
        assert "minimum spend" in broke.why_not(100)


class TestPaymentHelpers:
    def test_ocr_all_ok_requires_every_check(self):
        payment = Payment(appointment_id=1, method="advance", amount=500,
                          ocr_checked=True, ocr_number_ok=True,
                          ocr_amount_ok=True, ocr_success_ok=False)
        assert not payment.ocr_all_ok
        payment.ocr_success_ok = True
        assert payment.ocr_all_ok

    def test_ocr_flags_lists_failures(self):
        payment = Payment(appointment_id=1, method="advance", amount=500,
                          ocr_checked=True, ocr_number_ok=False,
                          ocr_amount_ok=True, ocr_success_ok=False)
        flags = payment.ocr_flags
        assert "eSewa number not found" in flags
        assert "no 'successful' confirmation" in flags
        assert len(flags) == 2

    def test_ocr_flags_empty_when_not_checked(self):
        payment = Payment(appointment_id=1, method="advance", amount=500,
                          ocr_checked=False)
        assert payment.ocr_flags == []
