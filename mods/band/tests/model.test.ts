import { expect, test } from 'claude-code/testing'

import type { AgentStore } from '../types'

import { LINGER_MS, MAX_AGENTS, MAX_SEGMENTS, addAgent, nextLeaveMs, tracedRows, moveMain, countAgents, orderAgents, splitByWindow, EMPTY_STORE, formatClock, moveAgent, newAgent, rosterOf, stateFromStatus, closeOpen, finishAgent } from '../hooks/model'
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
    store = addAgent(store, agentNamed(`end${index}`, index * LINGER_MS))
    store = moveAgent(store, { id: `end${index}`, state: index % 2 === 0 ? 'done' : 'failed', command: null, now: index * LINGER_MS + 1 })
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

test('the main row keeps a thinking span, a tool span with its command, an open idle span while idle, and stays bounded', () => {
  let store: AgentStore = moveMain(EMPTY_STORE, { activity: { state: 'thinking', command: null }, now: 10 })
  store = moveMain(store, { activity: { state: 'tool', command: 'make check' }, now: 20 })
  const inTool = store.main
  store = moveMain(store, { activity: { state: 'thinking', command: null }, now: 30, from: 'tool' })
  store = moveMain(store, { activity: null, now: 40 })

  expect(inTool?.command).toBe('make check')
  expect(store.main?.segments).toEqual([
    { state: 'thinking', from: 10, to: 20 },
    { state: 'tool', from: 20, to: 30 },
    { state: 'thinking', from: 30, to: 40 },
    { state: 'launched', from: 40, to: null },
  ])
  expect(store.main?.state).toBe('launched')
  expect(moveMain(store, { activity: null, now: 50 })).toBe(store)
  expect(moveMain(EMPTY_STORE, { activity: null, now: 1 })).toBe(EMPTY_STORE)

  for (let turn = 0; turn < MAX_SEGMENTS; turn += 1) {
    store = moveMain(store, { activity: { state: 'thinking', command: null }, now: 100 + turn * 10 })
    store = moveMain(store, { activity: { state: 'tool', command: `c${turn}` }, now: 105 + turn * 10 })
    store = moveMain(store, { activity: null, now: 108 + turn * 10 })
  }

  expect(store.main?.segments.length).toBeLessThanOrEqual(MAX_SEGMENTS)
})

test('inside a group live agents come first by start, then ended ones by latest end, before the window split', () => {
  let store: AgentStore = EMPTY_STORE

  for (const [id, start] of [['a', 10], ['b', 20], ['c', 30], ['d', 40]] as const) {
    store = addAgent(store, agentNamed(id, start))
  }

  store = moveAgent(store, { id: 'a', state: 'done', command: null, now: 100 })
  store = moveAgent(store, { id: 'c', state: 'failed', command: null, now: LINGER_MS + 200 })
  const rows = new Map(store.rows.map(row => [row.id, row]))
  const roster = rosterOf(store).rows

  expect(orderAgents(roster, rows).map(agent => agent.id)).toEqual(['b', 'd', 'c', 'a'])
  expect(splitByWindow(roster, rows, LINGER_MS + 150).shown.map(agent => agent.id)).toEqual(['b', 'd', 'c'])
})

const ENDED_AT = 1000
const JUST_INSIDE_LINGER_MS = 4900
const JUST_PAST_LINGER_MS = 5100

const fullStoreWithOneEnded = (): AgentStore => {
  let store: AgentStore = addAgent(EMPTY_STORE, agentNamed('old', 0))
  store = moveAgent(store, { id: 'old', state: 'done', command: null, now: ENDED_AT })

  for (let index = 0; index < MAX_AGENTS - 1; index += 1) {
    store = addAgent(store, agentNamed(`live${index}`, 0))
  }

  return store
}

test('an ended agent past the row cap stays 4.9 s and is evicted at 5.1 s, with the counts the same', () => {
  const full = fullStoreWithOneEnded()
  const early = addAgent(full, agentNamed('late', ENDED_AT + JUST_INSIDE_LINGER_MS))
  const late = addAgent(full, agentNamed('late', ENDED_AT + JUST_PAST_LINGER_MS))
  const countsOf = (store: AgentStore) => countAgents(rosterOf(store).rows, { done: store.evictedDone, failed: store.evictedFailed })

  expect(early.rows.some(row => row.id === 'old')).toBe(true)
  expect(early.rows.length).toBe(MAX_AGENTS + 1)
  expect(late.rows.some(row => row.id === 'old')).toBe(false)
  expect(late.rows.length).toBe(MAX_AGENTS)
  expect(late.evictedDone).toBe(1)
  expect(countsOf(early)).toEqual(countsOf(late))
})

