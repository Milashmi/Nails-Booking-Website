# Eleanora Nails

**A booking platform for a home-based nail studio in Ghattekulo, Dillibazar, Kathmandu.**

> *Nails that speak elegance.*

Customers browse the treatment menu and a gallery of 30 real nail-art designs,
build their set step by step (design → colours → shape → length → date → time),
pay a deposit through the studio's eSewa QR or choose to settle at the studio,
and wait for the owner to confirm. The owner runs the whole business — the menu,
the gallery, the palette, the diary, the customers and the reviews — from an
admin dashboard.

Built with **Flask (Python) · MySQL · Jinja2 · HTML · CSS · JavaScript** — the
same stack as the Bloggr project, following the same architecture and the same
security posture.

---

## Table of contents

1. [The idea](#1-the-idea)
2. [Technology](#2-technology)
3. [Project structure](#3-project-structure)
4. [Getting it running](#4-getting-it-running)
5. [Demo accounts](#5-demo-accounts)
6. [The pages](#6-the-pages)
7. [How booking works](#7-how-booking-works)
8. [How payment works](#8-how-payment-works)
9. [How the calendar decides what to show](#9-how-the-calendar-decides-what-to-show)
10. [The admin dashboard](#10-the-admin-dashboard)
11. [Two-factor authentication](#11-two-factor-authentication)
12. [Security architecture](#12-security-architecture)
13. [The database](#13-the-database)
14. [Design & motion](#14-design--motion)
15. [The seed data](#15-the-seed-data)
16. [Testing](#16-testing)
17. [Configuration reference](#17-configuration-reference)

---

## 1. The idea

Eleanora Nails is not a salon with six chairs. It is one person, working from
home, seeing **one client at a time**. That single fact drives the entire design
of the software:

- **A slot is exclusive.** If someone is booked from 14:00 to 16:00, nobody else
  can be booked at 15:00. There is no "second chair" to fall back on.
- **A date can genuinely run out.** Once the working day is full, that day must
  vanish from the calendar — not sit there greyed out, tempting people to click.
- **Nothing is promised automatically.** A request is a *request*. The owner
  looks at it, checks the money actually arrived, and only then does the slot
  become theirs. Until that moment the booking is **pending** and the slot is
  still up for grabs.

Everything below is a consequence of those three rules.

---

## 2. Technology

| Layer | What we use | Why |
|---|---|---|
| Web framework | **Flask 3** (application-factory pattern) | Small, explicit, easy to reason about |
| Database | **MySQL 8** | The brief's requirement; relational data with real foreign keys |
| ORM | **Flask-SQLAlchemy** | Parameterised queries by construction — SQL injection has no surface |
| Templating | **Jinja2** | Server-rendered HTML with auto-escaping on by default |
| Sessions | **Flask-Login** | Battle-tested session and "remember me" handling |
| CSRF | **Flask-WTF** (`CSRFProtect`) | A token on every single form |
| Rate limiting | **Flask-Limiter** | Per-IP throttles on login, register, booking, uploads |
| 2FA | **pyotp** + **qrcode** | Standard TOTP; works with Google Authenticator, Authy, etc. |
| Passwords | **Werkzeug** (`generate_password_hash`) | Salted hashes — the raw password is never stored |
| Images | **Pillow** | Every upload is re-encoded, which strips anything hidden inside it |
| Frontend | Hand-written **HTML / CSS / JavaScript** | No build step, no framework, no CDN |

### A note on "Framer Motion"

Framer Motion is a **React** library. This project is server-rendered Flask +
Jinja2 — there is no React in it, so Framer Motion cannot be installed here.
What you asked for was the *feel* of it, and that is exactly what was built,
natively:

- **spring easing curves** — `cubic-bezier(.34, 1.56, .48, 1)`, the overshoot
  curve Framer Motion uses for its `spring` transitions
- **scroll-triggered reveals** — an `IntersectionObserver` adds `.in` the first
  time an element scrolls into view (Framer's `whileInView`)
- **staggered children** — `.stagger` walks its children with increasing
  `transition-delay` (Framer's `staggerChildren`)
- **3D tilt on hover** — cards lean toward the cursor via a live
  `perspective() rotateX() rotateY()` transform
- **parallax** — the hero collage drifts at three different speeds, driven by
  `requestAnimationFrame` so it never fights the browser's frame budget
- **layout transitions** — the booking wizard slides each step in
- **`prefers-reduced-motion`** — every one of these is switched off for users who
  ask for that, which is more than most Framer Motion sites bother to do

The result is the same class of motion, delivered in the technology the project
actually runs on.

---

## 3. Project structure

```
elenora nails/
├── ABOUT.md                  ← you are here
├── logo.png                  ← the original brand asset
├── qrcode.jpeg               ← the original eSewa QR
│
├── backend/
│   ├── app.py                app factory, template filters, security headers,
│   │                         error pages, entry point
│   ├── config.py             every setting in one place (DB, salon details,
│   │                         opening hours, deposit, upload limits)
│   ├── extensions.py         db / login_manager / csrf / limiter, created
│   │                         without an app to avoid circular imports
│   ├── models.py             the 8 tables + the booking lifecycle constants
│   ├── utils.py              image saving, TOTP helpers, and the availability
│   │                         engine (the code that hides full days)
│   ├── seed.py               fills an empty database with the demo world
│   ├── schema.sql            optional manual DB creation
│   ├── requirements.txt
│   ├── .env.example
│   └── routes/
│       ├── main.py           home, about, services, gallery, colours,
│       │                     reviews, contact
│       ├── auth.py           register, login, TOTP 2FA, profile, password
│       ├── booking.py        the 9-step wizard, availability API, my
│       │                     appointments, reschedule, cancel, review, pay
│       └── admin.py          the dashboard and every CRUD screen
│
└── frontend/
    ├── templates/
    │   ├── base.html         the shell: preloader, navbar, flashes, footer
    │   ├── index.html        home
    │   ├── about.html  services.html  gallery.html  colors.html
    │   ├── reviews.html  contact.html  error.html
    │   ├── login.html  register.html  two_factor.html
    │   ├── profile.html  setup_2fa.html
    │   ├── book.html         ← the 9-step booking wizard
    │   ├── appointments.html reschedule.html
    │   ├── partials/         navbar, footer, icons (SVG macros)
    │   └── admin/
    │       ├── _shell.html   the admin sidebar + layout
    │       ├── _appt.html    one booking, as the owner sees it (shared macro)
    │       ├── dashboard.html appointments.html services.html
    │       ├── designs.html  colors.html  schedule.html
    │       └── users.html    reviews.html
    └── static/
        ├── css/style.css     the whole design system
        ├── js/
        │   ├── theme-init.js runs before first paint (no theme flash)
        │   ├── main.js       theme, menus, reveals, tilt, parallax,
        │   │                 counters, lightbox, modals, confirm dialog
        │   ├── booking.js    the wizard engine
        │   ├── reschedule.js the date/time picker for moving a booking
        │   ├── colors.js     the colour-preview playground
        │   └── admin.js      colour-picker sync
        ├── img/              logo.png, payment-qr.jpeg
        ├── designs/          the 30 gallery photos
        └── uploads/          payment screenshots, admin uploads, avatars
```

---

## 4. Getting it running

### Prerequisites
- Python 3.10 or newer
- MySQL 8 running locally

### Step 1 — create the database

```bash
mysql -u root -p
```
```sql
CREATE DATABASE eleanora_nails
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;
```

(Or just run `mysql -u root -p < backend/schema.sql`.)

### Step 2 — install the dependencies

```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### Step 3 — configure

Copy `.env.example` to `.env` and set your MySQL password and a random
`SECRET_KEY`. The defaults already assume `root` / `kali`, which is what this
machine uses, so you can skip this if that is your setup.

### Step 4 — run

```bash
python app.py
```

Open **http://localhost:5000**.

**The tables are created automatically on first launch, and the database is
seeded with the entire demo world.** There is nothing else to do — log in as the
admin and everything is already populated.

### Step 5 (optional) — the receipt reader

The site can **read payment screenshots automatically** and check they went to
the right eSewa number for the right amount (see §8). That needs the Tesseract
OCR engine, which is a separate program.

**This is entirely optional.** If Tesseract is not installed, the app detects
that at startup, logs one line saying so, and runs exactly as it otherwise
would — the owner simply verifies the screenshots by eye, as she would anyway.
**Nothing crashes and no page breaks.** The site will run on any machine whether
or not you do this step.

To turn it on:

```bash
# Windows
winget install UB-Mannheim.TesseractOCR

# macOS
brew install tesseract

# Debian / Ubuntu
sudo apt install tesseract-ocr
```

If it lands somewhere unusual, point `TESSERACT_CMD` at it in your `.env`.

---

## 5. Demo accounts

| Role | Email | Password |
|---|---|---|
| **Admin** (the salon owner) | `admin@eleanoranails.com` | `Admin@123` |
| **Customer** | `customer@example.com` | `Password@123` |

The demo customer already has appointments against her, so `/appointments` has
something to show the moment you log in.

The other 55 seeded customers all use the password `Password@123` too, with
generated addresses of the form `firstname.lastname{n}@example.com` — you can see
the full list under **Admin → Customers**.

---

## 6. The pages

### Public — no account needed

| Page | Route | What is on it |
|---|---|---|
| **Home** | `/` | Hero with a floating 3D collage and a **Book now** button, live stats that count up, the four services, eight featured designs, a "how it works" strip, real testimonials, and a closing call to action |
| **About** | `/about` | The studio's story, the mission, six reasons to choose it, the full week's opening hours and the location |
| **Services** | `/services` | The four treatments as cards — image, name, description, price, duration, **Book now** — plus an explanation of exactly what moves the price |
| **Gallery** | `/gallery` | All 30 designs. Filter by category (French, Chrome, Ombre, Glitter, Floral, Marble, Luxury, Minimalist) or search by name. Each tile shows the image, the name, the category and a **Select design** button that drops you straight into the wizard with it chosen |
| **Colours** | `/colors` | The palette, with a live preview: pick a layer (base / secondary / accent), tap a swatch, and three preview nails repaint |
| **Reviews** | `/reviews` | The average rating, a breakdown bar per star, and every visible review |
| **Contact** | `/contact` | A contact form, the phone number, the email, the hours, and a Google map |

### Customer — login required

| Page | Route | What it does |
|---|---|---|
| **Book** | `/book` | The nine-step wizard |
| **My appointments** | `/appointments` | Upcoming and past bookings; reschedule, cancel, re-send payment proof, leave a review |
| **Notifications** | `/notifications` | Has my booking been confirmed? Was there a problem with my payment? Where is my refund? |
| **Reschedule** | `/appointments/<id>/reschedule` | Move a booking to another free slot |
| **Profile & security** | `/profile` | Edit name, phone and photo; change password; turn 2FA on or off |

### Admin — owner only

`/admin` · `/admin/analytics` · `/admin/appointments` · `/admin/services` ·
`/admin/designs` · `/admin/colors` · `/admin/promos` · `/admin/schedule` ·
`/admin/users` · `/admin/reviews`

---

## 7. How booking works

The wizard is nine steps on a single page. JavaScript moves between them; the
running summary in the sidebar updates on every choice, and the price recalculates
live.

```
Step 1  Choose a service      Overlay · Gel Extension · Gel-X · Acrylic
   ↓
Step 2  Choose a design       30 designs, filterable; the ones that suit your
   ↓                          service float to the front
Step 3  Choose colours        base (required) + secondary + accent (optional),
   ↓                          with a live three-nail preview
Step 4  Choose a shape        Square · Coffin · Almond · Oval · Stiletto
   ↓                          (each one drawn, not just named)
Step 5  Choose a length       Short · Medium · Long · Extra Long
   ↓                          (longer costs more — shown up front)
Step 6  Choose a date         only dates that can still fit you are offered
   ↓
Step 7  Choose a time         only slots long enough for the whole treatment
   ↓
Step 8  Check it over         the full breakdown, line by line, with the total
   ↓
Step 9  Pay & confirm         promo code, then the MANDATORY Rs.500 advance:
   ↓                          transaction code + receipt, both required
        → status: PENDING     the slot is NOT yet held
```

### How the price is built

```
   service price          e.g. Gel Nail Extension  Rs. 2,500
 + design surcharge       intricate art            Rs.   500
 + length surcharge       Medium +200, Long +400, Extra Long +700
 ─────────────────────────────────────────────────────────────
 = subtotal                                        Rs. 3,200
 − promo discount         e.g. WELCOME10 (10% off) Rs.   320
 ─────────────────────────────────────────────────────────────
 = total                                           Rs. 2,880
      of which  Rs.   500  is the advance, paid now to hold the slot
                Rs. 2,380  is the balance, settled at the studio or by transfer
```

Design surcharges run from Rs. 0 (a simple finish) to Rs. 900 (hand-painted 3D
florals and luxury sets). Every figure is on screen before the customer confirms —
nothing is added at the studio.

### Nothing here is trusted

The wizard's validation exists to make the form pleasant. **Every single field is
re-validated on the server** in `routes/booking.py` — the service, the design, the
colours, the shape, the length, the date, the time, the payment method, the
transaction code, and the screenshot. The slot is re-checked for availability at
the moment of submission, so a form left open for twenty minutes cannot book a
slot that filled up in the meantime.

---

## 8. How payment works

The studio's real eSewa QR (**Mizumi Lamgade · 9847495064**) is shown in the
wizard.

### The Rs. 500 advance is mandatory

**Every booking pays the same Rs. 500 advance up front.** There is no route
through the form that skips it. That advance is what makes a slot worth holding:
without it, a no-show costs the studio a whole afternoon and nothing else.

So on every booking, without exception:

1. Scan the QR and transfer **Rs. 500**.
2. Enter the **transaction code** — this field *cannot be empty*. An empty code,
   or one shorter than 4 characters, is rejected by the server.
3. **Upload a screenshot** of the transfer — also mandatory. It must be a real
   image; a `.php` file renamed to `.png` is rejected, because Pillow actually
   tries to open it.

The only thing the customer *chooses* is how the **balance** is settled:

| Option | Now | Later |
|---|---|---|
| **Balance at the studio** | Rs. 500 advance | the rest in person on the day |
| **Settle it all by transfer** | Rs. 500 advance | the rest by eSewa before the appointment |

The booking is then saved as **pending**, with the payment **not checked yet**.
The owner sees the code and the screenshot side by side and either **verifies**
or **rejects** it. If she rejects it, the customer is notified, sees "Payment
rejected" on their appointments page, and gets a **Re-send proof** button.

### The receipt is read automatically

When the screenshot lands, the server **OCRs it** (Tesseract) and checks three
things:

- does the studio's **eSewa number** (9847495064) appear in the image?
- does the **Rs. 500** amount appear?
- does it say the transfer was **successful**?

The result is shown to the owner right next to the screenshot — either *"Receipt
checks out"* or *"Check this one by eye"* with the specific failures listed. That
turns her verification from squinting at a photo into confirming a verdict.

Two deliberate design decisions here:

**It is advisory, never authoritative.** OCR misreads genuine receipts — a dark
theme, a cropped screenshot, an unusual font. So a failed check *warns* the
customer and *flags* it for the owner; it never rejects the money outright, and
it never approves it either. A human still decides. Hard-blocking would strand
honest customers whose perfectly real receipt happened to scan badly.

**It is optional.** If the Tesseract engine is not installed on the machine — and
it will not be, on most — the whole OCR layer quietly turns itself off and the
site behaves exactly as it did before. Nothing crashes, nothing breaks. See
§4 for how to install it if you want it.

### The same receipt cannot be reused

One transfer buys one slot. Uploading a screenshot that already backs another
live booking is refused — the file is hashed by **content**, so renaming it
changes nothing.

Two exceptions, or the guard would punish honest people: a **cancelled**
booking's receipt is fair game again (that transfer is spent), and a **rejected**
payment's own receipt can be re-sent (the client is usually re-uploading the very
same image with a clearer code, and blocking that would trap them).

### The rule that matters

> **A booking is PENDING until the admin approves it. A pending booking does not
> hold its slot.**

This is deliberate. Two people can both request 14:00 on Thursday. Whichever one
the owner approves first takes the slot; when she tries to approve the second, the
system stops her and tells her the slot has gone. **Money changing hands does not
reserve anything on its own — only the owner's approval does.**

### Cancellation and refunds

| Who cancels | What comes back |
|---|---|
| **The client** | **half** the advance (Rs. 250). The studio keeps the rest — the slot was held for them and other people were turned away from it. |
| **The studio** | the **whole** advance (Rs. 500). The client is not at fault. |

The exact figure is shown in the confirmation *before* they cancel, recorded on
the booking, and pushed to the client as a notification. The owner sees "Rs. 250
owed to this client" on her dashboard until she marks it **sent**, at which point
the client is notified again.

A refund is only owed once the advance has actually been **verified** — you
cannot give back money you never confirmed arriving.

### Promo codes

The owner generates discount codes in the admin (see §10). A customer types one
at checkout and the discount comes off the total.

**The server always recalculates the discount.** Whatever the browser claims a
code is worth is ignored — the code is looked up, its rules are re-checked
(active? expired? used up? minimum spend met?), and the amount is worked out
server-side. A code cannot be forged by editing the page.

---

## 9. How the calendar decides what to show

This is the heart of the system, and it lives in `utils.py`.

A date is offered to a customer **only if** all of these are true:

1. It is not a weekday the studio is closed (Saturday, by default).
2. The owner has not blocked it (a holiday, a family trip, a restocking day).
3. There is at least one start time on that day where the **whole treatment** fits:
   - it must finish before closing time (18:00), so a 135-minute acrylic set
     cannot start at 17:00
   - it must not overlap any **approved** booking
   - if it is today, it must be at least 2 hours from now (prep time)

If no start time survives all of that, **the date does not appear at all**. It is
not greyed out. It is not disabled. It simply is not there — the customer cannot
click a day we cannot serve them on.

Note the word **approved** in point 3. Pending requests are invisible to this
calculation. That is what makes the "nothing is held until the owner says so" rule
actually work.

Two ranges overlap unless one ends before the other starts:

```python
if any(start < b_end and b_start < end for b_start, b_end in taken):
    continue   # this slot collides with a confirmed booking
```

The same engine powers rescheduling, with one change: the booking being moved is
excluded from the collision check, so it cannot conflict with itself.

---

## 10. The admin dashboard

Everything about the business is run from `/admin`. The owner can do all of it —
there is no part of the site she has to ask a developer to change.

### Dashboard
- **Total customers**, **total bookings**, **today's appointments**, **total earned**
- A bar chart of bookings taken over the last fortnight
- **Today's diary** — who is coming, at what time, for what
- **The queue** — every booking waiting for her, with the transaction code and
  the payment screenshot right there to check (click to enlarge)

### Analytics
- Bookings taken and revenue earned, charted over the last 6 calendar months
- **Top services**, ranked by completed revenue (not just booking count) —
  the treatment that gets booked the most isn't always the one that earns
  the most
- **Most-picked designs**, across every booking status
- **Export to CSV** — every appointment or every customer, one click, for
  the owner's own records or an accountant

### Manage appointments
Filter by pending / confirmed / completed / cancelled. On each booking:
- **Approve** — confirms it, holds the slot, verifies the advance, and **notifies
  the client**. If another booking has been approved into that slot in the
  meantime, the system refuses and explains why.
- **Mark completed** — the client has been served; the balance is settled
- **Cancel** — frees the slot, refunds the **whole** advance, notifies the client
- **Verify / Reject payment** — the screenshot, the transaction code and the
  **OCR verdict** are all right there. Rejecting notifies the client and asks
  them to re-send.
- **Mark refunded** — once she has actually sent a cancellation refund back

### Manage promo codes
Generate a discount code (or let the system invent one — no `O`/`0` or `I`/`1`,
because people mistype those). Each code can be:

- **percentage** (e.g. 10% off) or **flat** (e.g. Rs. 500 off)
- **capped**, so a % code cannot take a fortune off an expensive acrylic set
- limited by **minimum spend**
- limited to a **number of uses**
- given an **expiry date**
- **switched off** at any time — it stops working for customers immediately

A code that has already been claimed is switched off rather than deleted, so the
bookings that used it never lose the record of what they paid.

### Manage services
Add a treatment, edit its name, description, price, duration or photo, retire it,
or delete it. The **duration is what the calendar uses to size a slot** — change
a service from 90 to 120 minutes and the booking calendar immediately starts
reserving two hours for it.

A service that already has bookings against it is **retired rather than deleted**,
so historic bookings never lose the treatment they refer to.

### Manage designs
Upload a new photo, retag it, change its category or its surcharge, hide it, or
delete it. Uploads are re-encoded and given a random filename before they touch
the disk.

### Manage colours
Add a colour (with a real colour picker), edit it, deactivate it, delete it.

### Closed days
Close off a date and it disappears from every customer's calendar instantly. If
there are already confirmed bookings on a day she is closing, the page warns her
and shows how many, so she can deal with them.

### Customers
Search by name, email or phone. See how many bookings each has made and whether
they have 2FA switched on. Delete a customer (their bookings, payments and
reviews go with them).

### Reviews
Hide a review from the public site without destroying it, show it again, or
delete it outright.

---

## 11. Two-factor authentication

Standard **TOTP** — the same thing your bank uses.

**Turning it on** (`/profile` → Set up two-factor):
1. The server generates a random base32 secret.
2. It is rendered as a QR code (as a `data:` URI, so no image ever hits the disk)
   and shown alongside the raw key for anyone who cannot scan.
3. The user scans it with Google Authenticator, Authy, or any TOTP app.
4. **They must type a live code to prove the app is really set up.** Only then is
   2FA switched on. This prevents someone locking themselves out by scanning a QR
   that did not take.

**Logging in with it on:**
1. Email and password are checked as normal.
2. If they are right, the user is **not logged in**. Only a *pending* user id is
   put in the session.
3. They are asked for the 6-digit code.
4. Only when the code verifies does `login_user()` actually run.

**Why it cannot be brute-forced:** a 6-digit code has a million possibilities, and
an attacker who knows the password gets **five tries** before the account locks for
15 minutes. Guessing is not a viable strategy.

**Turning it off** requires the current password.

---

## 12. Security architecture

| Threat | How it is handled |
|---|---|
| **SQL injection** | Every query goes through SQLAlchemy's ORM, which parameterises by construction. There is not one line of hand-built SQL anywhere in the codebase. A payload like `' OR 1=1--` typed into the gallery search is treated as a literal string to search for — and finds nothing. |
| **XSS (cross-site scripting)** | Jinja2 auto-escaping is on everywhere. `<script>alert(1)</script>` typed into any field is rendered as text, not executed. The one place JavaScript inserts user data into the DOM (the wizard's toast), it uses `textContent`, never `innerHTML`. |
| **CSP (content security policy)** | `script-src 'self'` — scripts may load **only** from our own origin, and **there is no inline JavaScript anywhere in the project**. Even if an attacker found an injection point, the browser would refuse to execute what they injected. This is the single strongest defence against XSS, and it is why `theme-init.js` is a separate file rather than an inline `<script>`. |
| **CSRF** | Flask-WTF's `CSRFProtect` puts a token on every form and validates it on every POST. A POST without a valid token is rejected with a 400 before it reaches any route. |
| **Broken access control / IDOR** | Every customer route that touches a booking runs it through `_own_appointment()`, which aborts with 403 if the booking belongs to someone else. Guessing `/appointments/1/cancel` gets you a 403, not someone else's cancelled appointment. Every admin route is behind `@admin_required`. |
| **Brute force** | Two independent layers: a **per-account lockout** (5 failed password *or* TOTP attempts → locked for 15 minutes, and the lock applies even to the correct password) and a **per-IP rate limit** (Flask-Limiter on login, register, booking, contact and payment endpoints). |
| **Malicious file upload** | Four layers: an extension whitelist; a 5 MB hard cap enforced by Flask itself; **Pillow re-encodes every image**, which destroys any payload smuggled inside it and means a `.php` file renamed to `.png` fails to open and is rejected; and the saved file gets a **random 32-character name**, so the original filename — the vector for a path-traversal attack — is discarded entirely. |
| **Path traversal** | A filename like `../../../../etc/passwd` never survives: `secure_filename()` strips it, and then the name is thrown away and replaced with `secrets.token_hex(16)` anyway. Uploads can only ever land in the uploads folder, under a name we chose. |
| **SSRF** | The server never fetches a URL supplied by a user. Payment proof is an *uploaded file*, not a link. There is no image-by-URL feature, no webhook, no callback. The SSRF surface is zero by design. |
| **Clickjacking** | `X-Frame-Options: DENY` and `frame-ancestors 'none'`. The site cannot be embedded in an attacker's iframe. |
| **MIME sniffing** | `X-Content-Type-Options: nosniff`. |
| **Session theft** | Cookies are `HttpOnly` (JavaScript cannot read them, so an XSS cannot steal them), `SameSite=Lax`, and `Secure` when served over HTTPS. HSTS is advertised on HTTPS. |
| **Password storage** | Salted hashes via Werkzeug. The raw password is never written anywhere — not to the database, not to a log. |
| **User enumeration** | A wrong email and a wrong password produce the **identical** error message. The login form cannot be used to discover who has an account. |
| **Open redirect** | The `next` parameter after login is validated to be a local path (`/...`, and not `//evil.com`) before it is honoured. |
| **DoS** | Rate limits on every expensive or abusable endpoint, a 5 MB body cap, and Pillow downscaling large images rather than holding them at full size. |
| **Information disclosure** | Custom 403 / 404 / 413 / 429 / 500 pages. No stack trace, no framework version, no database error ever reaches the user. |

### Response headers on every single response

```
Content-Security-Policy: default-src 'self'; script-src 'self'; ...
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: geolocation=(), microphone=(), camera=()
Strict-Transport-Security: max-age=31536000   (HTTPS only)
```

---

## 13. The database

Eight tables.

### `users`
`id · full_name · email · password_hash · phone · avatar · role · totp_secret ·
totp_enabled · failed_attempts · locked_until · created_at`

`role` is `customer` or `admin`. **The first account ever registered becomes the
admin.**

### `services`
`id · service_name · description · price · duration · image · is_upload ·
is_active · sort_order`

`duration` (in minutes) is what the availability engine uses to size a slot.

### `designs`
`id · design_name · category · image · is_upload · service_id · extra_price ·
is_active · created_at`

`is_upload` says which folder the image lives in: the 30 seeded photos are in
`/static/designs`, anything the admin uploads goes to `/static/uploads`.

### `colors`
`id · color_name · hex_code · is_active`

### `appointments`
`id · user_id · service_id · design_id · color_id · secondary_color_id ·
accent_color_id · nail_shape · nail_length · booking_date · booking_time ·
duration · total_price · promo_id · discount · notes · status · admin_note ·
created_at`

`duration`, `total_price` and `discount` are **frozen at booking time**, so that
when the owner later raises a price or edits a promo code, existing bookings are
not silently repriced.

`status` is one of `pending` → `approved` → `completed`, or `cancelled`.

### `payments`
`id · appointment_id · method · amount · balance · transaction_code · screenshot ·
status · verified_at · ocr_checked · ocr_number_ok · ocr_amount_ok ·
ocr_success_ok · ocr_note · refund_due · refund_paid · created_at`

`method` is `advance` (balance at the studio) or `full` (balance by transfer).
Either way `amount` is the **Rs. 500 advance** — the only thing that changes is
how `balance` gets settled.

`status` is `pending` → `verified` / `rejected`, then `settled` once the balance
is paid too.

The `ocr_*` columns record what the automated read made of the screenshot, and
`refund_due` / `refund_paid` track money owed back after a cancellation.

### `promo_codes`
`id · code · description · kind · value · max_discount · min_spend · usage_limit ·
used_count · expires_on · is_active · created_at`

`kind` is `percent` (value is 0–100) or `flat` (value is rupees).

### `notifications`
`id · user_id · appointment_id · kind · title · body · is_read · created_at`

`kind` is one of `approved`, `rejected`, `cancelled`, `completed`, `refund`,
`promo`, `reminder`. This table is the answer to the only question a waiting
customer actually has: *has my booking been confirmed?*

### `reviews`
`id · user_id · appointment_id · rating · comment · is_visible · created_at`

A review is tied to the appointment it is about, so the site can show *"Gel-X ·
March 2026"* under each one. `is_visible` lets the owner hide a review without
destroying it.

### `blocked_dates`
`id · date · reason`

A single date the studio will not open.

---

## 14. Design & motion

The whole palette is lifted straight from the logo: **rose-gold on deep charcoal**,
warm ivory paper, one accent metal.

```css
--rose:  #b76e79      /* the metal in the logo */
--gold:  #c8a07a
--metal: linear-gradient(120deg, #b76e79, #e2c2a3, #c8a07a, #b76e79)
```

- **Typography** — Cormorant Garamond (the elegant serif), Jost (the clean sans),
  and Italianno (the script that echoes *"nails that speak elegance"* on the logo)
- **Dark and light mode** — a full second palette, remembered per device, applied
  *before the first paint* by `theme-init.js` so the page never flashes the wrong
  colours
- **A brand preloader** — the logo, a sweeping progress bar and the tagline, with a
  hard 2.6-second safety timeout so a slow image can never strand a visitor
- **3D depth** — cards tilt toward the cursor; the hero collage floats and
  parallaxes; the nail-shape icons are drawn with `clip-path` and lit with a
  gloss highlight
- **Real SVG icons throughout** — a set of 25 hand-written icon macros in
  `partials/icons.html`. There is not a single emoji anywhere in the interface.
- **Fully responsive** — the whole thing collapses gracefully to a phone
- **`prefers-reduced-motion`** — every animation is disabled for users who ask

---

## 15. The seed data

`seed.py` fills an empty database on first launch, so the site is a **working
demo from the moment you open it**. Nothing has to be clicked into existence.

| What | How much |
|---|---|
| Admin account | 1 (Mizumi Lamgade) |
| Customers | 55, with realistic Nepali names and phone numbers |
| Services | 4 — Overlay, Gel Nail Extension, Gel-X, Acrylic |
| Designs | **All 30 of the studio's real photos**, each given a name and a category by actually looking at the image |
| Colours | 10 |
| Appointments | ~90 — most in the past (completed, a few cancelled), a dozen confirmed and coming up, and several pending and waiting on the admin |
| Reviews | 42, skewed positive the way a real salon's ratings are |
| **Promo codes** | 4 — `WELCOME10`, `GLOWUP500`, `DASHAIN25`, `BESTIE15` |
| **Notifications** | ~85, so nobody's bell is an empty room |

Every appointment carries its Rs. 500 advance, with payments in every state —
verified, rejected, pending, settled — and cancelled bookings already showing the
Rs. 250 refund they are owed. That means the dashboard has a populated bar chart,
the homepage has real testimonials and statistics, the reviews page has a real
distribution, the admin queue has bookings genuinely waiting to be approved, and
the demo customer's bell has something unread in it.

Seeding is **idempotent**: it checks for an existing service and bails out
immediately if it finds one, so restarting the server never duplicates anything.

---

## 16. Testing

The system was driven end to end over real HTTP against the running server —
**132 checks across three suites, all passing**. Each suite runs against a fresh
database, so nothing one test leaves behind can make another one pass or fail by
accident.

### The new features

**The advance is mandatory** — a booking with no receipt is refused, and a booking
with an empty transaction code is refused, *whichever* way the client says they
will settle the balance. There is no path through the form that skips it.

**The receipt is really read** — a realistic fake eSewa receipt was generated and
fed to the OCR. It correctly **passes** the genuine one (right number, right
amount, "Payment Successful"), and correctly **flags** both a receipt sent to
somebody else's number for the wrong amount, and an image that is not a receipt at
all. Zero mistakes. The customer is warned when it cannot be confirmed, the admin
sees *"Check this one by eye"* with the exact failures, and the booking still goes
through — because OCR is a hint, not a judge.

**The same receipt cannot be reused** — the second booking to upload identical
bytes is refused.

**Refunds** — cancelling a confirmed booking promises exactly **Rs. 250 of the
Rs. 500** back and says the other half is retained; the client is notified; the
admin sees the refund is owed and can mark it sent; the client is notified again.
A booking whose advance was never verified is owed nothing — you cannot refund
money you never confirmed arriving.

**Notifications** — approving a booking notifies the client it is confirmed;
rejecting a payment notifies them there is a problem and offers a re-send button.

**Promo codes** — `WELCOME10` takes exactly 10% off; `DASHAIN25` is correctly
**capped** at Rs. 1,000 on a large booking; a code below its minimum spend is
refused; an invented code is refused; codes are case-insensitive; a code the admin
switches off stops working for customers immediately.

**Approval holds the slot** — two people *can* both request the same slot while
pending (nothing is held), and the moment one is approved the slot vanishes from
everyone else's calendar.

### The original suites

**Public pages** — all 9 render; the gallery filters and searches; a SQL-injection
payload in the search box is handled safely; an XSS payload is escaped.

**Access control** — anonymous visitors are bounced from `/book`, `/appointments`,
`/profile`, `/admin` and the availability API; a logged-in *customer* gets a 403
from every admin route; cancelling another user's appointment gets a 403.

**Registration and login** — a new account can be created and logged into.

**Two-factor** — the QR and secret are issued; a wrong code is refused at setup; the
real code enables it; login then *demands* the code; a wrong code is refused; the
real code logs in; disabling requires the correct password.

**Lockout** — repeated wrong passwords lock the account, and the lock refuses even
the correct password afterwards.

**Payment validation** — a pre-paid booking with an **empty transaction code is
rejected**; one with **no screenshot is rejected**; a **`.php` file disguised as a
`.png` is rejected**.

**The booking flow** — a valid pre-pay booking is accepted, lands as **pending**,
and shows its payment as "being checked". A post-pay booking is accepted with no
upload at all.

**Approval and slot-holding** — the pending booking appears in the admin queue; the
admin approves it; the customer immediately sees it as *Confirmed* with the payment
*Verified*; and **the slot it occupies is no longer offered to anyone else**.

**Admin CRUD** — colours, services and designs can each be added, edited and
deleted; a date can be closed, and **it immediately disappears from the customer's
booking calendar**; reviews can be hidden and shown again; payments can be verified
and rejected.

**Security headers** — CSP with no `unsafe-inline`, `X-Frame-Options: DENY`,
`nosniff`, and a referrer policy are present on every response. A POST with no CSRF
token is rejected with a 400.

---

## 17. Configuration reference

Everything lives in `backend/config.py`, and anything can be overridden with an
environment variable (see `.env.example`).

```python
# --- database ---
DB_USER          = "root"
DB_PASSWORD      = "kali"
DB_NAME          = "eleanora_nails"

# --- the studio ---
SALON_NAME       = "Eleanora Nails"
SALON_TAGLINE    = "Nails that speak elegance"
SALON_PHONE      = "+977 9847495064"
SALON_EMAIL      = "mizumilamgade@gmail.com"
SALON_AREA       = "Ghattekulo, Dillibazar"
SALON_ADDRESS    = "Home Studio · Ghattekulo, Dillibazar, Kathmandu, Nepal"
SALON_ESEWA      = "9847495064"
SALON_ESEWA_NAME = "Mizumi Lamgade"

# --- the booking window ---
OPEN_HOUR         = 10        # first appointment starts at 10:00
CLOSE_HOUR        = 18        # last appointment must END by 18:00
SLOT_MINUTES      = 30        # slots are offered on the half hour
BOOKING_DAYS_AHEAD = 45       # how far ahead customers may book
CLOSED_WEEKDAYS   = {5}       # Saturday (Mon=0 … Sun=6)

# --- money ---
DEPOSIT_AMOUNT    = 500       # the advance EVERY booking must transfer up front
REFUND_PERCENT    = 50        # how much of it comes back if the client cancels

# --- uploads ---
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
MAX_CONTENT_LENGTH = 5 * 1024 * 1024

# --- the receipt reader (optional; the app runs fine without it) ---
TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# --- rate limiting ---
# ON by default, and it should stay on in production: it is what stops password
# guessing and booking-spam from one machine. The test suite sets
# RATELIMIT_ENABLED=0 to get out of its own way.
RATELIMIT_ENABLED = True
```

Change `CLOSE_HOUR` to 20 and the calendar starts offering evening slots the very
next request. Change `CLOSED_WEEKDAYS` to `{4, 5}` and Fridays close too. Nothing
else needs touching — the availability engine reads these values every time it
runs.

---

## Credits

**Designed & developed by Mizumi Lamgade.**

Built on the same Flask · MySQL · Jinja2 · HTML/CSS/JS foundation as Bloggr, with
the same commitment to getting the security right rather than getting it shipped.
