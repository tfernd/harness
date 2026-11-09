import type { AgentRow, AgentState, Range, RosterRow } from '../types'

import { DIRECT_GROUP, MAIN_ID, MAIN_LABEL, MAIN_STATE_WORD, NEEDS_YOU_WORD, STATE_ICON, earliestStart, formatSpan, groupAgents, isLive, splitByWindow, stateWordOf, windowFor } from './model'
import {
  type Ctx,
  type Track,
  driftGroup,
  fit,
  horizontalLine,
  label,
  laneMarkup,
  nowMarker,
  num,
  rect,
  statePill,
} from './svg-parts'
import type { StripInput } from './svg-strip'

export type TimelineInput = StripInput & { range: Range; foldedGroups: readonly string[]; sessionStart: number }

export const HEAD_HEIGHT = 22
export const GROUP_HEIGHT = 22
export const ROW_HEIGHT = 24
export const MORE_HEIGHT = 22

const PAD = 16
const LABEL_MIN = 112
const LABEL_MAX = 200
const STATE_MIN = 184
const STATE_MAX = 260
const PILL_WIDTH = 66
const PILL_HEIGHT = 16
const PILL_GAP = 8
const TRACK_LANE = 6
const LANE_INSET = (ROW_HEIGHT - TRACK_LANE) / 2
const TEXT_DROP = 4
const GLYPH_WIDTH = 14

type Columns = { labelWidth: number; stateWidth: number; trackWidth: number }

export const columnsFor = (width: number, isWide: boolean): Columns => {
  const labelWidth = Math.max(LABEL_MIN, Math.min(LABEL_MAX, Math.round(width * 0.24)))
  const stateWidth = isWide ? Math.max(STATE_MIN, Math.min(STATE_MAX, Math.round(width * 0.27))) : 0

  return { labelWidth, stateWidth, trackWidth: width - labelWidth - stateWidth }
}

const GLYPH_CLASS: Record<AgentState, string> = {
  launched: 'acc',
  thinking: 'acc',
  tool: 'acc',
  waiting: 'acc',
  done: 'm',
  failed: 'bad b',
}

const rowMarkup = (
  input: { agent: RosterRow; row: AgentRow | undefined; y: number; width: number; columns: Columns; now: number },
): string => {
  const { agent, row, y, width, columns } = input
  const isMain = agent.id === MAIN_ID
  const fallback: AgentState = isMain ? 'launched' : agent.phase === 'failed' ? 'failed' : agent.phase === 'done' ? 'done' : 'thinking'
  const state: AgentState = row?.state ?? fallback
  const word = row === undefined ? (isMain ? MAIN_STATE_WORD[state] : undefined) : stateWordOf(row, input.now)
  const tone = word === NEEDS_YOU_WORD ? 'needs' : word?.startsWith('quiet') ? 'quiet' : state
  const baseline = y + ROW_HEIGHT / 2 + TEXT_DROP
  const stateX = columns.labelWidth + columns.trackWidth + PAD
  const textX = stateX + PILL_WIDTH + PILL_GAP
  const isEnded = state === 'done' || state === 'failed'
  const isQuiet = !isMain && isEnded
  const hasGlyph = columns.stateWidth === 0
  const labelX = PAD + (hasGlyph ? GLYPH_WIDTH : 0)
  const stateColumn =
    columns.stateWidth === 0
      ? ''
      : statePill({ x: stateX, y: y + (ROW_HEIGHT - PILL_HEIGHT) / 2, width: PILL_WIDTH, height: PILL_HEIGHT }, state, word, tone) +
        (row?.command == null
          ? ''
          : label(textX, baseline, isQuiet ? 'm' : '', fit(row.command, columns.stateWidth - PILL_WIDTH - PILL_GAP - PAD, 12)))

  return (
    '<g class="row">' +
    rect({ x: 0, y, width, height: ROW_HEIGHT }, 'hit') +
    horizontalLine(y, 0, width) +
    (hasGlyph ? label(PAD + 4, baseline, GLYPH_CLASS[state], STATE_ICON[state], ' text-anchor="middle"') : '') +
    label(labelX, baseline, isQuiet ? 'm' : isMain ? '' : 'b', fit(agent.label, columns.labelWidth - labelX - PAD, 12)) +
    stateColumn +
    '</g>'
  )
}

