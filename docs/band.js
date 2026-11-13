{
  const required = (parent, selector) => {
    const element = parent.querySelector(selector);
    if (!element) throw new Error(`The band page is missing ${selector}.`);
    return element;
  };

  const bindSize = (controls, frame) => {
    const range = required(controls, "[data-size-range]");
    const pixels = required(controls, "[data-size-px]");
    const columns = required(controls, "[data-size-columns]");
    const presets = [...controls.querySelectorAll("[data-size-preset]")];
    const setWidth = (width) => {
      frame.style.inlineSize = `${width}px`;
    };
    const showWidth = () => {
      const width = Math.round(frame.getBoundingClientRect().width);
      pixels.textContent = String(width);
      range.value = String(width);
      for (const preset of presets) preset.setAttribute("aria-pressed", String(Number(preset.dataset.sizePreset) === width));
    };
    range.addEventListener("input", () => setWidth(range.valueAsNumber));
    for (const preset of presets) preset.addEventListener("click", () => setWidth(Number(preset.dataset.sizePreset)));
    document.addEventListener("band-columns", (event) => {
      columns.textContent = String(event.detail);
    });
    new ResizeObserver(showWidth).observe(frame);
    showWidth();
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

  bindSize(required(document, "[data-size]"), required(document, "[data-frame]"));
  for (const root of document.querySelectorAll("[data-install]")) bindInstall(root);
}
