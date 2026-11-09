import { expect, mock, test } from 'claude-code/testing'

import { layoutBand } from '../hooks/model'

const BAND = {
  plugin: 'harness-band',
  component: 'AbovePrompt',
  requestId: 'band',
  props: {
    hasSurvey: false,
    isWorking: false,
    maxRows: 30,
    bodyColumns: 100,
    scroll: { offset: 0, bodyRows: 30 },
    view: {},
  },
} as const

const USAGE = {
  startedAt: 0,
  context: { window: 200000, tokens: 120000, percent: 60 },
  rateLimits: [{ kind: 'five_hour', percentUsed: 38, resetsAt: '1970-01-01T02:00:00Z' }],
}

const SPAWN = {
  tool_use_id: 'u1',
  prompt: 'go',
  description: 'scout the repo',
  subagentType: 'scout',
  provider: { plugin: 'engine', tier: 'core' },
  parentModel: 'm',
  background: true,
  fork: false,
  name: 'scout',
} as const

const TURN = { turnId: 't1', answer: '', durationMs: 1, isAborted: false } as const

test('the fold toggle flips the band between unfolded and folded', async ($, on) => {
  mock.clock(on)
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('session.usage', () => ({ value: USAGE }))
  on('config.list', () => ({ value: [] }))
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })

  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })

  expect(await ui.find({ key: 'timeline' })).toBeDefined()
  expect((await ui.find({ key: 'fold' }))?.text).toBe('▴')

  await ui.press({ key: 'fold' })

  expect((await ui.find({ key: 'fold' }))?.text).toBe('▾')
  expect(await ui.find({ key: 'timeline' })).toBeUndefined()
  await ui.unmount()
})

test('a range button changes the timeline scale', async ($, on) => {
  mock.clock(on)
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('session.usage', () => ({ value: USAGE }))
  on('config.list', () => ({ value: [] }))
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })

  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: '-1m' })).toBeDefined()

  await ui.press({ key: 'range-15m' })

  expect(await ui.find({ type: 'Text', text: '-15m' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: '-1m' })).toBeUndefined()
  await ui.unmount()
})

test('an agent going live then done moves the counts', async ($, on) => {
  mock.clock(on)
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('session.usage', () => ({ value: USAGE }))
  on('config.list', () => ({ value: [] }))
  on('agent.spawn', () => ({ model: 'm', agentId: 'a1' }))
  on('turn.start', (_, e) => ({ turnId: e.turnId }))
  on('turn.complete', () => ({ text: '' }))
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })

  await $.agent.spawn(SPAWN)
  await $.turn.start({ text: '', turnId: 'a', agentId: 'a1' })

  expect(await ui.find({ type: 'Text', text: '● 1 live' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: '✓0' })).toBeDefined()

  await $.turn.complete({ ...TURN, agentId: 'a1', reason: 'answer' })

  expect(await ui.find({ type: 'Text', text: '● 0 live' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: '✓1' })).toBeDefined()
  await ui.unmount()
})

const countRenders = (on: Parameters<typeof mock.clock>[0]) => {
  const seen = { renders: 0, blits: 0 }
  on('state.get', (_, e, next) => {
    if (e.key === 'isFolded') seen.renders += 1

    return next(e)
  })
  on('ui.blit', () => {
    seen.blits += 1

    return { value: {} }
  })

  return seen
}

const baseHooks = (on: Parameters<typeof mock.clock>[0]) => {
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('session.end', (_, e) => ({ sessionId: e.sessionId }))
  on('session.usage', () => ({ value: USAGE }))
  on('config.list', () => ({ value: [] }))
  on('agent.list', () => ({ value: [] }))
  on('turn.start', (_, e) => ({ turnId: e.turnId }))
  on('turn.complete', () => ({ text: '' }))
}

