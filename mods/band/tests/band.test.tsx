import { expect, mock, test } from 'claude-code/testing'

import { EMPTY_GAUGES, cacheClockOf, cacheRefreshMs } from '../hooks/gauges'
import { EMPTY_ROSTER, EMPTY_STORE, addAgent, layoutBand, moveMain, newAgent, rosterOf, themeOf } from '../hooks/model'
import { listedGroupsOf, piecesOf, refreshAfterMs } from '../hooks/svg-band'
import { FOLDED_CONTENT_INSET, FOLDED_GAP, FOLDED_STATUS_WIDTH, FOLDED_UNFOLD_WIDTH, foldedTracesWidth, gaugeSpecs } from '../hooks/svg-strip'
import { bandColorsOf } from '../hooks/svg-theme'
import { groupCountsText, liveStateCounts } from '../hooks/svg-timeline'
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

const sourceOf = async (ui: Mounted): Promise<string> =>
  (await ui.findAll({ type: 'Svg' }))
    .filter(svg => String(svg.props['alt']).startsWith('Agent '))
    .map(svg => String(svg.props['source']))
    .join('')

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
  const during = await sourceOf(ui)

  expect(during).toContain('>RUNNING<')
  expect(during).toContain('>make check<')
  expect(during).not.toContain('<title>')

  release()
  await call
  await clock.advance(MIN_REBUILD_MS + 200)
  const after = await sourceOf(ui)

  expect(after).toContain('>THINKING<')
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
  expect(JSON.stringify((await ui.find({ key: 'group-button-direct' }))?.props)).toContain('∧')
  expect(await ui.find({ key: 'range' })).toBeDefined()
  await ui.unmount()
})

const groupSpawn = (runId: string) => ({ ...SPAWN, workflow: { runId, agentIndex: 1 } })

test('each timeline group header is a native Button that folds its own rows Svg, and the controls row holds none', async ($, on) => {
  mock.clock(on)
  baseHooks(on)
  let spawned = 0
  on('agent.spawn', () => ({ model: 'm', agentId: `a${(spawned += 1)}` }))
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await $.agent.spawn(SPAWN)
  await $.agent.spawn(groupSpawn('wf_review'))
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  const rowsAlts = async () => (await ui.findAll({ type: 'Svg' })).map(svg => String(svg.props['alt'])).filter(alt => alt.startsWith('Agent rows'))
  const controls = await ui.find({ key: 'controls' })
  const timeline = await ui.find({ key: 'timeline' })

  expect(JSON.stringify(controls)).not.toContain('group-button')
  expect(JSON.stringify(timeline)).toContain('group-button-direct')
  expect(JSON.stringify(timeline)).toContain('group-button-wf_review')
  expect(await rowsAlts()).toHaveLength(2)

  await ui.press({ key: 'group-button-direct' })

  const left = await rowsAlts()
  expect(left).toHaveLength(1)
  expect(left[0]).toContain('review')
  expect(JSON.stringify(await ui.find({ key: 'group-button-direct' }))).toContain('∨')
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
  expect(warm?.detail).toBe('warm ~2m')
  expect(cold?.detail).toBe('cold')
  expect(unmetered?.detail).toBe('warm ~1m')
  expect(piecesOf({ ...SVG_INPUT, gauges } as never).some(spec => spec.key === 'ring-cache')).toBe(false)
  expect(piecesOf({ ...SVG_INPUT } as never).some(spec => spec.key === 'ring-ctx')).toBe(true)
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

  expect(first.builtKeys.sort()).toEqual(['counts', 'ring-ctx', 'rule', 'timeline', 'timeline-more', 'timeline-rows-direct'])
  expect(changed.builtKeys).toEqual([])
  expect(changed.retryInMs).toBe(MIN_REBUILD_MS - 50)
  expect(unchanged.builtKeys).toEqual([])
  expect(buttonPress.builtKeys.sort()).toEqual(['timeline', 'timeline-more', 'timeline-rows-direct'])
  expect(settled.builtKeys).toEqual(['timeline-rows-direct'])
})

