"""
seed.py
-------
Fills a brand-new database with everything the site needs to look alive:

  * the admin account (the salon owner)
  * the four services on the menu
  * the 30 gallery designs (the photos in /static/designs), each tagged with the
    category it actually belongs to
  * the colour palette
  * ~55 demo customers, a spread of past and upcoming appointments, and the
    reviews those customers left

It is safe to run more than once: `seed_all()` bails out the moment it finds an
existing service, so a restart never duplicates rows.
"""

import random
from datetime import datetime, timedelta, date, time

from extensions import db
from models import (User, Service, Design, Color, Appointment, Payment, Review,
                    PromoCode, Notification,
                    NAIL_SHAPES, NAIL_LENGTHS,
                    STATUS_PENDING, STATUS_APPROVED, STATUS_COMPLETED,
                    STATUS_CANCELLED)


ADMIN_EMAIL = "admin@eleanoranails.com"
ADMIN_PASSWORD = "Admin@123"

# A known customer account, so there is always a predictable login to demo with.
DEMO_EMAIL = "customer@example.com"
DEMO_PASSWORD = "Password@123"

# The advance every booking pays. Mirrors Config.DEPOSIT_AMOUNT; the seed runs
# inside an app context, but keeping it here makes the demo data self-contained.
DEPOSIT = 500


# ---------------------------------------------------------------- promos

PROMOS = [
    {
        "code": "WELCOME10", "kind": "percent", "value": 10,
        "description": "10% off your first set with us.",
        "max_discount": 600, "min_spend": 1500, "usage_limit": 0,
    },
    {
        "code": "GLOWUP500", "kind": "flat", "value": 500,
        "description": "Rs. 500 off any set over Rs. 3,000.",
        "max_discount": 0, "min_spend": 3000, "usage_limit": 50,
    },
    {
        "code": "DASHAIN25", "kind": "percent", "value": 25,
        "description": "Festival offer, 25% off, capped at Rs. 1,000.",
        "max_discount": 1000, "min_spend": 2000, "usage_limit": 100,
    },
    {
        "code": "BESTIE15", "kind": "percent", "value": 15,
        "description": "Bring a friend, 15% off for both of you.",
        "max_discount": 800, "min_spend": 2000, "usage_limit": 0,
    },
]


# ---------------------------------------------------------------- services

SERVICES = [
    {
        "service_name": "Overlay",
        "description": (
            "A gel overlay applied over your natural nails to strengthen them "
            "and add a flawless, glass-like shine, no added length, just your "
            "own nails at their strongest and glossiest."
        ),
        "price": 1000, "duration": 75, "image": "sugar-glitter-nude.jpg",
    },
    {
        "service_name": "Gel Nail Extension",
        "description": (
            "Builder-gel extensions sculpted to the length and shape you want. "
            "Flexible, lightweight and kind to the natural nail underneath, our "
            "most popular way to grow out a set."
        ),
        "price": 2500, "duration": 120, "image": "rose-ombre-square.jpg",
    },
    {
        "service_name": "Gel-X",
        "description": (
            "Soft-gel full-cover tips bonded with a gentle adhesive gel. Feather "
            "light, natural looking and quick to apply, the best pick if you want "
            "a beautiful set in a single lunch break."
        ),
        "price": 3000, "duration": 90, "image": "gold-line-french.jpg",
    },
    {
        "service_name": "Acrylic",
        "description": (
            "Strong, sculpted acrylic extensions built to last. The ideal canvas "
            "for detailed 3D nail art, encapsulated charms and dramatic lengths."
        ),
        "price": 4000, "duration": 135, "image": "midnight-lily-gold.jpg",
    },
]


# ---------------------------------------------------------------- designs
# (filename, display name, category, surcharge), the categories were assigned
# by looking at each photo, not by guessing from the file name.