test('a row 4.9 s past the window edge is still shown and one 5.1 s past is not, the earlier count follows', () => {
  const windowStart = 100_000
  const rowsAt = (endedAt: number) => {
    const store = moveAgent(addAgent(EMPTY_STORE, agentNamed('a', 0)), { id: 'a', state: 'done', command: null, now: endedAt })

    return { store, rows: new Map(store.rows.map(row => [row.id, row])) }
  }
  const inside = rowsAt(windowStart - JUST_INSIDE_LINGER_MS)
  const past = rowsAt(windowStart - JUST_PAST_LINGER_MS)
  const insideSplit = splitByWindow(rosterOf(inside.store).rows, inside.rows, windowStart)
  const pastSplit = splitByWindow(rosterOf(past.store).rows, past.rows, windowStart)

  expect(insideSplit.shown.map(row => row.id)).toEqual(['a'])
  expect(insideSplit.earlier).toBe(0)
  expect(pastSplit.shown).toEqual([])
  expect(pastSplit.earlier).toBe(1)
})

test('the folded traces keep an agent 4.9 s after it ends and drop it at 5.1 s, live ones always, and the wait is exact', () => {
  const live = addAgent(EMPTY_STORE, agentNamed('live', 0))
  const both = moveAgent(addAgent(live, agentNamed('gone', 0)), { id: 'gone', state: 'failed', command: null, now: ENDED_AT })
  const rows = new Map(both.rows.map(row => [row.id, row]))
  const roster = rosterOf(both).rows
  const idsAt = (now: number) => tracedRows(roster, rows, now).map(row => row.id)

  expect(idsAt(ENDED_AT + JUST_INSIDE_LINGER_MS)).toEqual(['live', 'gone'])
  expect(idsAt(ENDED_AT + JUST_PAST_LINGER_MS)).toEqual(['live'])
  expect(nextLeaveMs(rows.values(), '1m', ENDED_AT + JUST_INSIDE_LINGER_MS, true)).toBe(100)
  expect(nextLeaveMs(rows.values(), 'session', ENDED_AT + JUST_PAST_LINGER_MS, true)).toBeNull()
  expect(countAgents(roster).failed).toBe(1)
})

test('closeOpen closes every open segment at the given time, rests main and fails live agents', () => {
  let store: AgentStore = moveMain(EMPTY_STORE, { activity: { state: 'thinking', command: null }, now: 100 })
  store = addAgent(store, agentNamed('a', 100))
  store = moveAgent(store, { id: 'a', state: 'thinking', command: null, now: 150 })
  store = addAgent(store, agentNamed('b', 100))
  store = finishAgent(store, { id: 'b', state: 'done', now: 120 })

  const closed = closeOpen(store, 500)
  const everySegment = [...(closed.main?.segments ?? []), ...closed.rows.flatMap(row => row.segments)]

  expect(everySegment.some(segment => segment.to === null)).toBe(false)
  expect(closed.main?.state).toBe('launched')
  expect(closed.main?.segments.at(-1)?.to).toBe(500)
  expect(closed.rows.find(row => row.id === 'a')?.state).toBe('failed')
  expect(closed.rows.find(row => row.id === 'a')?.endedAt).toBe(500)
  expect(closed.rows.find(row => row.id === 'b')?.state).toBe('done')
  expect(closed.rows.find(row => row.id === 'b')?.endedAt).toBe(120)
})

test('closeOpen clears background tasks and the held flag', () => {
  let store: AgentStore = addAgent(EMPTY_STORE, agentNamed('a', 0))
  store = { ...store, tasks: { a: ['t1'], main: ['t2'] } }
  store = moveMain(store, { activity: { state: 'thinking', command: null }, now: 5 })

  const closed = closeOpen(store, 50)

  expect(closed.tasks?.['a']).toBeUndefined()
  expect(closed.tasks?.['main']).toBeUndefined()
  expect(closed.main?.background ?? 0).toBe(0)
})
