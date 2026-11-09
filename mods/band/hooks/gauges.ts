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
}

const limitOf = (limits: readonly SessionRateLimit[], kind: string): Limit | null => {
  const found = limits.find(limit => limit.kind === kind)

  if (found === undefined) {
    return null
  }

  const resetsAt = found.resetsAt === undefined ? Number.NaN : Date.parse(found.resetsAt)

  return { percent: found.percentUsed, resetsAt: Number.isNaN(resetsAt) ? null : resetsAt }
}

export const withUsage = (
  gauges: Gauges,
  usage: { context: SessionContextUsage; rateLimits: readonly SessionRateLimit[]; startedAt?: number },
): Gauges => ({
  ...gauges,
  contextPercent: usage.context.percent ?? null,
  contextTokens: usage.context.tokens ?? null,
  contextWindow: usage.context.window,
  fiveHour: limitOf(usage.rateLimits, 'five_hour'),
  sevenDay: limitOf(usage.rateLimits, 'seven_day'),
  sessionStartedAt: usage.startedAt ?? gauges.sessionStartedAt,
})

export const withCache = (gauges: Gauges, usage: TurnUsage): Gauges => {
  const total = usage.input_tokens + usage.cache_read_input_tokens + usage.cache_creation_input_tokens

  return total === 0 ? gauges : { ...gauges, cachePercent: Math.round((100 * usage.cache_read_input_tokens) / total) }
}

export const withCompaction = (gauges: Gauges, tokensBefore: number | undefined): Gauges => ({
  ...gauges,
  compactedFrom: tokensBefore ?? gauges.compactedFrom,
})

export const isSameGauges = (left: Gauges, right: Gauges): boolean => JSON.stringify(left) === JSON.stringify(right)
