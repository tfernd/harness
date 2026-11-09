import type { AgentStatus } from 'claude-code'
import { expect, mock, test } from 'claude-code/testing'

import type { AgentStore } from '../types'

import {
  EMPTY_STORE,
  MAIN_ID,
  addAgent,
  endBackgroundTask,
  finishAgent,
  moveAgent,
  newAgent,
  rosterOf,
  startBackgroundTask,
  stateWordOf,
  countAgents,
} from '../hooks/model'

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

const SPAWN = {
  tool_use_id: 'u1',
  prompt: 'go',
  description: 'scout the repo',
  subagentType: 'scout',
  provider: { plugin: 'engine', tier: 'core' },
  parentModel: 'm',
  background: true,
  fork: false,
  name: 'scout',
} as const

const TURN = { turnId: 't1', answer: '', durationMs: 1, isAborted: false } as const

const withAgent = (): AgentStore =>
  addAgent(EMPTY_STORE, newAgent({ id: 'a', label: 'a', group: 'direct', groupLabel: 'direct agents', now: 0 }))

const liveOf = (store: AgentStore): number => countAgents(rosterOf(store).rows).live

test('an agent that reported with a background command running stays live until the command ends', () => {
  let store = startBackgroundTask(withAgent(), { owner: 'a', taskId: 'b1', now: 10 })
  store = finishAgent(store, { id: 'a', state: 'done', now: 20 })

  expect(liveOf(store)).toBe(1)
  expect(stateWordOf(store.rows[0]!, 30)).toBe('BG 1')

  store = endBackgroundTask(store, { taskId: 'b1', now: 40 })

  expect(liveOf(store)).toBe(0)
  expect(store.rows[0]?.state).toBe('done')
  expect(store.rows[0]?.endedAt).toBe(40)
})

test('an agent already done is revived by a later background command and counts the commands still running', () => {
  let store = finishAgent(withAgent(), { id: 'a', state: 'done', now: 5 })
  store = startBackgroundTask(store, { owner: 'a', taskId: 'b1', now: 10 })
  store = startBackgroundTask(store, { owner: 'a', taskId: 'b2', now: 11 })
  store = startBackgroundTask(store, { owner: 'a', taskId: 'b2', now: 12 })

  expect(stateWordOf(store.rows[0]!, 13)).toBe('BG 2')

  store = endBackgroundTask(store, { taskId: 'b1', now: 20 })

  expect(liveOf(store)).toBe(1)
  expect(stateWordOf(store.rows[0]!, 21)).toBe('BG 1')
})

test('a failed agent ends failed and drops its background commands', () => {
  let store = startBackgroundTask(withAgent(), { owner: 'a', taskId: 'b1', now: 10 })
  store = finishAgent(store, { id: 'a', state: 'failed', now: 20 })

  expect(store.rows[0]?.state).toBe('failed')
  expect(store.tasks?.['a']).toBeUndefined()
})

test('the main session shows its running background commands as a count and clears it when they end', () => {
  let store = startBackgroundTask(EMPTY_STORE, { owner: MAIN_ID, taskId: 'm1', now: 10 })
  store = startBackgroundTask(store, { owner: MAIN_ID, taskId: 'm2', now: 11 })

  expect(store.main).not.toBeNull()
  expect(stateWordOf(store.main!, 12)).toBe('BG 2')

  store = endBackgroundTask(store, { taskId: 'm1', now: 20 })
  expect(stateWordOf(store.main!, 21)).toBe('BG 1')

  store = endBackgroundTask(store, { taskId: 'm2', now: 22 })
  expect(stateWordOf(store.main!, 23)).toBe('IDLE')
})

test('a working agent with a background command keeps its own state word', () => {
  let store = startBackgroundTask(withAgent(), { owner: 'a', taskId: 'b1', now: 1 })
  store = moveAgent(store, { id: 'a', state: 'thinking', command: null, now: 2 })

  expect(stateWordOf(store.rows[0]!, 3)).not.toBe('BG 1')
})

test('through the hooks, a sub-agent that answered stays live while its background command runs, until the notice', async ($, on) => {
  const clock = mock.clock(on)
  const status: AgentStatus = 'completed'
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('session.usage', () => ({ value: USAGE }))
  on('config.list', () => ({ value: [] }))
  on('agent.list', () => ({ value: [{ id: 'sub1', type: 'scout', status }] }))
  on('agent.spawn', () => ({ model: 'm', agentId: 'sub1' }))
  on('tool.call', () => ({ result: { backgroundTaskId: 'bg9', stdout: '', stderr: '', interrupted: false } }))
  on('turn.start', (_, e) => ({ turnId: e.turnId }))
  on('turn.complete', () => ({ text: '' }))
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount(BAND)

  await $.agent.spawn(SPAWN)
  await $.tool.call({ tool: 'Bash', command: 'sleep 99', run_in_background: true, agentId: 'sub1' })
  await $.turn.complete({ ...TURN, agentId: 'sub1', reason: 'answer' })
  await clock.advance(2000)
  expect(await ui.find({ type: 'Text', text: '● 1 live' })).toBeDefined()

  await $.session.append({
    message: {
      type: 'user',
      content: [{ type: 'text', text: '<task-notification><task-id>bg9</task-id><status>completed</status></task-notification>' }],
    },
  })
  await clock.advance(2000)
  expect(await ui.find({ type: 'Text', text: '● 0 live' })).toBeDefined()
  await ui.unmount()
})