const MAIN_ROSTER_ROW: RosterRow = { id: MAIN_ID, label: MAIN_LABEL, group: MAIN_ID, groupLabel: MAIN_LABEL, phase: 'live' }

const laneBlockMarkup = (
  ctx: Ctx,
  input: { lanes: readonly string[]; top: number; bottom: number; columns: Columns; track: Track },
): string => {
  const { columns, top, bottom } = input
  const height = bottom - top

  return (
    driftGroup(ctx, { x: columns.labelWidth, y: top, width: columns.trackWidth, height }, input.track, input.lanes.join('')) +
    nowMarker({ x: columns.labelWidth + columns.trackWidth, y: top, height })
  )
}

const headMarkup = (input: { columns: Columns; width: number; top: number; spanMs: number; range: Range }): string => {
  const { columns, top } = input
  const trackEnd = columns.labelWidth + columns.trackWidth
  const baseline = top + HEAD_HEIGHT / 2 + TEXT_DROP - 1

  return (
    horizontalLine(top, 0, input.width) +
    label(PAD, baseline, 'm b s cap', 'AGENT') +
    label(columns.labelWidth, baseline, 'm s', `-${formatSpan(input.spanMs)}`) +
    label(columns.labelWidth + columns.trackWidth / 2, baseline, 'm s mid', `-${formatSpan(input.spanMs / 2)}`) +
    label(trackEnd - 6, baseline, 'm s end b', 'now') +
    (columns.stateWidth > 0 ? label(trackEnd + PAD, baseline, 'm b s cap', 'STATE') : '')
  )
}

export type TimelinePiece = { markup: string; height: number }

export type GroupPlan = {
  id: string
  name: string
  counts: ReturnType<typeof groupAgents>[number]['counts']
  isFolded: boolean
  agents: readonly RosterRow[]
  shown: readonly RosterRow[]
  inWindowCount: number
  earlier: number
}

export type TimelinePlan = { groups: GroupPlan[]; hidden: number }

const windowOf = (input: TimelineInput, now: number) => windowFor(input.range, now, earliestStart([...input.rows.values()], input.sessionStart))

export const windowSpanOf = (input: TimelineInput, now: number): number => {
  const window = windowOf(input, now)

  return window.end - window.start
}

export const planGroups = (input: TimelineInput, now: number, rowLimit: number): TimelinePlan => {
  const windowStart = windowOf(input, now).start
  const groups: GroupPlan[] = []
  let used = 0
  let hidden = 0

  for (const group of groupAgents(input.roster.rows)) {
    const isFolded = input.foldedGroups.includes(group.id)
    const { shown: inWindow, earlier } = splitByWindow(group.agents, input.rows, windowStart)

    if (inWindow.length === 0 && earlier === 0) {
      continue
    }

    const shown = isFolded ? [] : inWindow.slice(0, Math.max(0, rowLimit - used))
    used += shown.length
    hidden += isFolded ? 0 : inWindow.length - shown.length
    groups.push({ id: group.id, name: group.label, counts: group.counts, isFolded, agents: group.agents, shown, inWindowCount: inWindow.length, earlier })
  }

  return { groups, hidden }
}

