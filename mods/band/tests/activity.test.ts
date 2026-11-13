import { expect, test } from 'claude-code/testing'

import type { AgentRow, AgentState, Gauges, Roster } from '../types'

import { ACTIVITY_ICON, ACTIVITY_KINDS, ACTIVITY_WORD, activityOf, cellsOf, runsOf, toolKindOf } from '../hooks/activity'
import { arcsOf, legendColumnsOf } from '../hooks/arcs'
import { ghostOf, mainEstimateLabelOf, mainEstimateOf, tileOf } from '../hooks/desktop'
import { ARC_IDS, STATE_COLOR_KEYS, arcColorOf, paletteOf } from '../hooks/desktop-theme'
import { stripSvg } from '../hooks/desktop-svg'
import { formatAge } from '../hooks/format'
import { EMPTY_GAUGES } from '../hooks/gauges'
import { EMPTY_ROSTER, newMainRow } from '../hooks/model'

const NOW = 1_000_000_000
const MINUTE = 60_000
const HOUR = 3_600_000

const agentRow = (patch: Partial<AgentRow>): AgentRow => ({ id: 'a1', label: 'build-1', group: 'direct', groupLabel: 'direct agents', state: 'thinking', command: null, startedAt: NOW - 5 * MINUTE, endedAt: null, segments: [], ...patch })

const mainRow = (patch: Partial<AgentRow>): AgentRow => ({ ...newMainRow(NOW - 10 * MINUTE), ...patch })

const gaugesWith = (kinds: readonly string[]): Gauges => ({
  ...EMPTY_GAUGES,
  contextPercent: 28,
  contextTokens: 283_000,
  contextWindow: 1_000_000,
  limits: kinds.map((kind, index) => ({ kind, name: kind, percent: 50 + index, resetsAt: null })),
})

const hueOf = (hex: string): number => {
  const [red = 0, green = 0, blue = 0] = [1, 3, 5].map(offset => parseInt(hex.slice(offset, offset + 2), 16) / 255)
  const high = Math.max(red, green, blue)
  const spread = high - Math.min(red, green, blue)
  const sector = high === red ? ((green - blue) / spread) % 6 : high === green ? (blue - red) / spread + 2 : (red - green) / spread + 4

  return (sector * 60 + 360) % 360
}

const saturationOf = (hex: string): number => {
  const [red = 0, green = 0, blue = 0] = [1, 3, 5].map(offset => parseInt(hex.slice(offset, offset + 2), 16) / 255)
  const high = Math.max(red, green, blue)
  const low = Math.min(red, green, blue)

  return high === 0 ? 0 : (high - low) / high
}

const hueGap = (left: string, right: string): number => {
  const gap = Math.abs(hueOf(left) - hueOf(right))

  return Math.min(gap, 360 - gap)
}

const MIN_HUE_GAP_DEGREES = 30
const MAX_NEUTRAL_SATURATION = 0.3

for (const setting of ['light', 'dark'] as const) {
  test(`the four arc colours differ from each other and from the state colours in ${setting}`, () => {
    const palette = paletteOf(setting)
    const hues = ARC_IDS.filter(id => id !== 'context').map(id => arcColorOf(palette, id))
    const states = STATE_COLOR_KEYS.map(key => palette[key])
    const everyColor = [...ARC_IDS.map(id => arcColorOf(palette, id)), ...states]

    expect(new Set(everyColor).size).toBe(everyColor.length)
    expect(saturationOf(arcColorOf(palette, 'context'))).toBeLessThan(MAX_NEUTRAL_SATURATION)

    for (const [index, hue] of hues.entries()) {
      for (const other of [...hues.slice(index + 1), ...states]) {
        expect(hueGap(hue, other)).toBeGreaterThanOrEqual(MIN_HUE_GAP_DEGREES)
      }
    }
  })
}

test('arcs follow the limits sent: five-hour, week, Fable only when sent, then context', () => {
  const withFable = arcsOf(gaugesWith(['five_hour', 'seven_day', 'fable_weekly']))
  const withoutFable = arcsOf(gaugesWith(['five_hour', 'seven_day']))
  const apiBilling = arcsOf(gaugesWith([]))

  expect(withFable.map(arc => arc.id)).toEqual(['fiveHour', 'week', 'fable', 'context'])
  expect(withFable.map(arc => arc.short)).toEqual(['5h', 'Wk', 'Fable', 'Ctx'])
  expect(withoutFable.map(arc => arc.id)).toEqual(['fiveHour', 'week', 'context'])
  expect(apiBilling.map(arc => arc.id)).toEqual(['context'])
  expect(withFable.at(-1)?.usage).toBe('283k of 1M')
})

