{
  const THEME_KEY = "harness-map-theme";
  const page = document.documentElement;

  const saveTheme = (theme) => {
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch (error) {
      console.warn("The theme could not be saved.", error);
    }
  };

  const bindTheme = (button) => {
    const applyTheme = (theme) => {
      page.dataset.theme = theme;
      button.setAttribute("aria-checked", String(theme === "dark"));
    };
    button.addEventListener("click", () => {
      const theme = page.dataset.theme === "dark" ? "light" : "dark";
      applyTheme(theme);
      saveTheme(theme);
    });
    applyTheme(page.dataset.theme === "dark" ? "dark" : "light");
  };

  const themeButton = document.querySelector("[data-theme-toggle]");
  if (themeButton) bindTheme(themeButton);
}
