import type { AgentRow, AgentState, Gauges, NamedLimit, Range, Roster, RosterRow } from '../types'

import type { Tone } from './c1-theme'
import { estimateCostUsd, formatUsd, tokensInOf } from './cost'
import { formatShort, formatSpan, formatTokens } from './format'
import { type Window, earliestStart, nextLeaveMs, splitByWindow, windowFor } from './layout'
import { MAIN_ID, NEEDS_YOU_WORD, STATE_WORD, newMainRow, stateWordOf } from './model'

export const TIMELINE_RANGES: readonly Range[] = ['1m', '5m', '1h', 'session']
export const MINI_LANES_RANGE: Range = '5m'
export const HIGH_CONTEXT_PERCENT = 80
export const CRITICAL_PERCENT = 95
export const MAX_LANE_ROWS = 8
export const AXIS_TICK_COUNT = 4
export const MIN_SPAN_PERCENT = 2
export const NO_VALUE = '—'
const ONE_DAY_MS = 86_400_000

export type Span = { left: number; width: number }

export type AxisTick = { fraction: number; text: string }

export const timelineWindowOf = (input: { range: Range; now: number; sessionStartedAt: number | null; rows: Iterable<AgentRow> }): Window => {
  const earliest = earliestStart([...input.rows], input.sessionStartedAt ?? input.now)

  return windowFor(input.range, input.now, Math.min(earliest, input.sessionStartedAt ?? earliest))
}

export const axisTicksOf = (window: Window): AxisTick[] => {
  const length = window.end - window.start

  return Array.from({ length: AXIS_TICK_COUNT }, (_, index) => {
    const fraction = index / (AXIS_TICK_COUNT - 1)
    const remaining = Math.round(length * (1 - fraction))
    const text = index === AXIS_TICK_COUNT - 1 ? 'now' : index === 0 ? formatSpan(remaining) + ' ago' : formatSpan(remaining)

    return { fraction, text }
  })
}

export const spanOf = (window: Window, from: number, to: number): Span | null => {
  const length = window.end - window.start

  if (length <= 0 || to < window.start || from > window.end) {
    return null
  }

  const left = Math.max(0, (Math.max(from, window.start) - window.start) / length) * 100
  const right = Math.min(1, (Math.min(to, window.end) - window.start) / length) * 100
  const width = Math.max(MIN_SPAN_PERCENT, right - left)

  return { left: Math.round(Math.min(left, 100 - width)), width: Math.round(width) }
}

export const toneOfPercent = (percent: number): Tone => (percent >= CRITICAL_PERCENT ? 'fail' : percent >= HIGH_CONTEXT_PERCENT ? 'warn' : 'ink')

export const isLongSession = (gauges: Gauges): boolean => gauges.contextPercent !== null && gauges.contextTokens !== null && gauges.contextPercent >= HIGH_CONTEXT_PERCENT

export const longSessionText = (gauges: Gauges): string => 'Long session: each turn re-reads ' + formatTokens(gauges.contextTokens ?? 0) + ' tokens. A fresh session is cheaper.'

export const resetTextOf = (limit: NamedLimit, now: number): string => {
  if (limit.resetsAt === null) {
    return ''
  }

  const date = new Date(limit.resetsAt)
  const time = date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
  const day = limit.resetsAt - now >= ONE_DAY_MS ? date.toLocaleDateString('en-US', { weekday: 'short' }) + ' ' : ''

  return 'Resets ' + day + time
}

export const shortLimitName = (limit: NamedLimit): string => limit.name.toLowerCase()

const WORD: Record<AgentState, string> = { launched: 'starting', thinking: 'thinking', tool: 'running', waiting: 'waiting', done: 'done', failed: 'failed' }
const GLYPH: Record<AgentState, string> = { launched: '▶', thinking: '▶', tool: '▶', waiting: '◐', done: '✓', failed: '✕' }
const TONE: Record<AgentState, Tone> = { launched: 'run', thinking: 'run', tool: 'run', waiting: 'warn', done: 'done', failed: 'fail' }

export type LaneRow = {
  id: string
  isMain: boolean
  label: string
  type: string | null
  model: string | null
  glyph: string
  word: string
  tone: Tone
  inside: string
  reason: string | null
  span: Span | null
  time: string
  tokens: string
  cost: string
}

export const modelBadgeOf = (model: string | undefined): string | null => {
  if (model === undefined) {
    return null
  }

  const family = /(opus|sonnet|haiku)/i.exec(model)?.[1]

  return family === undefined ? model : family.toLowerCase()
}

const tokensTextOf = (row: AgentRow): string => (row.usage === undefined ? NO_VALUE : formatTokens(tokensInOf(row.usage)) + ' / ' + formatTokens(row.usage.output))

export const costTextOf = (row: AgentRow): string => {
  const usd = row.usage === undefined ? null : estimateCostUsd(row.usage, row.model)

  return usd === null ? NO_VALUE : '~' + formatUsd(usd)
}