export const timelineHeadMarkup = (ctx: Ctx, input: TimelineInput): TimelinePiece => {
  const columns = columnsFor(input.width, input.isWide)
  const window = windowOf(input, ctx.now)
  const track: Track = { x: columns.labelWidth, width: columns.trackWidth, window }
  const mainRow = input.rows.get(MAIN_ID)
  const mainTop = HEAD_HEIGHT
  const mainBottom = mainTop + ROW_HEIGHT

  return {
    markup:
      headMarkup({ columns, width: input.width, top: 0, spanMs: window.end - window.start, range: input.range }) +
      rowMarkup({ agent: MAIN_ROSTER_ROW, row: mainRow, y: mainTop, width: input.width, columns, now: ctx.now }) +
      laneBlockMarkup(ctx, {
        lanes: [laneMarkup(ctx, mainRow, track, { y: mainTop + LANE_INSET, height: TRACK_LANE, radius: TRACK_LANE / 2 })],
        top: mainTop,
        bottom: mainBottom,
        columns,
        track,
      }),
    height: mainBottom,
  }
}

export const groupRowsMarkup = (ctx: Ctx, input: TimelineInput, plan: GroupPlan): TimelinePiece => {
  const columns = columnsFor(input.width, input.isWide)
  const track: Track = { x: columns.labelWidth, width: columns.trackWidth, window: windowOf(input, ctx.now) }
  const parts: string[] = []
  const lanes: string[] = []
  let y = 0

  for (const agent of plan.shown) {
    const row = input.rows.get(agent.id)
    parts.push(rowMarkup({ agent, row, y, width: input.width, columns, now: ctx.now }))
    lanes.push(laneMarkup(ctx, row, track, { y: y + LANE_INSET, height: TRACK_LANE, radius: TRACK_LANE / 2 }))
    y += ROW_HEIGHT
  }

  if (y > 0) {
    parts.push(laneBlockMarkup(ctx, { lanes, top: 0, bottom: y, columns, track }))
  }

  if (plan.earlier > 0) {
    parts.push(moreLine(y, input.width, `+${plan.earlier} earlier`))
    y += MORE_HEIGHT
  }

  return { markup: parts.join(''), height: y }
}

const moreLine = (y: number, width: number, text: string): string =>
  horizontalLine(y, 0, width) + label(PAD, y + MORE_HEIGHT / 2 + TEXT_DROP, 'm s', text)

export const hiddenAgentsMarkup = (input: TimelineInput, hidden: number): TimelinePiece =>
  hidden > 0 ? { markup: moreLine(0, input.width, `+${hidden} more agents not drawn`), height: MORE_HEIGHT } : { markup: '', height: 0 }

export const DENSITY_HEIGHT = 12
export const GROUP_PIECE_HEIGHT = 24
const DENSITY_BIN_WIDTH = 3
const DENSITY_MIN_BINS = 8
const DENSITY_MAX_BINS = 160
const DENSITY_NARROW_RESERVE = 120
const DENSITY_MIN_WIDTH = 60
const DENSITY_STATES = ['tool', 'thinking', 'waiting'] as const

export type StateCounts = { tool: number; thinking: number; waiting: number }

export const liveStateCounts = (rows: ReadonlyMap<string, AgentRow>, agents: readonly RosterRow[]): StateCounts => {
  const counts: StateCounts = { tool: 0, thinking: 0, waiting: 0 }

  for (const agent of agents) {
    const state = rows.get(agent.id)?.state

    if (state === 'tool' || state === 'thinking' || state === 'waiting') {
      counts[state] += 1
    }
  }

  return counts
}

export const groupTitleOf = (plan: GroupPlan): { kind: string; name: string } => ({
  kind: plan.id === DIRECT_GROUP ? 'DIRECT' : 'WORKFLOW',
  name: plan.name.replace(/^workflow /, ''),
})

export const groupLabelWidthOf = (input: TimelineInput): number => columnsFor(input.width, input.isWide).labelWidth

export const groupCountsWidthOf = (input: TimelineInput): number => columnsFor(input.width, input.isWide).stateWidth