DESIGNS = [
    ("gold-line-french.jpg", "Gold Line French", "French", 0),
    ("nude-flower-square.jpg", "Nude Blossom Square", "Floral", 300),
    ("baby-boomer-fade.jpg", "Baby Boomer Fade", "Ombre", 200),
    ("rose-ombre-square.jpg", "Rose Ombré Square", "Ombre", 200),
    ("blush-ombre-glass.jpg", "Blush Glass Ombré", "Ombre", 200),
    ("mauve-ombre-coffin.jpg", "Mauve Ombré Coffin", "Ombre", 200),
    ("rose-gold-blossom.jpg", "Rose Gold Blossom", "Floral", 500),
    ("pearl-petal-milk.jpg", "Pearl Petal Milk Bath", "Floral", 600),
    ("midnight-lily-gold.jpg", "Midnight Lily & Gold", "Luxury", 800),
    ("sage-chrome-cat-eye.jpg", "Sage Chrome Cat-Eye", "Chrome", 400),
    ("copper-cat-eye.jpg", "Copper Cat-Eye", "Chrome", 400),
    ("cherry-noir-almond.jpg", "Cherry Noir", "Minimalist", 0),
    ("porcelain-blue-bloom.jpg", "Porcelain Blue Bloom", "Floral", 700),
    ("lilac-gold-bridal.jpg", "Lilac & Gold Bridal", "Luxury", 900),
    ("iridescent-seashell.jpg", "Iridescent Seashell", "Luxury", 900),
    ("ocean-shell-3d.jpg", "Ocean Shell 3D", "Floral", 700),
    ("sugar-glitter-nude.jpg", "Sugar Glitter Nude", "Glitter", 250),
    ("gold-caviar-nude.jpg", "Gold Caviar Nude", "Minimalist", 300),
    ("albiceleste-glory.jpg", "Albiceleste Glory", "Glitter", 500),
    ("portugal-world-cup.jpg", "World Cup Gold", "Luxury", 900),
    ("celestial-chrome-swirl.jpg", "Celestial Chrome Swirl", "Chrome", 600),
    ("butter-hibiscus.jpg", "Butter Hibiscus", "Floral", 600),
    ("sakura-marble-pearl.jpg", "Sakura Marble & Pearl", "Marble", 700),
    ("ivory-petal-crystal.jpg", "Ivory Petal Crystal", "Luxury", 800),
    ("gold-ribbon-minimal.jpg", "Gold Ribbon Minimal", "Minimalist", 250),
    ("cherry-blossom-luxe.jpg", "Cherry Blossom Luxe", "Floral", 800),
    ("pink-chrome-florals.jpg", "Pink Chrome Florals", "Chrome", 600),
    ("magenta-marble-set.jpg", "Magenta Marble Set", "Marble", 700),
    ("eight-ball-retro.jpg", "Eight Ball Retro", "Minimalist", 400),
    ("glazed-pearl-oval.jpg", "Glazed Pearl Oval", "Glitter", 300),
]


# ---------------------------------------------------------------- colours

COLORS = [
    ("White", "#f8f6f2"),
    ("Black", "#16151a"),
    ("Nude", "#e3c2ae"),
    ("Pink", "#f0a7b8"),
    ("Red", "#c0303c"),
    ("Blue", "#5c7fb0"),
    ("Purple", "#8d6fb3"),
    ("Green", "#7d9b74"),
    ("Gold", "#c9a227"),
    ("Silver", "#c2c6cc"),
]


# ---------------------------------------------------------------- customers

FIRST_NAMES = [
    "Aayusha", "Anjali", "Anushka", "Aarati", "Bimala", "Bhawana", "Chandani",
    "Deepika", "Dikshya", "Elina", "Gita", "Isha", "Jyoti", "Kabita", "Karuna",
    "Kritika", "Laxmi", "Manisha", "Melina", "Nabina", "Nisha", "Nirmala",
    "Pooja", "Prakriti", "Pratima", "Rachana", "Rashmi", "Rekha", "Riya",
    "Sabina", "Salina", "Samjhana", "Sandhya", "Sangita", "Sarita", "Shreya",
    "Shristi", "Simran", "Sneha", "Sabnam", "Sujata", "Sunita", "Susmita",
    "Swastika", "Tara", "Urmila", "Usha", "Yamuna", "Ayushma", "Barsha",
    "Ishani", "Muskan", "Namrata", "Pragya", "Trishna",
]

LAST_NAMES = [
    "Shrestha", "Maharjan", "Tamang", "Gurung", "Rai", "Limbu", "Thapa",
    "Adhikari", "Karki", "Basnet", "Poudel", "Bhattarai", "Pradhan", "Joshi",
    "Sharma", "Dangol", "Manandhar", "Lama", "Magar", "Khadka",
]

REVIEW_TEXT = [
    "Eleanora is so gentle and the finish is flawless. My gel-x lasted five "
    "weeks without a single lift.",
    "The studio is spotless and so calming. She took her time getting the shape "
    "exactly right.",
    "I showed her a photo and she matched it perfectly, the chrome came out "
    "even better than the picture.",
    "Best acrylics I've had in Kathmandu. Strong, light and the 3D flowers are "
    "unreal.",
    "Booked for my sister's wedding and got so many compliments. Worth every rupee.",
    "Really professional, and she explained how to take care of them afterwards.",
    "Loved the ombré! Colour blend is so smooth you can't see where it starts.",
    "Second time here and I'm never going anywhere else. Such neat cuticle work.",
    "The overlay saved my natural nails, they've stopped breaking completely.",
    "Very sweet and patient, even when I changed my mind about the colour twice.",
    "Quick, clean, and the price is fair for this level of art.",
    "My french tips are razor sharp, you can tell she really cares about detail.",
    "Beautiful work and a lovely chat. Felt like a proper little escape.",
    "The marble design is stunning in person. Photos don't do it justice.",
    "Perfect almond shape, exactly the length I asked for. So happy.",
    "She fixed a set another salon ruined and made it look brand new.",
    "Gorgeous glitter, and not one nail has chipped in three weeks.",
    "Easy to book online and she confirmed the same day. Great experience.",
    "The nude with the gold caviar is so classy. Everyone at work asked about it.",
    "Honestly obsessed. Already booked my next appointment.",
]


