import type { AgentRow, AgentState } from '../types'

import { DRIFT_MS } from './svg-theme'
import { STATE_WORD, type Window, isLive } from './model'

export type Ctx = { defs: string[]; counter: number; now: number }

export type Track = { x: number; width: number; window: Window }

export type LaneShape = { y: number; height: number; radius: number }

const ENTITIES: Readonly<Record<string, string>> = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }

const CHAR_WIDTH_EM = 0.56
const SHIMMER_WIDTH = 40
const MIN_SEGMENT_WIDTH = 2
const END_CAP_WIDTH = 4
const RUN_GAP = 2
const PILL_FONT_BASELINE = 3.2

export const escapeText = (text: string): string =>
  text.replace(/[&<>"']/g, character => ENTITIES[character] ?? character).replace(/[\u0000-\u001f]/g, ' ')

export const num = (value: number): number => Math.round(value * 10) / 10

export const fit = (text: string, width: number, size: number): string => {
  const chars = Math.max(0, Math.floor(width / (size * CHAR_WIDTH_EM)))

  if (text.length <= chars) {
    return text
  }

  return chars <= 1 ? '' : `${text.slice(0, chars - 1)}…`
}

export const nextId = (ctx: Ctx, prefix: string): string => {
  ctx.counter += 1

  return `${prefix}${ctx.counter}`
}

export const clipRect = (ctx: Ctx, box: { x: number; y: number; width: number; height: number; radius?: number }): string => {
  const id = nextId(ctx, 'c')
  const radius = box.radius === undefined ? '' : ` rx="${box.radius}"`
  ctx.defs.push(
    `<clipPath id="${id}"><rect x="${num(box.x)}" y="${num(box.y)}" width="${num(box.width)}" height="${num(box.height)}"${radius}/></clipPath>`,
  )

  return id
}

export const rect = (box: { x: number; y: number; width: number; height: number; radius?: number }, cls: string, extra = ''): string => {
  const radius = box.radius === undefined ? '' : ` rx="${box.radius}"`

  return `<rect x="${num(box.x)}" y="${num(box.y)}" width="${num(box.width)}" height="${num(box.height)}"${radius} class="${cls}"${extra}/>`
}

export const label = (x: number, y: number, cls: string, content: string, extra = ''): string =>
  `<text x="${num(x)}" y="${num(y)}" class="${cls}"${extra}>${escapeText(content)}</text>`

export const horizontalLine = (y: number, from: number, to: number): string =>
  `<path class="ln" d="M${num(from)} ${num(y) + 0.5}H${num(to)}"/>`

export const verticalLine = (x: number, from: number, to: number): string =>
  `<path class="ln" d="M${num(x) + 0.5} ${num(from)}V${num(to)}"/>`

export const pill = (box: { x: number; y: number; width: number; height: number }, tone: string, content: string): string =>
  rect({ ...box, radius: box.height / 2 }, `pb-${tone}`) +
  label(box.x + box.width / 2, box.y + box.height / 2 + PILL_FONT_BASELINE, `mid b x pf-${tone}`, content, ' letter-spacing=".06em"')

export const statePill = (
  box: { x: number; y: number; width: number; height: number },
  state: AgentState,
  word: string = STATE_WORD[state],
  tone: string = state,
): string => pill(box, tone, word)

type Run = { state: AgentState; left: number; right: number; isOpen: boolean }

const motionOverlay = (ctx: Ctx, run: Run, shape: LaneShape): string => {
  const width = run.right - run.left
  const id = clipRect(ctx, { x: run.left, y: shape.y, width, height: shape.height, radius: shape.radius })

  if (run.state === 'tool') {
    return `<g clip-path="url(#${id})"><rect x="${num(run.left)}" y="${num(shape.y)}" width="${SHIMMER_WIDTH}" height="${num(shape.height)}" fill="url(#shg)" class="shim" style="--w:${num(width)}px"/></g>`
  }

  if (run.state === 'waiting') {
    return `<g clip-path="url(#${id})"><rect x="${num(run.left - 12)}" y="${num(shape.y)}" width="${num(width + 12)}" height="${num(shape.height)}" fill="url(#stp)" class="stripes"/></g>`
  }

  return ''
}

const runMarkup = (ctx: Ctx, run: Run, shape: LaneShape): string => {
  const base = rect({ x: run.left, y: shape.y, width: run.right - run.left, height: shape.height, radius: shape.radius }, `sg-${run.state}`)
  const body = base + (run.isOpen ? motionOverlay(ctx, run, shape) : '')

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

const separate = (runs: readonly Run[]): Run[] =>
  runs.map((run, index) => ({
    ...run,
    left: index > 0 ? run.left + RUN_GAP / 2 : run.left,
    right: index < runs.length - 1 ? Math.max(run.left + MIN_SEGMENT_WIDTH, run.right - RUN_GAP / 2) : run.right,
  }))

export const driftOffset = (track: Track): number => (track.width * DRIFT_MS) / Math.max(1, track.window.end - track.window.start)

export const laneMarkup = (ctx: Ctx, agent: AgentRow | undefined, track: Track, shape: LaneShape): string => {
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
    const end = segment.to ?? (isAgentLive ? ctx.now : (agent.endedAt ?? ctx.now))
    const left = Math.max(-2, (segment.from - track.window.start) * scale)
    const right = isOpen ? track.width + reach : (end - track.window.start) * scale

    if (right < -2 || left > track.width + reach) {
      continue
    }

    const minimum = isLive(segment.state) ? MIN_SEGMENT_WIDTH : END_CAP_WIDTH
    runs.push({ state: segment.state, left: track.x + left, right: track.x + left + Math.max(minimum, right - left), isOpen })
  }

  return separate(mergeRuns(runs))
    .map(run => runMarkup(ctx, run, shape))
    .join('')
}

export const driftGroup = (ctx: Ctx, box: { x: number; y: number; width: number; height: number }, track: Track, content: string): string => {
  const id = clipRect(ctx, box)

  return `<g clip-path="url(#${id})"><g class="drift" style="--dx:${num(-driftOffset(track))}px">${content}</g></g>`
}

export const nowMarker = (box: { x: number; y: number; height: number }): string =>
  `<path class="nowl" d="M${num(box.x) + 0.5} ${num(box.y)}V${num(box.y + box.height)}"/>`
