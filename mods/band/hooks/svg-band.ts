import type { AgentRow, Gauges, Range, Roster, RosterRow, ThemeSetting } from '../types'

import { cacheRefreshMs } from './gauges'
import { MAIN_ID, nextLeaveMs } from './model'
import type { Ctx } from './svg-parts'
import { FOLDED_RING_RADIUS, FOLDED_RING_SIZE, RING_SIZE, TRACES_MORE_WIDTH, foldedTracesWidth, type GaugeSpec, type StripInput, gaugeSpecs, ring, traceLanes, tracesHeight } from './svg-strip'
import { styleFor } from './svg-theme'
import { type GroupPlan, type TimelineInput, type TimelinePiece, groupRowsMarkup, hiddenAgentsMarkup, planGroups, timelineHeadMarkup, windowSpanOf } from './svg-timeline'

export type SvgInput = {
  width: number
  now: number
  isFolded: boolean
  range: Range
  foldedGroups: readonly string[]
  roster: Roster
  rows: ReadonlyMap<string, AgentRow>
  gauges: Gauges
  isWorking: boolean
  turnStartedAt: number | null
  scheme: ThemeSetting
}

export type BandSvg = { source: string; width: number; height: number }

export type PieceSpec = {
  key: string
  signature: string
  interaction: string
  maxAgeMs: number | null
  build: () => BandSvg
}

export const SOURCE_LIMIT_CHARACTERS = 120_000
export const WIDE_MIN_WIDTH = 640
export const REFRESH_LIVE_MS = 15_000
export const REFRESH_IDLE_MS = 55_000

const ROW_LIMITS: readonly number[] = [6, 4, 2, 0]
const BORDER_PX = 16
const MIN_TIMELINE_WIDTH = 304

const DEFS =
  '<pattern id="stp" width="12" height="12" patternUnits="userSpaceOnUse"><path class="stripef" d="M0 0H6L0 6ZM0 12L12 0V6L6 12Z"/></pattern>' +
  '<linearGradient id="shg"><stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset=".5" class="shimmerstop"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>'

const EXTRA_STYLE = '.stripef{fill:var(--stripe)}.shimmerstop{stop-color:var(--shimmer)}'

const wrap = (input: { scheme: ThemeSetting; width: number; height: number; ctx: Ctx; body: string }): BandSvg => ({
  source:
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${input.width} ${input.height}" width="${input.width}" height="${input.height}">` +
    `<style>${styleFor(input.scheme)}${EXTRA_STYLE}</style><defs>${DEFS}${input.ctx.defs.join('')}</defs>${input.body}</svg>`,
  width: input.width,
  height: input.height,
})

const newCtx = (now: number): Ctx => ({ defs: [], counter: 0, now })

const stripInputOf = (input: SvgInput): StripInput => ({
  width: input.width,
  isWide: input.width >= WIDE_MIN_WIDTH,
  isFolded: input.isFolded,
  gauges: input.gauges,
  roster: input.roster,
  rows: input.rows,
  isWorking: input.isWorking,
  turnStartedAt: input.turnStartedAt,
})

export const liveCountOf = (input: SvgInput): number => input.roster.rows.filter(row => row.phase === 'live').length

const detailsOfRows = (input: SvgInput, rows: readonly RosterRow[]) =>
  rows.map(row => {
    const detail = input.rows.get(row.id)

    return detail === undefined ? null : [row.id, detail.state, detail.command, detail.segments.length, detail.endedAt]
  })

const mainDetailOf = (input: SvgInput) => {
  const main = input.rows.get(MAIN_ID)

  return main === undefined ? null : [main.state, main.command, main.segments.length, main.segments.at(-1)?.from]
}

const ringPiece = (input: SvgInput, spec: GaugeSpec): PieceSpec => {
  const size = input.isFolded ? FOLDED_RING_SIZE : RING_SIZE
  const radius = input.isFolded ? FOLDED_RING_RADIUS : undefined

  return {
    key: `ring-${spec.id}`,
    signature: JSON.stringify([spec.id, Math.round(spec.percent), spec.tone, input.scheme, input.isFolded]),
    interaction: input.scheme,
    maxAgeMs: null,
    build: () =>
      wrap({
        scheme: input.scheme,
        width: size,
        height: size,
        ctx: newCtx(input.now),
        body: ring({ cx: size / 2, cy: size / 2, radius }, spec),
      }),
  }
}

const tracesWidthOf = (input: SvgInput): number => foldedTracesWidth(input.width, gaugeSpecs(input.gauges, input.now))

const tracesPiece = (input: SvgInput): PieceSpec => ({
  key: 'traces',
  signature: JSON.stringify([input.scheme, input.width, detailsOfRows(input, input.roster.rows.filter(row => row.phase === 'live'))]),
  interaction: input.scheme,
  maxAgeMs: REFRESH_IDLE_MS,
  build: () => {
    const ctx = newCtx(input.now)
    const height = tracesHeight(liveCountOf(input))
    const width = tracesWidthOf(input)
    const body = traceLanes(ctx, stripInputOf(input), { x: 0, y: 0, width: width - TRACES_MORE_WIDTH })

    return wrap({ scheme: input.scheme, width, height, ctx, body })
  },
})

const EMPTY_SVG: BandSvg = { source: '', width: 0, height: 0 }

