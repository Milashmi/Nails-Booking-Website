/* The colour page's little playground: choose a layer, tap a swatch, and the
   three preview nails repaint. Nothing is saved — it is purely a way to see how
   a trio looks together before you commit to it in the booking wizard. */
(function () {
  "use strict";

  const nails = {
    base: document.getElementById("prev-base"),
    secondary: document.getElementById("prev-secondary"),
    accent: document.getElementById("prev-accent"),
  };
  if (!nails.base) return;   // not on the colours page

  let layer = "base";

  document.querySelectorAll("[data-layer-btn]").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("[data-layer-btn]")
        .forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      layer = btn.dataset.layerBtn;
    });
  });

  document.querySelectorAll("[data-color-swatch]").forEach((swatch) => {
    swatch.addEventListener("click", () => {
      const target = nails[layer];
      if (!target) return;

      target.style.background = swatch.dataset.hex;
      target.title = swatch.dataset.name;

      // A quick bounce, so it is obvious which nail just changed.
      target.animate(
        [{ transform: "translateY(0)" },
         { transform: "translateY(-10px)" },
         { transform: "translateY(0)" }],
        { duration: 420, easing: "cubic-bezier(.34,1.56,.48,1)" }
      );
    });
  });
})();
