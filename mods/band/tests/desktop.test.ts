import { expect, test } from 'claude-code/testing'

import type { AgentRow } from '../types'

import { MODEL_PRICES, estimateCostUsd, formatUsd } from '../hooks/cost'
import { EMPTY_GAUGES, limitNameOf, namedLimitsOf, withUsage } from '../hooks/gauges'
import { bandRefreshMs, timelineWindowOf } from '../hooks/desktop'
import { EMPTY_ROSTER, EMPTY_STORE, MAIN_ID, recordTurnUsage } from '../hooks/model'

const NOW = 100_000_000
const MINUTE = 60_000
const HOUR = 3_600_000

const micros = (usd: number | null): number | null => (usd === null ? null : Math.round(usd * 1e6) / 1e6)

const CONTEXT = { window: 200_000, tokens: 1000, percent: 1 }

test('limits map known kinds to names, show an unknown kind as its own readable bar, and none gives none', () => {
  const limits = namedLimitsOf([
    { kind: 'five_hour', percentUsed: 35, resetsAt: '1970-01-01T02:00:00Z' },
    { kind: 'seven_day', percentUsed: 52 },
    { kind: 'fable_weekly', percentUsed: 19 },
    { kind: 'spend_limit', percentUsed: 5, resetsAt: 'not a date' },
  ])

  expect(limits.map(limit => limit.name)).toEqual(['Session', 'Week', 'Fable weekly', 'Spend limit'])
  expect(limits.map(limit => limit.percent)).toEqual([35, 52, 19, 5])
  expect(limits.map(limit => limit.resetsAt)).toEqual([7_200_000, null, null, null])
  expect(namedLimitsOf([])).toEqual([])
  expect(limitNameOf('five_hour')).toBe('Session')
  expect(limitNameOf('fable')).toBe('Fable')
  expect(limitNameOf('___')).toBe('___')
})

test('usage with limits fills every limit and the cost, and usage with none leaves them empty and not a subscription', () => {
  const some = withUsage(EMPTY_GAUGES, { context: CONTEXT, rateLimits: [{ kind: 'fable_weekly', percentUsed: 19 }], cost: { usd: 3.84 } })
  const none = withUsage(some, { context: CONTEXT, rateLimits: [] })

  expect(some.limits).toHaveLength(1)
  expect(some.costUsd).toBe(3.84)
  expect(some.isSubscription).toBe(true)
  expect(some.fiveHour).toBeNull()
  expect(none.limits).toEqual([])
  expect(none.costUsd).toBe(3.84)
  expect(none.isSubscription).toBe(false)
})

test('an agent cost is tokens times the price of its model, and a model not in the table has none', () => {
  const usage = { input: 1_000_000, output: 100_000, cacheRead: 2_000_000, cacheWrite: 1_000_000 }

  expect(micros(estimateCostUsd({ input: 1_000_000, output: 2_000_000, cacheRead: 0, cacheWrite: 0 }, 'claude-sonnet-4-5'))).toBe(33)
  expect(micros(estimateCostUsd(usage, 'claude-opus-4-1'))).toBe(5 + 2.5 + 2 * 0.5 + 6.25)
  expect(micros(estimateCostUsd(usage, 'claude-haiku-4-5'))).toBe(1 + 0.5 + 2 * 0.1 + 1.25)
  expect(estimateCostUsd(usage, 'fable-1')).toBeNull()
  expect(estimateCostUsd(usage, undefined)).toBeNull()
  expect(MODEL_PRICES.map(entry => entry.family)).toEqual(['opus', 'sonnet', 'haiku'])
  expect(formatUsd(0.004)).toBe('<$0.01')
  expect(formatUsd(0)).toBe('$0.00')
  expect(formatUsd(3.835)).toBe('$3.83')
})

test('turn usage adds up per agent and for the main session, and keeps the latest model', () => {
  const tokens = { input_tokens: 10, output_tokens: 2, cache_read_input_tokens: 5, cache_creation_input_tokens: 1 }
  const withAgent = { ...EMPTY_STORE, rows: [{ id: 'a1' } as AgentRow] }
  const first = recordTurnUsage(withAgent, { id: 'a1', tokens, model: 'sonnet', now: NOW })
  const second = recordTurnUsage(first, { id: 'a1', tokens, model: 'sonnet', now: NOW })
  const main = recordTurnUsage(EMPTY_STORE, { id: MAIN_ID, tokens, model: 'opus', now: NOW })

  expect(second.rows[0]?.usage).toEqual({ input: 20, output: 4, cacheRead: 10, cacheWrite: 2 })
  expect(second.rows[0]?.model).toBe('sonnet')
  expect(main.main?.usage).toEqual({ input: 10, output: 2, cacheRead: 5, cacheWrite: 1 })
})

test('the window follows the range: 1m, 5m, 1h end now, and session starts at the session start', () => {
  const rows: AgentRow[] = []

  expect(timelineWindowOf({ range: '1m', now: NOW, sessionStartedAt: NOW - 3 * HOUR, rows })).toEqual({ start: NOW - MINUTE, end: NOW })
  expect(timelineWindowOf({ range: '5m', now: NOW, sessionStartedAt: null, rows })).toEqual({ start: NOW - 5 * MINUTE, end: NOW })
  expect(timelineWindowOf({ range: '1h', now: NOW, sessionStartedAt: null, rows })).toEqual({ start: NOW - HOUR, end: NOW })
  expect(timelineWindowOf({ range: 'session', now: NOW, sessionStartedAt: NOW - 3 * HOUR, rows })).toEqual({ start: NOW - 3 * HOUR, end: NOW })
  expect(timelineWindowOf({ range: 'session', now: NOW, sessionStartedAt: NOW - 5_000, rows })).toEqual({ start: NOW - MINUTE, end: NOW })
})

test('the band refreshes every 5 s while anything is live and not at all when idle and empty', () => {
  const base = { rows: new Map<string, AgentRow>(), roster: EMPTY_ROSTER, range: '1m' as const, now: NOW, isFolded: false, isWorking: false }
  const live = { ...base, roster: { ...base.roster, rows: [{ id: 'a', label: 'a', group: 'direct', groupLabel: 'direct', phase: 'live' as const }] } }

  expect(bandRefreshMs(base)).toBeNull()
  expect(bandRefreshMs({ ...base, isWorking: true })).toBe(5000)
  expect(bandRefreshMs(live)).toBe(5000)
})
