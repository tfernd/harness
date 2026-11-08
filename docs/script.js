{
  const THEME_KEY = "harness-map-theme";
  // A pointer that only crosses a chip on its way elsewhere opens nothing.
  const HOVER_DELAY_MS = 90;
  // The room a popover keeps from the window's edge before it flips to the chip's other side.
  const EDGE_PX = 12;
  const WIDE_QUERY = window.matchMedia("(min-width: 40rem)");
  const page = document.documentElement;

  const findClosest = (event, selector) => (event.target instanceof Element ? event.target.closest(selector) : null);

  const save = (key, value) => {
    try {
      localStorage.setItem(key, value);
    } catch (error) {
      console.warn(`The choice ${key} could not be saved.`, error);
    }
  };

  const bindTheme = (button) => {
    const applyTheme = (theme) => {
      page.dataset.theme = theme;
      button.setAttribute("aria-pressed", String(theme === "dark"));
      button.textContent = theme === "dark" ? "Light mode" : "Dark mode";
    };
    button.addEventListener("click", () => {
      const theme = page.dataset.theme === "dark" ? "light" : "dark";
      applyTheme(theme);
      save(THEME_KEY, theme);
    });
    applyTheme(page.dataset.theme === "dark" ? "dark" : "light");
  };

  const bindTips = (root) => {
    let open = null;
    let isPinned = false;
    let hoverTimer = 0;

    const place = (chip, tip) => {
      tip.classList.remove("is-end", "is-above");
      if (!WIDE_QUERY.matches || tip.classList.contains("is-full")) return;
      const tipBox = tip.getBoundingClientRect();
      if (tipBox.right > page.clientWidth - EDGE_PX) tip.classList.add("is-end");
      const chipBox = chip.getBoundingClientRect();
      if (tipBox.bottom > window.innerHeight - EDGE_PX && chipBox.top > tipBox.height + EDGE_PX) tip.classList.add("is-above");
    };

    // The whole text is cloned from its template the first time it is asked for, so a closed page carries it inert.
    const setFull = (tip, isFull) => {
      const button = tip.querySelector(".tip-switch");
      const view = tip.querySelector(".tip-view");
      const template = document.getElementById(button?.dataset.full ?? "");
      if (!button || !view || !(template instanceof HTMLTemplateElement)) throw new Error(`The full text of ${tip.id} is missing from the page.`);
      if (isFull && view.childElementCount === 0) view.append(template.content.cloneNode(true));
      view.hidden = !isFull;
      view.scrollTop = 0;
      for (const part of tip.querySelectorAll(".tip-body")) part.hidden = isFull;
      tip.classList.toggle("is-full", isFull);
      if (isFull) tip.classList.remove("is-end", "is-above");
      button.setAttribute("aria-expanded", String(isFull));
      button.textContent = isFull ? "Summary" : "Full text";
    };

    const close = () => {
      clearTimeout(hoverTimer);
      if (!open) return;
      if (open.tip.contains(document.activeElement)) open.chip.focus({ preventScroll: true });
      setFull(open.tip, false);
      open.chip.classList.remove("is-open");
      open.tip.hidden = true;
      open = null;
      isPinned = false;
    };

    const show = (chip, pin) => {
      clearTimeout(hoverTimer);
      if (open?.chip !== chip) {
        close();
        const tip = document.getElementById(chip.getAttribute("aria-describedby") ?? "");
        if (!tip) throw new Error(`The popover of ${chip.dataset.item} is missing from the page.`);
        tip.hidden = false;
        chip.classList.add("is-open");
        place(chip, tip);
        open = { chip, tip };
      }
      isPinned = isPinned || pin;
    };

    root.addEventListener("pointerover", (event) => {
      if (event.pointerType === "touch") return;
      const chip = findClosest(event, ".chip");
      clearTimeout(hoverTimer);
      if (chip) hoverTimer = setTimeout(() => show(chip, false), HOVER_DELAY_MS);
    });
    root.addEventListener("pointerout", (event) => {
      const item = findClosest(event, ".chip-item");
      if (!item || isPinned || item.contains(event.relatedTarget)) return;
      clearTimeout(hoverTimer);
      if (open && item.contains(open.chip)) close();
    });
    root.addEventListener("focusin", (event) => {
      const chip = findClosest(event, ".chip");
      if (chip) show(chip, false);
    });
    root.addEventListener("focusout", (event) => {
      if (open && !isPinned && !open.chip.parentElement?.contains(event.relatedTarget)) close();
    });
    root.addEventListener("click", (event) => {
      const switcher = findClosest(event, ".tip-switch");
      if (switcher && open?.tip.contains(switcher)) {
        isPinned = true;
        const isFull = switcher.getAttribute("aria-expanded") !== "true";
        setFull(open.tip, isFull);
        if (!isFull) place(open.chip, open.tip);
        return;
      }
      const chip = findClosest(event, ".chip");
      if (!chip) return;
      if (open?.chip === chip && isPinned) close();
      else show(chip, true);
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") close();
    });
    document.addEventListener("pointerdown", (event) => {
      if (open && !findClosest(event, ".chip-item")) close();
    });
  };

  const bindPyramid = (root, panels) => {
    const levels = [...root.querySelectorAll("[data-level]")];
    const notes = [...root.querySelectorAll("[data-level-note]")];
    const chips = [...panels.querySelectorAll(".chip")];
    const pyramid = root.querySelector(".pyramid");
    let pinned = "";

    const light = (level) => {
      const lit = chips.filter((chip) => level !== "" && (chip.dataset.levels ?? "").split(" ").includes(level));
      for (const button of levels) button.classList.toggle("is-active", button.dataset.level === level);
      for (const note of notes) note.hidden = note.dataset.levelNote !== (level || "none");
      for (const chip of chips) chip.classList.toggle("is-lit", lit.includes(chip));
      pyramid?.classList.toggle("has-active", level !== "");
      // Only a panel on screen with a lit part dims the rest; a level that lights nothing here leaves the panel as it is.
      panels.classList.toggle("has-filter", lit.some((chip) => chip.offsetParent !== null));
    };

    root.addEventListener("pointerover", (event) => {
      const button = findClosest(event, "[data-level]");
      if (button) light(button.dataset.level);
    });
    root.addEventListener("pointerleave", () => light(pinned));
    root.addEventListener("focusin", (event) => {
      const button = findClosest(event, "[data-level]");
      if (button) light(button.dataset.level);
    });
    root.addEventListener("focusout", (event) => {
      if (!root.contains(event.relatedTarget)) light(pinned);
    });
    root.addEventListener("click", (event) => {
      const button = findClosest(event, "[data-level]");
      if (!button) return;
      pinned = pinned === button.dataset.level ? "" : button.dataset.level;
      for (const other of levels) other.setAttribute("aria-pressed", String(other.dataset.level === pinned));
      light(button.dataset.level);
    });
  };

  const themeButton = document.querySelector("[data-theme-toggle]");
  if (themeButton) bindTheme(themeButton);
  const panels = document.querySelector("[data-panels]");
  if (!panels) throw new Error("The page has no panels.");
  bindTips(panels);
  for (const root of document.querySelectorAll("[data-pyramid]")) bindPyramid(root, panels);
}

