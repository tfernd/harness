import type { BandSvg, PieceSpec, SvgInput } from './svg-band'
import { piecesOf } from './svg-band'

export const MIN_REBUILD_MS = 100

export type PieceCache = { signature: string; interaction: string; builtAt: number; svg: BandSvg }

export type PieceChoice = { cache: PieceCache; retryInMs: number | null; isBuilt: boolean }

export type BandChoice = {
  caches: Map<string, PieceCache>
  svgs: Map<string, BandSvg>
  retryInMs: number | null
  builtKeys: string[]
}

const build = (spec: PieceSpec, now: number): PieceCache => ({
  signature: spec.signature,
  interaction: spec.interaction,
  builtAt: now,
  svg: spec.build(),
})

export const choosePiece = (cache: PieceCache | null, spec: PieceSpec, now: number): PieceChoice => {
  if (cache === null) {
    return { cache: build(spec, now), retryInMs: null, isBuilt: true }
  }

  const age = now - cache.builtAt
  const isStale = spec.maxAgeMs !== null && age >= spec.maxAgeMs

  if (cache.signature === spec.signature && !isStale) {
    return { cache, retryInMs: null, isBuilt: false }
  }

  if (!isStale && cache.interaction === spec.interaction && age < MIN_REBUILD_MS) {
    return { cache, retryInMs: MIN_REBUILD_MS - age, isBuilt: false }
  }

  return { cache: build(spec, now), retryInMs: null, isBuilt: true }
}

export const chooseBand = (caches: ReadonlyMap<string, PieceCache>, input: SvgInput): BandChoice => {
  const choice: BandChoice = { caches: new Map(), svgs: new Map(), retryInMs: null, builtKeys: [] }

  for (const spec of piecesOf(input)) {
    const piece = choosePiece(caches.get(spec.key) ?? null, spec, input.now)
    choice.caches.set(spec.key, piece.cache)
    choice.svgs.set(spec.key, piece.cache.svg)

    if (piece.isBuilt) {
      choice.builtKeys.push(spec.key)
    }

    if (piece.retryInMs !== null) {
      choice.retryInMs = Math.min(choice.retryInMs ?? piece.retryInMs, piece.retryInMs)
    }
  }

  return choice
}
