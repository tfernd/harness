import type { AgentRow, Gauges, Roster } from '../types'

import { cacheClockOf } from './gauges'
import { FOLDED_RANGE, earliestStart, formatReset, formatTokens, tracedRows, windowFor } from './model'
import { COUNTS_RESERVED_WIDTH, type Ctx, driftGroup, label, laneMarkup, num } from './svg-parts'

export type StripInput = {
  width: number
  isWide: boolean
  isFolded: boolean
  gauges: Gauges
  roster: Roster
  rows: ReadonlyMap<string, AgentRow>
  isWorking: boolean
  turnStartedAt: number | null
}

export type Tone = 'ok' | 'warn' | 'bad'

export type GaugeSpec = {
  id: string
  name: string
  percent: number
  detail: string
  isDetailUrgent: boolean
  tone: Tone
  tip: string
}

export const RING_RADIUS = 13.5
export const RING_SIZE = 32
export const FOLDED_RING_RADIUS = 11.5
export const FOLDED_RING_SIZE = 28
export const FOLDED_GAP = 16
export const MIN_TRACES_WIDTH = 56
export const MAX_TRACES_WIDTH = 360
export const MAX_TRACE_LANES = 4
export const LANE_HEIGHT = 6
export const LANE_STEP = 8
export const TRACES_MORE_WIDTH = 30

const RING_FONT_BASELINE = 3.5
const RING_TEXT_MAX_CHARS = 3

const WARN_PERCENT = 70
const BAD_PERCENT = 90

const toneOf = (percent: number): Tone => (percent >= BAD_PERCENT ? 'bad' : percent >= WARN_PERCENT ? 'warn' : 'ok')

export const gaugeSpecs = (gauges: Gauges, now: number): GaugeSpec[] => {
  const specs: GaugeSpec[] = []

  if (gauges.contextPercent !== null) {
    const used =
      gauges.contextTokens !== null && gauges.contextWindow !== null
        ? `${formatTokens(gauges.contextTokens)}/${formatTokens(gauges.contextWindow)}`
        : ''
    const from = gauges.compactedFrom !== null ? ` ↻${formatTokens(gauges.compactedFrom)}` : ''
    const detail = `${used}${from}`.trim()
    specs.push({
      id: 'ctx',
      name: 'ctx',
      percent: gauges.contextPercent,
      detail,
      isDetailUrgent: false,
      tone: toneOf(gauges.contextPercent),
      tip: `Context window ${Math.round(gauges.contextPercent)}% used${detail === '' ? '' : `: ${detail}`}`,
    })
  }

  if (gauges.cachePercent !== null) {
    const clock = cacheClockOf(gauges, now)
    specs.push({
      id: 'cache',
      name: 'cache',
      percent: gauges.cachePercent,
      detail: clock?.detail ?? `${Math.round(gauges.cachePercent)}% hit`,
      isDetailUrgent: clock?.isUrgent ?? false,
      tone: clock?.isUrgent === true ? 'bad' : gauges.cachePercent >= WARN_PERCENT ? 'ok' : 'warn',
      tip: `Prompt cache hit rate ${Math.round(gauges.cachePercent)}%${clock === null ? '' : `. ${clock.tip}`}`,
    })
  }

  for (const [id, name, limit] of [
    ['5h', '5h', gauges.fiveHour],
    ['wk', 'week', gauges.sevenDay],
  ] as const) {
    if (limit !== null) {
      const detail = limit.resetsAt === null ? '' : `in ${formatReset(limit.resetsAt - now)}`
      specs.push({
        id,
        name,
        percent: limit.percent,
        detail,
        isDetailUrgent: false,
        tone: toneOf(limit.percent),
        tip: `${name} limit ${Math.round(limit.percent)}% used${detail === '' ? '' : `, resets ${detail}`}`,
      })
    }
  }

  return specs
}

export const hasRing = (spec: GaugeSpec): boolean => spec.id !== 'cache'

export const ring = (box: { cx: number; cy: number; radius?: number }, spec: GaugeSpec): string => {
  const radius = box.radius ?? RING_RADIUS
  const value = Math.max(0, Math.min(100, spec.percent))
  const arc =
    value <= 0
      ? ''
      : `<circle class="ring-v r-${spec.tone}" cx="${num(box.cx)}" cy="${num(box.cy)}" r="${radius}" pathLength="100" stroke-dasharray="${num(value)} 100"/>`
  const text = `${Math.round(value)}%`

  return (
    `<g transform="rotate(-90 ${num(box.cx)} ${num(box.cy)})"><circle class="ring-t" cx="${num(box.cx)}" cy="${num(box.cy)}" r="${radius}"/>${arc}</g>` +
    label(box.cx, box.cy + RING_FONT_BASELINE, 'mid n', text, text.length > RING_TEXT_MAX_CHARS || radius < RING_RADIUS ? ' style="font-size:7px"' : ' style="font-size:9px"')
  )
}

