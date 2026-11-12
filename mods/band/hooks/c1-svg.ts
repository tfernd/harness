import type { AgentRow, ThemeSetting } from '../types'

import { type Tone, svgStyleFor } from './c1-theme'
import { type Window } from './layout'
import { spanOf } from './c1'

export type BarSvg = { source: string; width: number; height: number }

const wrapSvg = (setting: ThemeSetting, width: number, height: number, body: string): BarSvg => ({
  source: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + width + ' ' + height + '" width="' + width + '" height="' + height + '"><style>' + svgStyleFor(setting) + '</style>' + body + '</svg>',
  width,
  height,
})

const rect = (box: { x: number; y: number; width: number; height: number; radius: number; tone: string }): string => '<rect class="' + box.tone + '" x="' + box.x + '" y="' + box.y + '" width="' + box.width + '" height="' + box.height + '" rx="' + box.radius + '"/>'

export const BAR_HEIGHT = 6
export const MINI_BAR_WIDTH = 34
export const FULL_BAR_WIDTH = 176
export const MINI_LANES_WIDTH = 120
export const MINI_LANE_COUNT = 5
const MINI_LANE_HEIGHT = 3
const MINI_LANE_STEP = 4
const MIN_FILL_WIDTH = 3

export const barSvg = (input: { percent: number; tone: Tone; width: number; setting: ThemeSetting }): BarSvg => {
  const clamped = Math.max(0, Math.min(100, input.percent))
  const fillWidth = clamped === 0 ? 0 : Math.max(MIN_FILL_WIDTH, Math.round((input.width * clamped) / 100))
  const radius = BAR_HEIGHT / 2
  const rail = rect({ x: 0, y: 0, width: input.width, height: BAR_HEIGHT, radius, tone: 'rail' })
  const fill = fillWidth === 0 ? '' : rect({ x: 0, y: 0, width: fillWidth, height: BAR_HEIGHT, radius, tone: 't-' + input.tone })

  return wrapSvg(input.setting, input.width, BAR_HEIGHT, rail + fill)
}

export type MiniLane = { row: AgentRow; tone: Tone }

export const miniLanesSvg = (input: { lanes: readonly MiniLane[]; window: Window; setting: ThemeSetting }): BarSvg => {
  const shown = input.lanes.slice(0, MINI_LANE_COUNT)
  const height = MINI_LANE_COUNT * MINI_LANE_STEP
  const bars = shown.map((lane, index) => {
    const y = index * MINI_LANE_STEP
    const span = spanOf(input.window, lane.row.startedAt, lane.row.endedAt ?? input.window.end)
    const rail = rect({ x: 0, y, width: MINI_LANES_WIDTH, height: MINI_LANE_HEIGHT, radius: 1, tone: 'rail' })

    if (span === null) {
      return rail
    }

    const x = Math.round((MINI_LANES_WIDTH * span.left) / 100)
    const width = Math.max(2, Math.round((MINI_LANES_WIDTH * span.width) / 100))

    return rail + rect({ x, y, width, height: MINI_LANE_HEIGHT, radius: 1, tone: 't-' + lane.tone })
  })
  const nowLine = rect({ x: MINI_LANES_WIDTH - 1, y: 0, width: 1, height, radius: 0, tone: 'now' })

  return wrapSvg(input.setting, MINI_LANES_WIDTH, height, bars.join('') + nowLine)
}
