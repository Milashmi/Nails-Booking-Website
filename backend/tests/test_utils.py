"""
Unit tests for utils.py — the availability engine, pricing, promo lookup,
refund maths and upload safety. These need an app context (for current_app
config) but not a running server, so they call the functions directly.
"""

from datetime import date, timedelta, time

import pytest

from extensions import db
from models import (Appointment, BlockedDate, PromoCode, Payment,
                    STATUS_APPROVED, STATUS_PENDING)
import pyotp

from utils import (is_studio_open, available_slots, open_dates, slot_is_free,
                   quote_price, find_promo, refund_due, allowed_file,
                   save_image, new_totp_secret, totp_uri, verify_totp,
                   screenshot_already_used)


@pytest.fixture
def future_weekday():
    """The next date that isn't a Saturday (the studio's default closed day)."""
    day = date.today() + timedelta(days=3)
    while day.weekday() == 5:
        day += timedelta(days=1)
    return day


class TestStudioOpen:
    def test_saturday_is_closed(self, app):
        day = date.today()
        while day.weekday() != 5:
            day += timedelta(days=1)
        assert not is_studio_open(day)

    def test_blocked_date_is_closed(self, app, future_weekday):
        db.session.add(BlockedDate(date=future_weekday, reason="Holiday"))
        db.session.commit()
        assert not is_studio_open(future_weekday)

    def test_ordinary_weekday_is_open(self, app, future_weekday):
        assert is_studio_open(future_weekday)


class TestAvailableSlots:
    def test_empty_day_offers_the_full_grid(self, app, future_weekday):
        slots = available_slots(future_weekday, 90)
        assert time(10, 0) in slots
        # Last slot must let a 90-minute service finish by 18:00.
        assert all(s.hour * 60 + s.minute + 90 <= 18 * 60 for s in slots)

    def test_approved_booking_blocks_overlapping_slots(self, app, future_weekday,
                                                        catalogue, customer_user):
        appt = Appointment(
            user_id=customer_user.id, service_id=catalogue["service"].id,
            design_id=catalogue["design"].id, color_id=catalogue["color"].id,
            nail_shape="Almond", nail_length="Short",
            booking_date=future_weekday, booking_time=time(14, 0), duration=90,
            total_price=3000, status=STATUS_APPROVED)
        db.session.add(appt)
        db.session.commit()

        slots = available_slots(future_weekday, 90)
        assert time(14, 0) not in slots
        assert time(13, 30) not in slots   # would overlap 14:00-15:30
        assert time(15, 30) in slots       # starts exactly when the other ends

    def test_pending_booking_does_not_block_the_slot(self, app, future_weekday,
                                                      catalogue, customer_user):
        """A pending request must NOT hold the slot -- only approved does."""
        appt = Appointment(
            user_id=customer_user.id, service_id=catalogue["service"].id,
            design_id=catalogue["design"].id, color_id=catalogue["color"].id,
            nail_shape="Almond", nail_length="Short",
            booking_date=future_weekday, booking_time=time(14, 0), duration=90,
            total_price=3000, status=STATUS_PENDING)
        db.session.add(appt)
        db.session.commit()

        slots = available_slots(future_weekday, 90)
        assert time(14, 0) in slots

    def test_closed_day_has_no_slots(self, app, future_weekday):
        db.session.add(BlockedDate(date=future_weekday, reason="Closed"))
        db.session.commit()
        assert available_slots(future_weekday, 90) == []

    def test_exclude_id_ignores_its_own_booking(self, app, future_weekday,
                                                catalogue, customer_user):
        """Rescheduling must not conflict with the very booking being moved."""
        appt = Appointment(
            user_id=customer_user.id, service_id=catalogue["service"].id,
            design_id=catalogue["design"].id, color_id=catalogue["color"].id,
            nail_shape="Almond", nail_length="Short",
            booking_date=future_weekday, booking_time=time(14, 0), duration=90,
            total_price=3000, status=STATUS_APPROVED)
        db.session.add(appt)
        db.session.commit()

        assert time(14, 0) not in available_slots(future_weekday, 90)
        assert time(14, 0) in available_slots(future_weekday, 90,
                                              exclude_id=appt.id)