test('the legend splits the arcs over two columns so 5h and Fable stack, and Wk and Ctx stack', () => {
  const [first, second] = legendColumnsOf(arcsOf(gaugesWith(['five_hour', 'seven_day', 'fable_weekly'])))

  expect(first.map(arc => arc.id)).toEqual(['fiveHour', 'fable'])
  expect(second.map(arc => arc.id)).toEqual(['week', 'context'])
})

test('a time is read in the largest two units, and a resumed session of 82h45m reads in days', () => {
  expect(formatAge(45_000)).toBe('45s')
  expect(formatAge(3 * MINUTE + 40_000)).toBe('3m40s')
  expect(formatAge(HOUR + 52 * MINUTE)).toBe('1h52m')
  expect(formatAge(82 * HOUR + 45 * MINUTE)).toBe('3d10h')
})

const SPEND_CONTEXT = (sessionStartedAt: number | null) => ({ now: NOW, window: { start: NOW - MINUTE, end: NOW }, sessionStartedAt, spend: { sessionUsd: null, agentsUsd: 0, main: { usd: null, isFromTotal: false }, tokensIn: 0, tokensOut: 0 } })

test('the main tile time is the session age from its start, not from the first event', () => {
  const row = mainRow({ startedAt: NOW - 5 * MINUTE })
  const tile = tileOf(row, SPEND_CONTEXT(NOW - (HOUR + 52 * MINUTE)))
  const unknown = tileOf(row, SPEND_CONTEXT(null))

  expect(tile.time).toBe('1h52m')
  expect(unknown.time).toBe('5m00s')
  expect(tile.name).toBe('main')
})

test('main est. is the session total minus the agents, else the token estimate, and says which', () => {
  const fromTotal = mainEstimateOf({ sessionUsd: 35.63, agentsUsd: 1.69, mainTokensUsd: 0.48 })
  const fromTokens = mainEstimateOf({ sessionUsd: null, agentsUsd: 1.69, mainTokensUsd: 0.48 })
  const overspent = mainEstimateOf({ sessionUsd: 1, agentsUsd: 2, mainTokensUsd: 0.48 })

  expect(Math.round((fromTotal.usd ?? 0) * 100)).toBe(3394)
  expect(fromTotal.isFromTotal).toBe(true)
  expect(fromTokens).toEqual({ usd: 0.48, isFromTotal: false })
  expect(overspent.usd).toBe(0)
  expect(mainEstimateLabelOf(fromTotal)).toBe('main est.')
  expect(mainEstimateLabelOf(fromTokens)).toBe('main est. (tokens)')
})

const roster = (patch: Partial<Roster>): Roster => ({ ...EMPTY_ROSTER, ...patch })

const MEMBER = { id: 'a1', label: 'build-1', group: 'direct', groupLabel: 'direct agents', phase: 'done' as const }

test('the empty slot says "No agents yet this session." only when there were none, else "+N ended earlier"', () => {
  expect(ghostOf({ roster: EMPTY_ROSTER, earlier: 0, hidden: 0 })).toEqual({ text: 'No agents yet this session.', widensRange: false })
  expect(ghostOf({ roster: roster({ rows: [MEMBER] }), earlier: 1, hidden: 0 })).toEqual({ text: '+1 ended earlier', widensRange: true })
  expect(ghostOf({ roster: roster({ rows: [], evictedDone: 2 }), earlier: 0, hidden: 0 })).toEqual({ text: '+2 ended earlier', widensRange: true })
  expect(ghostOf({ roster: roster({ rows: [MEMBER] }), earlier: 0, hidden: 0 })).toBeNull()
  expect(ghostOf({ roster: roster({ rows: [MEMBER] }), earlier: 0, hidden: 3 })?.widensRange).toBe(false)
})