def _hour_options():
    """Reasonable start times for the demo bookings."""
    return [time(h, m) for h in range(10, 17) for m in (0, 30)]


def seed_all():
    """Populate an empty database. Does nothing if it has already been seeded."""
    if Service.query.first():
        return # already seeded

    rng = random.Random(7) # a fixed seed keeps the demo data reproducible

    # ---- admin ----
    admin = User(full_name="Mizumi Lamgade", email=ADMIN_EMAIL,
                 phone="+977 9847495064", role="admin")
    admin.set_password(ADMIN_PASSWORD)
    db.session.add(admin)

    # ---- services ----
    services = []
    for i, row in enumerate(SERVICES):
        service = Service(sort_order=i, **row)
        db.session.add(service)
        services.append(service)

    # ---- colours ----
    colors = []
    for name, hex_code in COLORS:
        color = Color(color_name=name, hex_code=hex_code)
        db.session.add(color)
        colors.append(color)

    # ---- promo codes ----
    for row in PROMOS:
        db.session.add(PromoCode(
            expires_on=date.today() + timedelta(days=90), **row))

    db.session.flush() # give services + colours their ids

    # ---- designs ----
    # Pair each design with the service that suits it: heavy 3D art goes with
    # acrylic, simple finishes with the overlay, and so on.
    by_name = {s.service_name: s for s in services}
    designs = []
    for filename, name, category, extra in DESIGNS:
        if extra >= 700:
            service = by_name["Acrylic"]
        elif extra >= 400:
            service = by_name["Gel Nail Extension"]
        elif extra >= 200:
            service = by_name["Gel-X"]
        else:
            service = by_name["Overlay"]
        design = Design(design_name=name, category=category, image=filename,
                        extra_price=extra, service_id=service.id)
        db.session.add(design)
        designs.append(design)

    # ---- demo customers ----
    # The first one has a fixed, memorable address so there is always a known
    # customer login to demo with (see DEMO_EMAIL). The rest are generated.
    customers = []
    used_emails = {DEMO_EMAIL}

    demo = User(full_name="Aayusha Shrestha", email=DEMO_EMAIL,
                phone="+977 9812345678", role="customer",
                created_at=datetime.utcnow() - timedelta(days=200))
    demo.set_password(DEMO_PASSWORD)
    db.session.add(demo)
    customers.append(demo)

    for i in range(55):
        first = FIRST_NAMES[i % len(FIRST_NAMES)]
        last = rng.choice(LAST_NAMES)
        email = f"{first.lower()}.{last.lower()}{i}@example.com"
        if email in used_emails:
            continue
        used_emails.add(email)

        user = User(
            full_name=f"{first} {last}",
            email=email,
            phone=f"+977 98{rng.randint(10000000, 99999999)}",
            role="customer",
            created_at=datetime.utcnow() - timedelta(days=rng.randint(20, 400)),
        )
        user.set_password(DEMO_PASSWORD)
        db.session.add(user)
        customers.append(user)

    db.session.flush() # ids for designs + customers

    # ---- appointments ----
    # A believable history: mostly completed visits in the past, a handful of
    # confirmed and pending bookings ahead, and a few cancellations.
    slots = _hour_options()
    today = date.today()
    taken = set() # (date, time) pairs already used, so nothing overlaps
    reviewers = []

    def _make_appointment(day, status):
        slot = rng.choice(slots)
        if (day, slot) in taken:
            return None
        taken.add((day, slot))

        user = rng.choice(customers)
        design = rng.choice(designs)
        service = next(s for s in services if s.id == design.service_id)
        length = rng.choice(list(NAIL_LENGTHS.keys()))

        total = service.price + design.extra_price + NAIL_LENGTHS[length]
        prepaid = rng.random() < 0.55

        appt = Appointment(
            user_id=user.id,
            service_id=service.id,
            design_id=design.id,
            color_id=rng.choice(colors).id,
            secondary_color_id=rng.choice(colors).id if rng.random() < 0.6 else None,
            accent_color_id=rng.choice(colors).id if rng.random() < 0.4 else None,
            nail_shape=rng.choice(NAIL_SHAPES),
            nail_length=length,
            booking_date=day,
            booking_time=slot,
            duration=service.duration,
            total_price=total,
            status=status,
            created_at=datetime.combine(day, slot) - timedelta(days=rng.randint(2, 12)),
        )
        db.session.add(appt)
        db.session.flush()

        # Every booking pays the same Rs. 500 advance; the only difference is
        # how the client said they'd settle the balance.
        pay_status = {
            STATUS_COMPLETED: "settled",
            STATUS_APPROVED: "verified",
            STATUS_PENDING: "pending",
            STATUS_CANCELLED: "verified",
        }[status]

        payment = Payment(
            appointment_id=appt.id,
            method=("full" if prepaid else "advance"),
            amount=DEPOSIT,
            balance=(0 if status == STATUS_COMPLETED else max(0, total - DEPOSIT)),
            transaction_code=f"ESW{rng.randint(10**9, 10**10 - 1)}",
            status=pay_status,
            verified_at=(datetime.utcnow()
                         if pay_status in ("verified", "settled") else None),
            # The seeded receipts are imaginary, so they were never OCR'd.
            ocr_checked=False,
        )

        # A cancelled booking is owed half its advance back.
        if status == STATUS_CANCELLED:
            payment.refund_due = DEPOSIT // 2
            payment.refund_paid = rng.random() < 0.6 # most have been sent

        db.session.add(payment)

        if status == STATUS_COMPLETED:
            reviewers.append((user, appt))
        return appt

    # 70 past visits, nearly all completed.
    for _ in range(70):
        day = today - timedelta(days=rng.randint(1, 150))
        status = STATUS_COMPLETED if rng.random() < 0.88 else STATUS_CANCELLED
        _make_appointment(day, status)

    # 14 confirmed bookings coming up.
    for _ in range(14):
        day = today + timedelta(days=rng.randint(1, 30))
        _make_appointment(day, STATUS_APPROVED)

    # 6 fresh requests still waiting on the admin.
    for _ in range(6):
        day = today + timedelta(days=rng.randint(2, 30))
        _make_appointment(day, STATUS_PENDING)

    # ---- reviews ----
    # Roughly half of the completed visits leave a review, skewed positive the
    # way a real salon's ratings are.
    rng.shuffle(reviewers)
    for i, (user, appt) in enumerate(reviewers[:42]):
        rating = 5 if rng.random() < 0.72 else rng.choice([4, 4, 4, 3])
        db.session.add(Review(
            user_id=user.id,
            appointment_id=appt.id,
            rating=rating,
            comment=REVIEW_TEXT[i % len(REVIEW_TEXT)],
            created_at=appt.start_dt + timedelta(days=rng.randint(1, 5)),
        ))

    # ---- notifications ----
    # Give everyone the message their booking's status implies, so the bell is
    # not an empty room on a fresh install.
    for appt in Appointment.query.all():
        if appt.status == STATUS_APPROVED:
            db.session.add(Notification(
                user_id=appt.user_id, appointment_id=appt.id, kind="approved",
                title="Your booking is confirmed",
                body=(f"Your {appt.service.service_name} on "
                      f"{appt.booking_date.strftime('%A %d %B')} is confirmed. "
                      f"Rs. {max(0, appt.total_price - DEPOSIT):,} is due at the "
                      "studio."),
                is_read=rng.random() < 0.5,
                created_at=appt.created_at + timedelta(hours=rng.randint(2, 20)),
            ))
        elif appt.status == STATUS_COMPLETED:
            db.session.add(Notification(
                user_id=appt.user_id, appointment_id=appt.id, kind="completed",
                title="Thanks for visiting!",
                body=(f"Hope you love your {appt.service.service_name}. If you "
                      "have a moment, we'd really appreciate a review."),
                is_read=True,
                created_at=appt.end_dt + timedelta(hours=2),
            ))
        elif appt.status == STATUS_CANCELLED and appt.payment:
            db.session.add(Notification(
                user_id=appt.user_id, appointment_id=appt.id, kind="refund",
                title=f"Refund of Rs. {appt.payment.refund_due:,} on the way",
                body=("Half of your advance is being returned to your eSewa. "
                      "The other half is retained, as the slot was held for you."),
                is_read=rng.random() < 0.7,
                created_at=appt.created_at + timedelta(days=1),
            ))

    # A friendly nudge for the demo account, so its bell has something unread.
    db.session.add(Notification(
        user_id=demo.id, kind="promo",
        title="A little something for you",
        body=("Use code WELCOME10 at checkout for 10% off your next set, "
              "up to Rs. 600 off."),
        is_read=False,
        created_at=datetime.utcnow() - timedelta(hours=6),
    ))

    db.session.commit()