test('the tick keeps blitting the lanes after a /clear', async ($, on) => {
  const clock = mock.clock(on)
  const seen = countRenders(on)
  baseHooks(on)
  on('agent.spawn', () => ({ model: 'm', agentId: 'a1' }))
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  await $.agent.spawn(SPAWN)
  await $.turn.start({ text: '', turnId: 'a', agentId: 'a1' })
  await clock.advance(600)
  const before = seen.blits

  await $.session.end({ reason: 'clear', sessionId: 's', resume: { id: 's' } })
  await clock.advance(1200)

  expect(before).toBeGreaterThan(0)
  expect(seen.blits).toBeGreaterThan(before)
  await ui.unmount()
})

test('a tool that ends after an abort leaves the agent failed', async ($, on) => {
  const clock = mock.clock(on)
  baseHooks(on)
  on('agent.spawn', () => ({ model: 'm', agentId: 'a1' }))
  let release: () => void = () => {}
  let enter: () => void = () => {}
  const entered = new Promise<void>(resolve => { enter = resolve })
  on('tool.call', () => new Promise(resolve => {
    release = () => resolve({ result: 'ok' })
    enter()
  }))
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  await $.agent.spawn(SPAWN)
  await $.turn.start({ text: '', turnId: 'a', agentId: 'a1' })
  const call = $.tool.call({ tool: 'Bash', command: 'ls', agentId: 'a1' })
  await entered
  await $.turn.complete({ ...TURN, agentId: 'a1', reason: 'aborted' })

  expect(await ui.find({ type: 'Text', text: '✕1' })).toBeDefined()

  release()
  await call
  await clock.advance(10)

  expect(await ui.find({ type: 'Text', text: '● 0 live' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: '✕1' })).toBeDefined()
  await ui.unmount()
})

test('tool calls and minutes rebuild nothing; a spawn and an end rebuild once each', async ($, on) => {
  const clock = mock.clock(on)
  const seen = countRenders(on)
  baseHooks(on)
  let spawned = 0
  on('agent.spawn', () => ({ model: 'm', agentId: `a${(spawned += 1)}` }))
  on('tool.call', () => ({ result: 'ok' }))
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  await ui.find({ key: 'timeline' })
  const settledRenders = async (): Promise<number> => {
    await ui.find({ key: 'timeline' })

    return seen.renders
  }
  const start = await settledRenders()

  await $.agent.spawn(SPAWN)
  const afterFirstSpawn = await settledRenders()
  await $.agent.spawn(SPAWN)
  const afterSecondSpawn = await settledRenders()
  await $.agent.spawn(SPAWN)
  const afterSpawns = await settledRenders()

  for (const id of ['a1', 'a2', 'a3']) {
    await $.turn.start({ text: '', turnId: id, agentId: id })
  }

  for (let call = 0; call < 10; call += 1) {
    await $.tool.call({ tool: 'Bash', command: `echo ${call}`, agentId: `a${(call % 3) + 1}` })
  }

  await clock.advance(61_000)
  const afterTools = await settledRenders()
  await $.turn.complete({ ...TURN, agentId: 'a1', reason: 'answer' })
  const afterEnd = await settledRenders()

  expect(afterFirstSpawn - start).toBe(1)
  expect(afterSecondSpawn - afterFirstSpawn).toBe(1)
  expect(afterSpawns - afterSecondSpawn).toBe(1)
  expect(afterTools - afterSpawns).toBe(0)
  expect(afterEnd - afterTools).toBe(1)
  await ui.unmount()
})

test('a narrow band drops the week, then 5h, then cache, then context, never the counts', () => {
  const all = ['status', 'context', 'cache', 'fiveHour', 'sevenDay', 'counts', 'toggle'] as const
  const wide = layoutBand(200, all)
  const narrow = layoutBand(44, all)
  const tiny = layoutBand(10, all)

  expect(wide.parts).toEqual([...all])
  expect(wide.hasDetail).toBe(true)
  expect(narrow.hasDetail).toBe(false)
  expect(narrow.parts).toEqual(['status', 'context', 'counts', 'toggle'])
  expect(tiny.parts).toEqual(['status', 'counts', 'toggle'])
})
