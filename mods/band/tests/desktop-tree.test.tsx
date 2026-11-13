import { expect, mock, test } from 'claude-code/testing'

const BAND = { plugin: 'harness-band', component: 'AbovePrompt', requestId: 'band', surface: 'desktop', props: { hasSurvey: false, isWorking: false, maxRows: 30, bodyColumns: 100, scroll: { offset: 0, bodyRows: 30 }, view: {} } } as const

const SPAWN = { tool_use_id: 'u1', prompt: 'go', description: 'build it', subagentType: 'harness:worker', provider: { plugin: 'engine', tier: 'core' }, parentModel: 'm', background: true, fork: false, name: 'build' } as const

const LIMITS = [
  { kind: 'five_hour', percentUsed: 35, resetsAt: '1970-01-01T05:00:00Z' },
  { kind: 'seven_day', percentUsed: 52, resetsAt: '1970-01-05T05:00:00Z' },
  { kind: 'fable_weekly', percentUsed: 83 },
]

const keysOf = (node: unknown): string[] => {
  if (typeof node !== 'object' || node === null) {
    return []
  }

  const props = 'props' in node && typeof node.props === 'object' && node.props !== null ? node.props : {}
  const key = 'key' in props && typeof props.key === 'string' ? [props.key] : []
  const children = 'children' in node && Array.isArray(node.children) ? node.children : []

  return [...key, ...children.flatMap(keysOf)]
}

test('the unfolded tree is a gutter and a tile column, and the folded tree is one row: the parts each keeps', async ($, on) => {
  mock.clock(on)
  on('session.start', (_, event) => ({ cwd: event.cwd }))
  on('session.usage', () => ({ value: { startedAt: 0, context: { window: 200_000, tokens: 56_000, percent: 28 }, rateLimits: LIMITS, cost: { usd: 35.63 } } }))
  on('config.list', () => ({ value: [] }))
  on('agent.list', () => ({ value: [] }))
  on('agent.spawn', () => ({ model: 'claude-sonnet-4-5', agentId: 'a1' }))
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await $.agent.spawn(SPAWN)
  const ui = await $.ui.mount(BAND)
  const unfolded = keysOf(await ui.drawn())

  expect(unfolded.slice(0, 4)).toEqual(['unfolded', 'gutter', 'arc-fiveHour', 'arc-week'])
  expect(unfolded).toEqual(expect.arrayContaining(['arc-fable', 'arc-context', 'spend', 'divider', 'main-column', 'header', 'ranges', 'range-1m', 'range-5m', 'range-1h', 'range-session', 'counts', 'fold', 'tile-row-0', 'tile-main', 'tile-a1']))
  expect(unfolded).not.toEqual(expect.arrayContaining(['ring', 'legend', 'main-state', 'mini-lanes']))

  await ui.press({ key: 'fold' })
  const folded = keysOf(await ui.drawn())

  expect(folded).toEqual(['folded', 'ring', 'legend', 'legend-column-0', 'legend-fiveHour', 'legend-fable', 'legend-column-1', 'legend-week', 'legend-context', 'main-state', 'mini-lanes', 'counts', 'spacer', 'fold'])
  await ui.unmount()
})
