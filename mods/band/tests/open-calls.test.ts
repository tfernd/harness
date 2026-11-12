import { expect, mock, test } from 'claude-code/testing'

import { SETTLE_MS } from './settle'

import { EMPTY_STORE, QUIET_AFTER_MS, agentTypeName, applyListing, finishAgent, moveAgent, newAgent, addAgent, startBackgroundTask, stateWordOf } from '../hooks/model'

const BAND = {
  plugin: 'harness-band',
  component: 'AbovePrompt',
  requestId: 'band',
  surface: 'desktop',
  props: { hasSurvey: false, isWorking: true, maxRows: 30, bodyColumns: 100, scroll: { offset: 0, bodyRows: 30 }, view: {} },
} as const

const USAGE = { startedAt: 0, context: { window: 200000, tokens: 1000, percent: 1 }, rateLimits: [] }

const SPAWN = {
  tool_use_id: 'u1',
  prompt: 'go',
  description: 'scout the repo',
  subagentType: 'harness:scout',
  provider: { plugin: 'engine', tier: 'core' },
  parentModel: 'm',
  background: false,
  fork: false,
} as const

type Mounted = { find: (query: { key: string }) => Promise<{ text: string } | undefined> }

const timelineSource = async (ui: Mounted): Promise<string> => (await ui.find({ key: 'timeline' }))?.text ?? ''

const heldAgent = () => {
  const added = addAgent(EMPTY_STORE, newAgent({ id: 'a', label: 'a', group: 'direct', groupLabel: 'direct agents', now: 0 }))

  return finishAgent(startBackgroundTask(added, { owner: 'a', taskId: 'b1', now: 10 }), { id: 'a', state: 'done', now: 20 })
}

test('a held agent says BG n, not quiet, however long it has been silent', () => {
  const row = heldAgent().rows[0]

  expect(row && stateWordOf(row, 20 + 10 * QUIET_AFTER_MS)).toBe('BG 1')
})

test('an agent that answered and is held by a background command ends as done when it leaves the listing', () => {
  const listed = applyListing(heldAgent(), [{ id: 'a', type: 'scout', status: 'completed' }], 30, new Set())
  const gone = applyListing(listed, [], 40, new Set(['a']))

  expect(gone.rows[0]?.state).toBe('done')
  expect(gone.rows[0]?.endedAt).toBe(40)
  expect(gone.tasks?.['a']).toBeUndefined()
})

test('an agent that was still working when it left the listing is still failed', () => {
  const working = moveAgent(heldAgent(), { id: 'a', state: 'thinking', command: null, now: 25 })
  const gone = applyListing({ ...working, tasks: {} }, [], 40, new Set(['a']))

  expect(gone.rows[0]?.state).toBe('failed')
})

test('the plugin prefix of an agent type is dropped', () => {
  expect(agentTypeName('harness:scout')).toBe('scout')
  expect(agentTypeName('scout')).toBe('scout')
})

test('a prefixed agent type is labelled without the plugin prefix', async ($, on) => {
  const clock = mock.clock(on)
  on('session.start', (_, event) => ({ cwd: event.cwd }))
  on('session.usage', () => ({ value: USAGE }))
  on('config.list', () => ({ value: [] }))
  on('agent.list', () => ({ value: [] }))
  on('agent.spawn', () => ({ model: 'm', agentId: 'sub1' }))
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  const ui = await $.ui.mount(BAND)

  await $.agent.spawn(SPAWN)
  await clock.advance(SETTLE_MS + 500)
  const source = await timelineSource(ui)

  expect(source).toContain('scout-1')
  expect(source).not.toContain('harness:')
  await ui.unmount()
})

const gatedCalls = () => {
  const gates = new Map<string, () => void>()
  const handler = (_: unknown, event: object) =>
    new Promise<{ result: string }>(resolve => {
      gates.set('command' in event ? String(event.command) : '', () => resolve({ result: 'ok' }))
    })

  return { gates, handler }
}

test('a sub-agent stays running while a parallel call is open and thinks only when the last one ends', async ($, on) => {
  const clock = mock.clock(on)
  const { gates, handler } = gatedCalls()
  on('session.start', (_, event) => ({ cwd: event.cwd }))
  on('session.usage', () => ({ value: USAGE }))
  on('config.list', () => ({ value: [] }))
  on('agent.list', () => ({ value: [{ id: 'sub1', type: 'scout', description: 'scout', status: 'running' }] }))
  on('agent.spawn', () => ({ model: 'm', agentId: 'sub1' }))
  on('tool.call', handler)
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  const ui = await $.ui.mount(BAND)
  await $.agent.spawn(SPAWN)
  const first = $.tool.call({ tool: 'Bash', command: 'first', agentId: 'sub1' })
  const second = $.tool.call({ tool: 'Bash', command: 'second', agentId: 'sub1' })
  await clock.advance(SETTLE_MS + 500)

  gates.get('first')?.()
  await first
  await clock.advance(SETTLE_MS + 500)
  const whileOneOpen = await timelineSource(ui)

  gates.get('second')?.()
  await second
  await clock.advance(SETTLE_MS + 500)
  const whenAllEnded = await timelineSource(ui)

  expect(whileOneOpen).toContain('running')
  expect(whileOneOpen).not.toContain('thinking')
  expect(whenAllEnded).toContain('thinking')
  expect(whenAllEnded).not.toContain('running')
  await ui.unmount()
})

test('main keeps NEEDS YOU when a sibling call of the open question ends', async ($, on) => {
  const clock = mock.clock(on)
  const { gates, handler } = gatedCalls()
  on('session.start', (_, event) => ({ cwd: event.cwd }))
  on('session.usage', () => ({ value: USAGE }))
  on('config.list', () => ({ value: [] }))
  on('agent.list', () => ({ value: [] }))
  on('turn.start', (_, event) => ({ turnId: event.turnId }))
  on('tool.call', handler)
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  const ui = await $.ui.mount(BAND)
  await $.turn.start({ text: '', turnId: 't1' })
  const question = $.tool.call({ tool: 'AskUserQuestion', command: 'ask', questions: [] } as never)
  const sibling = $.tool.call({ tool: 'Bash', command: 'sibling' })
  await clock.advance(SETTLE_MS + 500)

  gates.get('sibling')?.()
  await sibling
  await clock.advance(SETTLE_MS + 500)
  const whileAsking = await timelineSource(ui)

  gates.get('ask')?.()
  await question
  await clock.advance(SETTLE_MS + 500)
  const afterAnswer = await timelineSource(ui)

  expect(whileAsking).toContain('NEEDS YOU')
  expect(afterAnswer).not.toContain('NEEDS YOU')
  await ui.unmount()
})
