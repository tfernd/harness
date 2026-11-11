{
  const THEME_KEY = "harness-map-theme";
  const SPEED = 4;
  const TICK_MS = 125;
  const MAX_STEP_MS = 1000;
  const SECOND = 1000;
  const MINUTE = 60 * SECOND;
  const HOUR = 60 * MINUTE;
  const WORK_MS = 5 * MINUTE;
  const IDLE_MS = MINUTE;
  const SEED_START_MS = -(18 * MINUTE + 74 * SECOND);
  const CACHE_LIFETIME_MS = HOUR;
  const MAX_ROWS = 6;
  const MIN_LIVE = 3;
  const MAX_LIVE = 5;
  const FAIL_CHANCE = 0.15;
  const KEEP_ENDED_MS = 2 * HOUR;
  const LINGER_MS = 5 * SECOND;
  const TOOL_LABELS = [
    "uv run pytest -q",
    "make check",
    'rg -n "budget" hooks',
    "git diff --stat",
    "uvx ruff check",
    "node --check band.js",
    "make map",
    "sed -n 1,80p SPEC.md",
  ];
  const ROLES = ["worker", "scout", "reviewer", "designer"];
  const GROUPS = [
    { key: "workflow", tag: "WORKFLOW", name: "workflow: review pass" },
    { key: "direct", tag: "DIRECT", name: "direct agents" },
  ];
  const PILL_TEXT = {
    launched: "STARTING",
    thinking: "THINKING",
    tool: "RUNNING",
    waiting: "WAITING",
    finished: "FINISHED",
    failed: "FAILED",
  };
  const MAIN_PILL_TEXT = { launched: "IDLE", thinking: "WORKING", tool: "TOOL", waiting: "NEEDS YOU" };
  const WAIT_CHANCE = 0.15;

  const createRandom = (seed) => {
    let state = seed >>> 0;
    return () => {
      state = (state + 0x6d2b79f5) >>> 0;
      let mixed = state;
      mixed = Math.imul(mixed ^ (mixed >>> 15), mixed | 1);
      mixed ^= mixed + Math.imul(mixed ^ (mixed >>> 7), mixed | 61);
      return ((mixed ^ (mixed >>> 14)) >>> 0) / 4294967296;
    };
  };

  const pick = (random, list) => list[Math.floor(random() * list.length)];
  const between = (random, low, high) => low + random() * (high - low);

  const planSpan = (random, kind, start) => {
    const isTool = kind === "tool";
    const length =
      kind === "launched"
        ? between(random, 2 * SECOND, 5 * SECOND)
        : kind === "waiting"
          ? between(random, 4 * SECOND, 12 * SECOND)
          : isTool
            ? between(random, 6 * SECOND, 26 * SECOND)
            : between(random, 8 * SECOND, 32 * SECOND);
    const labels = { launched: "starting", waiting: "waiting", thinking: "reasoning" };
    return { kind, start, end: null, plannedEnd: start + length, label: isTool ? pick(random, TOOL_LABELS) : labels[kind] };
  };

  const nextKind = (random, kind) => {
    if (kind === "launched") return "thinking";
    if (kind === "tool") return "thinking";
    return random() < WAIT_CHANCE && kind === "thinking" ? "waiting" : "tool";
  };

  const createAgent = (random, id, group, start) => ({
    id,
    name: `harness:${pick(random, ROLES)}-${id}`,
    group,
    spawnedAt: start,
    state: "live",
    endedAt: null,
    detail: "",
    limit: Math.floor(between(random, 6, 14)),
    spans: [planSpan(random, "launched", start)],
  });

  const lastSpan = (agent) => agent.spans[agent.spans.length - 1];

  const endAgent = (agent, state, at) => {
    const current = lastSpan(agent);
    if (current.end === null) current.end = Math.min(at, current.plannedEnd);
    agent.state = state;
    agent.endedAt = at;
    agent.detail = state === "failed" ? "tests failed" : "completed";
  };

  const advanceAgent = (random, agent, now) => {
    while (agent.state === "live") {
      const current = lastSpan(agent);
      if (current.end !== null || current.plannedEnd > now) return;
      current.end = current.plannedEnd;
      if (agent.spans.length >= agent.limit) {
        endAgent(agent, random() < FAIL_CHANCE ? "failed" : "finished", current.end);
        return;
      }
      agent.spans.push(planSpan(random, nextKind(random, current.kind), current.end));
    }
  };

  const liveAgents = (model) => model.agents.filter((agent) => agent.state === "live");

  const spawnAgent = (model) => {
    model.spawned += 1;
    const group = model.random() < 0.6 ? "workflow" : "direct";
    model.agents.push(createAgent(model.random, model.spawned, group, model.now));
  };

  const startTurn = (model) => {
    model.isWorking = true;
    model.turnStart = model.now;
    model.turnEnd = model.now + WORK_MS;
    model.cacheCalledAt = model.now;
    const idle = model.main.spans[model.main.spans.length - 1];
    if (idle && idle.end === null) idle.end = model.now;
    model.main.spans.push(planSpan(model.random, "thinking", model.now));
    for (let count = 0; count < MIN_LIVE; count += 1) spawnAgent(model);
  };

  const finishTurn = (model) => {
    model.isWorking = false;
    model.lastTurnMs = model.now - model.turnStart;
    model.idleEnd = model.now + IDLE_MS;
    const current = lastSpan(model.main);
    if (current.end === null) current.end = Math.min(model.now, current.plannedEnd);
    model.main.spans.push({ kind: "launched", start: current.end, end: null, plannedEnd: Number.POSITIVE_INFINITY, label: "waiting for a prompt" });
    for (const agent of liveAgents(model)) endAgent(agent, "finished", model.now);
  };

  const maybeSpawn = (model, deltaMs) => {
    if (model.turnEnd - model.now < 20 * SECOND) return;
    const live = liveAgents(model).length;
    const rate = live < MIN_LIVE ? 0.5 : live < MAX_LIVE ? 0.04 : 0;
    if (model.random() < (rate * deltaMs) / SECOND) spawnAgent(model);
  };

  const countEnded = (model) => {
    model.done = model.agents.filter((agent) => agent.state === "finished").length + model.prunedDone;
    model.failed = model.agents.filter((agent) => agent.state === "failed").length + model.prunedFailed;
  };

  const pruneAgents = (model) => {
    const keep = [];
    for (const agent of model.agents) {
      const isOld = agent.state !== "live" && model.now - agent.endedAt > KEEP_ENDED_MS + LINGER_MS;
      if (!isOld) keep.push(agent);
      else if (agent.state === "finished") model.prunedDone += 1;
      else model.prunedFailed += 1;
    }
    model.agents = keep;
  };

  const stepModel = (model, deltaMs) => {
    model.now += deltaMs;
    if (model.isWorking && model.now >= model.turnEnd) finishTurn(model);
    else if (!model.isWorking && model.now >= model.idleEnd) startTurn(model);
    advanceAgent(model.random, model.main, model.now);
    for (const agent of model.agents) advanceAgent(model.random, agent, model.now);
    if (model.isWorking) maybeSpawn(model, deltaMs);
    pruneAgents(model);
    countEnded(model);
  };

  const advanceModel = (model, deltaMs) => {
    let remaining = deltaMs;
    while (remaining > 0) {
      const step = Math.min(remaining, MAX_STEP_MS);
      stepModel(model, step);
      remaining -= step;
    }
  };

  const createModel = (seed) => {
    const random = createRandom(seed);
    const main = {
      id: 0,
      name: "main session",
      group: "main",
      state: "live",
      endedAt: null,
      detail: "",
      limit: Number.POSITIVE_INFINITY,
      spans: [],
    };
    const model = {
      random,
      now: SEED_START_MS,
      sessionStart: SEED_START_MS,
      main,
      agents: [],
      spawned: 0,
      prunedDone: 0,
      prunedFailed: 0,
      done: 0,
      failed: 0,
      isWorking: false,
      turnStart: SEED_START_MS,
      turnEnd: SEED_START_MS,
      idleEnd: SEED_START_MS,
      lastTurnMs: 0,
      cacheCalledAt: SEED_START_MS,
    };
    startTurn(model);
    advanceModel(model, -SEED_START_MS);
    model.cacheCalledAt = -18 * MINUTE;
    return model;
  };

  const pad = (value) => String(value).padStart(2, "0");

  const formatClock = (ms) => {
    const total = Math.max(0, Math.floor(ms / SECOND));
    return `${Math.floor(total / 60)}:${pad(total % 60)}`;
  };

  const formatSpan = (ms) => {
    if (ms < 90 * SECOND) return `${Math.max(1, Math.round(ms / SECOND))}s`;
    if (ms < 10 * MINUTE && ms % MINUTE !== 0) return `${Math.floor(ms / MINUTE)}m${pad(Math.round((ms % MINUTE) / SECOND))}s`;
    if (ms < 90 * MINUTE) return `${Math.round(ms / MINUTE)}m`;
    return `${Math.round(ms / HOUR)}h`;
  };

  const formatRemaining = (ms) => {
    const hours = Math.floor(ms / HOUR);
    const minutes = Math.floor((ms % HOUR) / MINUTE);
    if (hours >= 24) return `${Math.floor(hours / 24)}d${hours % 24}h`;
    return `${hours}h${pad(minutes)}`;
  };

  const readGauges = (model) => {
    const seconds = model.now / SECOND;
    const contextK = 93 + seconds * 0.05;
    const cacheReadK = 319 + seconds * 0.2;
    return {
      ctx: { pct: contextK / 10, detail: `${Math.round(contextK)}k/1M ↻${Math.round(cacheReadK)}k` },
      five: { pct: 35 + seconds * 0.004, detail: `in ${formatRemaining(3 * HOUR + 16 * MINUTE - model.now)}` },
      week: { pct: 11 + seconds * 0.0004, detail: `in ${formatRemaining(6 * 24 * HOUR + HOUR - model.now)}` },
    };
  };

  const create = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };

  const required = (root, selector) => {
    const node = root.querySelector(selector);
    if (!node) throw new Error(`The band page is missing ${selector}.`);
    return node;
  };

  const readRangeMs = (model, rangeMs) => (rangeMs === 0 ? Math.max(model.now - model.sessionStart, MINUTE) : rangeMs);

  const currentKind = (agent) => {
    if (agent.state !== "live") return agent.state;
    const current = lastSpan(agent);
    return current.end === null ? current.kind : "idle";
  };

  const drawSpans = (track, agent, windowStart, rangeMs, now) => {
    const runs = [];
    const lastIndex = agent.spans.length - 1;
    agent.spans.forEach((span, index) => {
      const end = span.end ?? Math.min(now, span.plannedEnd);
      const start = Math.max(span.start, windowStart);
      if (end <= windowStart || end <= start) return;
      const isEndMark = index === lastIndex && agent.state !== "live";
      runs.push({ kind: isEndMark ? agent.state : span.kind, start, end });
    });
    if (runs.length === 0) {
      track.replaceChildren();
      return;
    }
    const laneStart = runs[0].start;
    const laneEnd = runs[runs.length - 1].end;
    const laneSpan = Math.max(1, laneEnd - laneStart);
    const lane = create("div", "ab-lane");
    lane.style.insetInlineStart = `${((laneStart - windowStart) / rangeMs) * 100}%`;
    lane.style.inlineSize = `${((laneEnd - laneStart) / rangeMs) * 100}%`;
    for (const run of runs) {
      const node = create("span", `ab-span is-${run.kind}`);
      node.style.insetInlineStart = `${((run.start - laneStart) / laneSpan) * 100}%`;
      node.style.inlineSize = `${((run.end - run.start) / laneSpan) * 100}%`;
      lane.append(node);
    }
    track.replaceChildren(lane);
  };

  const setPill = (row, agent) => {
    const current = lastSpan(agent);
    const isBetween = currentKind(agent) === "idle";
    const kind = isBetween ? current.kind : currentKind(agent);
    const isMain = agent.group === "main";
    const isIdle = isMain && kind === "launched";
    row.pill.className = `ab-pill is-${kind}`;
    row.pill.textContent = isMain ? MAIN_PILL_TEXT[kind] : PILL_TEXT[kind];
    const isEnded = agent.state !== "live";
    let detail = agent.detail;
    if (agent.state === "live") detail = isIdle ? "waiting for a prompt" : current.label;
    row.detail.textContent = detail;
    row.detail.classList.toggle("is-ended", isEnded || isIdle);
    row.name.classList.toggle("is-ended", isEnded);
  };

  const createRow = (agent, isMain) => {
    const element = create("div", "ab-row");
    const name = create("span", `ab-name${isMain ? "" : " is-strong"}`, agent.name);
    const track = create("div", "ab-track");
    const state = create("div", "ab-state");
    const pill = create("span", "ab-pill");
    const detail = create("span", "ab-detail");
    state.append(pill, detail);
    element.append(name, track, state);
    return { element, name, track, pill, detail, agent };
  };

  const chooseVisible = (model, windowStart) => {
    const candidates = model.agents.filter((agent) => agent.state === "live" || agent.endedAt >= windowStart - LINGER_MS);
    const ranked = [...candidates].sort((left, right) => {
      if ((left.state === "live") !== (right.state === "live")) return left.state === "live" ? -1 : 1;
      return left.state === "live" ? left.spawnedAt - right.spawnedAt : right.endedAt - left.endedAt;
    });
    const shown = new Set(ranked.slice(0, MAX_ROWS).map((agent) => agent.id));
    return ranked.filter((agent) => shown.has(agent.id));
  };

  const STRIP_BINS = 60;
  const STRIP_HEIGHT = 16;
  const SVG_NS = "http://www.w3.org/2000/svg";

  const kindAt = (agent, at, now) => {
    for (const span of agent.spans) {
      const end = span.end ?? Math.min(now, span.plannedEnd);
      if (span.start <= at && at < end) return span.kind;
    }
    return null;
  };

  const stepPath = (heights, bottoms) => {
    const x = (bin) => bin;
    let path = `M0 ${heights[0]}`;
    for (let bin = 0; bin < heights.length; bin += 1) path += `H${x(bin + 1)}${bin + 1 < heights.length ? `V${heights[bin + 1]}` : ""}`;
    path += `V${bottoms[bottoms.length - 1]}`;
    for (let bin = bottoms.length - 1; bin >= 0; bin -= 1) path += `H${x(bin)}${bin > 0 ? `V${bottoms[bin - 1]}` : ""}`;
    return `${path}Z`;
  };

  const drawStrip = (svg, agents, windowStart, rangeMs, now) => {
    const live = agents.filter((agent) => agent.state === "live" || agent.endedAt > windowStart);
    const series = Array.from({ length: STRIP_BINS }, (_, bin) => {
      const at = windowStart + ((bin + 0.5) / STRIP_BINS) * rangeMs;
      const counts = { tool: 0, thinking: 0, waiting: 0 };
      for (const agent of live) {
        const kind = kindAt(agent, at, now);
        if (kind === "tool" || kind === "thinking" || kind === "waiting") counts[kind] += 1;
      }
      return counts;
    });
    const peak = Math.max(1, ...series.map((counts) => counts.tool + counts.thinking + counts.waiting));
    const base = STRIP_HEIGHT - 1;
    const scale = (base - 1) / peak;
    const floors = series.map(() => base);
    const nodes = [];
    for (const kind of ["tool", "thinking", "waiting"]) {
      const tops = series.map((counts, bin) => Number((floors[bin] - counts[kind] * scale).toFixed(2)));
      if (series.some((counts) => counts[kind] > 0)) {
        const path = document.createElementNS(SVG_NS, "path");
        path.setAttribute("class", `ab-strip-${kind}`);
        path.setAttribute("d", stepPath(tops, floors));
        nodes.push(path);
      }
      tops.forEach((top, bin) => {
        floors[bin] = top;
      });
    }
    const line = document.createElementNS(SVG_NS, "path");
    line.setAttribute("class", "ab-strip-base");
    line.setAttribute("d", `M0 ${base + 0.5}H${STRIP_BINS}`);
    svg.replaceChildren(line, ...nodes);
  };

  const groupCountsText = (group) => {
    const live = group.agents.filter((agent) => agent.state === "live");
    const count = (kind) => live.filter((agent) => currentKind(agent) === kind).length;
    const entries = [
      [count("tool"), "tool"],
      [count("thinking"), "think"],
      [count("waiting"), "wait"],
      [group.agents.length - live.length, "ended"],
    ];
    const parts = entries.filter(([amount]) => amount > 0).map(([amount, word]) => `${amount} ${word}`);
    return parts.length === 0 ? "idle" : parts.join(" · ");
  };

  const groupSignature = (groups, collapsed) =>
    groups
      .map((group) => `${group.key}${collapsed.has(group.key) ? "c" : "o"}${group.agents.map((agent) => agent.id).join(",")}`)
      .join("|");

  const createBand = (root, model, options) => {
    const view = {
      status: required(root, "[data-status]"),
      turn: required(root, "[data-turn]"),
      cache: required(root, "[data-cache]"),
      live: required(root, "[data-live]"),
      done: required(root, "[data-done]"),
      fail: required(root, "[data-fail]"),
      axisStart: required(root, "[data-axis-start]"),
      axisMiddle: required(root, "[data-axis-middle]"),
      rows: required(root, "[data-rows]"),
      earlier: required(root, "[data-earlier]"),
      foldLabel: required(root, "[data-fold-label]"),
      foldButton: required(root, "[data-fold]"),
      gauges: new Map(),
    };
    for (const node of root.querySelectorAll("[data-gauge]")) {
      view.gauges.set(node.dataset.gauge, {
        arc: required(node, "[data-arc]"),
        pct: required(node, "[data-pct]"),
        detail: required(node, "[data-detail]"),
      });
    }
    const state = {
      rangeMs: options.rangeMs,
      isFolded: false,
      collapsed: new Set(),
      signature: "",
      mainRow: null,
      agentRows: new Map(),
      groupHeads: new Map(),
    };

    const rebuildRows = (groups) => {
      const focusedKey = document.activeElement instanceof HTMLElement ? document.activeElement.dataset.group : undefined;
      state.agentRows.clear();
      state.groupHeads.clear();
      state.mainRow = createRow(model.main, true);
      const nodes = [state.mainRow.element];
      for (const group of groups) {
        const head = create("button", `ab-group${state.collapsed.has(group.key) ? " is-collapsed" : ""}`);
        head.type = "button";
        head.dataset.group = group.key;
        head.setAttribute("aria-expanded", String(!state.collapsed.has(group.key)));
        const line = create("span", "ab-group-row");
        const count = create("span", "ab-group-count");
        const title = create("span", "ab-group-title");
        title.append(create("span", "ab-chevron"), create("span", "ab-group-tag", group.tag), create("span", "ab-group-name", group.name.replace(/^workflow: /, "")));
        title.firstChild.setAttribute("aria-hidden", "true");
        line.append(title);
        let strip = null;
        if (state.collapsed.has(group.key)) {
          strip = document.createElementNS(SVG_NS, "svg");
          strip.setAttribute("class", "ab-strip");
          strip.setAttribute("viewBox", `0 0 ${STRIP_BINS} ${STRIP_HEIGHT}`);
          strip.setAttribute("preserveAspectRatio", "none");
          strip.setAttribute("aria-hidden", "true");
          line.classList.add("is-strip");
          line.append(strip);
        }
        line.append(count);
        head.append(line);
        state.groupHeads.set(group.key, { count, strip });
        nodes.push(head);
        if (state.collapsed.has(group.key)) continue;
        for (const agent of group.agents) {
          const row = createRow(agent, false);
          state.agentRows.set(agent.id, row);
          nodes.push(row.element);
        }
      }
      view.rows.replaceChildren(...nodes);
      if (focusedKey) view.rows.querySelector(`[data-group="${focusedKey}"]`)?.focus();
    };

    const render = () => {
      const rangeMs = readRangeMs(model, state.rangeMs);
      const windowStart = model.now - rangeMs;
      const visible = chooseVisible(model, windowStart);
      const groups = GROUPS.map((group) => ({ ...group, agents: visible.filter((agent) => agent.group === group.key) })).filter(
        (group) => group.agents.length > 0,
      );
      const signature = groupSignature(groups, state.collapsed);
      if (signature !== state.signature) {
        state.signature = signature;
        rebuildRows(groups);
      }
      if (state.mainRow) {
        drawSpans(state.mainRow.track, model.main, windowStart, rangeMs, model.now);
        setPill(state.mainRow, model.main);
      }
      for (const row of state.agentRows.values()) {
        drawSpans(row.track, row.agent, windowStart, rangeMs, model.now);
        setPill(row, row.agent);
      }
      for (const group of groups) {
        const head = state.groupHeads.get(group.key);
        if (head.strip) {
          drawStrip(head.strip, group.agents, windowStart, rangeMs, model.now);
          head.count.textContent = groupCountsText(group);
        } else {
          const live = group.agents.filter((agent) => agent.state === "live").length;
          head.count.textContent = `${live} live · ${group.agents.length - live} ended`;
        }
      }
      view.axisStart.textContent = `-${formatSpan(rangeMs)}`;
      view.axisMiddle.textContent = `-${formatSpan(rangeMs / 2)}`;
      const earlier = model.spawned - visible.length;
      view.earlier.textContent = earlier > 0 ? `+${earlier} earlier` : "";
      view.earlier.hidden = earlier <= 0;
      renderSummary();
    };

    const renderSummary = () => {
      view.status.textContent = model.isWorking ? "WORKING" : "IDLE";
      view.status.classList.toggle("is-idle", !model.isWorking);
      view.turn.textContent = model.isWorking
        ? `turn ${formatClock(model.now - model.turnStart)}`
        : `last turn ${formatClock(model.lastTurnMs)}`;
      const coldMs = CACHE_LIFETIME_MS - (model.now - model.cacheCalledAt);
      view.cache.textContent = coldMs > 0 ? `cold in ~${Math.ceil(coldMs / MINUTE)}m` : "cold";
      const live = liveAgents(model).length;
      view.live.textContent = `${live} live`;
      view.done.textContent = `${model.done} done`;
      view.fail.textContent = `${model.failed} fail`;
      const gauges = readGauges(model);
      for (const [key, values] of Object.entries(gauges)) {
        const gauge = view.gauges.get(key);
        if (!gauge) continue;
        const pct = Math.min(100, values.pct);
        gauge.arc.setAttribute("stroke-dasharray", `${pct.toFixed(1)} 100`);
        gauge.pct.textContent = `${Math.round(pct)}%`;
        gauge.detail.textContent = values.detail;
      }
    };

    const setRange = (rangeMs) => {
      state.rangeMs = rangeMs;
      for (const button of root.querySelectorAll("[data-range]")) {
        button.setAttribute("aria-pressed", String(Number(button.dataset.range) === rangeMs));
      }
      render();
    };

    const toggleFold = () => {
      state.isFolded = !state.isFolded;
      root.classList.toggle("is-folded", state.isFolded);
      view.foldButton.classList.toggle("is-folded", state.isFolded);
      view.foldButton.setAttribute("aria-expanded", String(!state.isFolded));
      view.foldLabel.textContent = state.isFolded ? "unfold" : "fold";
    };

    const toggleGroup = (key) => {
      if (state.collapsed.has(key)) state.collapsed.delete(key);
      else state.collapsed.add(key);
      state.signature = "";
      render();
    };

    root.addEventListener("click", (event) => {
      if (!(event.target instanceof Element)) return;
      const rangeButton = event.target.closest("[data-range]");
      if (rangeButton instanceof HTMLElement) return setRange(Number(rangeButton.dataset.range));
      if (event.target.closest("[data-fold]")) return toggleFold();
      const groupButton = event.target.closest("[data-group]");
      if (groupButton instanceof HTMLElement && groupButton.dataset.group) toggleGroup(groupButton.dataset.group);
    });

    return { render };
  };

  const bindTheme = (button) => {
    const page = document.documentElement;
    const applyTheme = (theme) => {
      page.dataset.theme = theme;
      button.setAttribute("aria-checked", String(theme === "dark"));
    };
    button.addEventListener("click", () => {
      const theme = page.dataset.theme === "dark" ? "dark" : "light";
      const next = theme === "dark" ? "light" : "dark";
      applyTheme(next);
      try {
        localStorage.setItem(THEME_KEY, next);
      } catch (error) {
        console.warn("The theme could not be saved.", error);
      }
    });
    applyTheme(page.dataset.theme === "dark" ? "dark" : "light");
  };

  const bindPause = (button, onChange, isPausedAtStart) => {
    let isPaused = isPausedAtStart;
    const show = () => {
      button.textContent = isPaused ? "Resume" : "Pause";
      button.setAttribute("aria-pressed", String(isPaused));
    };
    button.addEventListener("click", () => {
      isPaused = !isPaused;
      show();
      onChange(isPaused);
    });
    show();
  };

  const start = () => {
    const root = required(document, "[data-band]");
    bindTheme(required(document, "[data-theme-toggle]"));
    const model = createModel(Date.now());
    const band = createBand(root, model, { rangeMs: 5 * MINUTE });
    band.render();
    let isPaused = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let lastReal = performance.now();
    bindPause(
      required(document, "[data-pause]"),
      (value) => {
        isPaused = value;
        lastReal = performance.now();
      },
      isPaused,
    );
    window.setInterval(() => {
      const real = performance.now();
      const elapsed = Math.min(real - lastReal, 2 * SECOND);
      lastReal = real;
      if (isPaused) return;
      advanceModel(model, elapsed * SPEED);
      band.render();
    }, TICK_MS);
  };

  start();
}

{
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

  for (const root of document.querySelectorAll("[data-install]")) bindInstall(root);
}