export const TIMELINE_KEY = 'timeline'
export const HIDDEN_KEY = 'timeline-more'
export const groupRowsKey = (groupId: string): string => `timeline-rows-${groupId}`

const timelineInputOf = (input: SvgInput): TimelineInput => {
  const width = Math.max(MIN_TIMELINE_WIDTH, input.width - BORDER_PX)

  return {
    ...stripInputOf(input),
    width,
    isWide: width >= WIDE_MIN_WIDTH,
    range: input.range,
    foldedGroups: input.foldedGroups,
    sessionStart: input.gauges.sessionStartedAt ?? input.now,
  }
}

export const listedGroupsOf = (input: SvgInput): GroupPlan[] => planGroups(timelineInputOf(input), input.now, Number.POSITIVE_INFINITY).groups

const drawn = (input: SvgInput, width: number, draw: (ctx: Ctx) => TimelinePiece): BandSvg => {
  const ctx = newCtx(input.now)
  const piece = draw(ctx)

  return piece.height === 0 ? EMPTY_SVG : wrap({ scheme: input.scheme, width, height: piece.height, ctx, body: piece.markup })
}

const buildTimelinePieces = (input: SvgInput, rowLimit: number): Map<string, BandSvg> => {
  const timelineInput = timelineInputOf(input)
  const { width } = timelineInput
  const plan = planGroups(timelineInput, input.now, rowLimit)
  const pieces = new Map<string, BandSvg>([[TIMELINE_KEY, drawn(input, width, ctx => timelineHeadMarkup(ctx, timelineInput))]])

  for (const group of plan.groups) {
    pieces.set(groupRowsKey(group.id), drawn(input, width, ctx => groupRowsMarkup(ctx, timelineInput, group)))
  }

  pieces.set(HIDDEN_KEY, drawn(input, width, () => hiddenAgentsMarkup(timelineInput, plan.hidden)))

  return pieces
}

const fittingTimeline = (input: SvgInput): Map<string, BandSvg> => {
  for (const limit of ROW_LIMITS) {
    const built = buildTimelinePieces(input, limit)
    const characters = [...built.values()].reduce((sum, svg) => sum + svg.source.length, 0)

    if (characters <= SOURCE_LIMIT_CHARACTERS) {
      return built
    }
  }

  throw new Error(`band svg wider than ${SOURCE_LIMIT_CHARACTERS} characters even with no agent rows`)
}

const timelinePieces = (input: SvgInput): PieceSpec[] => {
  const timelineInput = timelineInputOf(input)
  const groups = listedGroupsOf(input)
  let fitted: Map<string, BandSvg> | null = null
  const fittedPiece = (key: string): BandSvg => {
    fitted ??= fittingTimeline(input)

    return fitted.get(key) ?? EMPTY_SVG
  }
  const base = [input.width, input.range, input.scheme]
  const interaction = JSON.stringify([...base, input.foldedGroups])
  const head: PieceSpec = {
    key: TIMELINE_KEY,
    signature: JSON.stringify([...base, mainDetailOf(input), windowSpanOf(timelineInput, input.now)]),
    interaction,
    maxAgeMs: REFRESH_IDLE_MS,
    build: () => fittedPiece(TIMELINE_KEY),
  }
  let rowsBefore = 0
  const rows = groups
    .filter(group => !group.isFolded)
    .map((group): PieceSpec => {
      const signature = JSON.stringify([
        ...base,
        group.id,
        rowsBefore,
        group.earlier,
        group.inWindowCount,
        detailsOfRows(input, group.shown),
        group.shown.map(row => row.id),
      ])
      rowsBefore += group.inWindowCount

      return { key: groupRowsKey(group.id), signature, interaction, maxAgeMs: REFRESH_IDLE_MS, build: () => fittedPiece(groupRowsKey(group.id)) }
    })
  const more: PieceSpec = {
    key: HIDDEN_KEY,
    signature: JSON.stringify([...base, rowsBefore]),
    interaction,
    maxAgeMs: REFRESH_IDLE_MS,
    build: () => fittedPiece(HIDDEN_KEY),
  }

  return rowsBefore === 0 ? [head, ...rows] : [head, ...rows, more]
}

export const piecesOf = (input: SvgInput): PieceSpec[] => {
  const pieces = gaugeSpecs(input.gauges, input.now).map(spec => ringPiece(input, spec))

  if (input.isFolded) {
    return liveCountOf(input) > 0 && tracesWidthOf(input) > 0 ? [...pieces, tracesPiece(input)] : pieces
  }

  return [...pieces, ...timelinePieces(input)]
}

export const refreshAfterMs = (input: SvgInput): number | null => {
  const waits = [
    input.isFolded ? null : nextLeaveMs(input.rows.values(), input.range, input.now),
    liveCountOf(input) > 0 ? REFRESH_LIVE_MS : null,
    input.roster.rows.length > 0 && !input.isFolded ? REFRESH_IDLE_MS : null,
    cacheRefreshMs(input.gauges, input.now),
  ].filter((wait): wait is number => wait !== null)

  return waits.length === 0 ? null : Math.min(...waits)
}

export const columnsToWidth = (columns: number): number => Math.max(320, Math.min(1100, Math.round(columns * 8)))