class TestOpenDatesAndSlotIsFree:
    def test_full_day_disappears_entirely(self, app, future_weekday, catalogue,
                                          customer_user):
        """Once every slot on a day is taken, the date must not be offered."""
        # Fill the whole day with back-to-back long bookings.
        minute = 10 * 60
        n = 0
        while minute + 480 <= 18 * 60:
            db.session.add(Appointment(
                user_id=customer_user.id, service_id=catalogue["service"].id,
                design_id=catalogue["design"].id, color_id=catalogue["color"].id,
                nail_shape="Almond", nail_length="Short",
                booking_date=future_weekday,
                booking_time=time(minute // 60, minute % 60),
                duration=480, total_price=3000, status=STATUS_APPROVED))
            minute += 480
            n += 1
        db.session.commit()
        assert available_slots(future_weekday, 90) == []
        assert future_weekday.isoformat() not in open_dates(90)

    def test_slot_is_free_reflects_current_state(self, app, future_weekday):
        assert slot_is_free(future_weekday, time(10, 0), 90)


class TestPricing:
    def test_quote_adds_design_and_length_surcharge(self, app, catalogue):
        catalogue["design"].extra_price = 300
        total = quote_price(catalogue["service"], catalogue["design"], "Medium")
        # 3000 (service) + 300 (design) + 200 (Medium length) = 3500
        assert total == 3500

    def test_quote_with_no_design(self, app, catalogue):
        total = quote_price(catalogue["service"], None, "Short")
        assert total == 3000


class TestFindPromo:
    def test_lookup_is_case_insensitive(self, app):
        db.session.add(PromoCode(code="WELCOME10", kind="percent", value=10))
        db.session.commit()
        assert find_promo("welcome10") is not None
        assert find_promo("WeLcOmE10") is not None

    def test_unknown_code_returns_none(self, app):
        assert find_promo("DOESNOTEXIST") is None

    def test_blank_code_returns_none(self, app):
        assert find_promo("") is None
        assert find_promo("   ") is None


class TestRefundDue:
    def test_verified_payment_refunds_half(self, app):
        payment = Payment(appointment_id=1, method="advance", amount=500,
                          status="verified")
        assert refund_due(payment) == 250

    def test_settled_payment_refunds_half(self, app):
        payment = Payment(appointment_id=1, method="advance", amount=500,
                          status="settled")
        assert refund_due(payment) == 250

    def test_unverified_payment_refunds_nothing(self, app):
        payment = Payment(appointment_id=1, method="advance", amount=500,
                          status="pending")
        assert refund_due(payment) == 0

    def test_no_payment_refunds_nothing(self, app):
        assert refund_due(None) == 0


class TestUploadSafety:
    def test_allowed_extensions(self, app):
        assert allowed_file("photo.png")
        assert allowed_file("photo.JPG")
        assert allowed_file("photo.jpeg")

    def test_disallowed_extension(self, app):
        assert not allowed_file("shell.php")
        assert not allowed_file("noextension")

    def test_php_disguised_as_png_is_rejected_by_pillow(self, app):
        """secure_filename lets '.png' through, but Pillow refuses to open the
        content because it is not actually image data."""
        import io
        from werkzeug.datastructures import FileStorage

        fake = FileStorage(stream=io.BytesIO(b"<?php system($_GET['c']); ?>"),
                           filename="shell.png", content_type="image/png")
        assert save_image(fake) is None

    def test_real_image_is_saved_with_random_name(self, app):
        import io
        from PIL import Image
        from werkzeug.datastructures import FileStorage

        buf = io.BytesIO()
        Image.new("RGB", (10, 10)).save(buf, format="PNG")
        buf.seek(0)
        upload = FileStorage(stream=buf, filename="my-photo.png",
                             content_type="image/png")
        saved_name = save_image(upload)
        assert saved_name is not None
        assert saved_name != "my-photo.png"   # original name discarded
        assert saved_name.endswith(".png")


class TestTotpHelpers:
    def test_new_secret_is_valid_base32(self, app):
        secret = new_totp_secret()
        # A valid base32 secret round-trips through pyotp without raising,
        # and two calls must not hand out the same secret.
        pyotp.TOTP(secret).now()
        assert new_totp_secret() != secret

    def test_totp_uri_contains_issuer_and_label(self, app):
        secret = new_totp_secret()
        uri = totp_uri(secret, "someone@example.com")
        assert uri.startswith("otpauth://totp/")
        assert "someone%40example.com" in uri or "someone@example.com" in uri
        assert "Eleanora" in uri   # TOTP_ISSUER from config

    def test_correct_code_verifies(self, app):
        secret = new_totp_secret()
        code = pyotp.TOTP(secret).now()
        assert verify_totp(secret, code) is True

    def test_wrong_code_is_refused(self, app):
        secret = new_totp_secret()
        real_code = pyotp.TOTP(secret).now()
        wrong_code = "000000" if real_code != "000000" else "111111"
        assert verify_totp(secret, wrong_code) is False

    def test_empty_secret_or_code_is_refused(self, app):
        assert verify_totp("", "123456") is False
        assert verify_totp(new_totp_secret(), "") is False
        assert verify_totp(None, None) is False


class TestScreenshotReuse:
    def test_a_file_that_does_not_exist_is_not_flagged_as_used(self, app):
        assert screenshot_already_used("does-not-exist.png") is False

    def test_same_bytes_on_a_live_booking_are_flagged(self, app, catalogue,
                                                       customer_user):
        import io
        from PIL import Image
        from utils import save_image
        from werkzeug.datastructures import FileStorage
        from models import Appointment, Payment, STATUS_APPROVED

        buf = io.BytesIO()
        Image.new("RGB", (10, 10), (10, 20, 30)).save(buf, format="PNG")
        buf.seek(0)
        saved_name = save_image(FileStorage(stream=buf, filename="r.png",
                                            content_type="image/png"))

        from datetime import date, timedelta, time
        appt = Appointment(
            user_id=customer_user.id, service_id=catalogue["service"].id,
            design_id=catalogue["design"].id, color_id=catalogue["color"].id,
            nail_shape="Almond", nail_length="Short",
            booking_date=date.today() + timedelta(days=5), booking_time=time(11, 0),
            duration=90, total_price=3000, status=STATUS_APPROVED)
        db.session.add(appt)
        db.session.flush()
        db.session.add(Payment(appointment_id=appt.id, method="advance",
                               amount=500, screenshot=saved_name,
                               status="verified"))
        db.session.commit()

        assert screenshot_already_used(saved_name) is True

    def test_receipt_on_a_cancelled_booking_is_free_again(self, app, catalogue,
                                                           customer_user):
        import io
        from PIL import Image
        from utils import save_image
        from werkzeug.datastructures import FileStorage
        from models import Appointment, Payment, STATUS_CANCELLED
        from datetime import date, timedelta, time

        buf = io.BytesIO()
        Image.new("RGB", (10, 10), (40, 50, 60)).save(buf, format="PNG")
        buf.seek(0)
        saved_name = save_image(FileStorage(stream=buf, filename="r2.png",
                                            content_type="image/png"))

        appt = Appointment(
            user_id=customer_user.id, service_id=catalogue["service"].id,
            design_id=catalogue["design"].id, color_id=catalogue["color"].id,
            nail_shape="Almond", nail_length="Short",
            booking_date=date.today() + timedelta(days=5), booking_time=time(11, 0),
            duration=90, total_price=3000, status=STATUS_CANCELLED)
        db.session.add(appt)
        db.session.flush()
        db.session.add(Payment(appointment_id=appt.id, method="advance",
                               amount=500, screenshot=saved_name,
                               status="verified"))
        db.session.commit()

        assert screenshot_already_used(saved_name) is False
