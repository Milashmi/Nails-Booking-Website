/* =========================================================================
   Eleanora Nails — site-wide behaviour
   Theme toggle, menus, scroll-reveal, 3D card tilt, hero parallax, counters,
   lightbox and the custom confirm dialog.

   No inline JS anywhere: the Content-Security-Policy forbids it, so every
   handler is attached from this file.
   ========================================================================= */
(function () {
  "use strict";

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------------- preloader ----------------
     Take the brand splash away once the page has actually loaded. The safety
     timeout matters: if an image 404s and `load` never fires, the curtain must
     still lift rather than stranding the visitor on the logo. */
  const preloader = document.getElementById("preloader");
  if (preloader) {
    // Fade it out, then take it out of the document entirely. Leaving it in
    // place — even invisible — would let a full-screen element keep swallowing
    // clicks meant for the page beneath it.
    const lift = () => {
      if (preloader.classList.contains("done")) return;
      preloader.classList.add("done");
      setTimeout(() => preloader.remove(), 700);   // after the fade finishes
    };

    window.addEventListener("load", () => setTimeout(lift, 300));
    setTimeout(lift, 2200);   // a slow image must never strand the visitor
  }

  /* ---------------- theme ---------------- */
  const root = document.documentElement;
  const themeBtn = document.getElementById("theme-toggle");
  if (themeBtn) {
    themeBtn.addEventListener("click", () => {
      const next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", next);
      localStorage.setItem("theme", next);
    });
  }

  /* ---------------- navbar ---------------- */
  const navbar = document.querySelector(".navbar");
  if (navbar) {
    const onScroll = () => navbar.classList.toggle("stuck", window.scrollY > 8);
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
  }

  const navToggle = document.getElementById("nav-toggle");
  const navLinks = document.getElementById("nav-links");
  if (navToggle && navLinks) {
    navToggle.addEventListener("click", () => navLinks.classList.toggle("open"));
  }

  /* Dropdown menus: [data-menu-btn="id"] opens the element with that id. */
  document.querySelectorAll("[data-menu-btn]").forEach((btn) => {
    const menu = document.getElementById(btn.dataset.menuBtn);
    if (!menu) return;
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      menu.classList.toggle("hidden");
    });
  });
  document.addEventListener("click", () => {
    document.querySelectorAll("[data-menu-btn]").forEach((btn) => {
      const menu = document.getElementById(btn.dataset.menuBtn);
      if (menu) menu.classList.add("hidden");
    });
  });

  /* ---------------- flash messages ---------------- */
  document.querySelectorAll(".flash").forEach((flash) => {
    const close = () => {
      flash.style.transition = "opacity .3s, transform .3s";
      flash.style.opacity = "0";
      flash.style.transform = "translateX(24px)";
      setTimeout(() => flash.remove(), 300);
    };
    const btn = flash.querySelector("[data-close]");
    if (btn) btn.addEventListener("click", close);
    setTimeout(close, 6000);   // they fade out on their own
  });

  /* ---------------- scroll reveal ----------------
     Elements marked .reveal / .stagger fade and lift into place the first
     time they scroll into view. This is what gives the page its rhythm. */
  const revealables = document.querySelectorAll(".reveal, .stagger");
  if (revealables.length && !reduceMotion && "IntersectionObserver" in window) {
    // threshold 0 — "any part of it has entered the viewport" — NOT a percentage.
    // A percentage looks tempting, but a container taller than the screen (the
    // admin review grid, a long gallery) can never show 12% of itself at once,
    // so it would never fire and its contents would stay invisible forever.
    const io = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("in");
          io.unobserve(entry.target);      // animate once, then leave it alone
        }
      });
    }, { threshold: 0, rootMargin: "0px 0px -40px 0px" });

    revealables.forEach((el) => io.observe(el));

    // A safety net: whatever happens above, nothing may stay invisible. If an
    // element is still un-revealed a moment after load, show it anyway. Content
    // the user cannot see is a far worse bug than an animation that didn't play.
    setTimeout(() => {
      revealables.forEach((el) => el.classList.add("in"));
    }, 1500);
  } else {
    revealables.forEach((el) => el.classList.add("in"));
  }

  /* ---------------- 3D tilt ----------------
     A card marked [data-tilt] leans towards the cursor. The rotation is tiny
     on purpose — it should read as depth, not as a gimmick. */
  if (!reduceMotion && window.matchMedia("(hover: hover)").matches) {
    document.querySelectorAll("[data-tilt]").forEach((card) => {
      const strength = parseFloat(card.dataset.tilt) || 7;

      card.addEventListener("mousemove", (e) => {
        const box = card.getBoundingClientRect();
        const px = (e.clientX - box.left) / box.width - 0.5;   // -0.5 .. 0.5
        const py = (e.clientY - box.top) / box.height - 0.5;
        card.style.transform =
          `perspective(900px) rotateX(${-py * strength}deg) ` +
          `rotateY(${px * strength}deg) translateY(-4px)`;
      });

      card.addEventListener("mouseleave", () => {
        card.style.transform = "";
      });
    });
  }

  /* ---------------- hero parallax ----------------
     The collage tiles drift at different speeds as the page scrolls. */
  const parallax = document.querySelectorAll("[data-parallax]");
  if (parallax.length && !reduceMotion) {
    let ticking = false;
    const move = () => {
      const y = window.scrollY;
      parallax.forEach((el) => {
        const depth = parseFloat(el.dataset.parallax) || 0.1;
        el.style.translate = `0 ${-y * depth}px`;
      });
      ticking = false;
    };
    window.addEventListener("scroll", () => {
      if (!ticking) {
        window.requestAnimationFrame(move);   // never fight the browser's frame budget
        ticking = true;
      }
    }, { passive: true });
  }

  /* ---------------- counters ----------------
     [data-count="1234"] ticks up from zero the first time it is seen. */
  const counters = document.querySelectorAll("[data-count]");
  if (counters.length && "IntersectionObserver" in window) {
    const countUp = (el) => {
      const target = parseFloat(el.dataset.count) || 0;
      const decimals = (el.dataset.count.split(".")[1] || "").length;
      if (reduceMotion) {
        el.textContent = target.toFixed(decimals);
        return;
      }
      const duration = 1200;
      const start = performance.now();

      const tick = (now) => {
        const t = Math.min((now - start) / duration, 1);
        const eased = 1 - Math.pow(1 - t, 3);          // ease-out cubic
        el.textContent = (target * eased).toFixed(decimals);
        if (t < 1) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    };

    const co = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          countUp(entry.target);
          co.unobserve(entry.target);
        }
      });
    }, { threshold: 0.5 });

    counters.forEach((el) => co.observe(el));
  }

  /* ---------------- lightbox ----------------
     Any [data-lightbox] image opens full-size (payment proofs, designs). */
  document.querySelectorAll("[data-lightbox]").forEach((img) => {
    img.addEventListener("click", () => {
      const box = document.createElement("div");
      box.className = "lightbox";

      const big = document.createElement("img");
      big.src = img.dataset.lightbox || img.src;
      big.alt = img.alt || "";
      box.appendChild(big);

      box.addEventListener("click", () => box.remove());
      document.body.appendChild(box);
    });
  });

  /* ---------------- confirm dialog ----------------
     Replaces the browser's confirm() for destructive actions. A form marked
     [data-confirm="message"] asks first, and only then submits. */
  const modal = document.getElementById("confirm-modal");
  if (modal) {
    const text = document.getElementById("confirm-text");
    const okBtn = document.getElementById("confirm-ok");
    const cancelBtn = document.getElementById("confirm-cancel");
    let pendingForm = null;

    const close = () => {
      modal.classList.add("hidden");
      pendingForm = null;
    };

    document.querySelectorAll("form[data-confirm]").forEach((form) => {
      form.addEventListener("submit", (e) => {
        if (form === pendingForm) return;         // already confirmed
        e.preventDefault();
        pendingForm = form;
        text.textContent = form.dataset.confirm;
        modal.classList.remove("hidden");
      });
    });

    okBtn.addEventListener("click", () => {
      if (pendingForm) {
        const form = pendingForm;
        modal.classList.add("hidden");
        form.submit();     // .submit() skips the submit event, so no loop
      }
    });

    cancelBtn.addEventListener("click", close);
    modal.querySelector(".modal-backdrop").addEventListener("click", close);
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !modal.classList.contains("hidden")) close();
    });
  }

  /* ---------------- generic modals ----------------
     [data-open-modal="id"] shows it, [data-close-modal] inside hides it. */
  document.querySelectorAll("[data-open-modal]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = document.getElementById(btn.dataset.openModal);
      if (target) target.classList.remove("hidden");
    });
  });
  document.querySelectorAll("[data-close-modal]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = btn.closest(".modal");
      if (target) target.classList.add("hidden");
    });
  });

  /* ---------------- file inputs ----------------
     Show the chosen file's name, and a thumbnail if it is an image. */
  document.querySelectorAll("[data-file-drop]").forEach((drop) => {
    const input = drop.querySelector('input[type="file"]');
    if (!input) return;

    drop.addEventListener("click", () => input.click());

    input.addEventListener("change", () => {
      const file = input.files && input.files[0];
      if (!file) return;

      const nameEl = drop.querySelector(".file-name");
      if (nameEl) nameEl.textContent = file.name;

      const preview = drop.querySelector(".thumb-preview");
      if (preview && file.type.startsWith("image/")) {
        preview.src = URL.createObjectURL(file);
        preview.classList.remove("hidden");
      }
    });
  });
})();
