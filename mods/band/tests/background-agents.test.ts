import type { AgentStatus } from 'claude-code'
import { expect, mock, test } from 'claude-code/testing'

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
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('session.usage', () => ({ value: USAGE }))
  on('config.list', () => ({ value: [] }))
  on('agent.list', () => ({ value: [{ id: 'bg1', type: 'scout', status }] }))
  on('tool.call', () => ({ result: 'Async agent launched successfully. agentId: bg1' }))
  on('turn.start', (_, e) => ({ turnId: e.turnId }))
  on('turn.complete', () => ({ text: '' }))
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount(BAND)

  await $.tool.call({ tool: 'Agent', description: 'scout', run_in_background: true })
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
