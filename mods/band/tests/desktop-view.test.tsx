import { type FoundElement, expect, mock, test } from 'claude-code/testing'

import { arcColorOf, paletteOf } from '../hooks/desktop-theme'
import { GUTTER_COLUMNS, STRIP_MIN_COLUMNS, TWO_TILES_MIN_COLUMNS } from '../hooks/view-desktop'
import { SETTLE_MS } from './settle'

const GAP_ALLOWANCE_COLUMNS = 4
const GUTTER_PADDING_COLUMNS = 4
const STRIP_PX_AT_100_COLUMNS = (100 - 36 - 1 - 4 - 37) * 8

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

const HOUR = 3_600_000
const MINUTE = 60_000

const LIMITS = [
  { kind: 'five_hour', percentUsed: 35, resetsAt: '1970-01-01T05:00:00Z' },
  { kind: 'seven_day', percentUsed: 52, resetsAt: '1970-01-05T05:00:00Z' },
  { kind: 'fable_weekly', percentUsed: 83, resetsAt: '1970-01-05T05:00:00Z' },
]

type Rate = { kind: string; percentUsed: number; resetsAt?: string }

const usageOf = (input: { percent: number; tokens: number; rateLimits: readonly Rate[]; startedAt?: number; usd?: number | null }) => ({
  startedAt: input.startedAt ?? 0,
  context: { window: 200_000, tokens: input.tokens, percent: input.percent },
  rateLimits: [...input.rateLimits],
  ...(input.usd === null ? {} : { cost: { usd: input.usd ?? 3.84 } }),
})

const hooksFor = (on: Parameters<typeof mock.clock>[0], usage: ReturnType<typeof usageOf>, theme = 'light') => {
  on('session.start', (_, event) => ({ cwd: event.cwd }))
  on('session.end', (_, event) => ({ sessionId: event.sessionId }))
  on('session.usage', () => ({ value: usage }))
  on('config.list', () => ({ value: [{ key: 'theme', label: 'Theme', kind: 'text', value: theme, provider: { plugin: 'engine', tier: 'core' }, isLocked: false }] }))
  on('agent.list', () => ({ value: [] }))
  on('turn.start', (_, event) => ({ turnId: event.turnId }))
  on('turn.complete', () => ({ text: '' }))
}

type Finder = { find: (query: { key: string }) => Promise<FoundElement | undefined>; findAll: (query: { type: string }) => Promise<FoundElement[]> }

const isFound = (value: unknown): value is FoundElement => typeof value === 'object' && value !== null && 'type' in value && 'props' in value

const childrenOf = (found: FoundElement | undefined): FoundElement[] => (found === undefined || !Array.isArray(found.children) ? [] : found.children.filter(isFound))

type Described = { props?: Record<string, unknown>; children?: unknown[] }

const isDescribed = (value: unknown): value is Described => typeof value === 'object' && value !== null

const stringsOf = (node: unknown): string => (typeof node === 'string' ? node : isDescribed(node) && Array.isArray(node.children) ? node.children.map(stringsOf).join('') : '')

const hiddenTextsOf = (node: unknown): string[] => (isDescribed(node) && Array.isArray(node.children) ? node.children.flatMap(child => (isDescribed(child) && child.props?.['display'] === 'none' ? [stringsOf(child)] : hiddenTextsOf(child))) : [])

const textOf = async (ui: Finder, key: string): Promise<string | undefined> => (await ui.find({ key }))?.text

const shownTextOf = async (ui: Finder, key: string): Promise<string | undefined> => {
  const found = await ui.find({ key })

  return found === undefined ? undefined : hiddenTextsOf(found).reduce((text, hidden) => text.replace(hidden, ''), found.text)
}

const firstTextColorOf = (found: FoundElement | undefined): unknown => {
  const queue = childrenOf(found)

  for (const child of queue) {
    if (child.type === 'Text' && child.props['color'] !== undefined) {
      return child.props['color']
    }

    queue.push(...childrenOf(child))
  }

  return undefined
}

