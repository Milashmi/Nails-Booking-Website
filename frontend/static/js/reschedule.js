/* The reschedule page: the same availability engine as the booking wizard, but
   with only the date and time steps. `exclude` tells the server to ignore this
   appointment's own slot, so the client can keep their current time if they
   change their mind, and so their booking never collides with itself. */
(function () {
  "use strict";

  const form = document.getElementById("reschedule-form");
  if (!form) return;

  const serviceId = form.dataset.service;
  const excludeId = form.dataset.exclude;

  const dateGrid = document.getElementById("date-grid");
  const timeGrid = document.getElementById("time-grid");
  const submitBtn = document.getElementById("reschedule-submit");
  const dateField = document.getElementById("f-date");
  const timeField = document.getElementById("f-time");

  function refreshSubmit() {
    submitBtn.disabled = !(dateField.value && timeField.value);
  }

  async function loadDates() {
    try {
      const res = await fetch(
        `/api/availability?service=${serviceId}&exclude=${excludeId}`);
      const data = await res.json();
      renderDates(data.dates || []);
    } catch (err) {
      dateGrid.innerHTML = '<p class="muted">Could not load the calendar.</p>';
    }
  }

  function renderDates(dates) {
    dateGrid.innerHTML = "";

    if (!dates.length) {
      dateGrid.innerHTML =
        '<p class="muted">There is nothing free in the next few weeks. ' +
        'Please call us and we will sort it out.</p>';
      return;
    }

    dates.forEach((iso) => {
      const day = new Date(iso + "T00:00:00");

      const cell = document.createElement("button");
      cell.type = "button";
      cell.className = "date-cell";
      cell.innerHTML =
        `<div class="dow">${day.toLocaleDateString("en-GB", { weekday: "short" })}</div>` +
        `<div class="dnum">${day.getDate()}</div>` +
        `<div class="dmon">${day.toLocaleDateString("en-GB", { month: "short" })}</div>`;

      cell.addEventListener("click", () => {
        dateGrid.querySelectorAll(".date-cell")
          .forEach((c) => c.classList.remove("selected"));
        cell.classList.add("selected");

        dateField.value = iso;
        timeField.value = "";     // the old time belongs to the old date
        refreshSubmit();
        loadTimes(iso);
      });

      dateGrid.appendChild(cell);
    });
  }

  async function loadTimes(iso) {
    timeGrid.innerHTML =
      '<div class="loading"><span class="spinner"></span>Checking that day…</div>';

    try {
      const res = await fetch(
        `/api/availability?service=${serviceId}&date=${iso}&exclude=${excludeId}`);
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
        '<p class="muted">That day just filled up. Please choose another.</p>';
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

        timeField.value = slot.value;
        refreshSubmit();
      });

      timeGrid.appendChild(cell);
    });
  }

  loadDates();
})();