const endedAgo = (minutes: number) => {
  const live = addAgent(EMPTY_STORE, newAgent({ id: 'old', label: 'old-1', group: 'direct', groupLabel: 'direct agents', now: NOW - 10 * MINUTE }))
  const row = { ...live.rows[0], state: 'done', endedAt: NOW - minutes * MINUTE }
  const roster = { ...rosterOf(live), rows: rosterOf(live).rows.map(entry => ({ ...entry, phase: 'done' })) }

  return { roster, rows: new Map([['old', row]]) }
}

test('an agent that ended 2 min ago is hidden in range 1m, shown in 5m, and counted as earlier', () => {
  const at = (range: '1m' | '5m') => sourceOfPiece({ ...SVG_INPUT, ...endedAgo(2), range } as never, 'timeline-rows-direct')

  expect(at('1m')).not.toContain('old-1')
  expect(at('1m')).toContain('+1 earlier')
  expect(at('5m')).toContain('old-1')
  expect(at('5m')).not.toContain('earlier')
})

const SECONDS_PER_MINUTE = 60

test('a row that left the 1m window 4.9 s ago is still drawn, one that left 5.1 s ago is not', () => {
  const at = (secondsAgo: number) =>
    sourceOfPiece({ ...SVG_INPUT, ...endedAgo(secondsAgo / SECONDS_PER_MINUTE) } as never, 'timeline-rows-direct')

  expect(at(60 + 4.9)).toContain('old-1')
  expect(at(60 + 5.1)).not.toContain('old-1')
})

test('the folded band draws an agent trace 4.9 s after it ends and none at 5.1 s, and redraws when the linger runs out', () => {
  const folded = (secondsAgo: number) => ({ ...SVG_INPUT, ...endedAgo(secondsAgo / SECONDS_PER_MINUTE), isFolded: true }) as never
  const hasTraces = (secondsAgo: number) => piecesOf(folded(secondsAgo)).some(spec => spec.key === 'traces')

  expect(hasTraces(4.9)).toBe(true)
  expect(hasTraces(5.1)).toBe(false)
  expect(refreshAfterMs(folded(4.9)) ?? Number.POSITIVE_INFINITY).toBeLessThanOrEqual(100)
})

test('leaving the window rebuilds the timeline once and a quiet clock tick rebuilds nothing', () => {
  const input = { ...SVG_INPUT, ...endedAgo(0.5) } as never
  const first = chooseBand(new Map(), input)
  const quiet = chooseBand(first.caches, { ...(input as object), now: NOW + 10_000 } as never)
  const left = chooseBand(first.caches, { ...(input as object), now: NOW + 40_000 } as never)

  expect(quiet.builtKeys).toEqual([])
  expect(left.builtKeys).toEqual(['timeline-rows-direct'])
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
  const titleOf = async (): Promise<string> => {
    const texts = [...(await sourceOf(ui)).matchAll(/<text[^>]*>([^<]*)<\/text>/g)].map(match => match[1] ?? '')

    return texts.slice(texts.indexOf('main session') + 1, texts.indexOf('main session') + 3).join(', ')
  }
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

  expect(idleAtStart).toBe('IDLE')
  expect(thinking).toBe('WORKING')
  expect(tool).toBe('TOOL, make check')
  expect(idle).toBe('IDLE')
  expect(await sourceOf(ui)).not.toContain('>idle<')
  await ui.unmount()
})

test('the main row shows in range 1m with no agent at all, apart from the rows of every group', () => {
  const source = sourceOfPiece({ ...SVG_INPUT, range: '1m' } as never, 'timeline')
  const withAgent = sourceOfPiece({ ...SVG_INPUT, ...oneAgent('launched') } as never, 'timeline')

  expect(source).toContain('main session')
  expect(withAgent).toContain('main session')
  expect(withAgent).not.toContain('scout-1')
})

const withMain = (state: 'launched' | 'tool', command: string | null) => {
  const main = moveMain(EMPTY_STORE, { activity: { state: 'thinking', command: null }, now: NOW - 5_000 })
  const moved = state === 'tool' ? moveMain(main, { activity: { state, command }, now: NOW - 2_000 }) : main

  return { ...SVG_INPUT, rows: new Map([['main', moved.main]]) }
}

