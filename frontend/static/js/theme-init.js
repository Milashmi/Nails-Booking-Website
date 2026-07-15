/* Runs in <head> BEFORE the page paints, so the right theme is already on the
   <html> element by the time the first pixel is drawn (no flash of the wrong
   colours). It lives in its own file so the Content-Security-Policy can keep
   forbidding inline scripts. */
(function () {
  // Tell the CSS that JS is alive, so it may safely hide elements that are
  // about to be animated in. Without JS they simply stay visible.
  document.documentElement.classList.add("js");

  var saved = localStorage.getItem("theme");
  if (!saved) {
    saved = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  document.documentElement.setAttribute("data-theme", saved);
})();