const swatchColorOf = async (ui: Finder, id: string): Promise<unknown> => firstTextColorOf(await ui.find({ key: 'legend-' + id }))

const cardOf = (tile: FoundElement | undefined): FoundElement | undefined => childrenOf(tile).find(child => child.props['display'] === 'none')

const ringSourceOf = async (ui: Finder): Promise<string> => {
  const sources = (await ui.findAll({ type: 'Svg' })).map(svg => String(svg.props['source']))

  return sources.find(source => source.includes('<circle')) ?? ''
}

const countOf = (text: string | undefined, part: string): number => (text ?? '').split(part).length - 1

for (const theme of ['light', 'dark'] as const) {
  test(`folded in ${theme}, the legend swatch of each arc is the colour that arc is drawn in, Fable included`, async ($, on) => {
    mock.clock(on)
    hooksFor(on, usageOf({ percent: 28, tokens: 56_000, rateLimits: LIMITS }), theme)
    await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
    const ui = await $.ui.mount(BAND)

    await ui.press({ key: 'fold' })

    const palette = paletteOf(theme)
    const source = await ringSourceOf(ui)

    expect(await swatchColorOf(ui, 'fiveHour')).toBe(arcColorOf(palette, 'fiveHour'))
    expect(await swatchColorOf(ui, 'week')).toBe(arcColorOf(palette, 'week'))
    expect(await swatchColorOf(ui, 'fable')).toBe(arcColorOf(palette, 'fable'))
    expect(await swatchColorOf(ui, 'context')).toBe(arcColorOf(palette, 'context'))
    expect(source).toContain('--arcFable:' + arcColorOf(palette, 'fable'))
    expect(source).toContain('class="s-arcFiveHour"')
    expect(source).toContain('class="s-arcFable"')
    expect(countOf(source, '<circle')).toBe(8)
    expect(await shownTextOf(ui, 'legend-fiveHour')).toBe('●5h35%↻ in 5h 0m')
    expect(await shownTextOf(ui, 'legend-fable')).toBe('●Fable83% ▲↻ in 4d 5h')
    expect(await textOf(ui, 'legend-context')).toBe('●Ctx28%56k/200k')
    await ui.unmount()
  })
}

test('folded without a Fable limit, the ring has three arcs and the legend has no Fable entry', async ($, on) => {
  mock.clock(on)
  hooksFor(on, usageOf({ percent: 28, tokens: 56_000, rateLimits: LIMITS.slice(0, 2) }))
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  const ui = await $.ui.mount(BAND)

  await ui.press({ key: 'fold' })

  const source = await ringSourceOf(ui)

  expect(countOf(source, '<circle')).toBe(6)
  expect(source).not.toContain('class="s-arcFable"')
  expect(await ui.find({ key: 'legend-fable' })).toBeUndefined()
  expect(await ui.find({ key: 'legend-week' })).toBeDefined()
  await ui.unmount()
})

test('unfolded, the gutter shows each arc with its name, percent and a bar in its colour, then the spend split', async ($, on) => {
  mock.clock(on)
  hooksFor(on, usageOf({ percent: 28, tokens: 56_000, rateLimits: LIMITS, usd: 35.63 }))
  on('agent.spawn', () => ({ model: 'claude-sonnet-4-5', agentId: 'a1' }))
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await $.agent.spawn(SPAWN)
  await $.turn.complete({ ...TURN, agentId: 'a1', reason: 'answer', usage: { input_tokens: 1_000_000, output_tokens: 100_000, cache_read_input_tokens: 0, cache_creation_input_tokens: 0, model: 'claude-sonnet-4-5' } })
  const ui = await $.ui.mount(BAND)
  const palette = paletteOf('light')

  expect(await textOf(ui, 'arc-fiveHour')).toContain('5-hour35%')
  expect(await textOf(ui, 'arc-fable')).toContain('Fable83% ▲')
  expect(await textOf(ui, 'arc-context')).toBe('●Context28%56k of 200k')
  expect(firstTextColorOf(await ui.find({ key: 'arc-week' }))).toBe(arcColorOf(palette, 'week'))
  expect(await textOf(ui, 'spend-session')).toBe('session total$35.63')
  expect(await textOf(ui, 'spend-main')).toBe('main est.~$31.13')
  expect(await textOf(ui, 'spend-agents')).toBe('agents est.~$4.50')
  expect(await ui.find({ key: 'spend-in' })).toBeUndefined()
  expect(await textOf(ui, 'cost-main')).toBe('~$31.13')
  await ui.unmount()
})

