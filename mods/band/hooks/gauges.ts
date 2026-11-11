import type { SessionContextUsage, SessionRateLimit, TurnUsage } from 'claude-code'

import type { Gauges, Limit } from '../types'

export const EMPTY_GAUGES: Gauges = {
  contextPercent: null,
  contextTokens: null,
  contextWindow: null,
  compactedFrom: null,
  cachePercent: null,
  fiveHour: null,
  sevenDay: null,
  sessionStartedAt: null,
  lastCallAt: null,
  isSubscription: false,
}

export const CACHE_TTL_MS = { '5m': 300_000, '1h': 3_600_000 } as const
export const CACHE_URGENT_MS = 120_000
export const CACHE_FAST_REFRESH_BELOW_MS = 300_000
export const CACHE_REFRESH_FAST_MS = 15_000
export const CACHE_REFRESH_SLOW_MS = 60_000

const limitOf = (limits: readonly SessionRateLimit[], kind: string): Limit | null => {
  const found = limits.find(limit => limit.kind === kind)

  if (found === undefined) {
    return null
  }

  const resetsAt = found.resetsAt === undefined ? Number.NaN : Date.parse(found.resetsAt)

  return { percent: found.percentUsed, resetsAt: Number.isNaN(resetsAt) ? null : resetsAt }
}

export const withUsage = (gauges: Gauges, usage: { context: SessionContextUsage; rateLimits: readonly SessionRateLimit[]; startedAt?: number }): Gauges => ({
  ...gauges,
  contextPercent: usage.context.percent ?? null,
  contextTokens: usage.context.tokens ?? null,
  contextWindow: usage.context.window,
  fiveHour: limitOf(usage.rateLimits, 'five_hour'),
  sevenDay: limitOf(usage.rateLimits, 'seven_day'),
  sessionStartedAt: usage.startedAt ?? gauges.sessionStartedAt,
  isSubscription: usage.rateLimits.length > 0,
})

export const withCache = (gauges: Gauges, usage: TurnUsage, now: number): Gauges => {
  const total = usage.input_tokens + usage.cache_read_input_tokens + usage.cache_creation_input_tokens

  return total === 0 ? gauges : { ...gauges, lastCallAt: now, cachePercent: Math.round((100 * usage.cache_read_input_tokens) / total) }
}

export const withCompaction = (gauges: Gauges, tokensBefore: number | undefined): Gauges => ({
  ...gauges,
  compactedFrom: tokensBefore ?? gauges.compactedFrom,
})

export const isSameGauges = (left: Gauges, right: Gauges): boolean => JSON.stringify(left) === JSON.stringify(right)

export type CacheClock = {
  text: string
  detail: string
  isCold: boolean
  isUrgent: boolean
  remainingMs: number
  tip: string
}

export const cacheTtlOf = (gauges: Gauges): keyof typeof CACHE_TTL_MS => (gauges.isSubscription ? '1h' : '5m')

export const cacheClockOf = (gauges: Gauges, now: number): CacheClock | null => {
  if (gauges.lastCallAt === null) {
    return null
  }

  const ttl = cacheTtlOf(gauges)
  const remainingMs = gauges.lastCallAt + CACHE_TTL_MS[ttl] - now
  const isCold = remainingMs <= 0
  const text = isCold ? 'cold' : `~${Math.ceil(remainingMs / 60_000)}m`
  const source = gauges.isSubscription ? 'subscription limits present, so 1h assumed' : 'no subscription limits, so 5m assumed'
  const calledAt = new Date(gauges.lastCallAt).toTimeString().slice(0, 8)

  return {
    text,
    detail: isCold ? 'cold' : `warm ${text}`,
    isCold,
    isUrgent: remainingMs < CACHE_URGENT_MS,
    remainingMs,
    tip: `Prompt cache ${isCold ? 'is cold' : `cold in ${text}`}. Last main-thread call ${calledAt}; TTL ${ttl} (${source}; an estimate).`,
  }
}

export const cacheRefreshMs = (gauges: Gauges, now: number): number | null => {
  const clock = cacheClockOf(gauges, now)

  if (clock === null || clock.isCold) {
    return null
  }

  return clock.remainingMs < CACHE_FAST_REFRESH_BELOW_MS ? CACHE_REFRESH_FAST_MS : CACHE_REFRESH_SLOW_MS
}
