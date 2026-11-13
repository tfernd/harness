import type { Engine, Payload, Sources } from './engine'

export type Billing = 'subscription' | 'api'

type Listing = { id: string; type: string; description: string; name: string; status: string }

type World = {
  startedAtMs: number
  billing: Billing
  themeValue: string
  listing: Listing[]
  contextTokens: number
  fiveHourPercent: number
  weekPercent: number
  fablePercent: number
  costUsd: number
  isWorking: boolean
  agentSerial: number
  callSerial: number
  turnSerial: number
}

export type Sim = {
  sources: Sources
  start: (engine: Engine) => Promise<void>
  setBilling: (engine: Engine, billing: Billing) => Promise<void>
  setTheme: (engine: Engine, theme: 'light' | 'dark') => Promise<void>
  isWorking: () => boolean
}

const SECOND = 1000
const MINUTE = 60 * SECOND
const HOUR = 60 * MINUTE
const CONTEXT_WINDOW_TOKENS = 1_000_000
const COMPACT_ABOVE_PERCENT = 88
const COMPACTED_TOKENS = 180_000
const MAX_LIVE_AGENTS = 4
const FAIL_CHANCE = 0.15
const PERMISSION_CHANCE = 0.12
const MAIN_QUESTION_CHANCE = 0.08
const MEASURE_EVERY_MS = 5 * SECOND
const SESSION_AGE_MS = 47 * MINUTE
const FIVE_HOUR_RESET_MS = 2 * HOUR + 13 * MINUTE
const WEEK_RESET_MS = 3 * 24 * HOUR + 5 * HOUR
const MAIN_MODEL = 'claude-opus-4-5'
const AGENT_MODELS: readonly string[] = ['claude-sonnet-4-5', 'claude-sonnet-4-5', 'claude-haiku-4-5', 'claude-opus-4-5']
const AGENT_NAMES: readonly string[] = ['build', 'review', 'scout', 'test', 'docs', 'lint', 'trace']
const AGENT_TYPES: readonly string[] = ['harness:worker', 'harness:reviewer', 'harness:scout']
const TOOLS: readonly { tool: string; field: string; values: readonly string[] }[] = [
  { tool: 'Bash', field: 'command', values: ['make check', 'git diff --stat', 'bun test', 'rg -n "register" src', 'ls -la'] },
  { tool: 'Read', field: 'file_path', values: ['src/model.ts', 'src/view.tsx', 'README.md', 'docs/plan.md'] },
  { tool: 'Grep', field: 'pattern', values: ['isFolded', 'TODO', 'export const', 'tileWidth'] },
  { tool: 'Edit', field: 'file_path', values: ['src/model.ts', 'src/gauges.ts', 'tests/model.test.ts'] },
]

const randomOf = (seed: number): (() => number) => {
  let state = seed

  return () => {
    state = (state + 0x6d2b79f5) | 0
    let mixed = Math.imul(state ^ (state >>> 15), 1 | state)
    mixed = (mixed + Math.imul(mixed ^ (mixed >>> 7), 61 | mixed)) ^ mixed

    return ((mixed ^ (mixed >>> 14)) >>> 0) / 4294967296
  }
}

const acknowledge = async (): Promise<unknown> => ({})

const reportFailure = (where: string, cause: unknown): void => {
  console.error(`The band simulation failed in ${where}.`, cause)
}