test('with no total from the host, main est. is the token estimate and the label says so', async ($, on) => {
  mock.clock(on)
  hooksFor(on, usageOf({ percent: 28, tokens: 56_000, rateLimits: [], usd: null }))
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await $.turn.complete({ ...TURN, reason: 'answer', usage: { input_tokens: 1_000_000, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0, model: 'claude-opus-4-1' } })
  const ui = await $.ui.mount(BAND)

  expect(await textOf(ui, 'spend-session')).toBe('session total—')
  expect(await textOf(ui, 'spend-main')).toBe('main est. (tokens)~$5.00')
  expect(await textOf(ui, 'spend-in')).toBe('tokens in1M')
  expect(await ui.find({ key: 'spend-out' })).toBeUndefined()
  expect(await ui.find({ key: 'arc-fiveHour' })).toBeUndefined()
  expect(await ui.find({ key: 'arc-context' })).toBeDefined()
  await ui.unmount()
})

test('the main tile time is the session age, 1h52m, not hours counted from a distant first event', async ($, on) => {
  mock.clock(on, { now: 100 * HOUR })
  hooksFor(on, usageOf({ percent: 10, tokens: 20_000, rateLimits: LIMITS, startedAt: 100 * HOUR - (HOUR + 52 * MINUTE) }))
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  const ui = await $.ui.mount(BAND)

  expect(await textOf(ui, 'time-main')).toBe('1h52m')
  await ui.unmount()
})

test('unfolded and folded share no fact: the session cost shows once in each, and each view lacks the other\'s parts', async ($, on) => {
  mock.clock(on)
  hooksFor(on, usageOf({ percent: 28, tokens: 56_000, rateLimits: LIMITS, usd: 35.63 }))
  on('agent.spawn', () => ({ model: 'claude-sonnet-4-5', agentId: 'a1' }))
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await $.agent.spawn(SPAWN)
  await $.turn.complete({ ...TURN, agentId: 'a1', reason: 'answer', usage: { input_tokens: 1_000_000, output_tokens: 100_000, cache_read_input_tokens: 0, cache_creation_input_tokens: 0, model: 'claude-sonnet-4-5' } })
  const ui = await $.ui.mount(BAND)
  const unfolded = await textOf(ui, 'unfolded')

  expect(countOf(unfolded, '$35.63')).toBe(1)
  expect(countOf(unfolded, '35%')).toBe(1)
  expect(countOf(unfolded, '28%')).toBe(1)
  expect(await ui.find({ key: 'cost' })).toBeUndefined()
  expect(await ringSourceOf(ui)).toBe('')
  expect(await ui.find({ key: 'legend' })).toBeUndefined()
  expect(await ui.find({ key: 'mini-lanes' })).toBeUndefined()
  expect(await ui.find({ key: 'main-state' })).toBeUndefined()
  expect(await ui.find({ key: 'gutter' })).toBeDefined()
  expect(await ui.find({ key: 'tile-a1' })).toBeDefined()

  await ui.press({ key: 'fold' })
  const folded = await textOf(ui, 'folded')

  expect(countOf(folded, '$35.63')).toBe(1)
  expect(countOf(folded, '35%')).toBe(1)
  expect(await ui.find({ key: 'gutter' })).toBeUndefined()
  expect(await ui.find({ key: 'tile-main' })).toBeUndefined()
  expect(await ui.find({ key: 'header' })).toBeUndefined()
  expect(await ui.find({ key: 'spend-session' })).toBeUndefined()
  expect(await ringSourceOf(ui)).toContain('<circle')
  expect(await ui.find({ key: 'mini-lanes' })).toBeDefined()
  expect(await textOf(ui, 'main-state')).toContain('main')
  await ui.unmount()
})

