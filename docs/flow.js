(() => {
  const root = document.querySelector("[data-wire]");
  if (!root) return;
  const edges = [...root.querySelectorAll("[data-wire-edge]")];
  const nodes = [...root.querySelectorAll("[data-wire-node]")];
  const toggles = [...root.querySelectorAll("[data-wire-kind]")];
  const status = root.querySelector("[data-wire-status]");
  const visibleKinds = new Set(toggles.filter((toggle) => toggle.getAttribute("aria-pressed") === "true").map((toggle) => toggle.dataset.wireKind));
  let selected = null;

  const touches = (edge) => edge.dataset.wireSource === selected || edge.dataset.wireTarget === selected;

  const render = () => {
    const linkedNodes = new Set();
    let linkCount = 0;
    for (const edge of edges) {
      const isLinked = selected !== null && touches(edge);
      const isShown = visibleKinds.has(edge.dataset.wireEdge) || isLinked;
      edge.classList.toggle("is-off", !isShown);
      edge.classList.toggle("is-linked", isLinked);
      edge.classList.toggle("is-dim", selected !== null && !isLinked);
      if (isLinked) {
        linkCount += 1;
        linkedNodes.add(edge.dataset.wireSource);
        linkedNodes.add(edge.dataset.wireTarget);
      }
    }
    for (const node of nodes) {
      const key = node.dataset.wireNode;
      node.classList.toggle("is-dim", selected !== null && !linkedNodes.has(key) && key !== selected);
      node.setAttribute("aria-pressed", String(key === selected));
    }
    status.textContent = selected === null ? "" : `${selected.split(":")[1]}: ${linkCount} links, ${linkedNodes.size - 1} linked parts.`;
  };

  const choose = (key) => {
    selected = selected === key ? null : key;
    render();
  };

  for (const node of nodes) {
    node.addEventListener("click", () => choose(node.dataset.wireNode));
    node.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      choose(node.dataset.wireNode);
    });
  }
  for (const toggle of toggles) {
    toggle.addEventListener("click", () => {
      const kind = toggle.dataset.wireKind;
      if (visibleKinds.has(kind)) visibleKinds.delete(kind);
      else visibleKinds.add(kind);
      toggle.setAttribute("aria-pressed", String(visibleKinds.has(kind)));
      render();
    });
  }
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || selected === null) return;
    selected = null;
    render();
  });
  render();
})();
