import { expect, mock, test } from 'claude-code/testing'

import { EMPTY_GAUGES, cacheClockOf, cacheRefreshMs } from '../hooks/gauges'
import { EMPTY_ROSTER, EMPTY_STORE, addAgent, layoutBand, moveMain, newAgent, rosterOf, themeOf } from '../hooks/model'
import { piecesOf, refreshAfterMs } from '../hooks/svg-band'
import { MIN_REBUILD_MS, chooseBand } from '../hooks/svg-cache'

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

type Mounted = { findAll: (query: { type: string }) => Promise<{ props: Record<string, unknown> }[]> }

const svgProps = async (ui: Mounted, altStart: string): Promise<Record<string, unknown> | undefined> =>
  (await ui.findAll({ type: 'Svg' })).find(svg => String(svg.props['alt']).startsWith(altStart))?.props

const sourceOf = async (ui: Mounted): Promise<unknown> => (await svgProps(ui, 'Agent timeline'))?.['source']

test('the desktop draws the band from native text and plain image Svgs, no Raster and no interactive frame', async ($, on) => {
  mock.clock(on)
  baseHooks(on)
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  const timeline = { props: await svgProps(ui, 'Agent timeline') }
  const ring = { props: await svgProps(ui, 'ctx ') }

  expect(timeline.props).toBeDefined()
  expect(ring.props).toBeDefined()
  expect(timeline.props?.['isInteractive']).toBeUndefined()
  expect(ring.props?.['isInteractive']).toBeUndefined()
  expect(String(timeline.props?.['source']).startsWith('<svg')).toBe(true)
  expect(String(ring.props?.['source']).startsWith('<svg')).toBe(true)
  expect(await ui.find({ type: 'Raster' })).toBeUndefined()
  expect(await ui.find({ key: 'fold' })).toBeDefined()
  await ui.unmount()
})

test('a state change inside one second is held, then drawn once; later changes draw at once', async ($, on) => {
  const clock = mock.clock(on)
  baseHooks(on)
  let spawned = 0
  on('agent.spawn', () => ({ model: 'm', agentId: `a${(spawned += 1)}` }))
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  const empty = await sourceOf(ui)
  await clock.advance(MIN_REBUILD_MS + 500)

  await $.agent.spawn(SPAWN)
  const first = await sourceOf(ui)
  await $.agent.spawn(SPAWN)
  await $.turn.start({ text: '', turnId: 'a', agentId: 'a1' })
  const held = await sourceOf(ui)
  await clock.advance(MIN_REBUILD_MS)
  const second = await sourceOf(ui)

  expect(first).not.toBe(empty)
  expect(held).toBe(first)
  expect(second).not.toBe(first)
  await ui.unmount()
})

test('a held sub-agent tool call shows RUNNING with its command in the desktop timeline, and THINKING after', async ($, on) => {
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
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  await $.agent.spawn(SPAWN)
  await $.turn.start({ text: '', turnId: 'a', agentId: 'a1' })
  await clock.advance(MIN_REBUILD_MS + 500)
  const call = $.tool.call({ tool: 'Bash', command: 'make check', agentId: 'a1' })
  await entered
  await clock.advance(MIN_REBUILD_MS + 200)
  const during = String(await sourceOf(ui))

  expect(during).toContain('scout-1: tool, make check')

  release()
  await call
  await clock.advance(MIN_REBUILD_MS + 200)
  const after = String(await sourceOf(ui))

  expect(after).toContain('scout-1: thinking, thinking...')
  expect(after).not.toContain('make check')
  await ui.unmount()
})

const NOW = 10_000_000
const MINUTE = 60_000

const SVG_INPUT = {
  width: 800,
  now: NOW,
  isFolded: false,
  range: '1m',
  foldedGroups: [],
  roster: EMPTY_ROSTER,
  rows: new Map(),
  gauges: { ...EMPTY_GAUGES, contextPercent: 40, cachePercent: 90 },
  isWorking: false,
  turnStartedAt: null,
  scheme: 'light',
} as const

const sourceOfPiece = (input: Parameters<typeof piecesOf>[0], key: string): string =>
  piecesOf(input)
    .find(spec => spec.key === key)
    ?.build().source ?? ''

