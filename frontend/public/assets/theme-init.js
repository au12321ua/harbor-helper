// Keep the preference rules in sync with src/app/theme.ts (covered by theme.spec.ts).
(function () {
  var theme = "dark";
  try {
    if (localStorage.getItem("harbor-helper.theme") === "light") theme = "light";
  } catch { /* Storage can be blocked by browser policy. */ }
  document.documentElement.dataset.theme = theme;
})();
