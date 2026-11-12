import { expect, mock, test } from 'claude-code/testing'

import { SETTLE_MS } from './settle'

const BAND = {
  plugin: 'harness-band',
  component: 'AbovePrompt',
  requestId: 'band',
  surface: 'desktop',
  props: { hasSurvey: false, isWorking: false, maxRows: 30, bodyColumns: 100, scroll: { offset: 0, bodyRows: 30 }, view: {} },
} as const

const SPAWN = {
  tool_use_id: 'u1',
  prompt: 'go',
  description: 'build it',
  subagentType: 'harness:worker',
  provider: { plugin: 'engine', tier: 'core' },
  parentModel: 'm',
  background: true,
  fork: false,
  name: 'build',
} as const

const TURN = { turnId: 't1', answer: '', durationMs: 1, isAborted: false } as const

const LIMITS = [
  { kind: 'five_hour', percentUsed: 35, resetsAt: '1970-01-01T05:00:00Z' },
  { kind: 'seven_day', percentUsed: 52, resetsAt: '1970-01-05T05:00:00Z' },
  { kind: 'fable_weekly', percentUsed: 19 },
]

const usageOf = (input: { percent: number; tokens: number; rateLimits: readonly { kind: string; percentUsed: number; resetsAt?: string }[] }) => ({
  startedAt: 0,
  context: { window: 200_000, tokens: input.tokens, percent: input.percent },
  rateLimits: [...input.rateLimits],
  cost: { usd: 3.84 },
})

const hooksFor = (on: Parameters<typeof mock.clock>[0], usage: ReturnType<typeof usageOf>) => {
  on('session.start', (_, event) => ({ cwd: event.cwd }))
  on('session.end', (_, event) => ({ sessionId: event.sessionId }))
  on('session.usage', () => ({ value: usage }))
  on('config.list', () => ({ value: [] }))
  on('agent.list', () => ({ value: [] }))
  on('turn.start', (_, event) => ({ turnId: event.turnId }))
  on('turn.complete', () => ({ text: '' }))
}

const textOf = async (ui: { find: (query: { key: string }) => Promise<{ text: string } | undefined> }, key: string): Promise<string | undefined> => (await ui.find({ key }))?.text

test('unfolded, the top line keeps counts and cost, the limits show once as full blocks, and the tiny lanes and mini bars are gone', async ($, on) => {
  mock.clock(on)
  hooksFor(on, usageOf({ percent: 40, tokens: 80_000, rateLimits: LIMITS }))
  on('agent.spawn', () => ({ model: 'm', agentId: 'a1' }))
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await $.agent.spawn(SPAWN)
  const ui = await $.ui.mount(BAND)
  const top = await textOf(ui, 'controls')

  expect(top).toContain('$3.84')
  expect(top).toContain('▶ 1')
  expect(top).not.toContain('%')
  expect(await textOf(ui, 'limit-five_hour')).toContain('Session35%')
  expect(await textOf(ui, 'limit-five_hour')).toContain('Resets')
  expect(await textOf(ui, 'limit-seven_day')).toContain('Week52%')
  expect(await textOf(ui, 'limit-fable_weekly')).toContain('Fable weekly19%')
  expect(await textOf(ui, 'limit-context')).toContain('80k of 200k tokens')
  expect(await ui.find({ key: 'mini-limits' })).toBeUndefined()
  expect(await ui.find({ key: 'mini-lanes' })).toBeUndefined()
  await ui.unmount()
})

test('folded, one row holds counts, tiny lanes, cost, ctx and a mini bar per limit, and the full blocks and timeline are gone', async ($, on) => {
  mock.clock(on)
  hooksFor(on, usageOf({ percent: 90, tokens: 180_000, rateLimits: LIMITS }))
  on('agent.spawn', () => ({ model: 'm', agentId: 'a1' }))
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await $.agent.spawn(SPAWN)
  const ui = await $.ui.mount(BAND)

  await ui.press({ key: 'fold' })

  expect(await ui.find({ key: 'limit-blocks' })).toBeUndefined()
  expect(await ui.find({ key: 'timeline' })).toBeUndefined()
  expect(await ui.find({ key: 'long-session' })).toBeUndefined()
  expect(await ui.find({ key: 'mini-lanes' })).toBeDefined()
  expect(await textOf(ui, 'ctx')).toBe('ctx 90% ▲')
  const mini = await textOf(ui, 'mini-limits')
  expect(mini).toContain('session35%')
  expect(mini).toContain('week52%')
  expect(mini).toContain('fable weekly19%')
  expect(await ui.find({ key: 'cost' })).toBeDefined()
  await ui.unmount()
})

