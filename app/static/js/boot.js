/* Pre-paint boot: theme before first paint, so nothing flashes.
   Language is resolved on the server (cookie `ss_lang`), so JS never touches it. */
(function () {
  "use strict";
  var root = document.documentElement;
  root.classList.add("js");

  var theme = null;
  try {
    theme = localStorage.getItem("socialscope-theme");
  } catch (error) {
    theme = null;
  }
  if (theme !== "light" && theme !== "dark") {
    theme = window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  }
  root.dataset.theme = theme;
})();
