"""
app.py
------
Application entry point. Uses the "application factory" pattern so the app is
easy to configure and test.

Run it with:   python app.py
Then open:     http://localhost:5000
"""

import os

from flask import Flask, render_template
from dotenv import load_dotenv

from config import Config
from extensions import db, login_manager, csrf, limiter

# Load variables from a local .env file if present (DB password, secret key...).
load_dotenv()


def create_app(config_class=Config):
    """Build and configure the Flask application."""
    app = Flask(
        __name__,
        template_folder=config_class.TEMPLATE_FOLDER,   # ../frontend/templates
        static_folder=config_class.STATIC_FOLDER,       # ../frontend/static
    )
    app.config.from_object(config_class)

    # Make sure the uploads folder exists.
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    # Wire up the extensions with this app instance.
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    # Import the models so SQLAlchemy knows about the tables, create them, then
    # fill an empty database with the salon's catalogue and demo data.
    with app.app_context():
        from models import (User, Service, Design, Color,          # noqa: F401
                            Appointment, Payment, Review, BlockedDate,
                            PromoCode, Notification)
        db.create_all()

        from seed import seed_all
        seed_all()

    # Register the route blueprints (grouped by feature).
    from routes.main import main_bp
    from routes.auth import auth_bp
    from routes.booking import booking_bp
    from routes.admin import admin_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(booking_bp)
    app.register_blueprint(admin_bp)

    # --- Things every template can reach ---
    import datetime as _dt

    @app.context_processor
    def inject_globals():
        from flask_login import current_user
        from models import Appointment, Notification, STATUS_PENDING

        # The admin's navbar shows a badge with the number of bookings waiting.
        pending = 0
        # A client's bell shows how many things they haven't read yet.
        unread = 0

        if current_user.is_authenticated:
            unread = Notification.query.filter_by(
                user_id=current_user.id, is_read=False).count()
            if current_user.is_admin:
                pending = Appointment.query.filter_by(
                    status=STATUS_PENDING).count()

        return {
            "current_year": _dt.datetime.utcnow().year,
            "unread_count": unread,
            "salon": {
                "name": app.config["SALON_NAME"],
                "tagline": app.config["SALON_TAGLINE"],
                "phone": app.config["SALON_PHONE"],
                "email": app.config["SALON_EMAIL"],
                "area": app.config["SALON_AREA"],
                "address": app.config["SALON_ADDRESS"],
                "map_embed": app.config["SALON_MAP_EMBED"],
                "esewa": app.config["SALON_ESEWA"],
                "esewa_name": app.config["SALON_ESEWA_NAME"],
                "open_hour": app.config["OPEN_HOUR"],
                "close_hour": app.config["CLOSE_HOUR"],
                "deposit": app.config["DEPOSIT_AMOUNT"],
                "refund_percent": app.config["REFUND_PERCENT"],
            },
            "pending_count": pending,
        }

    @app.template_filter("rs")
    def rupees(value):
        """Format a number the way prices are written in Nepal: Rs. 2,500."""
        try:
            return f"Rs. {int(value):,}"
        except (TypeError, ValueError):
            return "Rs. 0"

    @app.template_filter("clock")
    def clock(value):
        """A time object as '2:30 PM'."""
        if not value:
            return ""
        return value.strftime("%I:%M %p").lstrip("0")

    @app.template_filter("nice_date")
    def nice_date(value):
        """A date as 'Sat, 18 Jul 2026'."""
        if not value:
            return ""
        return value.strftime("%a, %d %b %Y")

    # --- Security response headers (defence in depth) ---
    @app.after_request
    def set_security_headers(response):
        # Content-Security-Policy: scripts may ONLY come from our own origin
        # (no inline scripts) — the strongest single defence against XSS.
        # The Google Maps iframe on the contact page needs frame-src.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src https://fonts.gstatic.com; "
            "img-src 'self' data: https:; "     # uploads + the TOTP QR data-uri
            "connect-src 'self'; "
            "frame-src https://www.google.com; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "frame-ancestors 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"   # no MIME sniffing
        response.headers["X-Frame-Options"] = "DENY"             # no clickjacking
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=()"
        )
        # Only advertise HSTS when actually served over HTTPS.
        if app.config.get("SESSION_COOKIE_SECURE"):
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        return response

    # Friendly error pages.
    @app.errorhandler(403)
    def forbidden(_e):
        return render_template("error.html", code=403,
                               message="That area is for the salon owner only."), 403

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("error.html", code=404,
                               message="We couldn't find that page."), 404

    @app.errorhandler(413)
    def too_large(_e):
        return render_template("error.html", code=413,
                               message="That image is too large (max 5 MB)."), 413

    @app.errorhandler(429)
    def rate_limited(_e):
        return render_template("error.html", code=429,
                               message="Too many requests — please slow down and "
                                       "try again in a moment."), 429

    @app.errorhandler(500)
    def server_error(_e):
        return render_template("error.html", code=500,
                               message="Something went wrong on our side."), 500

    return app


# A module-level app so both `flask run` and `python app.py` work.
app = create_app()


if __name__ == "__main__":
    # debug=True gives auto-reload + helpful error pages during development.
    app.run(host="0.0.0.0", port=5000, debug=True)