test('with no agents the empty slot says "No agents yet this session." and is not a button', async ($, on) => {
  mock.clock(on)
  hooksFor(on, usageOf({ percent: 10, tokens: 20_000, rateLimits: LIMITS }))
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  const ui = await $.ui.mount(BAND)

  expect(await textOf(ui, 'ghost')).toBe('No agents yet this session.')
  expect(await ui.find({ key: 'earlier' })).toBeUndefined()
  expect(await ui.find({ key: 'tile-main' })).toBeDefined()
  await ui.unmount()
})

test('an agent that ended before the range shows "+1 ended earlier", not "No agents yet", and pressing it switches to all', async ($, on) => {
  const clock = mock.clock(on)
  hooksFor(on, usageOf({ percent: 10, tokens: 20_000, rateLimits: LIMITS }))
  on('agent.spawn', () => ({ model: 'm', agentId: 'a1' }))
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  const ui = await $.ui.mount(BAND)
  await $.agent.spawn(SPAWN)
  await $.turn.complete({ ...TURN, agentId: 'a1', reason: 'answer' })
  await clock.advance(2 * MINUTE)

  expect(await textOf(ui, 'ghost')).toBe('+1 ended earlier')
  expect(await textOf(ui, 'ghost')).not.toContain('No agents')
  expect(await ui.find({ key: 'tile-a1' })).toBeUndefined()

  await ui.press({ key: 'earlier' })
  await clock.advance(SETTLE_MS)

  expect(await ui.find({ key: 'tile-a1' })).toBeDefined()
  expect((await ui.find({ key: 'range-session' }))?.props['variant']).toBe('primary')
  expect(await ui.find({ key: 'earlier' })).toBeUndefined()
  await ui.unmount()
})

test('a tile shows name, model, state, detail, strip, time, tokens and cost, and hover reveals the full facts', async ($, on) => {
  const clock = mock.clock(on)
  hooksFor(on, usageOf({ percent: 10, tokens: 20_000, rateLimits: LIMITS }))
  on('agent.spawn', () => ({ model: 'claude-sonnet-4-5', agentId: 'a1' }))
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  const ui = await $.ui.mount(BAND)
  await $.agent.spawn(SPAWN)
  await $.turn.complete({ ...TURN, agentId: 'a1', reason: 'error', usage: { input_tokens: 1_000_000, output_tokens: 100_000, cache_read_input_tokens: 0, cache_creation_input_tokens: 0, model: 'claude-sonnet-4-5' } })
  await clock.advance(SETTLE_MS)

  expect(await textOf(ui, 'name-a1')).toBe('build-1')
  expect(await textOf(ui, 'model-a1')).toBe('sonnet')
  expect(await textOf(ui, 'state-a1')).toBe('✕ failed')
  expect(await textOf(ui, 'detail-a1')).toBe('error')
  expect(await textOf(ui, 'tokens-a1')).toBe('1M↓ 100k↑')
  expect(await textOf(ui, 'cost-a1')).toBe('~$4.50')
  expect((await ui.findAll({ type: 'Svg' })).some(svg => svg.props['alt'] === 'build-1 activity over the range')).toBe(true)
  expect(await textOf(ui, 'tile-a1')).toContain('ran for')
  expect(cardOf(await ui.find({ key: 'tile-a1' }))?.props['display']).toBe('none')
  await ui.unmount()
})

