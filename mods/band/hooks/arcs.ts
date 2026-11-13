import type { Gauges, NamedLimit } from '../types'

import type { ArcId, Tone } from './desktop-theme'
import { formatTokens } from './format'

export const HIGH_PERCENT = 80
export const CRITICAL_PERCENT = 95
const ONE_DAY_MS = 86_400_000

export type Arc = { id: ArcId; name: string; short: string; percent: number; resetsAt: number | null; usage: string | null }

export const toneOfPercent = (percent: number): Tone => (percent >= CRITICAL_PERCENT ? 'fail' : percent >= HIGH_PERCENT ? 'warn' : 'ink')

export const isWarning = (percent: number): boolean => percent >= HIGH_PERCENT

const limitArc = (limit: NamedLimit | undefined, spec: { id: ArcId; name: string; short: string }): Arc[] => (limit === undefined ? [] : [{ ...spec, percent: limit.percent, resetsAt: limit.resetsAt, usage: null }])

const contextUsageOf = (gauges: Gauges): string | null => (gauges.contextTokens !== null && gauges.contextWindow !== null ? formatTokens(gauges.contextTokens) + ' of ' + formatTokens(gauges.contextWindow) : null)

const contextArc = (gauges: Gauges): Arc[] => (gauges.contextPercent === null ? [] : [{ id: 'context', name: 'Context', short: 'Ctx', percent: gauges.contextPercent, resetsAt: null, usage: contextUsageOf(gauges) }])

export const arcsOf = (gauges: Gauges): Arc[] => [
  ...limitArc(gauges.limits.find(limit => limit.kind === 'five_hour'), { id: 'fiveHour', name: '5-hour', short: '5h' }),
  ...limitArc(gauges.limits.find(limit => limit.kind === 'seven_day'), { id: 'week', name: 'Week', short: 'Wk' }),
  ...limitArc(gauges.limits.find(limit => limit.kind.toLowerCase().includes('fable')), { id: 'fable', name: 'Fable', short: 'Fable' }),
  ...contextArc(gauges),
]

export const resetClockOf = (resetsAt: number, now: number): string => {
  const date = new Date(resetsAt)
  const time = date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
  const day = resetsAt - now >= ONE_DAY_MS ? date.toLocaleDateString('en-US', { weekday: 'short' }) + ' ' : ''

  return day + time
}

export const legendColumnsOf = (arcs: readonly Arc[]): [Arc[], Arc[]] => [arcs.filter((_, index) => index % 2 === 0), arcs.filter((_, index) => index % 2 === 1)]

export const apiBillingText = (tokensIn: number, tokensOut: number): string => 'API billing · ' + formatTokens(tokensIn) + ' in / ' + formatTokens(tokensOut) + ' out'