export const createSim = (input: { startMs: number; seed: number }): Sim => {
  const random = randomOf(input.seed)
  const between = (low: number, high: number): number => low + random() * (high - low)
  const integerBetween = (low: number, high: number): number => Math.floor(between(low, high + 1))
  const pickFrom = <Item>(items: readonly Item[]): Item => items[integerBetween(0, items.length - 1)] ?? items[0] ?? failEmpty()
  const failEmpty = (): never => {
    throw new Error('The band simulation picked from an empty list.')
  }

  const world: World = {
    startedAtMs: input.startMs - SESSION_AGE_MS,
    billing: 'subscription',
    themeValue: 'light',
    listing: [],
    contextTokens: 310_000,
    fiveHourPercent: 35,
    weekPercent: 52,
    fablePercent: 83,
    costUsd: 12.4,
    isWorking: false,
    agentSerial: 0,
    callSerial: 0,
    turnSerial: 0,
  }

  const usageOf = (): Payload => ({
    startedAt: world.startedAtMs,
    context: { window: CONTEXT_WINDOW_TOKENS, tokens: world.contextTokens, percent: Math.round((100 * world.contextTokens) / CONTEXT_WINDOW_TOKENS) },
    rateLimits:
      world.billing === 'api'
        ? []
        : [
            { kind: 'five_hour', percentUsed: Math.round(world.fiveHourPercent), resetsAt: new Date(input.startMs + FIVE_HOUR_RESET_MS).toISOString() },
            { kind: 'seven_day', percentUsed: Math.round(world.weekPercent), resetsAt: new Date(input.startMs + WEEK_RESET_MS).toISOString() },
            { kind: 'fable_weekly', percentUsed: Math.round(world.fablePercent), resetsAt: new Date(input.startMs + WEEK_RESET_MS).toISOString() },
          ],
    cost: { usd: Math.round(world.costUsd * 100) / 100 },
  })

  const tokensOf = (scale: number, model: string): Payload => ({
    input_tokens: Math.round(between(300, 1800) * scale),
    output_tokens: Math.round(between(500, 3000) * scale),
    cache_read_input_tokens: Math.round(between(30_000, 160_000) * scale),
    cache_creation_input_tokens: Math.round(between(1500, 9000) * scale),
    model,
  })

  const measure = (engine: Engine): Promise<unknown> => engine.dispatch('session.measure', usageOf(), acknowledge)

  const runTool = async (engine: Engine, input: { agentId: string | undefined; tool: string; fields: Payload; durationMs: number }): Promise<void> => {
    world.callSerial += 1
    let finish: () => void = () => undefined
    const finished = new Promise<unknown>(resolve => void (finish = () => resolve({})))
    const owner = input.agentId === undefined ? {} : { agentId: input.agentId }
    const call = engine.dispatch('tool.call', { tool: input.tool, tool_use_id: `call-${world.callSerial}`, ...input.fields, ...owner }, () => finished)
    await engine.sleep(input.durationMs)
    finish()
    await call
  }

  const runRandomTool = async (engine: Engine, agentId: string | undefined): Promise<void> => {
    const choice = pickFrom(TOOLS)
    await runTool(engine, { agentId, tool: choice.tool, fields: { [choice.field]: pickFrom(choice.values) }, durationMs: between(2 * SECOND, 9 * SECOND) })
  }

  const beginTurn = async (engine: Engine, agentId: string | undefined): Promise<void> => {
    world.turnSerial += 1
    const owner = agentId === undefined ? {} : { agentId }
    await engine.dispatch('turn.start', { turnId: `turn-${world.turnSerial}`, ...owner }, acknowledge)
  }

  const runMainTurn = async (engine: Engine): Promise<void> => {
    world.isWorking = true
    await beginTurn(engine, undefined)

    for (let step = 0; step < integerBetween(1, 3); step += 1) {
      await engine.sleep(between(SECOND, 3 * SECOND))

      if (random() < MAIN_QUESTION_CHANCE) {
        await runTool(engine, { agentId: undefined, tool: 'AskUserQuestion', fields: {}, durationMs: between(6 * SECOND, 12 * SECOND) })
      }

      await runRandomTool(engine, undefined)
    }

    const usage = tokensOf(1, MAIN_MODEL)
    world.contextTokens = world.contextTokens > (COMPACT_ABOVE_PERCENT * CONTEXT_WINDOW_TOKENS) / 100 ? COMPACTED_TOKENS : world.contextTokens + Math.round(between(8000, 30_000))
    world.costUsd += between(0.02, 0.09)
    world.fiveHourPercent = Math.min(98, world.fiveHourPercent + between(0.05, 0.2))
    world.weekPercent = Math.min(98, world.weekPercent + between(0.01, 0.05))
    world.fablePercent = Math.min(99, world.fablePercent + between(0.02, 0.1))
    await engine.dispatch('turn.complete', { turnId: `turn-${world.turnSerial}`, reason: 'answer', usage }, acknowledge)
    world.isWorking = false
  }

  const setStatus = (id: string, status: string): void => {
    world.listing = world.listing.map(entry => (entry.id === id ? { ...entry, status } : entry))
  }

  const runAgent = async (engine: Engine): Promise<void> => {
    world.agentSerial += 1
    const id = `agent-${world.agentSerial}`
    const model = pickFrom(AGENT_MODELS)
    const name = pickFrom(AGENT_NAMES)
    const type = pickFrom(AGENT_TYPES)
    const spawn = { tool_use_id: `spawn-${world.agentSerial}`, prompt: 'go', description: name, subagentType: type, name, background: true, fork: false }
    await engine.dispatch('agent.spawn', spawn, async () => ({ model, agentId: id }))
    world.listing = [...world.listing, { id, type, description: name, name, status: 'running' }]
    await beginTurn(engine, id)

    for (let step = 0; step < integerBetween(2, 5); step += 1) {
      await engine.sleep(between(SECOND, 4 * SECOND))

      if (random() < PERMISSION_CHANCE) {
        setStatus(id, 'waiting')
        await engine.sleep(between(5 * SECOND, 9 * SECOND))
        setStatus(id, 'running')
      }

      await runRandomTool(engine, id)
    }

    const isFailed = random() < FAIL_CHANCE
    await engine.dispatch('turn.complete', { reason: isFailed ? 'error' : 'answer', agentId: id, usage: tokensOf(0.6, model) }, acknowledge)
    setStatus(id, isFailed ? 'failed' : 'completed')
    await engine.sleep(2 * SECOND)
    world.listing = world.listing.filter(entry => entry.id !== id)
  }

  const liveAgents = (): number => world.listing.filter(entry => entry.status === 'running' || entry.status === 'waiting').length

  const mainLoop = async (engine: Engine): Promise<void> => {
    for (;;) {
      await runMainTurn(engine)
      await engine.sleep(between(3 * SECOND, 9 * SECOND))
    }
  }

  const spawnLoop = async (engine: Engine): Promise<void> => {
    for (let index = 0; index < 2; index += 1) {
      runAgent(engine).catch(cause => reportFailure('an agent', cause))
      await engine.sleep(between(SECOND, 3 * SECOND))
    }

    for (;;) {
      await engine.sleep(between(5 * SECOND, 18 * SECOND))

      if (liveAgents() < MAX_LIVE_AGENTS) {
        runAgent(engine).catch(cause => reportFailure('an agent', cause))
      }
    }
  }

  const start = async (engine: Engine): Promise<void> => {
    await engine.dispatch('session.start', { cwd: '/', surface: 'desktop', isInteractive: true }, async () => ({ cwd: '/' }))
    engine.host.clock.every(MEASURE_EVERY_MS, () => void measure(engine).catch(cause => reportFailure('a measure', cause)))
    mainLoop(engine).catch(cause => reportFailure('the main session', cause))
    spawnLoop(engine).catch(cause => reportFailure('the spawner', cause))
  }

  return {
    sources: { usage: usageOf, listing: () => world.listing, themeValue: () => world.themeValue },
    start,
    setBilling: async (engine, billing) => {
      world.billing = billing
      await measure(engine)
    },
    setTheme: async (engine, theme) => {
      world.themeValue = theme
      await engine.dispatch('config.set', { key: 'theme', value: theme }, acknowledge)
    },
    isWorking: () => world.isWorking,
  }
}
