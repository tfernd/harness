import type { Gauges, NamedLimit } from '../types'

import type { ArcId, Tone } from './desktop-theme'
import { formatTokens } from './format'

export const HIGH_PERCENT = 80
export const CRITICAL_PERCENT = 95
const ONE_DAY_MS = 86_400_000
const ONE_HOUR_MS = 3_600_000
const ONE_MINUTE_MS = 60_000
const FIVE_HOUR_KIND = 'five_hour'
const WEEK_KIND = 'seven_day'

export type Arc = { id: ArcId; key: string; name: string; short: string; percent: number; resetsAt: number | null; usage: string | null }

export const toneOfPercent = (percent: number): Tone => (percent >= CRITICAL_PERCENT ? 'fail' : percent >= HIGH_PERCENT ? 'warn' : 'ink')

export const isWarning = (percent: number): boolean => percent >= HIGH_PERCENT

export const percentTextOf = (percent: number): string => Math.round(percent) + '%' + (isWarning(percent) ? ' ▲' : '')

const limitArc = (limit: NamedLimit | undefined, spec: { id: ArcId; name: string; short: string }): Arc[] => (limit === undefined ? [] : [{ ...spec, key: spec.id, percent: limit.percent, resetsAt: limit.resetsAt, usage: null }])

const isFableKind = (kind: string): boolean => kind.toLowerCase().includes('fable')

const isKnownKind = (kind: string): boolean => kind === FIVE_HOUR_KIND || kind === WEEK_KIND || isFableKind(kind)

export const otherLimitShortOf = (kind: string): string => {
  const words = kind.split(/[^A-Za-z0-9]+/).filter(word => word !== '' && word !== 'seven' && word !== 'day' && word !== 'limit')
  const text = words.length === 0 ? kind : words.join(' ')

  return text.charAt(0).toUpperCase() + text.slice(1)
}

const otherArcs = (limits: readonly NamedLimit[]): Arc[] =>
  limits.filter(limit => !isKnownKind(limit.kind)).map(limit => ({ id: 'other', key: 'other-' + limit.kind, name: limit.name, short: otherLimitShortOf(limit.kind), percent: limit.percent, resetsAt: limit.resetsAt, usage: null }))

const contextUsageOf = (gauges: Gauges): string | null => (gauges.contextTokens !== null && gauges.contextWindow !== null ? formatTokens(gauges.contextTokens) + ' of ' + formatTokens(gauges.contextWindow) : null)

const contextArc = (gauges: Gauges): Arc[] => (gauges.contextPercent === null ? [] : [{ id: 'context', key: 'context', name: 'Context', short: 'Ctx', percent: gauges.contextPercent, resetsAt: null, usage: contextUsageOf(gauges) }])

export const arcsOf = (gauges: Gauges): Arc[] => [
  ...limitArc(gauges.limits.find(limit => limit.kind === FIVE_HOUR_KIND), { id: 'fiveHour', name: '5-hour', short: '5h' }),
  ...limitArc(gauges.limits.find(limit => limit.kind === WEEK_KIND), { id: 'week', name: 'Week', short: 'Wk' }),
  ...limitArc(gauges.limits.find(limit => isFableKind(limit.kind)), { id: 'fable', name: 'Fable', short: 'Fable' }),
  ...otherArcs(gauges.limits),
  ...contextArc(gauges),
]

export const resetExactOf = (resetsAt: number, now: number): string => {
  const date = new Date(resetsAt)
  const time = date.toLocaleTimeString('en-GB', { hourCycle: 'h23', hour: '2-digit', minute: '2-digit' })
  const day = resetsAt - now >= ONE_DAY_MS ? date.toLocaleDateString('en-US', { weekday: 'short' }) + ' ' : ''

  return day + time
}

export const resetInOf = (resetsAt: number, now: number): string => {
  const remaining = resetsAt - now

  if (remaining < ONE_MINUTE_MS) {
    return remaining <= 0 ? 'now' : 'in <1m'
  }

  const days = Math.floor(remaining / ONE_DAY_MS)
  const hours = Math.floor((remaining % ONE_DAY_MS) / ONE_HOUR_MS)
  const minutes = Math.floor((remaining % ONE_HOUR_MS) / ONE_MINUTE_MS)

  if (days > 0) {
    return 'in ' + days + 'd ' + hours + 'h'
  }

  return hours > 0 ? 'in ' + hours + 'h ' + minutes + 'm' : 'in ' + minutes + 'm'
}

export const legendColumnsOf = (arcs: readonly Arc[]): [Arc[], Arc[]] => [arcs.filter((_, index) => index % 2 === 0), arcs.filter((_, index) => index % 2 === 1)]

export const apiBillingText = (tokensIn: number, tokensOut: number): string => (tokensIn === 0 && tokensOut === 0 ? 'API billing' : 'API billing · ' + formatTokens(tokensIn) + ' in / ' + formatTokens(tokensOut) + ' out')
