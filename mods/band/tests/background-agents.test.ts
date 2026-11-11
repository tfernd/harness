import type { AgentStatus } from 'claude-code'
import { expect, mock, test } from 'claude-code/testing'

import { EMPTY_STORE, applyListing } from '../hooks/model'

const BAND = {
  plugin: 'harness-band',
  component: 'AbovePrompt',
  requestId: 'band',
  surface: 'terminal',
  props: {
    hasSurvey: false,
    isWorking: false,
    maxRows: 30,
    bodyColumns: 100,
    scroll: { offset: 0, bodyRows: 30 },
    view: {},
  },
} as const

const USAGE = {
  startedAt: 0,
  context: { window: 200000, tokens: 120000, percent: 60 },
  rateLimits: [{ kind: 'five_hour', percentUsed: 38, resetsAt: '1970-01-01T02:00:00Z' }],
}

const TURN = { turnId: 't1', answer: '', durationMs: 1, isAborted: false } as const

test('a background agent launched async stays live between its turns until its completion event', async ($, on) => {
  const clock = mock.clock(on)
  let status: AgentStatus = 'running'
  on('session.start', (_, event) => ({ cwd: event.cwd }))
  on('session.usage', () => ({ value: USAGE }))
  on('config.list', () => ({ value: [] }))
  on('agent.list', () => ({ value: [{ id: 'bg1', type: 'scout', description: 'scout', status }] }))
  on('tool.call', () => ({ result: 'Async agent launched successfully. agentId: bg1' }))
  on('turn.start', (_, event) => ({ turnId: event.turnId }))
  on('turn.complete', () => ({ text: '' }))
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount(BAND)

  await $.tool.call({ tool: 'Agent', description: 'scout', prompt: 'look' })
  await clock.advance(1000)
  expect(await ui.find({ type: 'Text', text: '● 1 live' })).toBeDefined()

  status = 'idle'
  await clock.advance(1000)
  expect(await ui.find({ type: 'Text', text: '● 1 live' })).toBeDefined()

  status = 'running'
  await clock.advance(1000)
  expect(await ui.find({ type: 'Text', text: '● 1 live' })).toBeDefined()

  await $.turn.complete({ ...TURN, agentId: 'bg1', reason: 'answer' })
  status = 'completed'
  await clock.advance(1000)
  expect(await ui.find({ type: 'Text', text: '● 0 live' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: '✓1' })).toBeDefined()
  await ui.unmount()
})

test('a live agent missing from the listing is failed, not left live', async ($, on) => {
  const clock = mock.clock(on)
  let listed = true
  on('session.start', (_, event) => ({ cwd: event.cwd }))
  on('session.usage', () => ({ value: USAGE }))
  on('config.list', () => ({ value: [] }))
  on('agent.list', () => ({ value: listed ? [{ id: 'bg1', type: 'scout', description: 'scout', status: 'running' }] : [] }))
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount(BAND)

  await clock.advance(3000)
  expect(await ui.find({ type: 'Text', text: '● 1 live' })).toBeDefined()

  listed = false
  await clock.advance(3000)
  expect(await ui.find({ type: 'Text', text: '● 1 live' })).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: '✕1' })).toBeDefined()
  await ui.unmount()
})

test('applyListing fails a live row that earlier stood in the listing and is now absent', () => {
  const listed = applyListing(EMPTY_STORE, [{ id: 'bg1', type: 'scout', status: 'running' }], 10, new Set())
  const gone = applyListing(listed, [], 20, new Set(['bg1']))

  expect(listed.rows[0]?.state).toBe('thinking')
  expect(gone.rows[0]?.state).toBe('failed')
  expect(gone.rows[0]?.endedAt).toBe(20)
  expect(gone.rows[0]?.segments.some(segment => segment.to === null)).toBe(false)
})

test('applyListing leaves a live row alone that was never in the listing', () => {
  const listed = applyListing(EMPTY_STORE, [{ id: 'bg1', type: 'scout', status: 'running' }], 10, new Set())
  const kept = applyListing(listed, [], 20, new Set())

  expect(kept.rows[0]?.state).toBe('thinking')
})