export const groupCountsText = (counts: StateCounts, ended: number): string => {
  const entries: { count: number; word: string }[] = [
    { count: counts.tool, word: 'tool' },
    { count: counts.thinking, word: 'think' },
    { count: counts.waiting, word: 'wait' },
    { count: ended, word: 'ended' },
  ]
  const parts = entries.filter(entry => entry.count > 0).map(entry => `${entry.count} ${entry.word}`)

  return parts.length === 0 ? 'idle' : parts.join(' · ')
}

export const groupCountsMarkup = (text: string, width: number): TimelinePiece => ({
  markup: label(PAD, GROUP_PIECE_HEIGHT / 2 + TEXT_DROP, 'm s', fit(text, width - PAD, 11)),
  height: GROUP_PIECE_HEIGHT,
})

export const densityWidthOf = (input: TimelineInput): number => {
  const columns = columnsFor(input.width, input.isWide)

  return columns.stateWidth > 0 ? columns.trackWidth : Math.max(DENSITY_MIN_WIDTH, columns.trackWidth - DENSITY_NARROW_RESERVE)
}

const stateAt = (row: AgentRow, at: number, now: number): AgentState | null => {
  for (const segment of row.segments) {
    const end = segment.to ?? (isLive(row.state) ? now : (row.endedAt ?? now))

    if (segment.from <= at && at < end) {
      return segment.state
    }
  }

  return null
}

const countsOverTime = (input: TimelineInput, agents: readonly RosterRow[], bins: number, now: number): StateCounts[] => {
  const window = windowOf(input, now)
  const span = Math.max(1, window.end - window.start)
  const rows = agents.flatMap(agent => input.rows.get(agent.id) ?? [])

  return Array.from({ length: bins }, (_, bin) => {
    const at = window.start + ((bin + 0.5) / bins) * span
    const counts: StateCounts = { tool: 0, thinking: 0, waiting: 0 }

    for (const row of rows) {
      const state = stateAt(row, at, now)

      if (state === 'tool' || state === 'thinking' || state === 'waiting') {
        counts[state] += 1
      }
    }

    return counts
  })
}

const stepArea = (bins: number, binWidth: number, top: readonly number[], bottom: readonly number[]): string => {
  const x = (bin: number): number => num(bin * binWidth)
  let path = `M0 ${num(top[0] ?? 0)}`

  for (let bin = 0; bin < bins; bin += 1) {
    const next = top[bin + 1]
    if (next === undefined || next !== top[bin]) {
      path += `H${x(bin + 1)}${next === undefined ? '' : `V${num(next)}`}`
    }
  }

  path += `V${num(bottom[bins - 1] ?? 0)}`

  for (let bin = bins - 1; bin >= 0; bin -= 1) {
    const previous = bottom[bin - 1]
    if (previous === undefined || previous !== bottom[bin]) {
      path += `H${x(bin)}${previous === undefined ? '' : `V${num(previous)}`}`
    }
  }

  return `${path}Z`
}

export const densityMarkup = (input: TimelineInput, plan: GroupPlan, width: number, now: number): TimelinePiece => {
  const bins = Math.max(DENSITY_MIN_BINS, Math.min(DENSITY_MAX_BINS, Math.floor(width / DENSITY_BIN_WIDTH)))
  const series = countsOverTime(input, plan.agents, bins, now)
  const peak = Math.max(1, ...series.map(counts => counts.tool + counts.thinking + counts.waiting))
  const base = DENSITY_HEIGHT - 1
  const scale = (base - 1) / peak
  const floors = series.map(() => base)
  const layers: string[] = []

  for (const state of DENSITY_STATES) {
    const tops = series.map((counts, bin) => (floors[bin] ?? base) - counts[state] * scale)

    if (series.some(counts => counts[state] > 0)) {
      layers.push(`<path class="sg-${state}" d="${stepArea(bins, width / bins, tops, floors)}"/>`)
    }

    tops.forEach((top, bin) => {
      floors[bin] = top
    })
  }

  return { markup: `${horizontalLine(base, 0, width)}${layers.join('')}`, height: DENSITY_HEIGHT }
}
