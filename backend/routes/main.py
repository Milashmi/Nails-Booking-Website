"""
routes/main.py
--------------
The public pages anyone can browse without an account:
  - home (hero, featured designs & services, testimonials)
  - about
  - services
  - the design gallery (searchable + filterable)
  - the colour palette
  - contact
"""

from datetime import datetime

from flask import (Blueprint, render_template, request, flash, redirect,
                   url_for, current_app)
from sqlalchemy import func

from extensions import db, limiter
from models import (Service, Design, Color, Review, Appointment, User,
                    STATUS_COMPLETED)

main_bp = Blueprint("main", __name__)


def _rating_summary():
    """The average star rating and how many reviews it is based on."""
    avg, count = (db.session.query(func.avg(Review.rating), func.count(Review.id))
                  .filter(Review.is_visible.is_(True))
                  .first())
    return (round(float(avg), 1) if avg else 5.0), (count or 0)


@main_bp.route("/")
def index():
    services = (Service.query.filter_by(is_active=True)
                .order_by(Service.sort_order, Service.price).all())

    # Show a spread of the prettiest work on the homepage.
    featured = (Design.query.filter_by(is_active=True)
                .order_by(Design.extra_price.desc(), Design.id)
                .limit(8).all())

    testimonials = (Review.query.filter(Review.is_visible.is_(True),
                                        Review.rating >= 4,
                                        Review.comment != "")
                    .order_by(Review.created_at.desc())
                    .limit(6).all())

    avg_rating, review_count = _rating_summary()

    stats = {
        "clients": User.query.filter_by(role="customer").count(),
        "completed": Appointment.query.filter_by(status=STATUS_COMPLETED).count(),
        "designs": Design.query.filter_by(is_active=True).count(),
        "rating": avg_rating,
    }

    return render_template("index.html", services=services, featured=featured,
                           testimonials=testimonials, stats=stats,
                           review_count=review_count)


@main_bp.route("/about")
def about():
    avg_rating, review_count = _rating_summary()
    stats = {
        "clients": User.query.filter_by(role="customer").count(),
        "completed": Appointment.query.filter_by(status=STATUS_COMPLETED).count(),
        "rating": avg_rating,
        "reviews": review_count,
    }
    return render_template("about.html", stats=stats)


@main_bp.route("/services")
def services():
    rows = (Service.query.filter_by(is_active=True)
            .order_by(Service.sort_order, Service.price).all())
    return render_template("services.html", services=rows)


@main_bp.route("/gallery")
def gallery():
    """The design gallery, filterable by category and searchable by name."""
    category = request.args.get("category", "").strip()
    query_text = request.args.get("q", "").strip()

    designs = Design.query.filter_by(is_active=True)
    if category and category.lower() != "all":
        designs = designs.filter(Design.category == category)
    if query_text:
        like = f"%{query_text}%"
        designs = designs.filter(db.or_(Design.design_name.ilike(like),
                                        Design.category.ilike(like)))
    designs = designs.order_by(Design.id).all()

    # Build the filter chips from the categories that actually exist.
    categories = [row[0] for row in
                  db.session.query(Design.category)
                  .filter(Design.is_active.is_(True))
                  .distinct().order_by(Design.category).all()]

    return render_template("gallery.html", designs=designs, categories=categories,
                           active_category=category or "All", q=query_text)


@main_bp.route("/colors")
def colors():
    """The palette page — a preview of how a base/secondary/accent trio looks."""
    rows = Color.query.filter_by(is_active=True).order_by(Color.id).all()
    return render_template("colors.html", colors=rows)


@main_bp.route("/reviews")
def reviews():
    rows = (Review.query.filter(Review.is_visible.is_(True))
            .order_by(Review.created_at.desc()).all())
    avg_rating, review_count = _rating_summary()

    # How many reviews gave each star count — drives the little bar chart.
    spread = {star: 0 for star in range(1, 6)}
    for review in rows:
        spread[review.rating] = spread.get(review.rating, 0) + 1

    return render_template("reviews.html", reviews=rows, avg_rating=avg_rating,
                           review_count=review_count, spread=spread)


@main_bp.route("/contact", methods=["GET", "POST"])
@limiter.limit("10 per hour", methods=["POST"])   # stop contact-form spam
def contact():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        message = request.form.get("message", "").strip()

        if not name or not email or len(message) < 10:
            flash("Please fill in your name, email and a message of at least "
                  "10 characters.", "error")
            return render_template("contact.html", name=name, email=email,
                                   message=message)

        # A real deployment would email this on. For the demo we log it so the
        # owner can see it in the server console.
        current_app.logger.info(
            "Contact message from %s <%s> at %s:\n%s",
            name, email, datetime.utcnow().isoformat(timespec="seconds"), message)

        flash("Thank you, your message is with us. We usually reply within a "
              "few hours.", "success")
        return redirect(url_for("main.contact"))

    return render_template("contact.html")
