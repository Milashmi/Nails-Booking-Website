"""
extensions.py
-------------
Flask extensions are created here (without an app) and initialised later
inside the application factory. This avoids circular imports: models and
routes can `from extensions import db` without importing the whole app.
"""

from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_wtf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Database ORM handle.
db = SQLAlchemy()

# Per-IP rate limiter. Specific limits are declared on sensitive routes
# (login, register, 2FA, booking, uploads) to slow down abuse.
limiter = Limiter(key_func=get_remote_address, default_limits=[])

# Handles the logged-in user session (current_user, login_required, etc).
login_manager = LoginManager()
login_manager.login_view = "auth.login"           # where to send anonymous users
login_manager.login_message = "Please log in to book an appointment."
login_manager.login_message_category = "warning"

# Adds CSRF tokens to all forms automatically.
csrf = CSRFProtect()