test('a main tool call rebuilds the timeline alone, never a ring', () => {
  const idle = chooseBand(new Map(), withMain('launched', null) as never)
  const called = chooseBand(idle.caches, { ...withMain('tool', 'make check'), now: NOW + MIN_REBUILD_MS + 50 } as never)

  expect(idle.builtKeys.sort()).toEqual(['counts', 'ring-ctx', 'rule', 'timeline'])
  expect(called.builtKeys).toEqual(['timeline'])
})

const stateRoster = (states: readonly ('tool' | 'thinking' | 'waiting' | 'done')[]) => {
  const store = states.reduce(
    (current, _, index) =>
      addAgent(current, newAgent({ id: `s${index}`, label: `agent-${index}`, group: 'direct', groupLabel: 'direct agents', now: NOW - 40_000 })),
    EMPTY_STORE,
  )
  const rows = new Map(
    store.rows.map((row, index): [string, (typeof store.rows)[number]] => {
      const state = states[index] ?? 'thinking'
      const isEnded = state === 'done'

      return [
        row.id,
        {
          ...row,
          state,
          endedAt: isEnded ? NOW - 10_000 : null,
          segments: [{ state, from: NOW - 30_000, to: isEnded ? NOW - 10_000 : null }],
        },
      ]
    }),
  )

  return { roster: rosterOf(store), rows }
}

test('a folded group counts its live agents by state, and an ended agent counts as none', () => {
  const { roster, rows } = stateRoster(['tool', 'tool', 'thinking', 'done'])
  const plan = listedGroupsOf({ ...SVG_INPUT, roster, rows, foldedGroups: ['direct'], range: '1m' } as never)

  expect(plan).toHaveLength(1)
  expect(liveStateCounts(rows, plan[0]?.agents ?? [])).toEqual({ tool: 2, thinking: 1, waiting: 0 })
})

test('only a folded group gets a density strip, drawn in the tool and thinking colours and never the done one', () => {
  const { roster, rows } = stateRoster(['tool', 'thinking', 'done'])
  const input = { ...SVG_INPUT, roster, rows, range: '1m' } as never
  const unfolded = piecesOf(input).map(spec => spec.key)
  const foldedInput = { ...(input as object), foldedGroups: ['direct'] } as never
  const folded = piecesOf(foldedInput).map(spec => spec.key)
  const source = sourceOfPiece(foldedInput, 'density-direct')

  expect(unfolded.some(key => key.startsWith('density-'))).toBe(false)
  expect(folded).toContain('density-direct')
  expect(folded).not.toContain('timeline-rows-direct')
  expect(source).toContain('class="sg-tool"')
  expect(source).toContain('class="sg-thinking"')
  expect(source).not.toContain('class="sg-waiting"')
  expect(source).not.toContain('class="sg-done"')
})

test('a folded group header says how many agents are in each state now, beside its density strip', async ($, on) => {
  mock.clock(on)
  baseHooks(on)
  on('agent.spawn', () => ({ model: 'm', agentId: 'a1' }))
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await $.agent.spawn(SPAWN)
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })

  expect(JSON.stringify(await ui.find({ key: 'group-header-direct' }))).toContain(' live · ')

  await ui.press({ key: 'group-button-direct' })

  const header = JSON.stringify(await ui.find({ key: 'group-header-direct' }))
  expect(header).toMatch(/idle|\d+ (tool|think|wait)/)
  expect(header).not.toMatch(/\b0 (tool|think|wait|ended)/)
  expect(header).not.toContain(' live · ')
  expect((await ui.findAll({ type: 'Svg' })).some(svg => String(svg.props['alt']).includes('agents per state'))).toBe(true)
  await ui.unmount()
})

const quietInput = (now: number) => {
  const { roster, rows } = stateRoster(['thinking'])
  const quietRows = new Map([...rows].map(([id, row]) => [id, { ...row, segments: [{ state: row.state, from: NOW - 150_000, to: null }] }]))

  return { ...SVG_INPUT, roster, rows: quietRows, range: '5m', now } as never
}

