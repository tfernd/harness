import { expect, mock, test } from 'claude-code/testing'

import type { AgentRow } from '../types'

import { MIN_REBUILD_MS } from '../hooks/svg-cache'

import {
  QUIET_AFTER_MS,
  EMPTY_STORE,
  MAIN_ID,
  addAgent,
  moveAgent,
  moveMain,
  nextQuietChangeMs,
  newAgent,
  quietMs,
  stateWordOf,
} from '../hooks/model'

const START = 1_000_000

const agentAt = (state: 'thinking' | 'tool', since: number): AgentRow => {
  const added = addAgent(EMPTY_STORE, newAgent({ id: 'a1', label: 'a1', group: 'direct', groupLabel: 'direct agents', now: START }))
  const moved = moveAgent(added, { id: 'a1', state, command: state === 'tool' ? 'Bash x' : null, now: since })
  const row = moved.rows[0]

  if (row === undefined) {
    throw new Error('agent a1 missing')
  }

  return row
}

const mainAt = (activity: Parameters<typeof moveMain>[1]['activity'], since: number): AgentRow => {
  const row = moveMain(EMPTY_STORE, { activity, now: since }).main

  if (row === null) {
    throw new Error('main missing')
  }

  return row
}

test('a live agent shows quiet at exactly 2m, not at 1m59s, and counts up by the minute', () => {
  const row = agentAt('thinking', START)

  expect(stateWordOf(row, START + QUIET_AFTER_MS - 1)).toBe('THINKING')
  expect(stateWordOf(row, START + QUIET_AFTER_MS)).toBe('quiet 2m')
  expect(stateWordOf(row, START + 3 * 60_000 + 59_000)).toBe('quiet 3m')
  expect(stateWordOf(row, START + 4 * 60_000)).toBe('quiet 4m')
})

test('the next event clears quiet, and an ended agent is never quiet', () => {
  const row = agentAt('thinking', START)
  const later = START + 5 * 60_000
  const moved = moveAgent({ rows: [row], main: null, evictedDone: 0, evictedFailed: 0 }, { id: 'a1', state: 'tool', command: 'Read y', now: later })
  const next = moved.rows[0]

  expect(next && stateWordOf(next, later + 1000)).toBe('RUNNING')
  const ended = moveAgent(moved, { id: 'a1', state: 'done', command: null, now: later + 1000 }).rows[0]
  expect(ended && quietMs(ended, later + 10 * 60_000)).toBeNull()
})

test('the main session is quiet only while working, not while idle', () => {
  const working = mainAt({ state: 'thinking', command: null }, START)
  const idle = moveMain({ ...EMPTY_STORE, main: working }, { activity: null, now: START + 1000 }).main ?? working

  expect(stateWordOf(working, START + QUIET_AFTER_MS)).toBe('quiet 2m')
  expect(idle.id).toBe(MAIN_ID)
  expect(stateWordOf({ ...idle, state: 'launched' }, START + 10 * QUIET_AFTER_MS)).toBe('IDLE')
})

test('a question to the owner shows NEEDS YOU on main, even past 2m, and clears when answered', () => {
  const asking = mainAt({ state: 'waiting', command: null }, START)

  expect(stateWordOf(asking, START + 1000)).toBe('NEEDS YOU')
  expect(stateWordOf(asking, START + 10 * QUIET_AFTER_MS)).toBe('NEEDS YOU')

  const answered = moveMain({ ...EMPTY_STORE, main: asking }, { activity: { state: 'thinking', command: null }, now: START + 5000, from: 'waiting' }).main
  expect(answered && stateWordOf(answered, START + 6000)).toBe('WORKING')
})

test('the redraw wake-up falls on the 2m mark, then on each minute', () => {
  const row = agentAt('thinking', START)

  expect(nextQuietChangeMs([row], START + 30_000)).toBe(QUIET_AFTER_MS - 30_000)
  expect(nextQuietChangeMs([row], START + QUIET_AFTER_MS + 20_000)).toBe(40_000)
  expect(nextQuietChangeMs([], START)).toBeNull()
})

const BAND = {
  plugin: 'harness-band',
  component: 'AbovePrompt',
  requestId: 'band',
  surface: 'desktop',
  props: { hasSurvey: false, isWorking: true, maxRows: 30, bodyColumns: 100, scroll: { offset: 0, bodyRows: 30 }, view: {} },
} as const

const USAGE = { startedAt: 0, context: { window: 200000, tokens: 1000, percent: 1 }, rateLimits: [] }

type Mounted = { findAll: (query: { type: string }) => Promise<{ props: Record<string, unknown> }[]> }

const timelineSource = async (ui: Mounted): Promise<string> =>
  (await ui.findAll({ type: 'Svg' }))
    .filter(svg => String(svg.props['alt']).startsWith('Agent '))
    .map(svg => String(svg.props['source']))
    .join('')

test('main shows NEEDS YOU while AskUserQuestion is open and leaves it when answered', async ($, on) => {
  const clock = mock.clock(on)
  let answer: () => void = () => undefined
  let enter: () => void = () => undefined
  const entered = new Promise<void>(resolve => {
    enter = resolve
  })
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('session.usage', () => ({ value: USAGE }))
  on('config.list', () => ({ value: [] }))
  on('agent.list', () => ({ value: [] }))
  on('turn.start', (_, e) => ({ turnId: e.turnId }))
  on('tool.call', () => new Promise(resolve => {
    answer = () => resolve({ result: 'ok' })
    enter()
  }))
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  const ui = await $.ui.mount(BAND)
  await $.turn.start({ text: '', turnId: 't1' })
  await clock.advance(MIN_REBUILD_MS + 500)
  const pending = $.tool.call({ tool: 'AskUserQuestion', questions: [] } as never)
  await entered
  await clock.advance(MIN_REBUILD_MS + 200)
  const during = await timelineSource(ui)
  answer()
  await pending
  await clock.advance(MIN_REBUILD_MS + 200)
  const after = await timelineSource(ui)

  expect(during).toContain('NEEDS YOU')
  expect(after).not.toContain('NEEDS YOU')
  await ui.unmount()
})