{
  const COPY_LABEL = "Copy";
  const COPIED_LABEL = "Copied";
  const SELECTED_LABEL = "Selected: press Ctrl+C";
  const LABEL_RESET_MS = 1600;
  const KEY_STEPS = { ArrowRight: 1, ArrowLeft: -1 };

  const showTab = (root, tab) => {
    for (const other of root.querySelectorAll("[role='tab']")) {
      const isSelected = other === tab;
      const panelId = other.getAttribute("aria-controls");
      const panel = document.getElementById(panelId);
      if (!panel) throw new Error(`The install panel ${panelId} is missing from the page.`);
      other.setAttribute("aria-selected", String(isSelected));
      other.tabIndex = isSelected ? 0 : -1;
      panel.hidden = !isSelected;
    }
  };

  const moveTab = (root, tab, step) => {
    const tabs = [...root.querySelectorAll("[role='tab']")];
    const next = tabs[(tabs.indexOf(tab) + step + tabs.length) % tabs.length];
    showTab(root, next);
    next.focus();
  };

  const selectCommands = (panel) => {
    const commands = panel.querySelectorAll(".install-command");
    if (commands.length === 0) return;
    const range = document.createRange();
    range.setStartBefore(commands[0]);
    range.setEndAfter(commands[commands.length - 1]);
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
      selectCommands(button.closest("[role='tabpanel']"));
      button.textContent = SELECTED_LABEL;
    }
    setTimeout(() => {
      button.textContent = COPY_LABEL;
    }, LABEL_RESET_MS);
  };

  const bindInstall = (root) => {
    root.addEventListener("click", (event) => {
      if (!(event.target instanceof Element)) return;
      const tab = event.target.closest("[role='tab']");
      if (tab) showTab(root, tab);
      const copyButton = event.target.closest("[data-copy]");
      if (copyButton) void copyCommand(copyButton);
    });
    root.addEventListener("keydown", (event) => {
      const tab = event.target instanceof Element ? event.target.closest("[role='tab']") : null;
      const step = KEY_STEPS[event.key];
      if (!tab || !step) return;
      event.preventDefault();
      moveTab(root, tab, step);
    });
  };

  for (const root of document.querySelectorAll("[data-install]")) bindInstall(root);
}