const TRUNCATING_WRAPS = ['truncate', 'truncate-end', 'truncate-start', 'truncate-middle']

const truncatingTextsIn = async (ui: Finder, key: string): Promise<string[]> => {
  const queue = childrenOf(await ui.find({ key }))
  const truncating: string[] = []

  for (const child of queue) {
    if (child.type === 'Text' && TRUNCATING_WRAPS.includes(String(child.props['wrap']))) {
      truncating.push(child.text ?? '')
    }

    queue.push(...childrenOf(child))
  }

  return truncating
}

const textLinesOf = (found: FoundElement | undefined): number => {
  if (found === undefined) {
    return 0
  }

  if (found.type === 'Text') {
    return 1
  }

  const lines = childrenOf(found).map(textLinesOf)

  return found.props['flexDirection'] === 'column' ? lines.reduce((sum, count) => sum + count, 0) : Math.max(0, ...lines)
}

test('folded, the row is two text lines tall in every column, the cost sits in the legend, the lane grows and nothing trails the chevron', async ($, on) => {
  mock.clock(on)
  hooksFor(on, usageOf({ percent: 28, tokens: 56_000, rateLimits: LIMITS }))
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  const ui = await $.ui.mount(BAND)

  await ui.press({ key: 'fold' })

  const folded = await ui.find({ key: 'folded' })
  const row = childrenOf(folded)

  for (const column of row) {
    expect(textLinesOf(column)).toBeLessThanOrEqual(2)
  }

  expect(textLinesOf(await ui.find({ key: 'legend' }))).toBe(2)
  expect(await textOf(ui, 'legend')).toContain('$3.84')
  expect(await ui.find({ key: 'cost' })).toBeDefined()
  expect((await ui.find({ key: 'mini-lanes' }))?.props['flexGrow']).toBe(1)
  expect(await textOf(ui, 'main-state')).toContain('▶0')
  expect(row[row.length - 1]?.type).toBe('Button')
  await ui.unmount()
})

test('nothing the owner reads in full is ellipsised: legend and header texts never truncate, and the longest gutter row fits the gutter', async ($, on) => {
  mock.clock(on)
  hooksFor(on, usageOf({ percent: 100, tokens: 200_000, rateLimits: LIMITS.map(limit => ({ ...limit, percentUsed: 100 })) }))
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  const ui = await $.ui.mount(BAND)

  expect(await truncatingTextsIn(ui, 'header')).toEqual([])

  for (const id of ['fiveHour', 'week', 'fable', 'context']) {
    const row = (await shownTextOf(ui, 'arc-' + id)) ?? ''

    expect(await truncatingTextsIn(ui, 'arc-' + id)).toEqual([])
    expect(row.length + GAP_ALLOWANCE_COLUMNS).toBeLessThanOrEqual(GUTTER_COLUMNS - GUTTER_PADDING_COLUMNS)
  }

  await ui.press({ key: 'fold' })

  for (const id of ['fiveHour', 'week', 'fable', 'context']) {
    expect(await truncatingTextsIn(ui, 'legend-' + id)).toEqual([])
  }

  expect(await shownTextOf(ui, 'legend-fable')).toBe('●Fable100% ▲↻ in 4d 5h')
  expect((await ui.find({ key: 'legend' }))?.props['overflow']).toBeUndefined()
  await ui.unmount()
})