test('an unknown theme reads as light and auto puts both palettes under the media query', () => {
  expect(themeOf(undefined)).toBe('light')
  expect(themeOf('custom:mine')).toBe('light')
  expect(themeOf('dark-daltonized')).toBe('dark')
  expect(themeOf('auto')).toBe('auto')

  const auto = sourceOfPiece({ ...SVG_INPUT, scheme: 'auto' }, 'ring-ctx')
  const light = sourceOfPiece({ ...SVG_INPUT, scheme: 'light' }, 'ring-ctx')

  expect(auto).toContain('@media (prefers-color-scheme:dark){:root{--surface:#1a1c20')
  expect(auto).toContain(':root{--surface:#fbfaf7')
  expect(light).toContain('--surface:#fbfaf7')
  expect(light).not.toContain('prefers-color-scheme')
  expect(light).not.toContain('#1a1c20')
})

test('a fresh desktop band starts unfolded with every group open', async ($, on) => {
  mock.clock(on)
  baseHooks(on)
  on('agent.spawn', () => ({ model: 'm', agentId: 'a1' }))
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await $.agent.spawn(SPAWN)
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })

  expect(JSON.stringify((await ui.find({ key: 'fold' }))?.props)).toContain('▴ fold')
  expect(JSON.stringify((await ui.find({ key: 'group-button-direct' }))?.props)).toContain('▾')
  expect(await ui.find({ key: 'ranges' })).toBeDefined()
  await ui.unmount()
})

test('the session axis names real times and never the word session', () => {
  const input = { ...SVG_INPUT, range: 'session', gauges: { ...SVG_INPUT.gauges, sessionStartedAt: NOW - 51 * 3_600_000 - 20 * MINUTE } } as const
  const source = sourceOfPiece(input, 'timeline')

  expect(source.replaceAll('main session', '')).not.toContain('session')
  expect(source).toContain('>-51h<')
  expect(source).toContain('>-25h<')
  expect(source).toContain('>now<')
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
  expect(sourceOfPiece({ ...SVG_INPUT, gauges }, 'ring-cache')).toContain('r-bad')
})

test('the cache countdown refreshes every minute, every 15 s under 5m, and not once cold', () => {
  const at = (ago: number) => ({ ...EMPTY_GAUGES, isSubscription: true, lastCallAt: NOW - ago })

  expect(cacheRefreshMs(at(10 * MINUTE), NOW)).toBe(60_000)
  expect(cacheRefreshMs(at(56 * MINUTE), NOW)).toBe(15_000)
  expect(cacheRefreshMs(at(61 * MINUTE), NOW)).toBeNull()
  expect(refreshAfterMs({ ...SVG_INPUT, gauges: at(10 * MINUTE) })).toBe(60_000)
})

const oneAgent = (state: 'launched' | 'tool') => {
  const store = addAgent(EMPTY_STORE, newAgent({ id: 'a1', label: 'scout-1', group: 'direct', groupLabel: 'direct agents', now: NOW }))
  const row = { ...store.rows[0], state, command: state === 'tool' ? 'Read x' : null }

  return { roster: rosterOf(store), rows: new Map([['a1', row]]) }
}

test('an agent changing state rebuilds the timeline alone, never a ring, and draws at once', () => {
  const first = chooseBand(new Map(), { ...SVG_INPUT, ...oneAgent('launched') } as never)
  const changed = chooseBand(first.caches, { ...SVG_INPUT, ...oneAgent('tool'), now: NOW + 50 } as never)
  const unchanged = chooseBand(first.caches, { ...SVG_INPUT, ...oneAgent('launched'), now: NOW + 50 } as never)
  const buttonPress = chooseBand(first.caches, { ...SVG_INPUT, ...oneAgent('launched'), range: '5m', now: NOW + 50 } as never)
  const settled = chooseBand(changed.caches, { ...SVG_INPUT, ...oneAgent('tool'), now: NOW + MIN_REBUILD_MS + 50 } as never)

  expect(first.builtKeys.sort()).toEqual(['ring-cache', 'ring-ctx', 'timeline'])
  expect(changed.builtKeys).toEqual([])
  expect(changed.retryInMs).toBe(MIN_REBUILD_MS - 50)
  expect(unchanged.builtKeys).toEqual([])
  expect(buttonPress.builtKeys).toEqual(['timeline'])
  expect(settled.builtKeys).toEqual(['timeline'])
})