const signatureOfPiece = (input: Parameters<typeof piecesOf>[0], key: string): string => piecesOf(input).find(spec => spec.key === key)?.signature ?? ''

test('a quiet agent row reads "quiet 2m" in a muted amber pill on desktop, and its piece cache key changes when it turns quiet', () => {
  const quiet = quietInput(NOW)
  const justBefore = quietInput(NOW - 31_000)
  const source = sourceOfPiece(quiet, 'timeline-rows-direct')

  expect(source).toContain('>quiet 2m<')
  expect(source).toContain('class="pb-quiet"')
  expect(source).not.toContain('>THINKING<')
  expect(sourceOfPiece(justBefore, 'timeline-rows-direct')).toContain('>THINKING<')
  expect(signatureOfPiece(quiet, 'timeline-rows-direct')).not.toBe(signatureOfPiece(justBefore, 'timeline-rows-direct'))
})

test('a folded header strip is the track width and only 12px high, and no label piece exists (the Button holds the label)', () => {
  const folded = { ...(quietInput(NOW) as object), foldedGroups: ['direct'] } as never
  const density = sourceOfPiece(folded, 'density-direct')

  expect(piecesOf(folded).some(spec => spec.key.startsWith('group-label-'))).toBe(false)
  expect(Number(/width="(\d+)"/.exec(density)?.[1])).toBe(384)
  expect(Number(/height="(\d+)"/.exec(density)?.[1])).toBe(12)
})

test('a folded header gets its counts as a piece that fits the state column, in short words', () => {
  const folded = { ...(quietInput(NOW) as object), foldedGroups: ['direct'] } as never
  const counts = sourceOfPiece(folded, 'group-counts-direct')

  expect(counts).toContain('>1 think<')
  expect(counts).not.toContain('0 tool')
  expect(Number(/width="(\d+)"/.exec(counts)?.[1])).toBe(212)
})

test('group counts drop zeros', () => {
  expect(groupCountsText({ tool: 1, thinking: 0, waiting: 0 }, 5)).toBe('1 tool · 5 ended')
  expect(groupCountsText({ tool: 0, thinking: 0, waiting: 0 }, 0)).toBe('idle')
})

test('the auto theme paints no surface and tints with a translucent grey and a theme-key frame', () => {
  const auto = bandColorsOf('auto')

  expect(auto.surface).toBeUndefined()
  expect(auto.tint).toMatch(/^rgba\(/)
  expect(auto.frame).toBe('promptBorder')
  expect(bandColorsOf('dark').surface).toBeDefined()
})

test('on desktop one native range Button shows the range and cycles it on every press', async ($, on) => {
  mock.clock(on)
  baseHooks(on)
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })

  expect(JSON.stringify((await ui.find({ key: 'range' }))?.props)).toContain('range 1m ▾')

  await ui.press({ key: 'range' })

  expect(JSON.stringify((await ui.find({ key: 'range' }))?.props)).toContain('range 5m ▾')
  expect(await ui.find({ key: 'range-5m' })).toBeUndefined()
  await ui.unmount()
})

const LIVE_STORE = addAgent(EMPTY_STORE, newAgent({ id: 'live-1', label: 'worker', group: 'direct', groupLabel: 'direct agents', now: NOW - 20_000 }))

const OWNER_GAUGES = {
  ...EMPTY_GAUGES,
  contextPercent: 23,
  contextTokens: 227_000,
  contextWindow: 1_000_000,
  cachePercent: 84,
  fiveHour: { percent: 35, resetsAt: NOW + 3 * 3_600_000 },
  sevenDay: { percent: 11, resetsAt: NOW + 144 * 3_600_000 },
  sessionStartedAt: NOW - 62 * 3_600_000,
  lastCallAt: NOW - 4 * MINUTE,
  isSubscription: true,
}