test('a command maps to its tool kind and target, and anything that is not a named tool is bash', () => {
  expect(toolKindOf('make band')).toEqual({ kind: 'bash', target: 'make band' })
  expect(toolKindOf('Edit hooks/a.ts')).toEqual({ kind: 'editing', target: 'hooks/a.ts' })
  expect(toolKindOf('Write x.md').kind).toBe('editing')
  expect(toolKindOf('Read SPEC.md')).toEqual({ kind: 'reading', target: 'SPEC.md' })
  expect(toolKindOf('Grep spendOf').kind).toBe('searching')
  expect(toolKindOf('Glob **/*.ts').kind).toBe('searching')
  expect(toolKindOf('WebFetch https://a.b').kind).toBe('web')
  expect(toolKindOf('WebSearch q').kind).toBe('web')
  expect(toolKindOf('Task build it')).toEqual({ kind: 'agent', target: 'build it' })
  expect(toolKindOf('Read')).toEqual({ kind: 'reading', target: '' })
})

const kindOf = (row: AgentRow): string => activityOf(row, NOW).kind

test('every state has its own icon and the right word, from the row state and command', () => {
  const waiting = agentRow({ state: 'waiting', command: 'WebFetch https://a.b', segments: [{ state: 'waiting', from: NOW - 1000, to: null }] })
  const tool = (command: string) => agentRow({ state: 'tool', command })

  expect(kindOf(mainRow({ state: 'launched' }))).toBe('idle')
  expect(kindOf(agentRow({ state: 'thinking' }))).toBe('thinking')
  expect(kindOf(mainRow({ state: 'waiting' }))).toBe('needs-you')
  expect(kindOf(waiting)).toBe('permission')
  expect(activityOf(waiting, NOW).detail).toBe('permission: WebFetch')
  expect(kindOf(tool('make band'))).toBe('bash')
  expect(kindOf(tool('Edit a.ts'))).toBe('editing')
  expect(kindOf(tool('Read a.ts'))).toBe('reading')
  expect(kindOf(tool('Grep x'))).toBe('searching')
  expect(kindOf(tool('WebSearch x'))).toBe('web')
  expect(kindOf(tool('Task x'))).toBe('agent')
  expect(kindOf(agentRow({ state: 'done', endedAt: NOW }))).toBe('done')
  expect(activityOf(agentRow({ state: 'failed', endedAt: NOW, failReason: 'exit 2' }), NOW)).toMatchObject({ kind: 'failed', detail: 'exit 2', word: 'failed' })
  expect(new Set(ACTIVITY_KINDS.map(kind => ACTIVITY_ICON[kind])).size).toBe(ACTIVITY_KINDS.length)
  expect(ACTIVITY_KINDS.map(kind => ACTIVITY_WORD[kind])).toEqual(['idle', 'thinking', 'waiting', 'waiting', 'bash', 'editing', 'reading', 'searching', 'web', 'agent', 'done', 'failed'])
})

test('a main idle for the whole range is drawn as dotted light cells, never as ink', () => {
  const window = { start: NOW - 5 * MINUTE, end: NOW }
  const idle = mainRow({ state: 'launched', startedAt: window.start - MINUTE, segments: [{ state: 'launched', from: window.start - MINUTE, to: null }] })
  const cells = cellsOf(idle, window, NOW)
  const source = stripSvg({ cells, setting: 'light' }).source
  const body = source.slice(source.indexOf('</style>'))

  expect(cells.every(cell => cell === 'idle')).toBe(true)
  expect(runsOf(cells)).toEqual([{ kind: 'idle', from: 0, count: 24 }])
  expect(body).not.toContain('f-ink')
  expect(body).toContain('f-muted')
  expect(body.match(/f-rail/g)).toHaveLength(24)
})

test('a working main is ink and a working agent is violet, with thinking the soft shade', () => {
  const window = { start: NOW - 4 * MINUTE, end: NOW }
  const segments = (state: AgentState) => [{ state, from: window.start - MINUTE, to: null }]

  expect(cellsOf(mainRow({ state: 'tool', segments: segments('tool') }), window, NOW)[0]).toBe('ink')
  expect(cellsOf(mainRow({ state: 'thinking', segments: segments('thinking') }), window, NOW)[0]).toBe('inkSoft')
  expect(cellsOf(agentRow({ state: 'tool', segments: segments('tool') }), window, NOW)[0]).toBe('run')
  expect(cellsOf(agentRow({ state: 'thinking', segments: segments('thinking') }), window, NOW)[0]).toBe('runSoft')
  expect(cellsOf(agentRow({ state: 'waiting', segments: segments('waiting') }), window, NOW)[0]).toBe('warn')
  expect(cellsOf(agentRow({ state: 'thinking', startedAt: NOW + MINUTE }), window, NOW)[0]).toBe('empty')
})