const endedAgo = (minutes: number) => {
  const live = addAgent(EMPTY_STORE, newAgent({ id: 'old', label: 'old-1', group: 'direct', groupLabel: 'direct agents', now: NOW - 10 * MINUTE }))
  const row = { ...live.rows[0], state: 'done', endedAt: NOW - minutes * MINUTE }
  const roster = { ...rosterOf(live), rows: rosterOf(live).rows.map(entry => ({ ...entry, phase: 'done' })) }

  return { roster, rows: new Map([['old', row]]) }
}

test('an agent that ended 2 min ago is hidden in range 1m, shown in 5m, and counted as earlier', () => {
  const at = (range: '1m' | '5m') => sourceOfPiece({ ...SVG_INPUT, ...endedAgo(2), range } as never, 'timeline')

  expect(at('1m')).not.toContain('old-1')
  expect(at('1m')).toContain('+1 earlier')
  expect(at('5m')).toContain('old-1')
  expect(at('5m')).not.toContain('earlier')
})

test('leaving the window rebuilds the timeline once and a quiet clock tick rebuilds nothing', () => {
  const input = { ...SVG_INPUT, ...endedAgo(0.5) } as never
  const first = chooseBand(new Map(), input)
  const quiet = chooseBand(first.caches, { ...(input as object), now: NOW + 10_000 } as never)
  const left = chooseBand(first.caches, { ...(input as object), now: NOW + 40_000 } as never)

  expect(quiet.builtKeys).toEqual([])
  expect(left.builtKeys).toEqual(['timeline'])
})

test('a main turn with one tool call gives the main row WORKING, then TOOL with its command, then IDLE', async ($, on) => {
  const clock = mock.clock(on)
  baseHooks(on)
  let release: () => void = () => {}
  let enter: () => void = () => {}
  const entered = new Promise<void>(resolve => { enter = resolve })
  on('tool.call', () => new Promise(resolve => {
    release = () => resolve({ result: 'ok' })
    enter()
  }))
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  const titleOf = async (): Promise<string | undefined> => String(await sourceOf(ui)).match(/main session: [a-z]+, [^<]*/)?.[0]
  const idleAtStart = await titleOf()

  await $.turn.start({ text: '', turnId: 'm1' })
  await clock.advance(MIN_REBUILD_MS + 200)
  const thinking = await titleOf()
  const call = $.tool.call({ tool: 'Bash', command: 'make check' })
  await entered
  await clock.advance(MIN_REBUILD_MS + 200)
  const tool = await titleOf()

  release()
  await call
  await $.turn.complete({ ...TURN, reason: 'answer' })
  await clock.advance(MIN_REBUILD_MS + 200)
  const idle = await titleOf()

  expect(idleAtStart).toBe('main session: launched, idle')
  expect(thinking).toBe('main session: thinking, working...')
  expect(tool).toBe('main session: tool, make check')
  expect(idle).toBe('main session: launched, idle')
  expect(String(await sourceOf(ui))).not.toContain('>idle<')
  await ui.unmount()
})

test('the main row shows in range 1m with no agent at all, above every group and outside the counts', () => {
  const source = sourceOfPiece({ ...SVG_INPUT, range: '1m' } as never, 'timeline')
  const withAgent = sourceOfPiece({ ...SVG_INPUT, ...oneAgent('launched') } as never, 'timeline')

  expect(source).toContain('main session')
  expect(withAgent.indexOf('main session')).toBeGreaterThan(-1)
  expect(withAgent.indexOf('main session')).toBeLessThan(withAgent.indexOf('DIRECT'))
})

const withMain = (state: 'launched' | 'tool', command: string | null) => {
  const main = moveMain(EMPTY_STORE, { activity: { state: 'thinking', command: null }, now: NOW - 5_000 })
  const moved = state === 'tool' ? moveMain(main, { activity: { state, command }, now: NOW - 2_000 }) : main

  return { ...SVG_INPUT, rows: new Map([['main', moved.main]]) }
}

test('a main tool call rebuilds the timeline alone, never a ring', () => {
  const idle = chooseBand(new Map(), withMain('launched', null) as never)
  const called = chooseBand(idle.caches, { ...withMain('tool', 'make check'), now: NOW + MIN_REBUILD_MS + 50 } as never)

  expect(idle.builtKeys.sort()).toEqual(['ring-cache', 'ring-ctx', 'timeline'])
  expect(called.builtKeys).toEqual(['timeline'])
})
