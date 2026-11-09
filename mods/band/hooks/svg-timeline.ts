import type { AgentRow, AgentState, Range, RosterRow } from '../types'

import { DIRECT_GROUP, MAIN_ID, MAIN_LABEL, MAIN_STATE_WORD, STATE_ICON, earliestStart, formatSpan, groupAgents, splitByWindow, windowFor } from './model'
import {
  type Ctx,
  type Track,
  chevron,
  driftGroup,
  escapeText,
  fit,
  horizontalLine,
  label,
  laneMarkup,
  nowMarker,
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

const columnsFor = (width: number, isWide: boolean): Columns => {
  const labelWidth = Math.max(LABEL_MIN, Math.min(LABEL_MAX, Math.round(width * 0.24)))
  const stateWidth = isWide ? Math.max(STATE_MIN, Math.min(STATE_MAX, Math.round(width * 0.27))) : 0

  return { labelWidth, stateWidth, trackWidth: width - labelWidth - stateWidth }
}

const idleWord = (state: AgentState, isMain: boolean): string =>
  isMain ? (state === 'launched' ? 'idle' : 'working...') : state === 'launched' ? 'starting...' : state === 'waiting' ? 'waiting...' : state === 'done' ? 'completed' : state === 'failed' ? 'failed' : 'thinking...'

const GLYPH_CLASS: Record<AgentState, string> = {
  launched: 'acc',
  thinking: 'acc',
  tool: 'acc',
  waiting: 'acc',
  done: 'm',
  failed: 'bad b',
}

const rowMarkup = (
  input: { agent: RosterRow; row: AgentRow | undefined; y: number; width: number; columns: Columns },
): string => {
  const { agent, row, y, width, columns } = input
  const isMain = agent.id === MAIN_ID
  const fallback: AgentState = isMain ? 'launched' : agent.phase === 'failed' ? 'failed' : agent.phase === 'done' ? 'done' : 'thinking'
  const state: AgentState = row?.state ?? fallback
  const command = row?.command ?? idleWord(state, isMain)
  const word = isMain ? MAIN_STATE_WORD[state] : undefined
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
      : statePill({ x: stateX, y: y + (ROW_HEIGHT - PILL_HEIGHT) / 2, width: PILL_WIDTH, height: PILL_HEIGHT }, state, word) +
        (row?.command == null
          ? ''
          : label(textX, baseline, isQuiet ? 'm' : '', fit(row.command, columns.stateWidth - PILL_WIDTH - PILL_GAP - PAD, 12)))

  return (
    `<g class="row"><title>${escapeText(`${agent.label}: ${state}, ${command}`)}</title>` +
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

const groupHeader = (
  input: { id: string; name: string; counts: { live: number; done: number; failed: number }; isFolded: boolean; y: number; width: number },
): string => {
  const kind = input.id === DIRECT_GROUP ? 'DIRECT' : 'WORKFLOW'
  const name = input.name.replace(/^workflow /, '')
  const summary = `${input.counts.live} live · ${input.counts.done + input.counts.failed} ended`
  const baseline = input.y + GROUP_HEIGHT / 2 + TEXT_DROP
  const nameX = PAD + 17 + kind.length * 10 + 10

  return (
    rect({ x: 0, y: input.y, width: input.width, height: GROUP_HEIGHT }, 'pan') +
    horizontalLine(input.y, 0, input.width) +
    chevron(PAD, input.y + GROUP_HEIGHT / 2, input.isFolded) +
    label(PAD + 17, baseline, 'm b s cap', kind) +
    label(nameX, baseline, '', fit(name, input.width - nameX - summary.length * 6.4 - 2 * PAD, 12)) +
    label(input.width - PAD, baseline, 'm end', summary)
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

export const timelineMarkup = (ctx: Ctx, input: TimelineInput, top: number, rowLimit: number): { markup: string; height: number } => {
  const columns = columnsFor(input.width, input.isWide)
  const window = windowFor(input.range, ctx.now, earliestStart([...input.rows.values()], input.sessionStart))
  const track: Track = { x: columns.labelWidth, width: columns.trackWidth, window }
  let y = top + HEAD_HEIGHT
  let used = 0
  let hidden = 0
  const parts: string[] = [headMarkup({ columns, width: input.width, top, spanMs: window.end - window.start, range: input.range })]
  const mainRow = input.rows.get(MAIN_ID)
  const mainTop = y

  parts.push(rowMarkup({ agent: MAIN_ROSTER_ROW, row: mainRow, y, width: input.width, columns }))
  y += ROW_HEIGHT
  parts.push(
    laneBlockMarkup(ctx, {
      lanes: [laneMarkup(ctx, mainRow, track, { y: mainTop + LANE_INSET, height: TRACK_LANE, radius: TRACK_LANE / 2 })],
      top: mainTop,
      bottom: y,
      columns,
      track,
    }),
  )

  for (const group of groupAgents(input.roster.rows)) {
    const isFolded = input.foldedGroups.includes(group.id)
    const { shown: inWindow, earlier } = splitByWindow(group.agents, input.rows, window.start)

    if (inWindow.length === 0 && earlier === 0) {
      continue
    }

    const shown = inWindow.slice(0, Math.max(0, rowLimit - used))

    if (!isFolded && shown.length === 0 && inWindow.length > 0) {
      hidden += inWindow.length
      continue
    }

    parts.push(groupHeader({ id: group.id, name: group.label, counts: group.counts, isFolded, y, width: input.width }))
    y += GROUP_HEIGHT

    if (isFolded) {
      continue
    }

    hidden += inWindow.length - shown.length
    used += shown.length
    const blockTop = y
    const lanes: string[] = []

    for (const agent of shown) {
      const row = input.rows.get(agent.id)
      parts.push(rowMarkup({ agent, row, y, width: input.width, columns }))
      lanes.push(laneMarkup(ctx, row, track, { y: y + LANE_INSET, height: TRACK_LANE, radius: TRACK_LANE / 2 }))
      y += ROW_HEIGHT
    }

    if (y > blockTop) {
      parts.push(laneBlockMarkup(ctx, { lanes, top: blockTop, bottom: y, columns, track }))
    }

    if (earlier > 0) {
      parts.push(horizontalLine(y, 0, input.width), label(PAD, y + MORE_HEIGHT / 2 + TEXT_DROP, 'm s', `+${earlier} earlier`))
      y += MORE_HEIGHT
    }
  }

  if (hidden > 0) {
    parts.push(horizontalLine(y, 0, input.width), label(PAD, y + MORE_HEIGHT / 2 + TEXT_DROP, 'm s', `+${hidden} more agents not drawn`))
    y += MORE_HEIGHT
  }

  const height = y - top

  return { markup: parts.join(''), height }
}
