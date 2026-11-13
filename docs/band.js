{
  const THEME_KEY = "harness-map-theme";
  const SECOND = 1000;
  const MINUTE = 60 * SECOND;
  const HOUR = 60 * MINUTE;
  const SPEED = 6;
  const TICK_MS = 250;
  const MAX_REAL_STEP_MS = SECOND;
  const SIM_STEP_MS = 500;
  const SEED_MS = 6 * MINUTE;
  const SESSION_AGE_MS = 47 * MINUTE;
  const STRIP_CELLS = 24;
  const LANE_CELLS = 56;
  const LANE_WIDTH = 112;
  const LANE_STEP = 4;
  const LANE_HEIGHT = 3;
  const MAX_LANES = 4;
  const MAX_TILES = 12;
  const MAX_KEPT_ENDED = 150;
  const CELL_WIDTH = 5;
  const CELL_GAP = 1;
  const CELL_HEIGHT = 8;
  const LANE_RANGE_MS = 5 * MINUTE;
  const FAIL_CHANCE = 0.15;
  const PERMISSION_CHANCE = 0.12;
  const HIGH_PERCENT = 80;
  const CRITICAL_PERCENT = 95;
  const CONTEXT_WINDOW_TOKENS = 1_000_000;
  const RING_SIZE = 26;
  const RING_OUTER_RADIUS = 11.5;
  const RING_STEP = 3;
  const BAR_WIDTH = 100;
  const BAR_HEIGHT = 4;
  const SVG_NAMESPACE = "http://www.w3.org/2000/svg";
  const RANGE_MS = { "1m": MINUTE, "5m": 5 * MINUTE, "1h": HOUR, all: 0 };
  const PRICE_PER_MILLION = { opus: { input: 5, output: 25 }, sonnet: { input: 3, output: 15 }, haiku: { input: 1, output: 5 } };

  const ROLES = [
    { role: "scout", model: "haiku", tasks: ["hooks", "docs", "skills", "tests", "port"] },
    { role: "worker", model: "sonnet", tasks: ["band", "guard", "page", "cases", "report"] },
    { role: "reviewer", model: "opus", tasks: ["diff", "spec", "hooks"] },
    { role: "designer", model: "sonnet", tasks: ["tiles", "ring"] },
    { role: "researcher", model: "sonnet", tasks: ["api", "limits"] },
  ];

  const TOOLS = [
    { kind: "bash", targets: ["uv run pytest -q", "make check", "git diff --stat", "uvx ruff check", "make map"] },
    { kind: "editing", targets: ["docs/band.css", "hooks/guard.py", "mods/band/hooks/arcs.ts", "skills/design/SKILL.md"] },
    { kind: "reading", targets: ["hooks/turn.py", "AGENTS.md", "docs/build_map.py", "README.md"] },
    { kind: "searching", targets: ['rg -n "budget" hooks', "**/*.tsx", 'rg -n "ring" mods'] },
    { kind: "web", targets: ["docs.claude.com/en/docs/claude-code"] },
  ];

  const ACTIVITY_ICON = {
    idle: "○",
    thinking: "⋯",
    permission: "⊘",
    bash: "❯",
    editing: "✎",
    reading: "≡",
    searching: "⌕",
    web: "⊕",
    done: "✓",
    failed: "✕",
  };

  const ACTIVITY_WORD = {
    idle: "idle",
    thinking: "thinking",
    permission: "waiting",
    bash: "bash",
    editing: "editing",
    reading: "reading",
    searching: "searching",
    web: "web",
    done: "done",
    failed: "failed",
  };

  const ARC_DEFINITIONS = {
    fiveHour: { name: "5-hour", short: "5h", suffix: "five" },
    week: { name: "Week", short: "Wk", suffix: "week" },
    fable: { name: "Fable", short: "Fable", suffix: "fable" },
    context: { name: "Context", short: "Ctx", suffix: "context" },
  };

  const FAIL_REASONS = ["tests failed", "merge conflict", "gave up after 3 tries"];

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

  const pickFrom = (random, list) => list[Math.floor(random() * list.length)];
  const between = (random, low, high) => low + random() * (high - low);
  const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
  const pad = (value) => String(value).padStart(2, "0");

  const formatAge = (milliseconds) => {
    const seconds = Math.max(0, Math.floor(milliseconds / SECOND));
    if (seconds < 60) return `${seconds}s`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m${pad(seconds % 60)}s`;
    return `${Math.floor(seconds / 3600)}h${pad(Math.floor((seconds % 3600) / 60))}m`;
  };

  const formatSpan = (milliseconds) => {
    const seconds = Math.max(0, Math.floor(milliseconds / SECOND));
    if (seconds < 60) return `${seconds}s`;
    const minutes = Math.floor(seconds / 60);
    return minutes < 60 ? `${minutes}m` : `${Math.floor(minutes / 60)}h`;
  };

  const formatTokens = (tokens) => {
    if (tokens >= 1_000_000) return `${Number((tokens / 1_000_000).toFixed(1))}M`;
    if (tokens >= 1000) return `${Math.round(tokens / 1000)}k`;
    return String(Math.round(tokens));
  };

  const formatUsd = (usd) => `$${usd.toFixed(2)}`;

  const costOf = (model, tokensIn, tokensOut) => {
    const price = PRICE_PER_MILLION[model];
    return (tokensIn * price.input + tokensOut * price.output) / 1_000_000;
  };

  const lastSegmentIn = (segments, from, to) => {
    let found = null;
    for (const segment of segments) {
      const end = segment.to ?? Infinity;
      if (segment.from < to && end > from) found = segment;
    }
    return found;
  };

  const openSegment = (row, state, at) => {
    const last = row.segments.at(-1);
    if (last && last.to === null) last.to = at;
    row.segments.push({ state, from: at, to: null });
    row.state = state;
  };

  const createAgent = (random, counter, now) => {
    const spec = pickFrom(random, ROLES);
    const row = {
      id: `agent-${counter}`,
      label: `${spec.role}-${pickFrom(random, spec.tasks)}`,
      model: spec.model,
      startedAt: now,
      endedAt: null,
      state: "thinking",
      tool: null,
      permission: false,
      failReason: "",
      plannedEnd: now + between(random, 30 * SECOND, 90 * SECOND),
      nextChangeAt: now + between(random, 2 * SECOND, 6 * SECOND),
      tokensIn: 0,
      tokensOut: 0,
      segments: [],
    };
    openSegment(row, "thinking", now);
    return row;
  };

  const createMain = (now) => ({
    id: "main",
    label: "main",
    model: "opus",
    startedAt: now,
    endedAt: null,
    state: "thinking",
    tool: null,
    permission: false,
    failReason: "",
    plannedEnd: Infinity,
    nextChangeAt: now,
    tokensIn: 8_100_000,
    tokensOut: 92_000,
    segments: [{ state: "thinking", from: now, to: null }],
  });

  const createModel = () => {
    const random = createRandom(20260513);
    const sessionStart = -SESSION_AGE_MS;
    const model = {
      random,
      now: -SEED_MS,
      sessionStart,
      counter: 0,
      desiredLive: 2,
      nextDesiredAt: -SEED_MS,
      main: createMain(sessionStart),
      agents: [],
      evictedDone: 0,
      evictedFailed: 0,
      retiredUsd: 0,
      retiredIn: 0,
      retiredOut: 0,
      mainUsd: 35.08,
      limits: { fiveHour: 23, week: 57, fable: 82 },
      contextTokens: 99_000,
    };
    advance(model, SEED_MS);
    return model;
  };

  const setTool = (random, row) => {
    const spec = pickFrom(random, TOOLS);
    row.tool = { kind: spec.kind, target: pickFrom(random, spec.targets) };
    row.permission = random() < PERMISSION_CHANCE && spec.kind !== "reading";
  };

  const stepAgent = (model, row, now) => {
    const { random } = model;
    if (now >= row.plannedEnd) {
      const failed = random() < FAIL_CHANCE;
      row.endedAt = now;
      row.failReason = failed ? pickFrom(random, FAIL_REASONS) : "";
      openSegment(row, failed ? "failed" : "done", now);
      row.segments.at(-1).to = now + SECOND;
      return;
    }
    if (now < row.nextChangeAt) return;
    if (row.state === "waiting") {
      openSegment(row, "tool", now);
      row.nextChangeAt = now + between(random, 5 * SECOND, 20 * SECOND);
      return;
    }
    if (row.state === "tool") {
      openSegment(row, "thinking", now);
      row.nextChangeAt = now + between(random, 4 * SECOND, 14 * SECOND);
      return;
    }
    setTool(random, row);
    if (row.permission) {
      openSegment(row, "waiting", now);
      row.nextChangeAt = now + between(random, 4 * SECOND, 10 * SECOND);
      return;
    }
    openSegment(row, "tool", now);
    row.nextChangeAt = now + between(random, 6 * SECOND, 24 * SECOND);
  };

  const stepMain = (model, now) => {
    const { random, main } = model;
    if (now < main.nextChangeAt) return;
    const hasLive = model.agents.some((row) => row.endedAt === null);
    const roll = random();
    if (roll < (hasLive ? 0.45 : 0.1)) {
      openSegment(main, "launched", now);
      main.nextChangeAt = now + between(random, 6 * SECOND, 18 * SECOND);
      return;
    }
    if (roll < 0.75) {
      openSegment(main, "thinking", now);
      main.tool = null;
      main.nextChangeAt = now + between(random, 5 * SECOND, 15 * SECOND);
      return;
    }
    setTool(random, main);
    main.permission = false;
    openSegment(main, "tool", now);
    main.nextChangeAt = now + between(random, 4 * SECOND, 14 * SECOND);
  };

  const grow = (model, stepMs) => {
    const seconds = stepMs / SECOND;
    const live = model.agents.filter((row) => row.endedAt === null);
    let busySeconds = 0;
    for (const row of live) {
      if (row.state === "waiting") continue;
      row.tokensIn += seconds * (row.state === "tool" ? 1900 : 700);
      row.tokensOut += seconds * (row.state === "tool" ? 25 : 70);
      busySeconds += seconds;
    }
    const main = model.main;
    if (main.state === "thinking" || main.state === "tool") {
      main.tokensIn += seconds * 9000;
      main.tokensOut += seconds * 60;
      model.mainUsd += seconds * 0.011;
      model.contextTokens += seconds * 260;
      busySeconds += seconds;
    }
    if (model.contextTokens > CONTEXT_WINDOW_TOKENS * (CRITICAL_PERCENT / 100)) model.contextTokens = CONTEXT_WINDOW_TOKENS * 0.14;
    model.limits.fiveHour = Math.min(99.4, model.limits.fiveHour + busySeconds * 0.0016);
    model.limits.week = Math.min(99.4, model.limits.week + busySeconds * 0.0002);
    model.limits.fable = Math.min(99.4, model.limits.fable + busySeconds * 0.0006);
  };

  const evictOld = (model) => {
    const ended = model.agents.filter((row) => row.endedAt !== null);
    const surplus = ended.length - MAX_KEPT_ENDED;
    if (surplus <= 0) return;
    const gone = new Set(ended.slice(0, surplus));
    for (const row of gone) {
      if (row.state === "done") model.evictedDone += 1;
      else model.evictedFailed += 1;
      model.retiredUsd += costOf(row.model, row.tokensIn, row.tokensOut);
      model.retiredIn += row.tokensIn;
      model.retiredOut += row.tokensOut;
    }
    model.agents = model.agents.filter((row) => !gone.has(row));
  };

  const advance = (model, elapsedMs) => {
    const target = model.now + elapsedMs;
    while (model.now < target) {
      const step = Math.min(SIM_STEP_MS, target - model.now);
      model.now += step;
      const now = model.now;
      if (now >= model.nextDesiredAt) {
        model.desiredLive = 1 + Math.floor(model.random() * 4);
        model.nextDesiredAt = now + between(model.random, 20 * SECOND, 60 * SECOND);
      }
      stepMain(model, now);
      for (const row of model.agents) if (row.endedAt === null) stepAgent(model, row, now);
      const liveCount = model.agents.filter((row) => row.endedAt === null).length;
      if (liveCount < model.desiredLive && model.random() < 0.14) {
        model.counter += 1;
        model.agents.push(createAgent(model.random, model.counter, now));
      }
      grow(model, step);
    }
    evictOld(model);
  };

  const activityOf = (row, now) => {
    const isMain = row.id === "main";
    if (row.state === "done") return { kind: "done", detail: "", tone: "done" };
    if (row.state === "failed") return { kind: "failed", detail: row.failReason, tone: "fail" };
    if (row.state === "waiting") return { kind: "permission", detail: "permission: Bash", tone: "warn" };
    if (row.state === "launched") {
      const last = row.segments.at(-1);
      return { kind: "idle", detail: `since ${formatSpan(now - last.from)}`, tone: "idle" };
    }
    if (row.state === "tool" && row.tool) return { kind: row.tool.kind, detail: row.tool.target, tone: isMain ? "ink" : "run" };
    return { kind: "thinking", detail: "", tone: isMain ? "ink" : "run" };
  };

  const cellKindOf = (row, state) => {
    if (row.id === "main") {
      if (state === "tool") return "ink";
      if (state === "thinking") return "ink-soft";
      if (state === "waiting") return "warn";
      return "idle";
    }
    if (row.state === "done" || row.state === "failed") {
      const ended = row.state === "done" ? "done" : "fail";
      if (state === "tool") return ended;
      if (state === "done") return "done";
      if (state === "failed") return "fail";
      return `${ended}-soft`;
    }
    if (state === "tool") return "run";
    if (state === "waiting") return "warn";
    return "run-soft";
  };

  const cellsOf = (row, windowStart, windowEnd, count) => {
    const length = (windowEnd - windowStart) / count;
    return Array.from({ length: count }, (_, index) => {
      const from = windowStart + index * length;
      const segment = lastSegmentIn(row.segments, from, from + length);
      if (!segment) return "empty";
      return cellKindOf(row, segment.state);
    });
  };

  const windowOf = (model, rangeName) => {
    const length = RANGE_MS[rangeName];
    if (length === 0) return { start: Math.min(model.sessionStart, model.now - MINUTE), end: model.now };
    return { start: model.now - length, end: model.now };
  };

  const countsOf = (model) => {
    const live = model.agents.filter((row) => row.endedAt === null).length;
    const done = model.agents.filter((row) => row.state === "done").length + model.evictedDone;
    const failed = model.agents.filter((row) => row.state === "failed").length + model.evictedFailed;
    return { live, done, failed };
  };

  const spendOf = (model) => {
    let agentsUsd = model.retiredUsd;
    let tokensIn = model.main.tokensIn + model.retiredIn;
    let tokensOut = model.main.tokensOut + model.retiredOut;
    for (const row of model.agents) {
      agentsUsd += costOf(row.model, row.tokensIn, row.tokensOut);
      tokensIn += row.tokensIn;
      tokensOut += row.tokensOut;
    }
    return { sessionUsd: model.mainUsd + agentsUsd, mainUsd: model.mainUsd, agentsUsd, tokensIn, tokensOut };
  };

  const arcsOf = (model, billing) => {
    const context = {
      id: "context",
      percent: (model.contextTokens / CONTEXT_WINDOW_TOKENS) * 100,
      reset: null,
      usage: [formatTokens(model.contextTokens), formatTokens(CONTEXT_WINDOW_TOKENS)],
    };
    if (billing === "api") return [context];
    return [
      { id: "fiveHour", percent: model.limits.fiveHour, reset: "13:50", usage: null },
      { id: "week", percent: model.limits.week, reset: "Sun 04:00", usage: null },
      { id: "fable", percent: model.limits.fable, reset: "Sun 04:00", usage: null },
      context,
    ];
  };

  const svgElement = (name, attributes) => {
    const element = document.createElementNS(SVG_NAMESPACE, name);
    for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, String(value));
    return element;
  };

  const textElement = (tag, text, className = "") => {
    const element = document.createElement(tag);
    element.textContent = text;
    if (className) element.className = className;
    return element;
  };

  const percentText = (percent) => `${Math.round(percent)}%${percent >= HIGH_PERCENT ? " ▲" : ""}`;

  const toneOfPercent = (percent) => {
    if (percent >= CRITICAL_PERCENT) return "tone-fail";
    return percent >= HIGH_PERCENT ? "tone-warn" : "";
  };

  const percentElement = (percent) => {
    const element = textElement("span", percentText(percent), toneOfPercent(percent));
    if (percent >= HIGH_PERCENT) element.classList.add("is-bold");
    return element;
  };

  const stripShapes = (cells, cellWidth, cellGap, height, radius, groundOnEmpty) => {
    const shapes = [];
    cells.forEach((kind, index) => {
      const x = index * (cellWidth + cellGap);
      if (kind === "empty" || kind === "idle") {
        if (!groundOnEmpty) return;
        shapes.push(svgElement("rect", { x, y: 0, width: cellWidth, height, rx: radius, class: "fill-rail" }));
        if (kind === "idle") shapes.push(svgElement("rect", { x: x + (cellWidth - 2) / 2, y: (height - 2) / 2, width: 2, height: 2, rx: 1, class: "fill-muted" }));
        return;
      }
      shapes.push(svgElement("rect", { x, y: 0, width: cellWidth, height, rx: radius, class: `fill-${kind}` }));
    });
    return shapes;
  };

  const drawStrip = (svg, cells) => {
    svg.replaceChildren(...stripShapes(cells, CELL_WIDTH, CELL_GAP, CELL_HEIGHT, 1, true));
  };

  const drawLane = (svg, lanes) => {
    const shapes = [];
    const cellWidth = LANE_WIDTH / LANE_CELLS;
    lanes.forEach((cells, index) => {
      const y = index * LANE_STEP;
      shapes.push(svgElement("rect", { x: 0, y, width: LANE_WIDTH, height: LANE_HEIGHT, class: "fill-rail" }));
      let runStart = 0;
      cells.forEach((kind, cellIndex) => {
        const isEnd = cellIndex === cells.length - 1 || cells[cellIndex + 1] !== kind;
        if (!isEnd) return;
        const x = runStart * cellWidth;
        const width = Math.max(1, (cellIndex - runStart + 1) * cellWidth);
        runStart = cellIndex + 1;
        if (kind === "empty") return;
        if (kind === "idle") shapes.push(svgElement("rect", { x, y: y + 1, width, height: 1, class: "fill-muted" }));
        else shapes.push(svgElement("rect", { x, y, width, height: LANE_HEIGHT, class: `fill-${kind}` }));
      });
    });
    shapes.push(svgElement("rect", { x: LANE_WIDTH - 1, y: 0, width: 1, height: LANE_HEIGHT + (Math.max(1, lanes.length) - 1) * LANE_STEP, class: "fill-ink" }));
    svg.replaceChildren(...shapes);
  };

  const drawRing = (svg, arcs) => {
    const center = RING_SIZE / 2;
    const circles = arcs.flatMap((arc, index) => {
      const radius = RING_OUTER_RADIUS - index * RING_STEP;
      const circumference = 2 * Math.PI * radius;
      const filled = (circumference * clamp(arc.percent, 0, 100)) / 100;
      const common = { cx: center, cy: center, r: radius };
      return [
        svgElement("circle", { ...common, class: "stroke-rail" }),
        svgElement("circle", {
          ...common,
          class: `stroke-arc-${ARC_DEFINITIONS[arc.id].suffix}`,
          "stroke-dasharray": `${filled.toFixed(2)} ${circumference.toFixed(2)}`,
          transform: `rotate(-90 ${center} ${center})`,
        }),
      ];
    });
    svg.replaceChildren(...circles);
    svg.setAttribute("aria-label", arcs.map((arc) => `${ARC_DEFINITIONS[arc.id].name} ${Math.round(arc.percent)}%`).join(", "));
  };

  const drawBar = (percent, id) => {
    const svg = svgElement("svg", { class: "limit-bar", viewBox: `0 0 ${BAR_WIDTH} ${BAR_HEIGHT}`, preserveAspectRatio: "none", role: "img", "aria-label": `${ARC_DEFINITIONS[id].name} ${Math.round(percent)}%` });
    svg.append(svgElement("rect", { x: 0, y: 0, width: BAR_WIDTH, height: BAR_HEIGHT, rx: 2, class: "fill-rail" }));
    const width = Math.round(clamp(percent, 0, 100));
    if (width > 0) svg.append(svgElement("rect", { x: 0, y: 0, width, height: BAR_HEIGHT, rx: 2, class: `fill-arc-${ARC_DEFINITIONS[id].suffix}` }));
    return svg;
  };

  const dotElement = (id) => textElement("span", "●", `text-arc-${ARC_DEFINITIONS[id].suffix}`);

  const resetText = (arc) => (arc.reset === null ? "" : `↻${arc.reset}`);

  const legendItem = (arc) => {
    const item = textElement("span", "", "legend-item");
    item.append(dotElement(arc.id), textElement("strong", ARC_DEFINITIONS[arc.id].short), percentElement(arc.percent));
    const detail = arc.reset === null ? arc.usage.join("/") : resetText(arc);
    item.append(textElement("span", detail, "band-dim"));
    return item;
  };

  const legendOf = (arcs, spend, billing) => {
    const hasLimits = billing === "subscription";
    const columns = [arcs.filter((_, index) => index % 2 === 0), arcs.filter((_, index) => index % 2 === 1)];
    const cost = textElement("strong", formatUsd(spend.sessionUsd));
    const firstLines = (hasLimits ? 0 : 1) + columns[0].length;
    const isCostShorter = columns[1].length < firstLines;
    return columns.map((column, index) => {
      const element = document.createElement("div");
      element.className = "legend-column";
      if (index === 0 && !hasLimits) element.append(textElement("span", `API billing · ${formatTokens(spend.tokensIn)} in / ${formatTokens(spend.tokensOut)} out`, "band-dim"));
      column.forEach((arc, position) => {
        const isLast = position === column.length - 1;
        if (index === 1 && !isCostShorter && isLast) {
          const line = textElement("span", "", "legend-last");
          line.append(legendItem(arc), cost.cloneNode(true));
          element.append(line);
        } else element.append(legendItem(arc));
      });
      if (index === 1 && (isCostShorter || column.length === 0)) element.append(cost);
      return element;
    });
  };

  const activityText = (activity) => `${ACTIVITY_ICON[activity.kind]} ${ACTIVITY_WORD[activity.kind]}`;

  const factsOf = (row, activity, spend, now, isMain) => {
    const usd = isMain ? spend.mainUsd : costOf(row.model, row.tokensIn, row.tokensOut);
    const lifetime = (row.endedAt ?? now) - row.startedAt;
    return [
      ["now", activity.detail ? `${ACTIVITY_WORD[activity.kind]}: ${activity.detail}` : ACTIVITY_WORD[activity.kind]],
      ["model", row.model],
      [isMain ? "session age" : "ran for", formatAge(lifetime)],
      ["tokens in", `${formatTokens(row.tokensIn)} (cache reads included)`],
      ["tokens out", formatTokens(row.tokensOut)],
      [isMain ? "main est." : "cost", `~${formatUsd(usd)}${isMain ? " session total minus agents" : " estimated from tokens"}`],
    ];
  };

  const createTile = () => {
    const root = document.createElement("li");
    root.className = "tile";
    root.tabIndex = 0;
    const top = document.createElement("div");
    top.className = "tile-top";
    const name = textElement("strong", "", "tile-name");
    const model = textElement("span", "", "tile-model");
    const state = textElement("strong", "");
    const detail = textElement("span", "", "tile-detail");
    top.append(name, model, state, detail);
    const bottom = document.createElement("div");
    bottom.className = "tile-bottom";
    const strip = svgElement("svg", { class: "strip", viewBox: `0 0 ${STRIP_CELLS * (CELL_WIDTH + CELL_GAP) - CELL_GAP} ${CELL_HEIGHT}`, preserveAspectRatio: "none", role: "img" });
    const time = textElement("strong", "", "tile-time");
    const tokens = textElement("span", "", "tile-tokens");
    const cost = textElement("strong", "", "tile-cost");
    bottom.append(strip, time, tokens, cost);
    const card = document.createElement("div");
    card.className = "tile-card";
    card.setAttribute("aria-hidden", "true");
    const cardTitle = textElement("span", "", "tile-card-title");
    const facts = document.createElement("dl");
    card.append(cardTitle, facts);
    root.append(top, bottom, card);
    return { root, name, model, state, detail, strip, time, tokens, cost, cardTitle, facts };
  };

  const fillTile = (tile, row, model, windowRange, spend) => {
    const isMain = row.id === "main";
    const now = model.now;
    const activity = activityOf(row, now);
    const hasUsage = isMain || now - row.startedAt > 8 * SECOND;
    tile.name.textContent = row.label;
    tile.model.textContent = row.model;
    tile.state.textContent = activityText(activity);
    tile.state.className = `tone-${activity.tone}`;
    tile.detail.textContent = activity.detail;
    drawStrip(tile.strip, cellsOf(row, windowRange.start, windowRange.end, STRIP_CELLS));
    tile.strip.setAttribute("aria-label", `${row.label} activity over the range`);
    tile.time.textContent = formatAge(((row.endedAt ?? now) - (isMain ? model.sessionStart : row.startedAt)));
    tile.tokens.textContent = hasUsage ? `${formatTokens(row.tokensIn)}↓ ${formatTokens(row.tokensOut)}↑` : "no usage";
    tile.cost.textContent = hasUsage ? `~${formatUsd(isMain ? spend.mainUsd : costOf(row.model, row.tokensIn, row.tokensOut))}` : "";
    tile.root.classList.toggle("is-waiting", activity.kind === "permission");
    tile.root.setAttribute("aria-label", `${row.label}, ${activityText(activity)}`);
    tile.cardTitle.textContent = `${row.label} ${activityText(activity)}`;
    const rows = factsOf(row, activity, spend, now, isMain).map(([term, value]) => {
      const fact = document.createElement("div");
      fact.className = "fact";
      fact.append(textElement("dt", term), textElement("dd", value));
      return fact;
    });
    tile.facts.replaceChildren(...rows);
  };

  const createBand = (root, model, settings) => {
    const folded = root.querySelector('[data-view="folded"]');
    const open = root.querySelector('[data-view="open"]');
    const ring = root.querySelector("[data-ring]");
    const legend = root.querySelector("[data-legend]");
    const lane = root.querySelector("[data-lane]");
    const mainActivity = root.querySelector("[data-main-activity]");
    const limits = root.querySelector("[data-limits]");
    const spendList = root.querySelector("[data-spend]");
    const tileList = root.querySelector("[data-tiles]");
    const foldButtons = [...root.querySelectorAll("[data-fold]")];
    const rangeButtons = [...root.querySelectorAll("[data-range]")];
    const countGroups = [...root.querySelectorAll("[data-counts]")];
    const tiles = new Map();
    let ghost = { key: "", element: null };

    const showCounts = (counts) => {
      const symbols = { live: "▶", done: "✓", failed: "✕" };
      for (const group of countGroups) {
        for (const element of group.querySelectorAll("[data-count]")) {
          const key = element.dataset.count;
          element.textContent = `${symbols[key]}${counts[key]}`;
          element.classList.toggle("is-zero", counts[key] === 0);
        }
      }
    };

    const drawGutter = (arcs, spend) => {
      const blocks = arcs.map((arc) => {
        const block = document.createElement("div");
        const head = document.createElement("div");
        head.className = "limit-head";
        const name = textElement("span", "", "limit-name");
        name.append(dotElement(arc.id), textElement("strong", ARC_DEFINITIONS[arc.id].name), percentElement(arc.percent));
        head.append(name);
        const detail = arc.reset === null ? arc.usage.join(" of ") : `↻ ${arc.reset}`;
        head.append(textElement("span", detail, "band-dim"));
        block.append(head, drawBar(arc.percent, arc.id));
        return block;
      });
      limits.replaceChildren(...blocks);
      const lines = [
        ["session total", formatUsd(spend.sessionUsd), true],
        ["main est.", `~${formatUsd(spend.mainUsd)}`, false],
        ["agents est.", `~${formatUsd(spend.agentsUsd)}`, false],
      ];
      if (settings.billing === "api") {
        lines.push(["tokens in", formatTokens(spend.tokensIn), false], ["tokens out", formatTokens(spend.tokensOut), false]);
      }
      spendList.replaceChildren(
        ...lines.map(([term, value, isStrong]) => {
          const row = document.createElement("div");
          row.className = "spend-row";
          row.append(textElement("dt", term), textElement("dd", value, isStrong ? "is-bold" : ""));
          return row;
        }),
      );
    };

    const makeGhost = (text, canWiden) => {
      const item = document.createElement("li");
      item.className = "ghost";
      if (canWiden) {
        const button = textElement("button", text, "ghost-button");
        button.type = "button";
        button.dataset.widen = "all";
        item.append(button);
      } else item.textContent = text;
      return item;
    };

    const drawTiles = (spend) => {
      const windowRange = windowOf(model, settings.range);
      const isShown = (row) => row.endedAt === null || row.endedAt >= windowRange.start;
      const inWindow = model.agents.filter(isShown);
      const shown = inWindow.slice(-(MAX_TILES - 1));
      const earlier = model.agents.length - inWindow.length + model.evictedDone + model.evictedFailed;
      const hidden = inWindow.length - shown.length;
      const entries = [model.main, ...shown];
      const keep = new Set(entries.map((row) => row.id));
      for (const [id, tile] of tiles) {
        if (!keep.has(id)) {
          tile.root.remove();
          tiles.delete(id);
        }
      }
      const elements = entries.map((row) => {
        if (!tiles.has(row.id)) tiles.set(row.id, createTile());
        const tile = tiles.get(row.id);
        fillTile(tile, row, model, windowRange, spend);
        return tile.root;
      });
      const parts = [earlier > 0 ? `+${earlier} ended earlier` : "", hidden > 0 ? `+${hidden} more` : ""].filter(Boolean);
      const hasAgents = model.agents.length + model.evictedDone + model.evictedFailed > 0;
      const ghostText = hasAgents ? parts.join(" \u00b7 ") : "No agents yet this session.";
      const canWiden = hasAgents && earlier > 0 && settings.range !== "all";
      const ghostKey = ghostText === "" ? "" : `${ghostText}|${canWiden}`;
      if (ghostKey !== ghost.key) ghost = { key: ghostKey, element: ghostKey === "" ? null : makeGhost(ghostText, canWiden) };
      if (ghost.element) elements.push(ghost.element);
      const current = [...tileList.children];
      const isSame = current.length === elements.length && current.every((child, index) => child === elements[index]);
      if (!isSame) tileList.replaceChildren(...elements);
    };

    const render = () => {
      const spend = spendOf(model);
      const arcs = arcsOf(model, settings.billing);
      const counts = countsOf(model);
      showCounts(counts);
      drawRing(ring, arcs);
      legend.replaceChildren(...legendOf(arcs, spend, settings.billing));
      const mainState = activityOf(model.main, model.now);
      mainActivity.textContent = activityText(mainState);
      mainActivity.className = `activity tone-${mainState.tone}`;
      const laneWindow = { start: model.now - LANE_RANGE_MS, end: model.now };
      const liveAgents = model.agents.filter((row) => row.endedAt === null);
      const laneRows = [model.main, ...liveAgents].slice(0, MAX_LANES);
      drawLane(lane, laneRows.map((row) => cellsOf(row, laneWindow.start, laneWindow.end, LANE_CELLS)));
      if (!settings.isFolded) {
        drawGutter(arcs, spend);
        drawTiles(spend);
      }
    };

    const showFold = () => {
      folded.hidden = !settings.isFolded;
      open.hidden = settings.isFolded;
      for (const button of foldButtons) {
        button.setAttribute("aria-expanded", String(!settings.isFolded));
        button.setAttribute("aria-label", settings.isFolded ? "Unfold the band" : "Fold the band");
      }
    };

    const showRange = () => {
      for (const button of rangeButtons) button.setAttribute("aria-pressed", String(button.dataset.range === settings.range));
    };

    root.addEventListener("click", (event) => {
      if (!(event.target instanceof Element)) return;
      if (event.target.closest("[data-fold]")) {
        settings.isFolded = !settings.isFolded;
        showFold();
        render();
        return;
      }
      const rangeButton = event.target.closest("[data-range]");
      if (rangeButton instanceof HTMLElement) {
        settings.range = rangeButton.dataset.range ?? "5m";
        showRange();
        render();
        return;
      }
      if (event.target.closest("[data-widen]")) {
        settings.range = "all";
        showRange();
        render();
      }
    });

    showFold();
    showRange();
    return { render };
  };

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

  const bindBilling = (buttons, settings, onChange) => {
    for (const button of buttons) {
      button.addEventListener("click", () => {
        settings.billing = button.dataset.billingChoice === "api" ? "api" : "subscription";
        for (const other of buttons) other.setAttribute("aria-pressed", String(other === button));
        onChange();
      });
    }
  };

  const bindPause = (button, state) => {
    const show = () => {
      button.textContent = state.isPaused ? "Resume" : "Pause";
      button.setAttribute("aria-pressed", String(state.isPaused));
    };
    button.addEventListener("click", () => {
      state.isPaused = !state.isPaused;
      show();
    });
    show();
  };

  const required = (parent, selector) => {
    const element = parent.querySelector(selector);
    if (!element) throw new Error(`The band page is missing ${selector}.`);
    return element;
  };

  const start = () => {
    bindTheme(required(document, "[data-theme-toggle]"), [...document.querySelectorAll("[data-theme-choice]")]);
    const settings = { billing: "subscription", range: "5m", isFolded: false };
    const model = createModel();
    const band = createBand(required(document, "[data-band]"), model, settings);
    const state = { isPaused: window.matchMedia("(prefers-reduced-motion: reduce)").matches };
    bindBilling([...document.querySelectorAll("[data-billing-choice]")], settings, band.render);
    bindPause(required(document, "[data-pause]"), state);
    band.render();
    let lastReal = performance.now();
    setInterval(() => {
      const nowReal = performance.now();
      const elapsed = Math.min(nowReal - lastReal, MAX_REAL_STEP_MS);
      lastReal = nowReal;
      if (state.isPaused || document.hidden) return;
      advance(model, elapsed * SPEED);
      band.render();
    }, TICK_MS);
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

  start();
  for (const root of document.querySelectorAll("[data-install]")) bindInstall(root);
}