const failureTextOf = (row: AgentRow): string => (row.failReason === undefined ? 'failed' : 'failed: ' + row.failReason)

const insideOf = (row: AgentRow, word: string): string => {
  if (row.state === 'done') {
    return '✓ done'
  }

  if (row.state === 'failed') {
    return '✕'
  }

  return row.command ?? word
}

const wordOf = (row: AgentRow, now: number): string => {
  const stated = stateWordOf(row, now)

  if (stated === NEEDS_YOU_WORD) {
    return stated
  }

  if (row.id === MAIN_ID || stated !== STATE_WORD[row.state]) {
    return stated.toLowerCase()
  }

  return WORD[row.state]
}

export const laneRowOf = (row: AgentRow, options: { now: number; window: Window; sessionStartedAt: number | null }): LaneRow => {
  const isMain = row.id === MAIN_ID
  const word = wordOf(row, options.now)
  const startedAt = isMain ? (options.sessionStartedAt ?? row.startedAt) : row.startedAt
  const endedAt = row.endedAt ?? options.now

  return {
    id: row.id,
    isMain,
    label: isMain ? 'main' : row.label,
    type: isMain ? null : (row.type ?? null),
    model: modelBadgeOf(row.model),
    glyph: isMain ? '●' : GLYPH[row.state],
    word,
    tone: isMain ? 'ink' : TONE[row.state],
    inside: insideOf(row, word),
    reason: !isMain && row.state === 'failed' ? failureTextOf(row) : null,
    span: spanOf(options.window, startedAt, isMain ? options.now : endedAt),
    time: formatShort(endedAt - startedAt),
    tokens: tokensTextOf(row),
    cost: costTextOf(row),
  }
}

export type Lanes = { main: LaneRow; agents: LaneRow[]; earlier: number; hidden: number }

export const lanesOf = (input: { roster: Roster; rows: ReadonlyMap<string, AgentRow>; now: number; window: Window; sessionStartedAt: number | null }): Lanes => {
  const options = { now: input.now, window: input.window, sessionStartedAt: input.sessionStartedAt }
  const mainRow = input.rows.get(MAIN_ID) ?? newMainRow(input.sessionStartedAt ?? input.now)
  const split = splitByWindow<RosterRow>(input.roster.rows, input.rows, input.window.start)
  const capped = split.shown.slice(0, MAX_LANE_ROWS)
  const agents = capped.flatMap(member => {
    const row = input.rows.get(member.id)

    return row === undefined ? [] : [laneRowOf(row, options)]
  })

  return { main: laneRowOf(mainRow, options), agents, earlier: split.earlier, hidden: split.shown.length - capped.length }
}

export type Spend = { sessionUsd: number | null; agentsUsd: number; pricedAgents: number; unpricedAgents: number; tokensIn: number; tokensOut: number; turns: number; elapsedMs: number | null }

export const spendOf = (input: { gauges: Gauges; rows: ReadonlyMap<string, AgentRow>; now: number }): Spend => {
  let agentsUsd = 0
  let pricedAgents = 0
  let unpricedAgents = 0
  let tokensIn = 0
  let tokensOut = 0

  for (const row of input.rows.values()) {
    const usd = row.usage === undefined ? null : estimateCostUsd(row.usage, row.model)

    tokensIn += row.usage === undefined ? 0 : tokensInOf(row.usage)
    tokensOut += row.usage?.output ?? 0

    if (row.id !== MAIN_ID && row.usage !== undefined) {
      pricedAgents += usd === null ? 0 : 1
      unpricedAgents += usd === null ? 1 : 0
      agentsUsd += usd ?? 0
    }
  }

  const startedAt = input.gauges.sessionStartedAt

  return { sessionUsd: input.gauges.costUsd, agentsUsd, pricedAgents, unpricedAgents, tokensIn, tokensOut, turns: input.gauges.turns, elapsedMs: startedAt === null ? null : input.now - startedAt }
}

export type MiniLaneRow = { row: AgentRow; tone: Tone }

export const miniLanesOf = (input: { roster: Roster; rows: ReadonlyMap<string, AgentRow>; window: Window }): MiniLaneRow[] =>
  splitByWindow<RosterRow>(input.roster.rows, input.rows, input.window.start).shown.flatMap(member => {
    const row = input.rows.get(member.id)

    return row === undefined ? [] : [{ row, tone: TONE[row.state] }]
  })

export const REFRESH_LIVE_MS = 5_000

export const bandRefreshMs = (input: { rows: ReadonlyMap<string, AgentRow>; roster: Roster; range: Range; now: number; isFolded: boolean; isWorking: boolean }): number | null => {
  const hasLive = input.isWorking || input.roster.rows.some(row => row.phase === 'live')
  const waits = [nextLeaveMs(input.rows.values(), input.range, input.now, input.isFolded), hasLive ? REFRESH_LIVE_MS : null].filter((wait): wait is number => wait !== null)

  return waits.length === 0 ? null : Math.min(...waits)
}
