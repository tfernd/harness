import type { ThemeSetting } from '../types'

import { type CellKind, type CellRun, runsOf } from './activity'
import type { Arc } from './arcs'
import { type ArcId, svgStyleFor } from './desktop-theme'

export type DrawnSvg = { source: string; width: number; height: number }

const wrapSvg = (setting: ThemeSetting, width: number, height: number, body: string, aspect = ''): DrawnSvg => ({
  source: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + width + ' ' + height + '" width="' + width + '" height="' + height + '"' + aspect + '><style>' + svgStyleFor(setting) + '</style>' + body + '</svg>',
  width,
  height,
})

type Box = { x: number; y: number; width: number; height: number; radius: number; className: string }

const rect = (box: Box): string => '<rect class="' + box.className + '" x="' + box.x + '" y="' + box.y + '" width="' + box.width + '" height="' + box.height + '" rx="' + box.radius + '"/>'

const ARC_FILL: Readonly<Record<ArcId, string>> = { fiveHour: 'f-arcFiveHour', week: 'f-arcWeek', fable: 'f-arcFable', context: 'f-arcContext' }

const ARC_STROKE: Readonly<Record<ArcId, string>> = { fiveHour: 's-arcFiveHour', week: 's-arcWeek', fable: 's-arcFable', context: 's-arcContext' }

const STRETCH = ' preserveAspectRatio="none"'

export const RING_SIZE = 26
export const RING_OUTER_RADIUS = 11.5
export const RING_STEP = 3
export const RING_STROKE = 2
export const BAR_HEIGHT = 4
export const GUTTER_BAR_WIDTH = 150
export const STRIP_CELL_WIDTH = 5
export const STRIP_CELL_GAP = 1
export const STRIP_HEIGHT = 8
export const MINI_LANES_WIDTH = 112
export const MINI_LANE_HEIGHT = 3
export const MINI_LANE_STEP = 4
export const MINI_LANE_CELLS = 56

export const ringRadiusOf = (index: number): number => RING_OUTER_RADIUS - index * RING_STEP

export const ringSvg = (input: { arcs: readonly Arc[]; setting: ThemeSetting }): DrawnSvg => {
  const center = RING_SIZE / 2
  const circles = input.arcs.map((arc, index) => {
    const radius = ringRadiusOf(index)
    const circumference = 2 * Math.PI * radius
    const filled = (circumference * Math.max(0, Math.min(100, arc.percent))) / 100
    const common = ' cx="' + center + '" cy="' + center + '" r="' + radius + '" fill="none" stroke-width="' + RING_STROKE + '"'
    const track = '<circle class="s-rail"' + common + '/>'
    const arcPath = '<circle class="' + ARC_STROKE[arc.id] + '"' + common + ' stroke-dasharray="' + filled.toFixed(2) + ' ' + circumference.toFixed(2) + '" transform="rotate(-90 ' + center + ' ' + center + ')"/>'

    return track + arcPath
  })

  return wrapSvg(input.setting, RING_SIZE, RING_SIZE, circles.join(''))
}

export const barSvg = (input: { percent: number; id: ArcId; width: number; setting: ThemeSetting }): DrawnSvg => {
  const clamped = Math.max(0, Math.min(100, input.percent))
  const fillWidth = Math.round((input.width * clamped) / 100)
  const radius = BAR_HEIGHT / 2
  const track = rect({ x: 0, y: 0, width: input.width, height: BAR_HEIGHT, radius, className: 'f-rail' })
  const fill = fillWidth === 0 ? '' : rect({ x: 0, y: 0, width: fillWidth, height: BAR_HEIGHT, radius, className: ARC_FILL[input.id] })

  return wrapSvg(input.setting, input.width, BAR_HEIGHT, track + fill)
}

export const ruleSvg = (input: { width: number; setting: ThemeSetting }): DrawnSvg =>
  wrapSvg(input.setting, input.width, 1, '<line class="s-muted" x1="0" x2="' + input.width + '" y1="0.5" y2="0.5" stroke-width="1" stroke-dasharray="2 3" opacity="0.6"/>')

const CELL_CLASS: Readonly<Record<Exclude<CellKind, 'empty' | 'idle'>, string>> = {
  run: 'f-run',
  runSoft: 'f-runSoft',
  ink: 'f-ink',
  inkSoft: 'f-inkSoft',
  warn: 'f-warn',
  done: 'f-done',
  doneSoft: 'f-doneSoft',
  fail: 'f-fail',
  failSoft: 'f-failSoft',
}

const cellShapes = (kind: CellKind, box: { x: number; width: number; height: number; radius: number }): string => {
  const ground = rect({ x: box.x, y: 0, width: box.width, height: box.height, radius: box.radius, className: 'f-rail' })

  if (kind === 'empty') {
    return ground
  }

  if (kind === 'idle') {
    const dotSize = Math.min(2, box.width)

    return ground + rect({ x: box.x + (box.width - dotSize) / 2, y: (box.height - dotSize) / 2, width: dotSize, height: dotSize, radius: dotSize / 2, className: 'f-muted' })
  }

  return rect({ x: box.x, y: 0, width: box.width, height: box.height, radius: box.radius, className: CELL_CLASS[kind] })
}

export const stripWidthOf = (cellCount: number): number => cellCount * (STRIP_CELL_WIDTH + STRIP_CELL_GAP) - STRIP_CELL_GAP

export const stripSvg = (input: { cells: readonly CellKind[]; setting: ThemeSetting }): DrawnSvg => {
  const shapes = input.cells.map((kind, index) => cellShapes(kind, { x: index * (STRIP_CELL_WIDTH + STRIP_CELL_GAP), width: STRIP_CELL_WIDTH, height: STRIP_HEIGHT, radius: 1 }))

  return wrapSvg(input.setting, stripWidthOf(input.cells.length), STRIP_HEIGHT, shapes.join(''), STRETCH)
}

const laneRunShape = (run: CellRun, y: number): string => {
  const cellWidth = MINI_LANES_WIDTH / MINI_LANE_CELLS
  const x = run.from * cellWidth
  const width = Math.max(1, run.count * cellWidth)

  if (run.kind === 'empty') {
    return ''
  }

  if (run.kind === 'idle') {
    return rect({ x, y: y + 1, width, height: 1, radius: 0, className: 'f-muted' })
  }

  return rect({ x, y, width, height: MINI_LANE_HEIGHT, radius: 0, className: CELL_CLASS[run.kind] })
}

export const miniLanesSvg = (input: { lanes: readonly (readonly CellKind[])[]; setting: ThemeSetting }): DrawnSvg => {
  const height = Math.max(1, input.lanes.length) * MINI_LANE_STEP
  const bars = input.lanes.map((cells, index) => {
    const y = index * MINI_LANE_STEP
    const ground = rect({ x: 0, y, width: MINI_LANES_WIDTH, height: MINI_LANE_HEIGHT, radius: 0, className: 'f-rail' })

    return ground + runsOf(cells).map(run => laneRunShape(run, y)).join('')
  })
  const nowLine = rect({ x: MINI_LANES_WIDTH - 1, y: 0, width: 1, height, radius: 0, className: 'f-ink' })

  return wrapSvg(input.setting, MINI_LANES_WIDTH, height, bars.join('') + nowLine, STRETCH)
}
