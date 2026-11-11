import type { AgentRow, AgentState } from '../types'

import { DRIFT_MS } from './svg-theme'
import { STATE_WORD, isLive } from './model'
import { type Window } from './layout'

export type SvgContext = { defs: string[]; counter: number; now: number }

export type Track = { x: number; width: number; window: Window }

export type LaneShape = { y: number; height: number; radius: number }

const ENTITIES: Readonly<Record<string, string>> = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }

const CHAR_WIDTH_EM = 0.56
const SHIMMER_WIDTH = 40
const MIN_SEGMENT_WIDTH = 2
const END_CAP_WIDTH = 4
const PILL_FONT_BASELINE = 3.2

export const escapeText = (text: string): string => text.replace(/[&<>"']/g, character => ENTITIES[character] ?? character).replace(/[\u0000-\u001f]/g, ' ')

export const roundTenth = (value: number): number => Math.round(value * 10) / 10

export const fit = (text: string, width: number, size: number): string => {
  const chars = Math.max(0, Math.floor(width / (size * CHAR_WIDTH_EM)))

  if (text.length <= chars) {
    return text
  }

  return chars <= 1 ? '' : `${text.slice(0, chars - 1)}…`
}

export const nextId = (context: SvgContext, prefix: string): string => {
  context.counter += 1

  return `${prefix}${context.counter}`
}

export const clipRect = (context: SvgContext, box: { x: number; y: number; width: number; height: number; radius?: number }): string => {
  const id = nextId(context, 'c')
  const radius = box.radius === undefined ? '' : ` rx="${box.radius}"`
  context.defs.push(`<clipPath id="${id}"><rect x="${roundTenth(box.x)}" y="${roundTenth(box.y)}" width="${roundTenth(box.width)}" height="${roundTenth(box.height)}"${radius}/></clipPath>`)

  return id
}

export const rect = (box: { x: number; y: number; width: number; height: number; radius?: number }, cls: string, extra = ''): string => {
  const radius = box.radius === undefined ? '' : ` rx="${box.radius}"`

  return `<rect x="${roundTenth(box.x)}" y="${roundTenth(box.y)}" width="${roundTenth(box.width)}" height="${roundTenth(box.height)}"${radius} class="${cls}"${extra}/>`
}

export const label = (x: number, y: number, cls: string, content: string, extra = ''): string => `<text x="${roundTenth(x)}" y="${roundTenth(y)}" class="${cls}"${extra}>${escapeText(content)}</text>`

export const COUNTS_ROW_STEP = 14
export const COUNTS_ICON_WIDTH = 14
export const COUNTS_DIGIT_WIDTH = 7.5
export const COUNTS_MIN_DIGITS = 3
export const COUNTS_RESERVED_WIDTH = COUNTS_ICON_WIDTH + 4 + COUNTS_MIN_DIGITS * COUNTS_DIGIT_WIDTH

export type CountsMark = { live: number; done: number; failed: number }

export const countsIcons = (counts: CountsMark): { markup: string; width: number; height: number } => {
  const digits = Math.max(COUNTS_MIN_DIGITS, ...[counts.live, counts.done, counts.failed].map(value => String(value).length))
  const width = COUNTS_ICON_WIDTH + 4 + digits * COUNTS_DIGIT_WIDTH
  const mid = (row: number): number => row * COUNTS_ROW_STEP + COUNTS_ROW_STEP / 2
  const dim = (value: number): string => (value === 0 ? ' ic-dim' : '')
  const text = (row: number, value: number): string => label(width, mid(row) + 4, `b end${value === 0 ? ' m' : ''}`, String(value))
  const check = `<path class="ico ic-ok${dim(counts.done)}" d="M2 ${roundTenth(mid(1))}L5.5 ${roundTenth(mid(1) + 3.5)}L11 ${roundTenth(mid(1) - 3.5)}"/>`
  const cross = `<path class="ico ic-bad${dim(counts.failed)}" d="M2.5 ${roundTenth(mid(2) - 3.5)}L10.5 ${roundTenth(mid(2) + 3.5)}M10.5 ${roundTenth(mid(2) - 3.5)}L2.5 ${roundTenth(mid(2) + 3.5)}"/>`
  const dot = `<circle class="ic-live${dim(counts.live)}" cx="6.5" cy="${roundTenth(mid(0))}" r="4"/>`

  return {
    markup: dot + text(0, counts.live) + check + text(1, counts.done) + cross + text(2, counts.failed),
    width,
    height: 3 * COUNTS_ROW_STEP,
  }
}

export const horizontalLine = (y: number, from: number, to: number): string => `<path class="ln" d="M${roundTenth(from)} ${roundTenth(y) + 0.5}H${roundTenth(to)}"/>`

export const pill = (box: { x: number; y: number; width: number; height: number }, tone: string, content: string): string => rect({ ...box, radius: box.height / 2 }, `pb-${tone}`) + label(box.x + box.width / 2, box.y + box.height / 2 + PILL_FONT_BASELINE, `mid b x pf-${tone}`, content, ' letter-spacing=".06em"')

export const statePill = (box: { x: number; y: number; width: number; height: number }, state: AgentState, word: string = STATE_WORD[state], tone: string = state): string => pill(box, tone, word)

type Run = { state: AgentState; left: number; right: number; isOpen: boolean }

const motionOverlay = (context: SvgContext, run: Run, shape: LaneShape): string => {
  const width = run.right - run.left
  const id = clipRect(context, { x: run.left, y: shape.y, width, height: shape.height, radius: shape.radius })

  if (run.state === 'tool') {
    return `<g clip-path="url(#${id})"><rect x="${roundTenth(run.left)}" y="${roundTenth(shape.y)}" width="${SHIMMER_WIDTH}" height="${roundTenth(shape.height)}" fill="url(#shg)" class="shim" style="--w:${roundTenth(width)}px"/></g>`
  }

  if (run.state === 'waiting') {
    return `<g clip-path="url(#${id})"><rect x="${roundTenth(run.left - 12)}" y="${roundTenth(shape.y)}" width="${roundTenth(width + 12)}" height="${roundTenth(shape.height)}" fill="url(#stp)" class="stripes"/></g>`
  }

  return ''
}

const runMarkup = (context: SvgContext, run: Run, shape: LaneShape): string => {
  const base = rect({ x: run.left, y: shape.y, width: run.right - run.left, height: shape.height }, `sg-${run.state}`)
  const body = base + (run.isOpen ? motionOverlay(context, run, shape) : '')

  return run.isOpen && run.state === 'thinking' ? `<g class="blink">${body}</g>` : body
}

const mergeRuns = (runs: readonly Run[]): Run[] => {
  const merged: Run[] = []

  for (const run of runs) {
    const last = merged.at(-1)

    if (last !== undefined && last.state === run.state) {
      merged[merged.length - 1] = { ...last, right: Math.max(last.right, run.right), isOpen: run.isOpen }
    } else {
      merged.push(run)
    }
  }

  return merged
}

const abut = (runs: readonly Run[]): Run[] =>
  runs.map((run, index) => {
    const next = runs[index + 1]

    return next === undefined ? run : { ...run, right: Math.max(run.left + MIN_SEGMENT_WIDTH, next.left) }
  })

export const driftOffset = (track: Track): number => (track.width * DRIFT_MS) / Math.max(1, track.window.end - track.window.start)

export const laneMarkup = (context: SvgContext, agent: AgentRow | undefined, track: Track, shape: LaneShape): string => {
  if (agent === undefined) {
    return ''
  }

  const span = Math.max(1, track.window.end - track.window.start)
  const scale = track.width / span
  const isAgentLive = isLive(agent.state)
  const reach = driftOffset(track) + 6
  const runs: Run[] = []

  for (const segment of agent.segments) {
    const isOpen = segment.to === null && isAgentLive
    const end = segment.to ?? (isAgentLive ? context.now : (agent.endedAt ?? context.now))
    const left = Math.max(-2, (segment.from - track.window.start) * scale)
    const right = isOpen ? track.width + reach : (end - track.window.start) * scale

    if (right < -2 || left > track.width + reach) {
      continue
    }

    const minimum = isLive(segment.state) ? MIN_SEGMENT_WIDTH : END_CAP_WIDTH
    runs.push({ state: segment.state, left: track.x + left, right: track.x + left + Math.max(minimum, right - left), isOpen })
  }

  const joined = abut(mergeRuns(runs))
  const first = joined[0]
  const last = joined.at(-1)

  if (first === undefined || last === undefined) {
    return ''
  }

  const id = clipRect(context, { x: first.left, y: shape.y, width: last.right - first.left, height: shape.height, radius: shape.radius })

  return `<g clip-path="url(#${id})">${joined.map(run => runMarkup(context, run, shape)).join('')}</g>`
}

export const driftGroup = (context: SvgContext, box: { x: number; y: number; width: number; height: number }, track: Track, content: string): string => {
  const id = clipRect(context, box)

  return `<g clip-path="url(#${id})"><g class="drift" style="--dx:${roundTenth(-driftOffset(track))}px">${content}</g></g>`
}

export const nowMarker = (box: { x: number; y: number; height: number }): string => `<path class="nowl" d="M${roundTenth(box.x) + 0.5} ${roundTenth(box.y)}V${roundTenth(box.y + box.height)}"/>`