test('the folded band keeps its live traces at 800 px and 1500 px with one live agent, shrunk to fit, and drops them when nothing fits', () => {
  const folded = (width: number) =>
    ({ ...SVG_INPUT, width, isFolded: true, roster: rosterOf(LIVE_STORE), rows: new Map([['live-1', LIVE_STORE.rows[0]]]), gauges: OWNER_GAUGES }) as never
  const traces = (width: number) => piecesOf(folded(width)).find(spec => spec.key === 'traces')?.build().width

  expect(traces(800)).toBeGreaterThanOrEqual(56)
  expect(traces(1500)).toBeGreaterThan(traces(800) ?? 0)
  expect(traces(1500)).toBeLessThanOrEqual(360)
  expect(traces(500)).toBeUndefined()
})

test('live, done and failed are three icon rows with numbers and no words, dim at zero, in both the folded and the open band', () => {
  const counts = (isFolded: boolean, done: number) => {
    const roster = { ...rosterOf(LIVE_STORE), evictedDone: done, evictedFailed: 0 }

    return sourceOfPiece({ ...SVG_INPUT, isFolded, roster, rows: new Map() } as never, 'counts')
  }

  for (const isFolded of [true, false]) {
    const source = counts(isFolded, 51)

    expect(source).toContain('ic-live')
    expect(source).toContain('ic-ok')
    expect(source).toContain('ic-bad ic-dim')
    expect(source).toContain('>51<')
    expect([...source.matchAll(/<text[^>]*>([^<]*)<\/text>/g)].map(match => match[1])).toEqual(['1', '51', '0'])
  }

  expect(counts(true, 0)).toContain('ic-ok ic-dim')
})

test('the cache gauge says only "cache" and a short detail: warm with minutes left, cold, or the hit rate', () => {
  const specOf = (gauges: typeof OWNER_GAUGES | typeof EMPTY_GAUGES) => gaugeSpecs(gauges, NOW).find(spec => spec.id === 'cache')

  expect(specOf(OWNER_GAUGES)?.name).toBe('cache')
  expect(specOf(OWNER_GAUGES)?.detail).toBe('warm ~56m')
  expect(specOf({ ...OWNER_GAUGES, lastCallAt: NOW - 61 * MINUTE })?.detail).toBe('cold')
  expect(specOf({ ...EMPTY_GAUGES, cachePercent: 84 })?.detail).toBe('84% hit')
})

test('the folded line keeps the counts at full width for 2 live, 53 done, 0 failed and the trace strip gives way', () => {
  const roster = { ...rosterOf(LIVE_STORE), evictedDone: 52, evictedFailed: 0 }

  for (const width of [900, 1000, 1500]) {
    const input = { ...SVG_INPUT, width, isFolded: true, roster, rows: new Map([['live-1', LIVE_STORE.rows[0]]]), gauges: OWNER_GAUGES } as never
    const built = piecesOf(input).map(spec => [spec.key, spec.build()] as const)
    const countsWidth = built.find(([key]) => key === 'counts')?.[1].width ?? 0
    const tracesWidth = built.find(([key]) => key === 'traces')?.[1].width ?? 0
    const specs = gaugeSpecs(OWNER_GAUGES, SVG_INPUT.now)
    const gauges = specs.reduce((sum, spec) => sum + 32 + Math.max(spec.name.length, spec.detail.replace(/\s*↻.*$/, '').length) * 7, 0)
    const fixed = FOLDED_UNFOLD_WIDTH + FOLDED_STATUS_WIDTH + gauges + (specs.length + 3) * FOLDED_GAP + FOLDED_CONTENT_INSET

    expect(countsWidth).toBeGreaterThanOrEqual(40.5)
    expect(tracesWidth + countsWidth + fixed).toBeLessThanOrEqual(width)
    expect(foldedTracesWidth(width, specs)).toBe(tracesWidth)
  }
})

test('a session end leaves no open segment, no live agent and no turn clock', async ($, on) => {
  const clock = mock.clock(on)
  baseHooks(on)
  on('agent.spawn', () => ({ model: 'm', agentId: 'a1' }))
  const written = { agents: [] as string[], turnStartedAt: [] as string[] }
  on('state.set', (_, e, next) => {
    if (e.key === 'agents') written.agents.push(JSON.stringify(e.value))
    if (e.key === 'turnStartedAt') written.turnStartedAt.push(JSON.stringify(e.value))

    return next(e)
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
