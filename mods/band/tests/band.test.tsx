import { expect, mock, test } from 'claude-code/testing'

import { EMPTY_GAUGES, cacheClockOf, cacheRefreshMs } from '../hooks/gauges'
import { layoutBand } from '../hooks/layout'
import { themeOf } from '../hooks/format'
import { bandColorsOf } from '../hooks/svg-theme'
import { SETTLE_MS } from './settle'

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
  on('session.start', (_, event) => ({ cwd: event.cwd }))
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
  on('session.start', (_, event) => ({ cwd: event.cwd }))
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
  on('session.start', (_, event) => ({ cwd: event.cwd }))
  on('session.usage', () => ({ value: USAGE }))
  on('config.list', () => ({ value: [] }))
  on('agent.spawn', () => ({ model: 'm', agentId: 'a1' }))
  on('turn.start', (_, event) => ({ turnId: event.turnId }))
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
  on('state.get', (_, event, next) => {
    if (event.key === 'isFolded') seen.renders += 1

    return next(event)
  })
  on('ui.blit', () => {
    seen.blits += 1

    return { value: {} }
  })

  return seen
}

const baseHooks = (on: Parameters<typeof mock.clock>[0]) => {
  on('session.start', (_, event) => ({ cwd: event.cwd }))
  on('session.end', (_, event) => ({ sessionId: event.sessionId }))
  on('session.usage', () => ({ value: USAGE }))
  on('config.list', () => ({ value: [] }))
  on('agent.list', () => ({ value: [] }))
  on('turn.start', (_, event) => ({ turnId: event.turnId }))
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
  const entered = new Promise<void>(resolve => {
    enter = resolve
  })
  on(
    'tool.call',
    () =>
      new Promise(resolve => {
        release = () => resolve({ result: 'ok' })
        enter()
      }),
  )
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

type Mounted = { findAll: (query: { type: string }) => Promise<{ props: Record<string, unknown> }[]> }

const svgProps = async (ui: Mounted, altStart: string): Promise<Record<string, unknown> | undefined> => (await ui.findAll({ type: 'Svg' })).find(svg => String(svg.props['alt']).startsWith(altStart))?.props

const timelineText = async (ui: { find: (query: { key: string }) => Promise<{ text: string } | undefined> }): Promise<string> => (await ui.find({ key: 'timeline' }))?.text ?? ''

test('the desktop draws the band from native text and bar Svgs, no Raster and no interactive frame', async ($, on) => {
  mock.clock(on)
  baseHooks(on)
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  const bar = await svgProps(ui, 'Session 38%')

  expect(bar).toBeDefined()
  expect(bar?.['isInteractive']).toBeUndefined()
  expect(String(bar?.['source']).startsWith('<svg')).toBe(true)
  expect(await ui.find({ type: 'Raster' })).toBeUndefined()
  expect(await ui.find({ key: 'fold' })).toBeDefined()
  await ui.unmount()
})

test('a held sub-agent tool call shows running with its command inside the bar, and thinking after', async ($, on) => {
  const clock = mock.clock(on)
  baseHooks(on)
  on('agent.spawn', () => ({ model: 'm', agentId: 'a1' }))
  let release: () => void = () => {}
  let enter: () => void = () => {}
  const entered = new Promise<void>(resolve => {
    enter = resolve
  })
  on(
    'tool.call',
    () =>
      new Promise(resolve => {
        release = () => resolve({ result: 'ok' })
        enter()
      }),
  )
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  await $.agent.spawn(SPAWN)
  await $.turn.start({ text: '', turnId: 'a', agentId: 'a1' })
  await clock.advance(SETTLE_MS + 500)
  const call = $.tool.call({ tool: 'Bash', command: 'make check', agentId: 'a1' })
  await entered
  await clock.advance(SETTLE_MS + 200)
  const during = await timelineText(ui)

  expect(during).toContain('running')
  expect(during).toContain('make check')

  release()
  await call
  await clock.advance(SETTLE_MS + 200)
  const after = await timelineText(ui)

  expect(after).toContain('thinking')
  expect(after).not.toContain('make check')
  await ui.unmount()
})

const NOW = 10_000_000
const MINUTE = 60_000

test('an unknown theme reads as light', () => {
  expect(themeOf(undefined)).toBe('light')
  expect(themeOf('custom:mine')).toBe('light')
  expect(themeOf('dark-daltonized')).toBe('dark')
  expect(themeOf('auto')).toBe('auto')
})

test('a fresh desktop band starts unfolded with the limit blocks and the timeline', async ($, on) => {
  mock.clock(on)
  baseHooks(on)
  on('agent.spawn', () => ({ model: 'm', agentId: 'a1' }))
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await $.agent.spawn(SPAWN)
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })

  expect(JSON.stringify((await ui.find({ key: 'fold' }))?.props)).toContain('▴')
  expect(await ui.find({ key: 'limit-blocks' })).toBeDefined()
  expect(await ui.find({ key: 'timeline' })).toBeDefined()
  expect(await ui.find({ key: 'range-1h' })).toBeDefined()
  await ui.unmount()
})