test('a tile bottom line can shrink its strip, keeps time and cost at natural width, and shows no placeholder before usage', async ($, on) => {
  mock.clock(on)
  hooksFor(on, usageOf({ percent: 28, tokens: 56_000, rateLimits: LIMITS }))
  on('agent.spawn', () => ({ model: 'claude-sonnet-4-5', agentId: 'a1' }))
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await $.agent.spawn(SPAWN)
  const ui = await $.ui.mount(BAND)

  for (const id of ['main', 'a1']) {
    const strip = await ui.find({ key: 'strip-' + id })

    expect(strip?.props['flexShrink']).toBe(1)
    expect(strip?.props['minWidth']).toBe(STRIP_MIN_COLUMNS)
    expect(strip?.props['overflow']).toBe('hidden')
    expect(childrenOf(strip)[0]?.props['width']).toBe(STRIP_PX_AT_100_COLUMNS)
    expect((await ui.find({ key: 'time-' + id }))?.props['flexShrink']).toBe(0)
  }

  expect(await textOf(ui, 'tokens-a1')).toBe('no usage')
  expect(await textOf(ui, 'cost-a1')).toBe('')
  expect(await textOf(ui, 'bottom-a1')).not.toContain('—')
  await ui.unmount()
})

test('every tile bottom line has the same strip and slot boxes, and no tile text is ellipsised, with usage or without', async ($, on) => {
  const clock = mock.clock(on)
  hooksFor(on, usageOf({ percent: 28, tokens: 56_000, rateLimits: LIMITS }))
  let spawned = 0
  on('agent.spawn', () => ({ model: 'claude-sonnet-4-5', agentId: 'a' + ++spawned }))
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  const ui = await $.ui.mount(BAND)
  await $.agent.spawn(SPAWN)
  await $.agent.spawn(SPAWN)
  await $.turn.complete({ ...TURN, agentId: 'a1', reason: 'answer', usage: { input_tokens: 8_100_000, output_tokens: 92_000, cache_read_input_tokens: 0, cache_creation_input_tokens: 0, model: 'claude-sonnet-4-5' } })
  await clock.advance(SETTLE_MS)

  const boxesOf = async (id: string) => {
    const strip = await ui.find({ key: 'strip-' + id })
    const tokens = await ui.find({ key: 'tokens-' + id })
    const cost = await ui.find({ key: 'cost-' + id })

    return [strip, tokens, cost].map(found => [found?.props['flexGrow'], found?.props['flexShrink'], found?.props['width']])
  }

  expect(await textOf(ui, 'tokens-a1')).toBe('8.1M↓ 92k↑')
  expect(await textOf(ui, 'tokens-a2')).toBe('no usage')
  expect(await boxesOf('a2')).toEqual(await boxesOf('a1'))
  expect(await boxesOf('main')).toEqual(await boxesOf('a1'))

  for (const id of ['tokens-a1', 'tokens-a2', 'cost-a1']) {
    expect(await truncatingTextsIn(ui, id)).toEqual([])
  }

  await ui.unmount()
})

test('an agent that finishes before its spawn is recorded still has its tokens and cost counted', async ($, on) => {
  mock.clock(on)
  hooksFor(on, usageOf({ percent: 28, tokens: 56_000, rateLimits: LIMITS, usd: 35.63 }))
  let release: () => void = () => undefined
  const started = new Promise<void>(resolve => {
    release = resolve
  })
  on('agent.spawn', async () => {
    await started

    return { model: 'claude-sonnet-4-5', agentId: 'a1' }
  })
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  const spawning = $.agent.spawn(SPAWN)
  await $.turn.complete({ ...TURN, agentId: 'a1', reason: 'answer', usage: { input_tokens: 1_000_000, output_tokens: 100_000, cache_read_input_tokens: 0, cache_creation_input_tokens: 0, model: 'claude-sonnet-4-5' } })
  release()
  await spawning
  const ui = await $.ui.mount(BAND)

  expect(await textOf(ui, 'spend-agents')).toBe('agents est.~$4.50')
  await ui.unmount()
})

type TileLayout = { sizes: number[]; stripMinimums: unknown[] }

