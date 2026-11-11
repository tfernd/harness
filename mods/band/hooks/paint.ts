import type { AgentRow, AgentState, Scheme } from '../types'

import { type Window, stateInSlice } from './layout'

export const TICK_MS = 200
export const BLINK_MS = 600
const SHIMMER_TAIL = 4
const GLYPH_BLOCK = 0x2588
const GLYPH_UPPER_HALF = 0x2580
const GLYPH_SPACE = 0x20

export type Palette = {
  lane: number
  ink: number
  launched: number
  thinking: number
  tool: number
  waiting: number
  done: number
  failed: number
}

export const PALETTES: Record<Scheme, Palette> = {
  dark: {
    lane: 0x232a35,
    ink: 0xe7eaef,
    launched: 0x6b7788,
    thinking: 0x6d9cf2,
    tool: 0x35b0a2,
    waiting: 0xe0a02e,
    done: 0x8592a3,
    failed: 0xee6c60,
  },
  light: {
    lane: 0xe9e3d8,
    ink: 0x1c2430,
    launched: 0x9aa5b4,
    thinking: 0x3f6fcb,
    tool: 0x0f8a84,
    waiting: 0xc9820a,
    done: 0x75818f,
    failed: 0xc0392b,
  },
}

export const mix = (from: number, to: number, amount: number): number => {
  const channel = (shift: number): number => {
    const a = (from >> shift) & 0xff
    const b = (to >> shift) & 0xff

    return Math.round(a + (b - a) * amount) << shift
  }

  return channel(16) | channel(8) | channel(0)
}

export const stateColor = (palette: Palette, state: AgentState): number => palette[state]

export type Frame = { now: number; phase: number }

export const frameAt = (now: number): Frame => ({ now, phase: Math.floor(now / BLINK_MS) % 2 })

const shade = (palette: Palette, state: AgentState, column: number, columns: number, frame: Frame): number => {
  const base = stateColor(palette, state)

  if (state === 'thinking') {
    return (column + frame.phase) % 2 === 0 ? base : mix(base, palette.lane, 0.45)
  }

  if (state === 'waiting') {
    return (column + frame.phase) % 2 === 0 ? base : mix(base, palette.lane, 0.6)
  }

  if (state === 'tool') {
    const shimmer = (Math.floor(frame.now / TICK_MS) % (columns + SHIMMER_TAIL)) - 2

    return Math.abs(column - shimmer) <= 1 ? mix(base, palette.ink, 0.45) : base
  }

  return base
}

export const laneColors = (agent: AgentRow, window: Window, columns: number, palette: Palette, frame: Frame): number[] => {
  const span = (window.end - window.start) / columns

  return Array.from({ length: columns }, (_, column) => {
    const from = window.start + column * span
    const state = stateInSlice(agent, from, from + span, frame.now)

    return state === null ? palette.lane : shade(palette, state, column, columns, frame)
  })
}

export type Grid = { columns: number; rows: number; words: Uint32Array }

export const createGrid = (columns: number, rows: number, background: number): Grid => {
  const words = new Uint32Array(columns * rows * 3)

  for (let index = 0; index < columns * rows; index += 1) {
    words[index * 3] = GLYPH_SPACE
    words[index * 3 + 2] = background
  }

  return { columns, rows, words }
}

export const setCell = (grid: Grid, position: { column: number; row: number }, cell: { glyph: number; foreground: number; background: number }): void => {
  if (position.column < 0 || position.column >= grid.columns || position.row < 0 || position.row >= grid.rows) {
    return
  }

  const index = (position.row * grid.columns + position.column) * 3
  grid.words[index] = cell.glyph
  grid.words[index + 1] = cell.foreground
  grid.words[index + 2] = cell.background
}

const BASE64_ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'

export const encodeGrid = (grid: Grid): string => {
  const bytes = new Uint8Array(grid.words.length * 4)
  const view = new DataView(bytes.buffer)
  grid.words.forEach((word, index) => view.setUint32(index * 4, word, true))
  let text = ''

  for (let index = 0; index < bytes.length; index += 3) {
    const first = bytes[index] ?? 0
    const second = bytes[index + 1] ?? 0
    const third = bytes[index + 2] ?? 0
    const chunk = (first << 16) | (second << 8) | third
    const remaining = bytes.length - index
    text += BASE64_ALPHABET.charAt((chunk >> 18) & 63) + BASE64_ALPHABET.charAt((chunk >> 12) & 63)
    text += remaining > 1 ? BASE64_ALPHABET.charAt((chunk >> 6) & 63) : '='
    text += remaining > 2 ? BASE64_ALPHABET.charAt(chunk & 63) : '='
  }

  return text
}

export const paintLanes = (agents: readonly (AgentRow | undefined)[], options: { columns: number; window: Window; palette: Palette; frame: Frame }): Grid => {
  const grid = createGrid(options.columns, Math.max(1, agents.length), options.palette.lane)

  agents.forEach((agent, row) => {
    if (agent === undefined) {
      return
    }

    laneColors(agent, options.window, options.columns, options.palette, options.frame).forEach((color, column) => setCell(grid, { column, row }, { glyph: GLYPH_BLOCK, foreground: color, background: options.palette.lane }))
  })

  return grid
}

export const paintTraces = (agents: readonly (AgentRow | undefined)[], options: { columns: number; window: Window; palette: Palette; frame: Frame }): Grid => {
  const rows = Math.max(1, Math.ceil(agents.length / 2))
  const grid = createGrid(options.columns, rows, options.palette.lane)
  const colorsOf = (agent: AgentRow | undefined): number[] => (agent === undefined ? Array.from({ length: options.columns }, () => options.palette.lane) : laneColors(agent, options.window, options.columns, options.palette, options.frame))

  for (let row = 0; row < rows; row += 1) {
    const upper = colorsOf(agents[row * 2])
    const lower = colorsOf(agents[row * 2 + 1])

    upper.forEach((color, column) => setCell(grid, { column, row }, { glyph: GLYPH_UPPER_HALF, foreground: color, background: lower[column] ?? options.palette.lane }))
  }

  return grid
}

export const DEFAULT_COLOR = 0x01000000

export type TextSpan = { text: string; color: number | null }

export type TextAlign = 'left' | 'right'

const fitText = (text: string, columns: number, align: TextAlign): string[] => {
  const glyphs = Array.from(text)
  const blanks = Array.from({ length: Math.max(0, columns - glyphs.length) }, () => ' ')

  return align === 'right' ? [...blanks, ...glyphs].slice(-columns) : [...glyphs, ...blanks].slice(0, columns)
}

export const paintTextRows = (spans: readonly TextSpan[], columns: number, align: TextAlign): Grid => {
  const grid = createGrid(columns, Math.max(1, spans.length), DEFAULT_COLOR)

  spans.forEach((span, row) => fitText(span.text, columns, align).forEach((glyph, column) => setCell(grid, { column, row }, { glyph: glyph.codePointAt(0) ?? GLYPH_SPACE, foreground: span.color ?? DEFAULT_COLOR, background: DEFAULT_COLOR })))

  return grid
}

export type Run = { color: number; length: number }

export const runsOf = (colors: readonly number[]): Run[] => {
  const runs: Run[] = []

  for (const color of colors) {
    const last = runs[runs.length - 1]

    if (last !== undefined && last.color === color) {
      last.length += 1
    } else {
      runs.push({ color, length: 1 })
    }
  }

  return runs
}

export const hexOf = (color: number): string => `#${color.toString(16).padStart(6, '0')}`