export const foldedDetail = (spec: GaugeSpec): string => spec.detail.replace(/\s*↻.*$/, '')

export const STRIP_CHAR_PX = 8.5
export const STRIP_GAP = 12
export const STRIP_RING_GAP = 8
export const STRIP_FRAME_INSET = 16 + 2 * 12

export type StripBudget = { width: number; statusChars: number; countsChars: number }

export const stripWidth = (specs: readonly GaugeSpec[], budget: StripBudget, detailOf: (spec: GaugeSpec) => string): number => {
  const gauges = specs.reduce(
    (sum, spec) => sum + (hasRing(spec) ? RING_SIZE + STRIP_RING_GAP : 0) + Math.max(spec.name.length, detailOf(spec).length) * STRIP_CHAR_PX,
    0,
  )

  return gauges + (budget.statusChars + budget.countsChars) * STRIP_CHAR_PX + (specs.length + 1) * STRIP_GAP
}

export const stripDetailOf = (specs: readonly GaugeSpec[], budget: StripBudget): ((spec: GaugeSpec) => string) => {
  const full = (spec: GaugeSpec): string => spec.detail

  return stripWidth(specs, budget, full) <= budget.width - STRIP_FRAME_INSET ? full : foldedDetail
}

const TEXT_CHAR_PX = 8
export const FOLDED_CONTENT_INSET = 48
export const FOLDED_STATUS_WIDTH = 80
export const FOLDED_UNFOLD_WIDTH = 40
export const FOLDED_COUNTS_WIDTH = Math.ceil(COUNTS_RESERVED_WIDTH) + FOLDED_GAP

export const foldedTracesWidth = (width: number, specs: readonly GaugeSpec[]): number => {
  const gauges = specs.reduce(
    (sum, spec) => sum + (FOLDED_RING_SIZE + FOLDED_GAP / 4) + Math.max(spec.name.length, foldedDetail(spec).length) * TEXT_CHAR_PX,
    0,
  )
  const items = specs.length + 3
  const fixed = FOLDED_UNFOLD_WIDTH + FOLDED_STATUS_WIDTH + gauges + FOLDED_COUNTS_WIDTH + items * FOLDED_GAP
  const free = Math.floor(width - FOLDED_CONTENT_INSET - fixed)

  return free >= MIN_TRACES_WIDTH ? Math.min(free, MAX_TRACES_WIDTH) : 0
}

export const tracesHeight = (laneCount: number): number => Math.max(1, Math.min(laneCount, MAX_TRACE_LANES)) * LANE_STEP

export const traceLanes = (ctx: Ctx, input: StripInput, box: { x: number; y: number; width: number }): string => {
  const live = tracedRows(input.roster.rows, input.rows, ctx.now)
  const shown = live.slice(0, MAX_TRACE_LANES)
  const window = windowFor(FOLDED_RANGE, ctx.now, earliestStart([...input.rows.values()], ctx.now))
  const track = { x: box.x, width: box.width, window }
  const height = shown.length * LANE_STEP - (LANE_STEP - LANE_HEIGHT)
  const lanes = shown.map((row, index) => {
    const y = box.y + index * LANE_STEP
    const background = `<rect x="${num(box.x)}" y="${num(y)}" width="${num(box.width)}" height="${LANE_HEIGHT}" rx="${LANE_HEIGHT / 2}" class="lan"/>`

    return { background, markup: laneMarkup(ctx, input.rows.get(row.id), track, { y, height: LANE_HEIGHT, radius: LANE_HEIGHT / 2 }) }
  })
  const hidden = live.length - shown.length
  const moreY = box.y + height / 2 + 4

  return (
    lanes.map(lane => lane.background).join('') +
    driftGroup(ctx, { x: box.x, y: box.y, width: box.width, height }, track, lanes.map(lane => lane.markup).join('')) +
    (hidden > 0 ? label(box.x + box.width + TRACES_MORE_WIDTH - 4, moreY, 'm s end', `+${hidden}`) : '')
  )
}
