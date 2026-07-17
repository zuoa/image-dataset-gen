(function () {
  try {
    var mode = localStorage.getItem("dataset-forge-theme") || "system";
    var isDark =
      mode === "dark" ||
      (mode === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);

    document.documentElement.classList.toggle("dark", isDark);
    document.documentElement.style.colorScheme = isDark ? "dark" : "light";
  } catch (error) {
    // Storage access can be denied by the browser; the React app will apply the fallback theme.
  }
})();
