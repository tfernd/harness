import { expect, test } from 'claude-code/testing'

import type { AgentRow } from '../types'

import { laneMarkup } from '../hooks/svg-parts'

const SHAPE = { y: 0, height: 6, radius: 3 }
const TRACK = { x: 100, width: 600, window: { start: 0, end: 60_000 } }

const agentWith = (segments: AgentRow['segments']): AgentRow => ({
  id: 'a',
  label: 'a',
  group: 'direct',
  groupLabel: 'direct agents',
  state: 'thinking',
  command: null,
  startedAt: 0,
  endedAt: null,
  segments,
})

const runsOf = (markup: string): { left: number; right: number }[] =>
  [...markup.matchAll(/<rect x="([\d.-]+)" y="0" width="([\d.]+)" height="6" class="sg-/g)].map(match => ({
    left: Number(match[1]),
    right: Number(match[1]) + Number(match[2]),
  }))

test('a lane has no gap between its runs, so the bar is continuous while an agent lives', () => {
  const agent = agentWith([
    { state: 'thinking', from: 0, to: 20_000 },
    { state: 'tool', from: 20_000, to: 20_100 },
    { state: 'thinking', from: 20_100, to: 40_000 },
    { state: 'waiting', from: 40_000, to: null },
  ])
  const runs = runsOf(laneMarkup({ defs: [], counter: 0, now: 50_000 }, agent, TRACK, SHAPE))

  expect(runs.length).toBe(4)
  runs.slice(1).forEach((run, index) => expect(run.left).toBeLessThanOrEqual(runs[index]?.right ?? Number.NaN))
})

test('every state of a lane is drawn with its own class', () => {
  const states = ['launched', 'thinking', 'tool', 'waiting', 'done', 'failed'] as const
  const agent = agentWith(states.map((state, index) => ({ state, from: index * 5000, to: index * 5000 + 5000 })))
  const markup = laneMarkup({ defs: [], counter: 0, now: 40_000 }, agent, TRACK, SHAPE)

  states.forEach(state => expect(markup).toContain(`class="sg-${state}"`))
})
