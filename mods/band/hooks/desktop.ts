import type { AgentRow, Gauges, Range, Roster, RosterRow } from '../types'

import { type Activity, type CellKind, activityOf, cellsOf } from './activity'
import { estimateCostUsd, formatUsd, tokensInOf } from './cost'
import { formatAge, formatTokens } from './format'
import { type Window, earliestStart, nextLeaveMs, splitByWindow, windowFor } from './layout'
import { MAIN_ID, newMainRow } from './model'

export const TIMELINE_RANGES: readonly Range[] = ['1m', '5m', '1h', 'session']
export const MINI_LANES_RANGE: Range = '5m'
export const MAX_TILES = 12
export const MAX_MINI_LANES = 4
export const NO_VALUE = '—'
export const EMPTY_SESSION_TEXT = 'No agents yet this session.'
export const REFRESH_LIVE_MS = 5_000

export const rangeLabelOf = (range: Range): string => (range === 'session' ? 'all' : range)

export const timelineWindowOf = (input: { range: Range; now: number; sessionStartedAt: number | null; rows: Iterable<AgentRow> }): Window => {
  const earliest = earliestStart([...input.rows], input.sessionStartedAt ?? input.now)

  return windowFor(input.range, input.now, Math.min(earliest, input.sessionStartedAt ?? earliest))
}

export const modelBadgeOf = (model: string | undefined): string | null => {
  if (model === undefined) {
    return null
  }

  const family = /(opus|sonnet|haiku)/i.exec(model)?.[1]

  return family === undefined ? model : family.toLowerCase()
}

const tokenCostOf = (row: AgentRow | undefined): number | null => (row?.usage === undefined ? null : estimateCostUsd(row.usage, row.model))

const costTextOf = (usd: number | null): string => (usd === null ? '' : '~' + formatUsd(usd))

export const NO_USAGE_TEXT = 'no usage'

const tokensTextOf = (row: AgentRow, cost: string): string => (row.usage === undefined ? (cost === '' ? NO_USAGE_TEXT : '') : formatTokens(tokensInOf(row.usage)) + '↓ ' + formatTokens(row.usage.output) + '↑')

export type MainEstimate = { usd: number | null; isFromTotal: boolean }

export const mainEstimateOf = (input: { sessionUsd: number | null; agentsUsd: number; mainTokensUsd: number | null }): MainEstimate =>
  input.sessionUsd === null ? { usd: input.mainTokensUsd, isFromTotal: false } : { usd: Math.max(0, input.sessionUsd - input.agentsUsd), isFromTotal: true }

export const mainEstimateLabelOf = (estimate: MainEstimate): string => (estimate.isFromTotal ? 'main est.' : 'main est. (tokens)')

export type TileFact = { term: string; value: string }

export type Tile = {
  id: string
  isMain: boolean
  name: string
  model: string | null
  activity: Activity
  isWaiting: boolean
  strip: CellKind[]
  time: string
  tokens: string
  cost: string
  facts: TileFact[]
}

export type Spend = {
  sessionUsd: number | null
  agentsUsd: number
  main: MainEstimate
  tokensIn: number
  tokensOut: number
}

export const spendOf = (input: { gauges: Gauges; rows: ReadonlyMap<string, AgentRow> }): Spend => {
  let agentsUsd = 0
  let tokensIn = 0
  let tokensOut = 0

  for (const row of input.rows.values()) {
    tokensIn += row.usage === undefined ? 0 : tokensInOf(row.usage)
    tokensOut += row.usage?.output ?? 0
    agentsUsd += row.id === MAIN_ID ? 0 : (tokenCostOf(row) ?? 0)
  }

  const main = mainEstimateOf({ sessionUsd: input.gauges.costUsd, agentsUsd, mainTokensUsd: tokenCostOf(input.rows.get(MAIN_ID)) })

  return { sessionUsd: input.gauges.costUsd, agentsUsd, main, tokensIn, tokensOut }
}

type TileContext = { now: number; window: Window; sessionStartedAt: number | null; spend: Spend }