const tileLayoutTest = (name: string, columns: number, check: (layout: TileLayout) => void) => {
  test(name, async ($, on) => {
    mock.clock(on)
    hooksFor(on, usageOf({ percent: 28, tokens: 56_000, rateLimits: LIMITS }))
    let spawned = 0
    on('agent.spawn', () => ({ model: 'claude-sonnet-4-5', agentId: 'a' + ++spawned }))
    await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
    await $.agent.spawn(SPAWN)
    await $.agent.spawn(SPAWN)
    const ui = await $.ui.mount({ ...BAND, props: { ...BAND.props, bodyColumns: columns } })
    const boxes = await ui.findAll({ type: 'Box' })
    const keyOf = (box: FoundElement) => String(box.props['key'])
    const sizes = boxes.filter(box => keyOf(box).startsWith('tile-row-')).map(row => childrenOf(row).filter(child => keyOf(child).startsWith('tile-')).length)
    const stripMinimums = boxes.filter(box => keyOf(box).startsWith('strip-')).map(strip => strip.props['minWidth'])
    await ui.unmount()
    check({ sizes, stripMinimums })
  })
}

tileLayoutTest('a narrow band stacks the tiles in one column and never lets a strip shrink below its minimum', TWO_TILES_MIN_COLUMNS - 1, layout => {
  expect(layout.sizes).toEqual([1, 1, 1])
  expect(layout.stripMinimums).toEqual([STRIP_MIN_COLUMNS, STRIP_MIN_COLUMNS, STRIP_MIN_COLUMNS])
})

tileLayoutTest('a wide band keeps two tile columns', TWO_TILES_MIN_COLUMNS, layout => {
  expect(layout.sizes).toEqual([2, 1])
})

const bandAt = (columns: number) => ({ ...BAND, props: { ...BAND.props, bodyColumns: columns } })

const svgWidthsOf = async (ui: Finder, altStart: string): Promise<unknown[]> => (await ui.findAll({ type: 'Svg' })).filter(svg => String(svg.props['alt']).startsWith(altStart)).map(svg => svg.props['width'])

test('nothing to count shows no zero rows: no tokens in or out, no agents estimate, no main estimate equal to the total, and no 0 in / 0 out', async ($, on) => {
  mock.clock(on)
  hooksFor(on, usageOf({ percent: 13, tokens: 132_000, rateLimits: [], usd: 50.72 }))
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  const ui = await $.ui.mount(BAND)

  expect(await textOf(ui, 'spend-session')).toBe('session total$50.72')

  for (const key of ['spend-main', 'spend-agents', 'spend-in', 'spend-out']) {
    expect(await ui.find({ key })).toBeUndefined()
  }

  expect(await textOf(ui, 'unfolded')).not.toMatch(/\b0 in|\b0 out|~\$0\.00/)
  await ui.press({ key: 'fold' })
  expect(await textOf(ui, 'folded')).not.toMatch(/\b0 in|\b0 out/)
  await ui.unmount()
})

test('API billing is not claimed before an answer has come since the load, and is claimed after one arrives with no limits', async ($, on) => {
  mock.clock(on)
  hooksFor(on, usageOf({ percent: 13, tokens: 132_000, rateLimits: [], usd: 50.72 }))
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  const ui = await $.ui.mount(BAND)
  await ui.press({ key: 'fold' })

  expect(await textOf(ui, 'legend')).not.toContain('API')
  await $.turn.complete({ ...TURN, reason: 'answer', usage: { input_tokens: 1_000_000, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0, model: 'claude-opus-4-1' } })
  await ui.unmount()
  const after = await $.ui.mount(BAND)

  expect(await textOf(after, 'legend')).toContain('API billing · 1M in / 0 out')
  await after.unmount()
})

test('with limits reported there is no API billing label, even after an answer', async ($, on) => {
  mock.clock(on)
  hooksFor(on, usageOf({ percent: 13, tokens: 132_000, rateLimits: LIMITS }))
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await $.turn.complete({ ...TURN, reason: 'answer', usage: { input_tokens: 10, output_tokens: 10, cache_read_input_tokens: 0, cache_creation_input_tokens: 0, model: 'claude-opus-4-1' } })
  const ui = await $.ui.mount(BAND)
  await ui.press({ key: 'fold' })

  expect(await textOf(ui, 'legend')).not.toContain('API')
  await ui.unmount()
})

