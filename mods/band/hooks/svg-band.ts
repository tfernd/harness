import type { AgentRow, Gauges, Range, Roster, ThemeSetting } from '../types'

export type SvgInput = {
  width: number
  columns: number
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
  loadedAt: number
}

export const columnsToWidth = (columns: number): number => Math.max(320, Math.min(1100, Math.round(columns * 8)))