test('without limits (API billing) the blocks show session cost, agent estimate, tokens, turns and elapsed', async ($, on) => {
  mock.clock(on)
  hooksFor(on, usageOf({ percent: 10, tokens: 20_000, rateLimits: [] }))
  on('agent.spawn', () => ({ model: 'claude-sonnet-4-5', agentId: 'a1' }))
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await $.agent.spawn(SPAWN)
  await $.turn.complete({ ...TURN, agentId: 'a1', reason: 'answer', usage: { input_tokens: 1_000_000, output_tokens: 100_000, cache_read_input_tokens: 0, cache_creation_input_tokens: 0, model: 'claude-sonnet-4-5' } })
  await $.turn.complete({ ...TURN, reason: 'answer' })
  const ui = await $.ui.mount(BAND)

  expect(await ui.find({ key: 'limit-five_hour' })).toBeUndefined()
  expect(await textOf(ui, 'spend-session')).toContain('Session cost$3.84')
  expect(await textOf(ui, 'spend-session')).toContain('agents ~$4.50, estimated')
  expect(await textOf(ui, 'spend-tokens')).toContain('1M / 100k')
  expect(await textOf(ui, 'spend-turns')).toContain('1 ·')
  expect(await ui.find({ key: 'limit-context' })).toBeDefined()
  await ui.unmount()
})

test('the main session is its own lane above the agents, labelled main, with a legend for main session and agents', async ($, on) => {
  mock.clock(on)
  hooksFor(on, usageOf({ percent: 10, tokens: 20_000, rateLimits: LIMITS }))
  on('agent.spawn', () => ({ model: 'claude-sonnet-4-5', agentId: 'a1' }))
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  const ui = await $.ui.mount(BAND)
  const alone = await textOf(ui, 'timeline')

  expect(alone).toContain('main')
  expect(alone).toContain('No agents yet.')

  await $.agent.spawn(SPAWN)
  const timeline = await textOf(ui, 'timeline')

  expect(await textOf(ui, 'legend')).toContain('main session')
  expect(await textOf(ui, 'legend')).toContain('agents')
  expect(await textOf(ui, 'name-main')).toBe('main')
  expect(await textOf(ui, 'name-a1')).toBe('build-1worker')
  expect(await textOf(ui, 'badge-a1')).toBe('sonnet')
  expect(timeline?.indexOf('● idle')).toBeLessThan(timeline?.indexOf('build-1') ?? -1)
  expect(await ui.find({ key: 'lane-main' })).toBeDefined()
  await ui.unmount()
})

test('an agent row estimates its cost from tokens, and an unpriced model shows tokens only', async ($, on) => {
  const clock = mock.clock(on)
  hooksFor(on, usageOf({ percent: 10, tokens: 20_000, rateLimits: LIMITS }))
  let spawned = 0
  on('agent.spawn', () => ({ model: 'm', agentId: `a${(spawned += 1)}` }))
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  const ui = await $.ui.mount(BAND)
  await $.agent.spawn(SPAWN)
  await $.agent.spawn(SPAWN)
  const tokens = { input_tokens: 1_000_000, output_tokens: 100_000, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 }
  await $.turn.complete({ ...TURN, agentId: 'a1', reason: 'answer', usage: { ...tokens, model: 'claude-sonnet-4-5' } })
  await $.turn.complete({ ...TURN, agentId: 'a2', reason: 'answer', usage: { ...tokens, model: 'fable-1' } })
  await clock.advance(SETTLE_MS)

  expect(await textOf(ui, 'cost-a1')).toBe('~$4.50')
  expect(await textOf(ui, 'tokens-a1')).toBe('1M / 100k')
  expect(await textOf(ui, 'cost-a2')).toBe('—')
  expect(await textOf(ui, 'tokens-a2')).toBe('1M / 100k')
  await ui.unmount()
})

test('a failed agent ends in a failed bar with its reason beside it', async ($, on) => {
  mock.clock(on)
  hooksFor(on, usageOf({ percent: 10, tokens: 20_000, rateLimits: LIMITS }))
  on('agent.spawn', () => ({ model: 'm', agentId: 'a1' }))
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  const ui = await $.ui.mount(BAND)
  await $.agent.spawn(SPAWN)
  await $.turn.complete({ ...TURN, agentId: 'a1', reason: 'error' })

  expect(await textOf(ui, 'glyph-a1')).toBe('✕ failed')
  expect(await textOf(ui, 'track-a1')).toBe('✕ failed: error')
  await ui.unmount()
})

test('a high context shows the long-session note with the token count, and Dismiss removes it', async ($, on) => {
  mock.clock(on)
  hooksFor(on, usageOf({ percent: 90, tokens: 180_000, rateLimits: LIMITS }))
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  const ui = await $.ui.mount(BAND)

  expect(await textOf(ui, 'long-session')).toContain('Long session: each turn re-reads 180k tokens. A fresh session is cheaper.')
  expect(await ui.find({ key: 'start-fresh' })).toBeUndefined()

  await ui.press({ key: 'dismiss-note' })

  expect(await ui.find({ key: 'long-session' })).toBeUndefined()
  await ui.unmount()
})

test('a calm context shows no long-session note', async ($, on) => {
  mock.clock(on)
  hooksFor(on, usageOf({ percent: 79, tokens: 158_000, rateLimits: LIMITS }))
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  const ui = await $.ui.mount(BAND)

  expect(await ui.find({ key: 'long-session' })).toBeUndefined()
  await ui.unmount()
})
