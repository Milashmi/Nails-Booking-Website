-- ---------------------------------------------------------------------------
-- Eleanora Nails — database setup
--
-- You do NOT need to run this by hand. `python app.py` creates every table on
-- first launch (SQLAlchemy's create_all) and then seeds the demo data.
--
-- This file exists for two reasons:
--   1. to create the empty database itself, which the app cannot do for you
--   2. to document the schema in plain SQL, for anyone reading the design
--
-- To use it:  mysql -u root -p < schema.sql
-- ---------------------------------------------------------------------------

CREATE DATABASE IF NOT EXISTS eleanora_nails
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE eleanora_nails;

-- ---------------------------------------------------------------- users
CREATE TABLE IF NOT EXISTS users (
  id              INT AUTO_INCREMENT PRIMARY KEY,
  full_name       VARCHAR(80)  NOT NULL,
  email           VARCHAR(120) NOT NULL UNIQUE,
  password_hash   VARCHAR(255) NOT NULL,      -- salted hash, never the password
  phone           VARCHAR(20)  DEFAULT '',
  avatar          VARCHAR(255) DEFAULT '',
  role            VARCHAR(20)  NOT NULL DEFAULT 'customer',   -- customer | admin

  -- TOTP two-factor authentication
  totp_secret     VARCHAR(32)  DEFAULT '',
  totp_enabled    BOOLEAN      DEFAULT FALSE,

  -- brute-force lockout
  failed_attempts INT          DEFAULT 0,
  locked_until    DATETIME     NULL,

  created_at      DATETIME     DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_users_email (email),
  INDEX idx_users_role  (role)
) ENGINE=InnoDB;

-- ------------------------------------------------------------- services
CREATE TABLE IF NOT EXISTS services (
  id           INT AUTO_INCREMENT PRIMARY KEY,
  service_name VARCHAR(80)  NOT NULL,
  description  VARCHAR(400) DEFAULT '',
  price        INT          NOT NULL,     -- rupees
  duration     INT          NOT NULL,     -- minutes; sizes the booking slot
  image        VARCHAR(255) DEFAULT '',
  is_upload    BOOLEAN      DEFAULT FALSE,
  is_active    BOOLEAN      DEFAULT TRUE,
  sort_order   INT          DEFAULT 0,
  INDEX idx_services_active (is_active)
) ENGINE=InnoDB;

-- -------------------------------------------------------------- designs
CREATE TABLE IF NOT EXISTS designs (
  id          INT AUTO_INCREMENT PRIMARY KEY,
  design_name VARCHAR(120) NOT NULL,
  category    VARCHAR(40)  DEFAULT 'Minimalist',
  image       VARCHAR(255) NOT NULL,
  is_upload   BOOLEAN      DEFAULT FALSE,   -- /uploads if true, else /designs
  service_id  INT          NULL,
  extra_price INT          DEFAULT 0,       -- surcharge for intricate art
  is_active   BOOLEAN      DEFAULT TRUE,
  created_at  DATETIME     DEFAULT CURRENT_TIMESTAMP,

  FOREIGN KEY (service_id) REFERENCES services(id) ON DELETE SET NULL,
  INDEX idx_designs_category (category),
  INDEX idx_designs_active   (is_active)
) ENGINE=InnoDB;

-- --------------------------------------------------------------- colors
CREATE TABLE IF NOT EXISTS colors (
  id         INT AUTO_INCREMENT PRIMARY KEY,
  color_name VARCHAR(40) NOT NULL,
  hex_code   VARCHAR(7)  NOT NULL,       -- e.g. #b76e79
  is_active  BOOLEAN     DEFAULT TRUE,
  INDEX idx_colors_active (is_active)
) ENGINE=InnoDB;

-- -------------------------------------------------------- blocked_dates
-- A day the owner has closed the studio (holiday, leave, restocking).
CREATE TABLE IF NOT EXISTS blocked_dates (
  id     INT AUTO_INCREMENT PRIMARY KEY,
  date   DATE         NOT NULL UNIQUE,
  reason VARCHAR(120) DEFAULT '',
  INDEX idx_blocked_date (date)
) ENGINE=InnoDB;

-- ----------------------------------------------------------- promo_codes
-- Declared BEFORE appointments, which carries a foreign key into it.
CREATE TABLE IF NOT EXISTS promo_codes (
  id           INT AUTO_INCREMENT PRIMARY KEY,
  code         VARCHAR(24)  NOT NULL UNIQUE,
  description  VARCHAR(140) DEFAULT '',

  kind         VARCHAR(10)  NOT NULL DEFAULT 'percent',  -- percent | flat
  value        INT          NOT NULL,   -- 0-100 for percent, rupees for flat

  max_discount INT DEFAULT 0,   -- cap a % code so it cannot take a fortune off
  min_spend    INT DEFAULT 0,   -- 0 = usable on any amount
  usage_limit  INT DEFAULT 0,   -- 0 = unlimited
  used_count   INT DEFAULT 0,

  expires_on   DATE     NULL,          -- NULL = never expires
  is_active    BOOLEAN  DEFAULT TRUE,
  created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,

  INDEX idx_promo_code   (code),
  INDEX idx_promo_active (is_active)
) ENGINE=InnoDB;

-- --------------------------------------------------------- appointments
CREATE TABLE IF NOT EXISTS appointments (
  id                 INT AUTO_INCREMENT PRIMARY KEY,
  user_id            INT NOT NULL,
  service_id         INT NOT NULL,
  design_id          INT NULL,

  -- the three colour layers
  color_id           INT NULL,           -- base
  secondary_color_id INT NULL,
  accent_color_id    INT NULL,

  nail_shape   VARCHAR(20) NOT NULL,     -- Square|Coffin|Almond|Oval|Stiletto
  nail_length  VARCHAR(20) NOT NULL,     -- Short|Medium|Long|Extra Long

  booking_date DATE NOT NULL,
  booking_time TIME NOT NULL,

  -- copied from the service at booking time, so a later price change does not
  -- silently reprice a booking that has already been made
  duration     INT NOT NULL DEFAULT 90,
  total_price  INT NOT NULL,

  -- The promo code used, and what it took off. The discount is stored on the
  -- booking so that editing (or deleting) the code later cannot silently
  -- reprice a booking that has already been made.
  promo_id    INT NULL,
  discount    INT DEFAULT 0,

  notes       VARCHAR(500) DEFAULT '',
  -- pending -> approved -> completed, or cancelled
  -- NOTE: only an approved (or completed) booking actually HOLDS its slot
  status      VARCHAR(20)  NOT NULL DEFAULT 'pending',
  admin_note  VARCHAR(300) DEFAULT '',
  created_at  DATETIME     DEFAULT CURRENT_TIMESTAMP,

  FOREIGN KEY (promo_id)           REFERENCES promo_codes(id) ON DELETE SET NULL,
  FOREIGN KEY (user_id)            REFERENCES users(id),
  FOREIGN KEY (service_id)         REFERENCES services(id),
  FOREIGN KEY (design_id)          REFERENCES designs(id) ON DELETE SET NULL,
  FOREIGN KEY (color_id)           REFERENCES colors(id)  ON DELETE SET NULL,
  FOREIGN KEY (secondary_color_id) REFERENCES colors(id)  ON DELETE SET NULL,
  FOREIGN KEY (accent_color_id)    REFERENCES colors(id)  ON DELETE SET NULL,

  INDEX idx_appt_user   (user_id),
  INDEX idx_appt_date   (booking_date),
  INDEX idx_appt_status (status)
) ENGINE=InnoDB;

-- -------------------------------------------------------------- payments
-- EVERY booking pays the same Rs. 500 advance up front — it is what makes the
-- slot worth holding. The only choice is how the BALANCE is settled.
CREATE TABLE IF NOT EXISTS payments (
  id               INT AUTO_INCREMENT PRIMARY KEY,
  appointment_id   INT NOT NULL UNIQUE,

  method  VARCHAR(20) NOT NULL,      -- advance (rest at studio) | full (all online)
  amount  INT NOT NULL DEFAULT 0,    -- what they actually transferred (the advance)
  balance INT DEFAULT 0,             -- what is left to settle

  -- Both are ALWAYS required: the route refuses an empty transaction code, and
  -- refuses a booking with no screenshot.
  transaction_code VARCHAR(60)  DEFAULT '',
  screenshot       VARCHAR(255) DEFAULT '',   -- filename in /static/uploads

  -- pending -> verified | rejected;  'settled' once the balance is paid too
  status      VARCHAR(20) NOT NULL DEFAULT 'pending',
  verified_at DATETIME    NULL,

  -- What the OCR made of the screenshot. Advisory only: it speeds up the
  -- owner's check, it never approves or rejects money on its own.
  ocr_checked    BOOLEAN DEFAULT FALSE,
  ocr_number_ok  BOOLEAN DEFAULT FALSE,   -- the studio's eSewa number appears?
  ocr_amount_ok  BOOLEAN DEFAULT FALSE,   -- the right amount appears?
  ocr_success_ok BOOLEAN DEFAULT FALSE,   -- it says the transfer succeeded?
  ocr_note       VARCHAR(200) DEFAULT '',

  -- Cancel and half the advance comes back; the studio keeps the other half,
  -- because the slot was held and other clients were turned away from it.
  refund_due  INT     DEFAULT 0,
  refund_paid BOOLEAN DEFAULT FALSE,

  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

  FOREIGN KEY (appointment_id) REFERENCES appointments(id) ON DELETE CASCADE,
  INDEX idx_pay_status (status)
) ENGINE=InnoDB;

-- --------------------------------------------------------- notifications
-- What the client is told: above all, whether their booking was confirmed.
CREATE TABLE IF NOT EXISTS notifications (
  id             INT AUTO_INCREMENT PRIMARY KEY,
  user_id        INT NOT NULL,
  appointment_id INT NULL,

  -- approved | rejected | cancelled | completed | reminder | refund | promo
  kind    VARCHAR(20)  NOT NULL,
  title   VARCHAR(120) NOT NULL,
  body    VARCHAR(400) DEFAULT '',

  is_read    BOOLEAN  DEFAULT FALSE,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

  FOREIGN KEY (user_id)        REFERENCES users(id)        ON DELETE CASCADE,
  FOREIGN KEY (appointment_id) REFERENCES appointments(id) ON DELETE CASCADE,
  INDEX idx_notif_user    (user_id),
  INDEX idx_notif_read    (is_read),
  INDEX idx_notif_created (created_at)
) ENGINE=InnoDB;

-- --------------------------------------------------------------- reviews
CREATE TABLE IF NOT EXISTS reviews (
  id             INT AUTO_INCREMENT PRIMARY KEY,
  user_id        INT NOT NULL,
  appointment_id INT NULL UNIQUE,          -- one review per appointment

  rating     INT          NOT NULL,        -- 1..5
  comment    VARCHAR(600) DEFAULT '',
  is_visible BOOLEAN      DEFAULT TRUE,    -- the owner can hide, not just delete
  created_at DATETIME     DEFAULT CURRENT_TIMESTAMP,

  FOREIGN KEY (user_id)        REFERENCES users(id)        ON DELETE CASCADE,
  FOREIGN KEY (appointment_id) REFERENCES appointments(id) ON DELETE CASCADE,
  INDEX idx_rev_user    (user_id),
  INDEX idx_rev_visible (is_visible),
  INDEX idx_rev_created (created_at)
) ENGINE=InnoDB;
