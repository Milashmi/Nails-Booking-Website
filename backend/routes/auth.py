"""
routes/auth.py
--------------
Everything about accounts and sessions:
  - register / log in / log out
  - the optional TOTP second factor at login
  - editing the profile and changing the password
  - enabling / disabling two-factor authentication

Security notes:
  - passwords are stored only as salted hashes (see models.User)
  - every form carries a CSRF token (Flask-WTF)
  - during a 2FA login only a *pending* user id is held in the session; the
    user is not really logged in until the correct 6-digit code arrives
  - a wrong password and an unknown email give the identical error message, so
    the login form cannot be used to discover who has an account
"""

import re

from flask import (Blueprint, render_template, redirect, url_for, request,
                   flash, session)
from flask_login import login_user, logout_user, login_required, current_user

from extensions import db, limiter
from models import User
from utils import (save_image, delete_upload, new_totp_secret, totp_qr_data_uri,
                   verify_totp)

auth_bp = Blueprint("auth", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^[0-9+\-\s()]{7,20}$")


@auth_bp.route("/register", methods=["GET", "POST"])
@limiter.limit("20 per hour", methods=["POST"])   # slow down mass sign-ups
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")

        errors = []
        if len(full_name) < 3:
            errors.append("Please enter your full name.")
        if not EMAIL_RE.match(email):
            errors.append("Please enter a valid email address.")
        if not PHONE_RE.match(phone):
            errors.append("Please enter a valid phone number.")
        if len(password) < 8:
            errors.append("Password must be at least 8 characters long.")
        if password != confirm:
            errors.append("The two passwords do not match.")
        if User.query.filter_by(email=email).first():
            errors.append("An account with that email already exists.")

        if errors:
            for message in errors:
                flash(message, "error")
            return render_template("register.html", full_name=full_name,
                                   email=email, phone=phone)

        user = User(full_name=full_name, email=email, phone=phone)
        user.set_password(password)
        # The very first account ever created runs the salon.
        if User.query.count() == 0:
            user.role = "admin"
        db.session.add(user)
        db.session.commit()

        flash("Welcome to Eleanora Nails! Please log in to book your first "
              "appointment.", "success")
        return redirect(url_for("auth.login"))

    return render_template("register.html")


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("40 per minute", methods=["POST"])   # per-IP throttle
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        remember = bool(request.form.get("remember"))

        user = User.query.filter_by(email=email).first()

        # Identical message for a wrong email and a wrong password.
        if not user or not user.check_password(password):
            if user:
                if user.is_locked():
                    return _locked_response(user, "login.html", email=email)
                user.register_failure()
                db.session.commit()
            flash("Those details don't match an account. Please try again.",
                  "error")
            return render_template("login.html", email=email)

        # Right password, but the account is inside a lockout window.
        if user.is_locked():
            return _locked_response(user, "login.html", email=email)

        # ---- Second factor required? ----
        if user.totp_enabled:
            # Do not log in yet: remember who is trying, then ask for the code.
            session["pending_user_id"] = user.id
            session["pending_remember"] = remember
            return redirect(url_for("auth.two_factor"))

        user.reset_failures()
        db.session.commit()
        login_user(user, remember=remember)
        session.permanent = True
        flash(f"Welcome back, {user.first_name}!", "success")
        return _redirect_next()

    return render_template("login.html")


@auth_bp.route("/login/2fa", methods=["GET", "POST"])
@limiter.limit("40 per minute", methods=["POST"])
def two_factor():
    """Second step of login: verify the 6-digit authenticator code."""
    user_id = session.get("pending_user_id")
    if not user_id:
        return redirect(url_for("auth.login"))   # arrived here without step one

    user = db.session.get(User, user_id)
    if not user:
        session.pop("pending_user_id", None)
        return redirect(url_for("auth.login"))

    if user.is_locked():
        session.pop("pending_user_id", None)
        session.pop("pending_remember", None)
        return _locked_response(user, "login.html")

    if request.method == "POST":
        code = request.form.get("code", "")
        if verify_totp(user.totp_secret, code):
            user.reset_failures()
            db.session.commit()
            login_user(user, remember=session.get("pending_remember", False))
            session.permanent = True
            session.pop("pending_user_id", None)
            session.pop("pending_remember", None)
            flash(f"Welcome back, {user.first_name}!", "success")
            return _redirect_next()

        # A wrong code counts as a failure. This is what stops someone brute
        # forcing the 6-digit code: only a handful of tries before a lockout.
        user.register_failure()
        db.session.commit()
        if user.is_locked():
            session.pop("pending_user_id", None)
            session.pop("pending_remember", None)
            return _locked_response(user, "login.html")

        left = 5 - (user.failed_attempts or 0)
        flash(f"That code was not correct. {left} attempt(s) left before a "
              "temporary lockout.", "error")

    return render_template("two_factor.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "success")
    return redirect(url_for("main.index"))


# ---------------- profile & security ----------------

@auth_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    """Edit name, phone and profile photo."""
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        phone = request.form.get("phone", "").strip()

        if len(full_name) < 3:
            flash("Please enter your full name.", "error")
            return redirect(url_for("auth.profile"))
        if phone and not PHONE_RE.match(phone):
            flash("Please enter a valid phone number.", "error")
            return redirect(url_for("auth.profile"))

        current_user.full_name = full_name
        current_user.phone = phone

        saved = save_image(request.files.get("avatar"), max_side=600)
        if saved:
            delete_upload(current_user.avatar)   # don't leave orphans on disk
            current_user.avatar = saved

        db.session.commit()
        flash("Your profile has been updated.", "success")
        return redirect(url_for("auth.profile"))

    return render_template("profile.html")


@auth_bp.route("/profile/password", methods=["POST"])
@login_required
@limiter.limit("10 per hour")
def change_password():
    current = request.form.get("current_password", "")
    new = request.form.get("new_password", "")
    confirm = request.form.get("confirm_password", "")

    if not current_user.check_password(current):
        flash("Your current password is not correct.", "error")
    elif len(new) < 8:
        flash("The new password must be at least 8 characters long.", "error")
    elif new != confirm:
        flash("The two new passwords do not match.", "error")
    else:
        current_user.set_password(new)
        db.session.commit()
        flash("Your password has been changed.", "success")

    return redirect(url_for("auth.profile"))


@auth_bp.route("/profile/2fa/setup", methods=["GET", "POST"])
@login_required
def setup_2fa():
    """
    Turn 2FA on. We generate a secret and show its QR code, but only flip the
    'enabled' flag once the user proves they scanned it by typing a live code.
    """
    if current_user.totp_enabled:
        flash("Two-factor authentication is already switched on.", "info")
        return redirect(url_for("auth.profile"))

    # Reuse one secret across the GET and POST of this flow so the QR on screen
    # stays valid while the user scans it.
    secret = session.get("setup_totp_secret")
    if not secret:
        secret = new_totp_secret()
        session["setup_totp_secret"] = secret

    if request.method == "POST":
        tries = session.get("setup_2fa_tries", 0)
        if tries >= 6:
            flash("Too many incorrect codes. Reload this page to start the "
                  "setup again.", "error")
            session.pop("setup_totp_secret", None)
            session.pop("setup_2fa_tries", None)
            return redirect(url_for("auth.profile"))

        code = request.form.get("code", "")
        if verify_totp(secret, code):
            current_user.totp_secret = secret
            current_user.totp_enabled = True
            db.session.commit()
            session.pop("setup_totp_secret", None)
            session.pop("setup_2fa_tries", None)
            flash("Two-factor authentication is now protecting your account.",
                  "success")
            return redirect(url_for("auth.profile"))

        session["setup_2fa_tries"] = tries + 1
        flash("That code was not correct. Check your phone's clock is in sync.",
              "error")

    qr = totp_qr_data_uri(secret, current_user.email)
    return render_template("setup_2fa.html", qr=qr, secret=secret)


@auth_bp.route("/profile/2fa/disable", methods=["POST"])
@login_required
def disable_2fa():
    """Turn 2FA off — the current password is required to confirm."""
    password = request.form.get("password", "")
    if not current_user.check_password(password):
        flash("Password incorrect, two-factor authentication is still on.",
              "error")
        return redirect(url_for("auth.profile"))

    current_user.totp_enabled = False
    current_user.totp_secret = ""
    db.session.commit()
    flash("Two-factor authentication has been switched off.", "success")
    return redirect(url_for("auth.profile"))


# ---------------- small helpers ----------------

def _locked_response(user, template, **kwargs):
    """Render a page telling the user their account is temporarily locked."""
    minutes = max(1, round(user.lock_seconds_left() / 60))
    flash(f"Too many failed attempts. This account is locked for about "
          f"{minutes} minute(s). Please try again later.", "error")
    return render_template(template, **kwargs)


def _redirect_next():
    """
    Send the user back to the page they originally wanted, but only if it is a
    safe local path — otherwise home. This closes off open-redirect attacks.
    """
    next_url = request.args.get("next") or session.pop("next_url", None)
    if next_url and next_url.startswith("/") and not next_url.startswith("//"):
        return redirect(next_url)
    if current_user.is_authenticated and current_user.is_admin:
        return redirect(url_for("admin.dashboard"))
    return redirect(url_for("main.index"))
