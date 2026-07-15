/* =========================================================================
   Eleanora Nails — the booking wizard
   Nine steps on one page. This file moves between them, keeps the running
   summary in sync, asks the server which dates and times are actually free,
   and refuses to let a step be left half-finished.

   The server re-validates all of it in routes/booking.py — nothing here is a
   security control, it is only there to make the form pleasant.
   ========================================================================= */
(function () {
  "use strict";

  const form = document.getElementById("booking-form");
  if (!form) return;   // not on the booking page

  const TOTAL_STEPS = 9;
  let step = 1;

  const state = {
    service: null,      // { id, name, price, duration }
    design: null,       // { id, name, category, extra }
    colors: { base: null, secondary: null, accent: null },
    shape: null,
    length: null,
    date: null,         // "2026-07-18"
    time: null,         // "14:30"
    payment: null,      // "advance" | "full"
    promo: null,        // { code, discount } — the SERVER decides the amount
  };

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  /* ---------------- moving between steps ---------------- */

  const steps = $$(".step");
  const dots = $$(".step-dot");
  const backBtn = $("#wizard-back");
  const nextBtn = $("#wizard-next");
  const submitBtn = $("#wizard-submit");

  function show(n) {
    step = Math.min(Math.max(n, 1), TOTAL_STEPS);

    steps.forEach((el) => {
      el.classList.toggle("active", Number(el.dataset.step) === step);
    });

    dots.forEach((dot, i) => {
      dot.classList.toggle("done", i + 1 < step);
      dot.classList.toggle("current", i + 1 === step);
    });

    backBtn.classList.toggle("hidden", step === 1);
    nextBtn.classList.toggle("hidden", step === TOTAL_STEPS);
    submitBtn.classList.toggle("hidden", step !== TOTAL_STEPS);

    // The wizard is tall; put the current step back at the top of the screen.
    const top = form.getBoundingClientRect().top + window.scrollY - 100;
    window.scrollTo({ top, behavior: "smooth" });
  }

  /* What must be answered before a step can be left. */
  function validate(n) {
    switch (n) {
      case 1: return state.service ? null : "Please choose a service.";
      case 2: return state.design ? null : "Please choose a design.";
      case 3: return state.colors.base ? null : "Please choose at least a base colour.";
      case 4: return state.shape ? null : "Please choose a nail shape.";
      case 5: return state.length ? null : "Please choose a nail length.";
      case 6: return state.date ? null : "Please choose a date.";
      case 7: return state.time ? null : "Please choose a time.";
      case 8: return null;                    // the summary is read-only
      case 9: return state.payment
        ? null : "Please choose how you'd like to settle the balance.";
      default: return null;
    }
  }

  function toast(message) {
    const stack = document.getElementById("flash-stack");
    if (!stack) return;

    const el = document.createElement("div");
    el.className = "flash flash-error";
    el.innerHTML = '<span></span><button class="flash-close">&times;</button>';
    el.querySelector("span").textContent = message;   // textContent = no XSS
    el.querySelector("button").addEventListener("click", () => el.remove());

    stack.appendChild(el);
    setTimeout(() => el.remove(), 4000);
  }

  nextBtn.addEventListener("click", () => {
    const problem = validate(step);
    if (problem) return toast(problem);

    // Stepping onto the date step re-asks the server which days are open,
    // because the answer depends on the service the client just picked.
    if (step === 5) loadDates();
    show(step + 1);
    if (step === 8) renderSummaryStep();
  });

  backBtn.addEventListener("click", () => show(step - 1));

  /* ---------------- step 1: service ---------------- */

  $$("[data-service]").forEach((card) => {
    card.addEventListener("click", () => {
      $$("[data-service]").forEach((c) => c.classList.remove("selected"));
      card.classList.add("selected");

      state.service = {
        id: Number(card.dataset.service),
        name: card.dataset.name,
        price: Number(card.dataset.price),
        duration: Number(card.dataset.duration),
      };

      // Changing the service invalidates the slot that was picked for the old
      // one (a longer treatment may no longer fit where the old one did).
      state.date = null;
      state.time = null;

      filterDesignsByService();
      refreshSummary();
    });
  });

  /* ---------------- step 2: design ---------------- */

  const designTiles = $$("[data-design]");

  function filterDesignsByService() {
    // Designs are only *suggested* per service — all of them stay pickable, we
    // simply float the matching ones to the front of the grid.
    if (!state.service) return;
    const grid = $("#design-grid");
    if (!grid) return;

    const match = [];
    const rest = [];
    designTiles.forEach((tile) => {
      (Number(tile.dataset.serviceId) === state.service.id ? match : rest).push(tile);
    });
    match.concat(rest).forEach((tile) => grid.appendChild(tile));
  }

  designTiles.forEach((tile) => {
    tile.addEventListener("click", () => {
      designTiles.forEach((t) => t.classList.remove("selected"));
      tile.classList.add("selected");

      state.design = {
        id: Number(tile.dataset.design),
        name: tile.dataset.name,
        category: tile.dataset.category,
        extra: Number(tile.dataset.extra || 0),
        image: tile.dataset.image,
      };
      refreshSummary();
    });
  });

  // The design step has its own little category filter.
  $$("[data-design-filter]").forEach((chip) => {
    chip.addEventListener("click", () => {
      $$("[data-design-filter]").forEach((c) => c.classList.remove("active"));
      chip.classList.add("active");

      const want = chip.dataset.designFilter;
      designTiles.forEach((tile) => {
        const show = want === "All" || tile.dataset.category === want;
        tile.classList.toggle("hidden", !show);
      });
    });
  });

  /* ---------------- step 3: colours ---------------- */

  $$("[data-color]").forEach((dot) => {
    dot.addEventListener("click", () => {
      const layer = dot.dataset.layer;        // base | secondary | accent
      const id = Number(dot.dataset.color);
      const same = state.colors[layer] && state.colors[layer].id === id;

      $$(`[data-layer="${layer}"]`).forEach((d) => d.classList.remove("selected"));

      if (same) {
        // Clicking the chosen colour again clears it (the two extra layers
        // are optional, so this is how you say "none").
        state.colors[layer] = null;
      } else {
        dot.classList.add("selected");
        state.colors[layer] = {
          id: id,
          name: dot.dataset.name,
          hex: dot.dataset.hex,
        };
      }
      paintPreview();
      refreshSummary();
    });
  });

  function paintPreview() {
    const { base, secondary, accent } = state.colors;
    const fallback = getComputedStyle(document.documentElement)
      .getPropertyValue("--surface-3");

    const nails = [
      [$("#nail-base"), base],
      [$("#nail-secondary"), secondary || base],
      [$("#nail-accent"), accent || base],
    ];
    nails.forEach(([el, color]) => {
      if (el) el.style.background = color ? color.hex : fallback;
    });
  }

  /* ---------------- steps 4 & 5: shape and length ---------------- */

  $$("[data-shape]").forEach((opt) => {
    opt.addEventListener("click", () => {
      $$("[data-shape]").forEach((o) => o.classList.remove("selected"));
      opt.classList.add("selected");
      state.shape = opt.dataset.shape;
      refreshSummary();
    });
  });

  $$("[data-length]").forEach((opt) => {
    opt.addEventListener("click", () => {
      $$("[data-length]").forEach((o) => o.classList.remove("selected"));
      opt.classList.add("selected");
      state.length = opt.dataset.length;
      refreshSummary();
    });
  });

  /* ---------------- step 6: date ----------------
     The server hands back only the dates that still have room for a treatment
     this long. A day that is full, closed or blocked never appears at all. */

  const dateGrid = $("#date-grid");

  async function loadDates() {
    if (!state.service || !dateGrid) return;

    dateGrid.innerHTML =
      '<div class="loading"><span class="spinner"></span>Finding free dates…</div>';

    try {
      const res = await fetch(`/api/availability?service=${state.service.id}`);
      const data = await res.json();
      renderDates(data.dates || []);
    } catch (err) {
      dateGrid.innerHTML =
        '<p class="muted">Could not load the calendar. Please refresh.</p>';
    }
  }

  function renderDates(dates) {
    dateGrid.innerHTML = "";

    if (!dates.length) {
      dateGrid.innerHTML =
        '<p class="muted">We are fully booked for the next few weeks. ' +
        'Please call us and we will fit you in.</p>';
      return;
    }

    dates.forEach((iso) => {
      const day = new Date(iso + "T00:00:00");

      const cell = document.createElement("button");
      cell.type = "button";
      cell.className = "date-cell";
      cell.dataset.date = iso;
      cell.innerHTML =
        `<div class="dow">${day.toLocaleDateString("en-GB", { weekday: "short" })}</div>` +
        `<div class="dnum">${day.getDate()}</div>` +
        `<div class="dmon">${day.toLocaleDateString("en-GB", { month: "short" })}</div>`;

      cell.addEventListener("click", () => {
        dateGrid.querySelectorAll(".date-cell")
          .forEach((c) => c.classList.remove("selected"));
        cell.classList.add("selected");

        state.date = iso;
        state.time = null;      // the old time belongs to the old date
        loadTimes(iso);
        refreshSummary();
      });

      dateGrid.appendChild(cell);
    });
  }

  /* ---------------- step 7: time ---------------- */

  const timeGrid = $("#time-grid");

  async function loadTimes(iso) {
    if (!timeGrid) return;

    timeGrid.innerHTML =
      '<div class="loading"><span class="spinner"></span>Checking that day…</div>';

    try {
      const res = await fetch(
        `/api/availability?service=${state.service.id}&date=${iso}`);
      const data = await res.json();
      renderTimes(data.slots || []);
    } catch (err) {
      timeGrid.innerHTML = '<p class="muted">Could not load the times.</p>';
    }
  }

  function renderTimes(slots) {
    timeGrid.innerHTML = "";

    if (!slots.length) {
      timeGrid.innerHTML =
        '<p class="muted">That day just filled up. Please choose another date.</p>';
      return;
    }

    slots.forEach((slot) => {
      const cell = document.createElement("button");
      cell.type = "button";
      cell.className = "time-cell";
      cell.textContent = slot.label;

      cell.addEventListener("click", () => {
        timeGrid.querySelectorAll(".time-cell")
          .forEach((c) => c.classList.remove("selected"));
        cell.classList.add("selected");

        state.time = slot.value;
        state.timeLabel = slot.label;
        refreshSummary();
      });

      timeGrid.appendChild(cell);
    });
  }

  /* ---------------- steps 8 & 9: summary and payment ---------------- */

  const deposit = Number($("#deposit-amount")?.value || 500);

  function money(n) {
    return "Rs. " + Number(n || 0).toLocaleString("en-US");
  }

  /* What the set costs BEFORE any discount. */
  function subtotal() {
    const service = state.service ? state.service.price : 0;
    const design = state.design ? state.design.extra : 0;
    const lengthOpt = $(`[data-length="${state.length}"]`);
    const length = lengthOpt ? Number(lengthOpt.dataset.extra || 0) : 0;
    return service + design + length;
  }

  /* What they actually pay, once a promo code is taken off. */
  function total() {
    const off = state.promo ? state.promo.discount : 0;
    return Math.max(0, subtotal() - off);
  }

  /* Left to settle after the advance. */
  function balance() {
    return Math.max(0, total() - deposit);
  }

  /* The sticky panel beside the wizard, updated on every single choice. */
  function refreshSummary() {
    const set = (id, value) => {
      const el = document.getElementById(id);
      if (!el) return;
      el.textContent = value || "Not set";
      el.classList.toggle("empty-v", !value);
    };

    set("sum-service", state.service && state.service.name);
    set("sum-design", state.design && state.design.name);
    set("sum-shape", state.shape);
    set("sum-length", state.length);
    set("sum-date", state.date
      ? new Date(state.date + "T00:00:00")
        .toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" })
      : null);
    set("sum-time", state.timeLabel);

    // The colour row shows the actual dots rather than their names.
    const dots = $("#sum-colors");
    if (dots) {
      dots.innerHTML = "";
      ["base", "secondary", "accent"].forEach((layer) => {
        const color = state.colors[layer];
        if (!color) return;
        const dot = document.createElement("i");
        dot.style.background = color.hex;
        dot.title = `${layer}: ${color.name}`;
        dots.appendChild(dot);
      });
      if (!dots.children.length) dots.textContent = "None chosen";
    }

    const totalEl = $("#sum-total");
    if (totalEl) totalEl.textContent = money(total());

    // The discount row only exists when a code is actually applied.
    const discountRow = $("#sum-discount-row");
    if (discountRow) {
      const off = state.promo ? state.promo.discount : 0;
      discountRow.classList.toggle("hidden", !off);
      if (off) $("#sum-discount").textContent = "− " + money(off);
    }

    const balanceEl = $("#sum-balance");
    if (balanceEl) balanceEl.textContent = money(balance());

    // The two payment cards quote live figures.
    const later = $("#pay-later-amount");
    if (later) later.textContent = money(balance());
    const full = $("#pay-full-amount");
    if (full) full.textContent = money(total());

    // NOTE: the promo <input> carries name="promo_code" and posts itself, so
    // there is no hidden field to sync here.

    // Keep the real form fields in step with the state object.
    $("#f-service").value = state.service ? state.service.id : "";
    $("#f-design").value = state.design ? state.design.id : "";
    $("#f-color").value = state.colors.base ? state.colors.base.id : "";
    $("#f-secondary").value = state.colors.secondary ? state.colors.secondary.id : "";
    $("#f-accent").value = state.colors.accent ? state.colors.accent.id : "";
    $("#f-shape").value = state.shape || "";
    $("#f-length").value = state.length || "";
    $("#f-date").value = state.date || "";
    $("#f-time").value = state.time || "";
  }

  /* The full review on step 8, with the price broken down line by line. */
  function renderSummaryStep() {
    const box = $("#final-summary");
    if (!box || !state.service) return;

    const lengthOpt = $(`[data-length="${state.length}"]`);
    const lengthExtra = lengthOpt ? Number(lengthOpt.dataset.extra || 0) : 0;
    const designExtra = state.design ? state.design.extra : 0;

    const rows = [
      ["Service", state.service.name, money(state.service.price)],
      ["Design", state.design ? state.design.name : "Not set",
        designExtra ? "+ " + money(designExtra) : "included"],
      ["Nail shape", state.shape, ""],
      ["Nail length", state.length,
        lengthExtra ? "+ " + money(lengthExtra) : "included"],
      ["Date", new Date(state.date + "T00:00:00")
        .toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" }), ""],
      ["Time", `${state.timeLabel} · about ${state.service.duration} mins`, ""],
    ];

    box.innerHTML = "";
    rows.forEach(([key, value, extra]) => {
      const row = document.createElement("div");
      row.className = "summary-row";
      row.innerHTML =
        `<span class="k"></span><span class="v"></span>`;
      row.querySelector(".k").textContent = key;
      row.querySelector(".v").textContent = extra ? `${value}  (${extra})` : value;
      box.appendChild(row);
    });

    // Colours get their own row, drawn as dots.
    const colorRow = document.createElement("div");
    colorRow.className = "summary-row";
    const label = document.createElement("span");
    label.className = "k";
    label.textContent = "Colours";
    const dots = document.createElement("span");
    dots.className = "summary-dots";
    ["base", "secondary", "accent"].forEach((layer) => {
      const color = state.colors[layer];
      if (!color) return;
      const dot = document.createElement("i");
      dot.style.background = color.hex;
      dot.title = color.name;
      dots.appendChild(dot);
    });
    colorRow.appendChild(label);
    colorRow.appendChild(dots);
    box.appendChild(colorRow);

    // A discount gets its own line, so it is impossible to miss.
    if (state.promo) {
      const row = document.createElement("div");
      row.className = "summary-row";
      row.innerHTML = '<span class="k"></span><span class="v"></span>';
      row.querySelector(".k").textContent = `Promo (${state.promo.code})`;
      row.querySelector(".v").textContent = "− " + money(state.promo.discount);
      row.querySelector(".v").style.color = "var(--ok)";
      box.appendChild(row);
    }

    $("#final-total").textContent = money(total());
    refreshSummary();
  }

  /* ---------------- payment method ----------------
     Both options pay the same advance up front — the only choice here is how
     the BALANCE is settled. So the transaction code and the screenshot are
     always required, whichever one is picked. */

  $$("[data-payment]").forEach((opt) => {
    opt.addEventListener("click", () => {
      $$("[data-payment]").forEach((o) => o.classList.remove("selected"));
      opt.classList.add("selected");

      state.payment = opt.dataset.payment;
      $("#f-payment").value = state.payment;
    });
  });

  /* ---------------- promo code ----------------
     The server decides what a code is worth. This only asks and displays —
     a discount the browser invented would be recalculated away on submit. */

  const promoInput = $("#promo-input");
  const promoNote = $("#promo-note");

  function showPromoNote(message, ok) {
    promoNote.textContent = message;
    promoNote.classList.remove("hidden", "ok", "bad");
    promoNote.classList.add(ok ? "ok" : "bad");
  }

  async function applyPromo() {
    const code = promoInput.value.trim();

    if (!code) {
      state.promo = null;
      promoNote.classList.add("hidden");
      refreshSummary();
      return;
    }

    try {
      const res = await fetch(
        `/api/promo?code=${encodeURIComponent(code)}&subtotal=${subtotal()}`);
      const data = await res.json();

      if (data.ok) {
        state.promo = { code: data.code, discount: data.discount };
        showPromoNote(`${data.label} applied, ${money(data.discount)} off.`, true);
      } else {
        state.promo = null;
        showPromoNote(data.error || "That code can't be used.", false);
      }
    } catch (err) {
      state.promo = null;
      showPromoNote("Could not check that code. Please try again.", false);
    }

    refreshSummary();
  }

  if (promoInput) {
    $("#promo-apply").addEventListener("click", applyPromo);

    // Enter should apply the code, not submit the whole booking.
    promoInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        applyPromo();
      }
    });

    // If they edit the code after applying it, the old discount is stale.
    promoInput.addEventListener("input", () => {
      if (state.promo && promoInput.value.trim().toUpperCase() !== state.promo.code) {
        state.promo = null;
        promoNote.classList.add("hidden");
        refreshSummary();
      }
    });
  }

  /* ---------------- submit ----------------
     A last look before the request leaves the browser. The server checks all
     of this again — in particular that the transaction code is not empty and
     that the slot is still free. */
  form.addEventListener("submit", (e) => {
    for (let n = 1; n <= TOTAL_STEPS; n++) {
      const problem = validate(n);
      if (problem) {
        e.preventDefault();
        show(n);
        return toast(problem);
      }
    }

    // The advance is paid on EVERY booking, so these two are always required.
    const code = $("#f-txn").value.trim();
    const file = $("#f-screenshot").files[0];

    if (!code) {
      e.preventDefault();
      show(9);
      return toast("Please enter the transaction code from your transfer.");
    }
    if (!file) {
      e.preventDefault();
      show(9);
      return toast("Please upload a screenshot of your payment.");
    }

    submitBtn.disabled = true;      // no double-submits
    submitBtn.textContent = "Sending your request…";
  });

  /* ---------------- boot ---------------- */

  // The wizard can be opened straight from a service card or a gallery tile.
  const pre = form.dataset;
  if (pre.preselectService) {
    const card = $(`[data-service="${pre.preselectService}"]`);
    if (card) card.click();
  }
  if (pre.preselectDesign) {
    const tile = $(`[data-design="${pre.preselectDesign}"]`);
    if (tile) {
      tile.click();
      // If they arrived via a design, the service is already implied — skip
      // them straight past the two steps they have effectively answered.
      if (state.service) show(3);
    }
  }

  paintPreview();
  refreshSummary();
  show(1);
})();