test('a 1h cache last called 58 minutes ago counts down to ~2m, is urgent under 2m and cold at the end', () => {
  const gauges = { ...EMPTY_GAUGES, cachePercent: 90, isSubscription: true, lastCallAt: NOW - 58 * MINUTE }
  const warm = cacheClockOf(gauges, NOW)
  const urgent = cacheClockOf(gauges, NOW + 30_000)
  const cold = cacheClockOf(gauges, NOW + 2 * MINUTE)
  const unmetered = cacheClockOf({ ...gauges, isSubscription: false, lastCallAt: NOW - 4 * MINUTE }, NOW)

  expect(warm?.text).toBe('~2m')
  expect(warm?.isUrgent).toBe(false)
  expect(urgent?.isUrgent).toBe(true)
  expect(cold?.text).toBe('cold')
  expect(unmetered?.text).toBe('~1m')
  expect(warm?.tip).toContain('TTL 1h')
  expect(warm?.detail).toBe('warm ~2m')
  expect(cold?.detail).toBe('cold')
  expect(unmetered?.detail).toBe('warm ~1m')
})

test('the cache countdown refreshes every minute, every 15 s under 5m, and not once cold', () => {
  const at = (ago: number) => ({ ...EMPTY_GAUGES, isSubscription: true, lastCallAt: NOW - ago })

  expect(cacheRefreshMs(at(10 * MINUTE), NOW)).toBe(60_000)
  expect(cacheRefreshMs(at(56 * MINUTE), NOW)).toBe(15_000)
  expect(cacheRefreshMs(at(61 * MINUTE), NOW)).toBeNull()
})

test('a main turn with one tool call gives the main lane working, then tool with its command, then idle', async ($, on) => {
  const clock = mock.clock(on)
  baseHooks(on)
  let release: () => void = () => {}
  let enter: () => void = () => {}
  const entered = new Promise<void>(resolve => {
    enter = resolve
  })
  on(
    'tool.call',
    () =>
      new Promise(resolve => {
        release = () => resolve({ result: 'ok' })
        enter()
      }),
  )
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  const titleOf = async (): Promise<string> => `${(await ui.find({ key: 'glyph-main' }))?.text ?? ''}, ${(await ui.find({ key: 'track-main' }))?.text ?? ''}`
  const idleAtStart = await titleOf()

  await $.turn.start({ text: '', turnId: 'm1' })
  await clock.advance(SETTLE_MS + 200)
  const thinking = await titleOf()
  const call = $.tool.call({ tool: 'Bash', command: 'make check' })
  await entered
  await clock.advance(SETTLE_MS + 200)
  const tool = await titleOf()

  release()
  await call
  await $.turn.complete({ ...TURN, reason: 'answer' })
  await clock.advance(SETTLE_MS + 200)
  const idle = await titleOf()

  expect(idleAtStart).toBe('● idle, idle')
  expect(thinking).toBe('● working, working')
  expect(tool).toBe('● tool, make check')
  expect(idle).toBe('● idle, idle')
  await ui.unmount()
})

test('the auto theme paints no surface and tints with a translucent grey and a theme-key frame', () => {
  const auto = bandColorsOf('auto')

  expect(auto.surface).toBeUndefined()
  expect(auto.tint).toMatch(/^rgba\(/)
  expect(auto.frame).toBe('promptBorder')
  expect(bandColorsOf('dark').surface).toBeDefined()
})

test('on desktop four range buttons choose the window, and the axis follows', async ($, on) => {
  mock.clock(on)
  baseHooks(on)
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })

  expect(JSON.stringify((await ui.find({ key: 'range-1m' }))?.props)).toContain('primary')
  expect(await ui.find({ key: 'range-15m' })).toBeUndefined()
  expect((await ui.find({ key: 'axis' }))?.text).toContain('1m ago')

  await ui.press({ key: 'range-1h' })

  expect(JSON.stringify((await ui.find({ key: 'range-1h' }))?.props)).toContain('primary')
  expect((await ui.find({ key: 'axis' }))?.text).toContain('1h ago')
  await ui.unmount()
})

test('a session end leaves no open segment, no live agent and no turn clock', async ($, on) => {
  const clock = mock.clock(on)
  baseHooks(on)
  on('agent.spawn', () => ({ model: 'm', agentId: 'a1' }))
  const written = { agents: [] as string[], turnStartedAt: [] as string[] }
  on('state.set', (_, event, next) => {
    if (event.key === 'agents') written.agents.push(JSON.stringify(event.value))
    if (event.key === 'turnStartedAt') written.turnStartedAt.push(JSON.stringify(event.value))

    return next(event)
  })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  await $.agent.spawn(SPAWN)
  await $.turn.start({ text: '', turnId: 'a', agentId: 'a1' })
  await $.turn.start({ text: '', turnId: 'm' })
  await clock.advance(600)

  await $.session.end({ reason: 'prompt_input_exit', sessionId: 's', resume: { id: 's' } })

  expect(written.agents.length).toBeGreaterThan(0)
  expect(written.agents.at(-1)).not.toContain('"to":null')
  expect(written.agents.at(-1)).toContain('"state":"failed"')
  expect(written.turnStartedAt.at(-1)).toBe('null')
  await ui.unmount()
})