const factsOf = (row: AgentRow, tile: Omit<Tile, 'facts'>, context: TileContext): TileFact[] => {
  const now = tile.activity.detail === '' ? tile.activity.word : tile.activity.word + ': ' + tile.activity.detail
  const model = (tile.model ?? NO_VALUE) + (row.type === undefined ? '' : ' · ' + row.type)

  return [
    { term: 'now', value: now },
    { term: 'model', value: model },
    { term: tile.isMain ? 'session age' : 'ran for', value: tile.time },
    { term: 'tokens in', value: row.usage === undefined ? NO_VALUE : formatTokens(tokensInOf(row.usage)) + ' (cache reads included)' },
    { term: 'tokens out', value: row.usage === undefined ? NO_VALUE : formatTokens(row.usage.output) },
    { term: tile.isMain ? mainEstimateLabelOf(context.spend.main) : 'cost', value: tile.cost + (tile.isMain && context.spend.main.isFromTotal ? ' session total minus agents' : ' estimated from tokens') },
  ]
}

export const tileOf = (row: AgentRow, context: TileContext): Tile => {
  const isMain = row.id === MAIN_ID
  const activity = activityOf(row, context.now)
  const startedAt = isMain ? (context.sessionStartedAt ?? row.startedAt) : row.startedAt
  const endedAt = row.endedAt ?? context.now
  const cost = costTextOf(isMain ? context.spend.main.usd : tokenCostOf(row))
  const base: Omit<Tile, 'facts'> = {
    id: row.id,
    isMain,
    name: isMain ? 'main' : row.label,
    model: modelBadgeOf(row.model),
    activity,
    isWaiting: activity.kind === 'needs-you' || activity.kind === 'permission',
    strip: cellsOf(row, context.window, context.now),
    time: formatAge(endedAt - startedAt),
    tokens: tokensTextOf(row, cost),
    cost,
  }

  return { ...base, facts: factsOf(row, base, context) }
}

export type Ghost = { text: string; widensRange: boolean }

export const ghostOf = (input: { roster: Roster; earlier: number; hidden: number }): Ghost | null => {
  const evicted = input.roster.evictedDone + input.roster.evictedFailed

  if (input.roster.rows.length + evicted === 0) {
    return { text: EMPTY_SESSION_TEXT, widensRange: false }
  }

  const endedEarlier = input.earlier + evicted
  const parts = [endedEarlier > 0 ? '+' + endedEarlier + ' ended earlier' : '', input.hidden > 0 ? '+' + input.hidden + ' more' : ''].filter(part => part !== '')

  return parts.length === 0 ? null : { text: parts.join(' · '), widensRange: endedEarlier > 0 }
}

export type Tiles = { main: Tile; agents: Tile[]; ghost: Ghost | null }

export const tilesOf = (input: { roster: Roster; rows: ReadonlyMap<string, AgentRow>; now: number; window: Window; gauges: Gauges }): Tiles => {
  const sessionStartedAt = input.gauges.sessionStartedAt
  const context: TileContext = { now: input.now, window: input.window, sessionStartedAt, spend: spendOf({ gauges: input.gauges, rows: input.rows }) }
  const mainRow = input.rows.get(MAIN_ID) ?? newMainRow(sessionStartedAt ?? input.now)
  const split = splitByWindow<RosterRow>(input.roster.rows, input.rows, input.window.start)
  const capped = split.shown.slice(0, MAX_TILES)
  const agents = capped.flatMap(member => {
    const row = input.rows.get(member.id)

    return row === undefined ? [] : [tileOf(row, context)]
  })

  return { main: tileOf(mainRow, context), agents, ghost: ghostOf({ roster: input.roster, earlier: split.earlier, hidden: split.shown.length - capped.length }) }
}

export const miniLaneRowsOf = (input: { roster: Roster; rows: ReadonlyMap<string, AgentRow>; now: number }): AgentRow[] => {
  const main = input.rows.get(MAIN_ID) ?? newMainRow(input.now)
  const live = input.roster.rows.flatMap(member => (member.phase === 'live' ? [input.rows.get(member.id)] : [])).flatMap(row => (row === undefined ? [] : [row]))

  return [main, ...live].slice(0, MAX_MINI_LANES)
}

export const bandRefreshMs = (input: { rows: ReadonlyMap<string, AgentRow>; roster: Roster; range: Range; now: number; isFolded: boolean; isWorking: boolean }): number | null => {
  const hasLive = input.isWorking || input.roster.rows.some(row => row.phase === 'live')
  const waits = [nextLeaveMs(input.rows.values(), input.range, input.now, input.isFolded), hasLive ? REFRESH_LIVE_MS : null].filter((wait): wait is number => wait !== null)

  return waits.length === 0 ? null : Math.min(...waits)
}
