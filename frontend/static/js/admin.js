/* Small helpers for the admin screens.
   Right now: keep the colour-picker swatch and the hex text box in step with
   each other, in both directions. */
(function () {
  "use strict";

  document.querySelectorAll('input[type="color"][data-sync]').forEach((picker) => {
    const text = document.getElementById(picker.dataset.sync);
    if (!text) return;

    // swatch -> text
    picker.addEventListener("input", () => {
      text.value = picker.value;
    });

    // text -> swatch (only once it is a complete, valid hex code)
    text.addEventListener("input", () => {
      if (/^#[0-9a-fA-F]{6}$/.test(text.value)) {
        picker.value = text.value;
      }
    });
  });
})();
