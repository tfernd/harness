import { expect, test } from 'claude-code/testing'

import type { AgentStore } from '../types'

import { MAX_AGENTS, MAX_SEGMENTS, addAgent, countAgents, EMPTY_STORE, formatClock, moveAgent, newAgent, rosterOf, stateFromStatus } from '../hooks/model'
import { paintTextRows } from '../hooks/paint'
import { CLOCK_COLUMNS } from '../hooks/view'

const agentNamed = (id: string, now: number) =>
  newAgent({ id, label: id, group: 'direct', groupLabel: 'direct agents', now })

const textOf = (spans: Parameters<typeof paintTextRows>[0], columns: number): string => {
  const grid = paintTextRows(spans, columns, 'left')

  return Array.from({ length: columns }, (_, column) => String.fromCodePoint(grid.words[column * 3] ?? 0x20)).join('')
}

test('a thousand tool calls keep the segments bounded and contiguous', () => {
  let store: AgentStore = addAgent(EMPTY_STORE, agentNamed('a', 0))

  for (let call = 0; call < 1000; call += 1) {
    store = moveAgent(store, { id: 'a', state: 'tool', command: `c${call}`, now: call * 1000 + 1 })
    store = moveAgent(store, { id: 'a', state: 'thinking', command: null, now: call * 1000 + 500 })
  }

  const segments = store.rows[0]?.segments ?? []

  expect(segments.length).toBeLessThanOrEqual(MAX_SEGMENTS)
  expect(segments.length).toBeGreaterThan(MAX_SEGMENTS / 2)
  expect(segments[0]?.from).toBe(0)
  expect(segments.at(-1)?.state).toBe('thinking')
  expect(segments.at(-1)?.to).toBeNull()
  segments.slice(1).forEach((segment, index) => expect(segment.from).toBe(segments[index]?.to))
})

test('eviction drops ended agents first, never a live one, and the total keeps counting', () => {
  let store: AgentStore = EMPTY_STORE

  for (let index = 0; index < 3; index += 1) {
    store = addAgent(store, agentNamed(`live${index}`, 0))
  }

  for (let index = 0; index < MAX_AGENTS + 2; index += 1) {
    store = addAgent(store, agentNamed(`end${index}`, 1))
    store = moveAgent(store, { id: `end${index}`, state: index % 2 === 0 ? 'done' : 'failed', command: null, now: 2 })
  }

  const counts = countAgents(rosterOf(store).rows, { done: store.evictedDone, failed: store.evictedFailed })

  expect(store.rows.length).toBe(MAX_AGENTS)
  expect(['live0', 'live1', 'live2'].every(id => store.rows.some(row => row.id === id))).toBe(true)
  expect(counts.live).toBe(3)
  expect(counts.total).toBe(MAX_AGENTS + 5)
  expect(counts.done + counts.failed + counts.live).toBe(MAX_AGENTS + 5)
  expect(store.evictedDone + store.evictedFailed).toBe(5)

  let crowded: AgentStore = EMPTY_STORE

  for (let index = 0; index < MAX_AGENTS + 3; index += 1) {
    crowded = addAgent(crowded, agentNamed(`live${index}`, 0))
  }

  expect(crowded.rows.length).toBe(MAX_AGENTS + 3)
})

test('an agent never announced by a spawn gets no row, and a tool end does not revive an ended one', () => {
  const store = addAgent(EMPTY_STORE, agentNamed('a', 0))
  const ended = moveAgent(store, { id: 'a', state: 'failed', command: null, now: 5 })

  expect(moveAgent(store, { id: 'fork', state: 'tool', command: 'ls', now: 1 })).toBe(store)
  expect(moveAgent(ended, { id: 'a', state: 'thinking', command: null, now: 6, from: 'tool' })).toBe(ended)
  expect(stateFromStatus('running', 'done')).toBe('done')
  expect(stateFromStatus('waiting', 'failed')).toBe('failed')
  expect(stateFromStatus('running', 'launched')).toBe('thinking')
})

test('the clock raster holds the longest turn text whole', () => {
  const longest = `turn ${formatClock(10 * 3_600_000)}`

  expect(textOf([{ text: 'turn 10:00', color: null }], CLOCK_COLUMNS).trimEnd()).toBe('turn 10:00')
  expect(textOf([{ text: longest, color: null }], CLOCK_COLUMNS).trimEnd()).toBe(longest)
})
