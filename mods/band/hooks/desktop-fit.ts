import type { Activity } from './activity'
import { type Arc, apiBillingText, percentTextOf, resetInOf } from './arcs'
import { formatUsd } from './cost'

export const COLUMN_PX = 8
export const FOLDED_PADDING_COLUMNS = 4
export const FOLDED_GAP_COLUMNS = 6
export const FOLDED_BUTTON_COLUMNS = 3
export const FOLDED_RING_COLUMNS = 5
export const FOLDED_SAFETY_COLUMNS = 2
export const MAIN_STATE_NAME_COLUMNS = 4
export const COUNTS_COLUMNS = 9
export const LEGEND_ITEM_GAP_COLUMNS = 3
export const LEGEND_COLUMN_GAP_COLUMNS = 2
export const MINI_LANE_MIN_COLUMNS = 14
export const GUTTER_COLUMNS = 36
export const TOKENS_COLUMNS = 12
export const COST_COLUMNS = 9
export const STRIP_MIN_COLUMNS = 12
export const TIME_COLUMNS = 6
export const TILE_PADDING_COLUMNS = 4
export const SECTION_GAP_COLUMNS = 2
export const MAIN_COLUMN_PADDING_COLUMNS = 4
export const TILE_FIXED_COLUMNS = TILE_PADDING_COLUMNS + TIME_COLUMNS + TOKENS_COLUMNS + COST_COLUMNS + 3 * SECTION_GAP_COLUMNS
export const GUTTER_SIDE_COLUMNS = GUTTER_COLUMNS + 1 + MAIN_COLUMN_PADDING_COLUMNS
export const TILE_ROW_GAP_COLUMNS = 1

export const pixelsOf = (columns: number): number => columns * COLUMN_PX

const legendItemColumnsOf = (arc: Arc, now: number): number => {
  const reset = arc.resetsAt === null ? (arc.usage === null ? '' : arc.usage) : '↻ ' + resetInOf(arc.resetsAt, now)

  return 1 + arc.short.length + percentTextOf(arc.percent).length + reset.length + LEGEND_ITEM_GAP_COLUMNS
}

export const legendColumnsWidthOf = (input: { columns: readonly (readonly Arc[])[]; now: number; costUsd: number | null; apiText: string | null }): number => {
  const widths = input.columns.map((column, index) => {
    const items = Math.max(0, ...column.map(arc => legendItemColumnsOf(arc, input.now)))
    const cost = index === 1 && input.costUsd !== null ? formatUsd(input.costUsd).length + LEGEND_COLUMN_GAP_COLUMNS : 0
    const api = index === 0 && input.apiText !== null ? input.apiText.length : 0

    return Math.max(items + cost, api)
  })

  return widths.reduce((sum, width) => sum + width, 0) + LEGEND_COLUMN_GAP_COLUMNS * Math.max(0, widths.length - 1)
}

export const miniLaneColumnsOf = (input: { columns: number; legendColumns: number; activity: Activity }): number => {
  const mainState = Math.max(MAIN_STATE_NAME_COLUMNS + COUNTS_COLUMNS, input.activity.icon.length + 1 + input.activity.word.length)
  const used = FOLDED_PADDING_COLUMNS + FOLDED_GAP_COLUMNS + FOLDED_BUTTON_COLUMNS + FOLDED_RING_COLUMNS + FOLDED_SAFETY_COLUMNS + input.legendColumns + mainState

  return Math.max(MINI_LANE_MIN_COLUMNS, input.columns - used)
}

export const stripColumnsOf = (input: { columns: number; tilesPerRow: number }): number => {
  const available = input.columns - GUTTER_SIDE_COLUMNS
  const tileColumns = input.tilesPerRow === 2 ? Math.floor((available - TILE_ROW_GAP_COLUMNS) / 2) : available

  return Math.max(STRIP_MIN_COLUMNS, tileColumns - TILE_FIXED_COLUMNS)
}