test('the folded lane and every tile strip get an explicit width that grows by 8 px for each extra column', async ($, on) => {
  mock.clock(on)
  hooksFor(on, usageOf({ percent: 13, tokens: 132_000, rateLimits: LIMITS }))
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  const narrow = await $.ui.mount(bandAt(120))
  const stripNarrow = (await svgWidthsOf(narrow, 'main activity'))[0]
  await narrow.press({ key: 'fold' })
  const laneNarrow = (await svgWidthsOf(narrow, 'main and live agents'))[0]
  await narrow.unmount()
  const wide = await $.ui.mount(bandAt(139))
  const laneWide = (await svgWidthsOf(wide, 'main and live agents'))[0]
  await wide.press({ key: 'fold' })
  const stripWide = (await svgWidthsOf(wide, 'main activity'))[0]
  await wide.unmount()

  expect(stripNarrow).toBe((120 - 36 - 1 - 4 - 37) * 8)
  expect(stripWide).toBe((139 - 36 - 1 - 4 - 37) * 8)
  expect(Number(laneNarrow)).toBeGreaterThan(14 * 8)
  expect(Number(laneWide) - Number(laneNarrow)).toBe(19 * 8)
})

test('the strip keeps its minimum width on a band too narrow to fill and the lane never drops under its minimum', async ($, on) => {
  mock.clock(on)
  hooksFor(on, usageOf({ percent: 13, tokens: 132_000, rateLimits: LIMITS }))
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  const ui = await $.ui.mount(bandAt(60))

  expect((await svgWidthsOf(ui, 'main activity'))[0]).toBe(STRIP_MIN_COLUMNS * 8)
  await ui.press({ key: 'fold' })
  expect((await svgWidthsOf(ui, 'main and live agents'))[0]).toBe(14 * 8)
  await ui.unmount()
})

test('a main tile with a cost and no tokens shows the cost and no "no usage"', async ($, on) => {
  mock.clock(on)
  hooksFor(on, usageOf({ percent: 13, tokens: 132_000, rateLimits: LIMITS, usd: 50.72 }))
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  const ui = await $.ui.mount(BAND)

  expect(await textOf(ui, 'cost-main')).toBe('~$50.72')
  expect(await textOf(ui, 'tokens-main')).toBe('')
  await ui.unmount()
})

test('a main tile with neither tokens nor cost shows "no usage"', async ($, on) => {
  mock.clock(on)
  hooksFor(on, usageOf({ percent: 13, tokens: 132_000, rateLimits: LIMITS, usd: null }))
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  const ui = await $.ui.mount(BAND)

  expect(await textOf(ui, 'tokens-main')).toBe('no usage')
  expect(await textOf(ui, 'cost-main')).toBe('')
  await ui.unmount()
})

test('the empty-session note is one muted line: no border, no growth, not a tile slot', async ($, on) => {
  mock.clock(on)
  hooksFor(on, usageOf({ percent: 13, tokens: 132_000, rateLimits: LIMITS }))
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  const ui = await $.ui.mount(BAND)
  const ghost = await ui.find({ key: 'ghost' })

  expect(ghost?.props['borderStyle']).toBeUndefined()
  expect(ghost?.props['flexGrow']).toBeUndefined()
  expect(childrenOf(ghost)[0]?.props['dimColor']).toBe(true)
  expect(textLinesOf(ghost)).toBe(1)

  for (const row of (await ui.findAll({ type: 'Box' })).filter(box => String(box.props['key']).startsWith('tile-row-'))) {
    expect(childrenOf(row).map(child => child.props['key'])).not.toContain('ghost')
  }

  await ui.unmount()
})
