"""
tests/conftest.py
------------------
Shared pytest fixtures for the backend test suite.

Every test runs against a REAL MySQL database — a separate one from the
development database, so nothing here ever touches the demo data seeded by
seed.py. The schema is dropped and rebuilt before each test function, which
keeps every test fully isolated at the cost of a little speed (acceptable for
a suite this size).

Key choices:
  - DB_NAME is forced to "eleanora_nails_test" *before* config.py is imported,
    so every table lives in its own database.
  - CSRF and rate limiting are switched off by default so tests can post forms
    directly without scraping tokens or hitting throttles; test_security.py
    flips CSRF back on for the one test that specifically checks it.
  - Uploaded files land in a throwaway temp folder, never in the real
    frontend/static/uploads.
"""

import os
import sys
import io
import tempfile

# Make sure DB_NAME is set before config.py (imported via app.py) reads it.
os.environ["DB_NAME"] = "eleanora_nails_test"

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import pytest
from PIL import Image

from config import Config
from extensions import db as _db

TEST_UPLOAD_DIR = tempfile.mkdtemp(prefix="eleanora_test_uploads_")


class TestConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False
    SECRET_KEY = "test-secret-key"
    UPLOAD_FOLDER = TEST_UPLOAD_DIR


@pytest.fixture(scope="session")
def app():
    from app import create_app
    application = create_app(TestConfig)
    with application.app_context():
        _db.drop_all()
        _db.create_all()
    yield application
    with application.app_context():
        _db.drop_all()


@pytest.fixture(autouse=True)
def _db_reset(app):
    """Every table emptied before each test, without paying for drop/create
    (schema DDL) 112 times over a real network connection to MySQL."""
    ctx = app.app_context()
    ctx.push()
    for table in reversed(_db.metadata.sorted_tables):
        _db.session.execute(table.delete())
    _db.session.commit()
    yield
    _db.session.remove()
    ctx.pop()


@pytest.fixture
def client(app):
    return app.test_client()


# ---------------------------------------------------------------- factories

@pytest.fixture
def catalogue():
    """A minimal but complete catalogue: one service, one design, one colour."""
    from models import Service, Design, Color

    service = Service(service_name="Gel-X", description="Soft gel tips.",
                      price=3000, duration=90, sort_order=0)
    _db.session.add(service)
    _db.session.flush()

    design = Design(design_name="Gold Line French", category="French",
                    image="gold-line-french.jpg", extra_price=0,
                    service_id=service.id)
    _db.session.add(design)

    color = Color(color_name="Nude", hex_code="#e3c2ae")
    _db.session.add(color)

    _db.session.commit()
    return {"service": service, "design": design, "color": color}


@pytest.fixture
def admin_user():
    from models import User
    user = User(full_name="Mizumi Lamgade", email="admin@eleanoranails.com",
               phone="+977 9847495064", role="admin")
    user.set_password("Admin@123")
    _db.session.add(user)
    _db.session.commit()
    return user


@pytest.fixture
def customer_user():
    from models import User
    user = User(full_name="Aayusha Shrestha", email="customer@example.com",
               phone="+977 9812345678", role="customer")
    user.set_password("Password@123")
    _db.session.add(user)
    _db.session.commit()
    return user


def login(client, email, password):
    return client.post("/login", data={"email": email, "password": password},
                       follow_redirects=True)


def fake_png_bytes(size=(40, 40), color=(200, 100, 120)):
    """A real, tiny, valid PNG — good enough to pass Pillow's re-encode check."""
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    buf.seek(0)
    return buf


def fake_upload(filename="receipt.png"):
    """A Werkzeug-compatible (filename, BytesIO) tuple for a valid image upload."""
    return (fake_png_bytes(), filename)
