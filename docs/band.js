{
  const THEME_KEY = "harness-map-theme";

  const bindTheme = (switchButton, choiceButtons) => {
    const page = document.documentElement;
    const applyTheme = (theme) => {
      page.dataset.theme = theme;
      switchButton.setAttribute("aria-checked", String(theme === "dark"));
      for (const choice of choiceButtons) choice.setAttribute("aria-pressed", String(choice.dataset.themeChoice === theme));
    };
    const choose = (theme) => {
      applyTheme(theme);
      try {
        localStorage.setItem(THEME_KEY, theme);
      } catch (error) {
        console.warn("The theme could not be saved.", error);
      }
    };
    switchButton.addEventListener("click", () => choose(page.dataset.theme === "dark" ? "light" : "dark"));
    for (const choice of choiceButtons) choice.addEventListener("click", () => choose(choice.dataset.themeChoice === "dark" ? "dark" : "light"));
    applyTheme(page.dataset.theme === "dark" ? "dark" : "light");
  };

  const required = (parent, selector) => {
    const element = parent.querySelector(selector);
    if (!element) throw new Error(`The band page is missing ${selector}.`);
    return element;
  };

  const COPY_LABEL = "Copy";
  const COPIED_LABEL = "Copied";
  const SELECTED_LABEL = "Selected: press Ctrl+C";
  const LABEL_RESET_MS = 1600;

  const selectCommand = (panel) => {
    const command = panel.querySelector(".install-command:not([hidden])");
    if (!command) return;
    const range = document.createRange();
    range.selectNodeContents(command);
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
  };

  const copyCommand = async (button) => {
    try {
      await navigator.clipboard.writeText(button.dataset.copy ?? "");
      button.textContent = COPIED_LABEL;
    } catch (error) {
      console.warn("The clipboard is not available; the command is selected for copying.", error);
      selectCommand(button.closest(".install-panel"));
      button.textContent = SELECTED_LABEL;
    }
    setTimeout(() => {
      button.textContent = COPY_LABEL;
    }, LABEL_RESET_MS);
  };

  const showMode = (root, mode) => {
    for (const choice of root.querySelectorAll("[data-mode-choice]")) {
      choice.setAttribute("aria-pressed", String(choice.dataset.modeChoice === mode));
    }
    for (const item of root.querySelectorAll("[data-mode]")) item.hidden = item.dataset.mode !== mode;
  };

  const bindInstall = (root) => {
    root.addEventListener("click", (event) => {
      if (!(event.target instanceof Element)) return;
      const modeChoice = event.target.closest("[data-mode-choice]");
      if (modeChoice instanceof HTMLElement) showMode(root, modeChoice.dataset.modeChoice ?? "install");
      const copyButton = event.target.closest("[data-copy]");
      if (copyButton instanceof HTMLElement) void copyCommand(copyButton);
    });
  };

  bindTheme(required(document, "[data-theme-toggle]"), [...document.querySelectorAll("[data-theme-choice]")]);
  for (const root of document.querySelectorAll("[data-install]")) bindInstall(root);
}
