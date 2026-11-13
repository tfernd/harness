import type { AgentRow, AgentState } from '../types'

import type { Tone } from './desktop-theme'
import { formatSpan } from './format'
import { type Window, stateInSlice } from './layout'
import { MAIN_ID, lastEventAt, stateWordOf } from './model'

export type ToolKind = 'bash' | 'editing' | 'reading' | 'searching' | 'web' | 'agent'

export type ActivityKind = ToolKind | 'idle' | 'thinking' | 'needs-you' | 'permission' | 'done' | 'failed'

export const ACTIVITY_KINDS: readonly ActivityKind[] = ['idle', 'thinking', 'needs-you', 'permission', 'bash', 'editing', 'reading', 'searching', 'web', 'agent', 'done', 'failed']

export const ACTIVITY_ICON: Readonly<Record<ActivityKind, string>> = {
  idle: '○',
  thinking: '⋯',
  'needs-you': '◐',
  permission: '⊘',
  bash: '❯',
  editing: '✎',
  reading: '≡',
  searching: '⌕',
  web: '⊕',
  agent: '◈',
  done: '✓',
  failed: '✕',
}

export const ACTIVITY_WORD: Readonly<Record<ActivityKind, string>> = {
  idle: 'idle',
  thinking: 'thinking',
  'needs-you': 'waiting',
  permission: 'waiting',
  bash: 'bash',
  editing: 'editing',
  reading: 'reading',
  searching: 'searching',
  web: 'web',
  agent: 'agent',
  done: 'done',
  failed: 'failed',
}

const TOOL_KIND_BY_NAME: Readonly<Record<string, ToolKind>> = {
  Bash: 'bash',
  Edit: 'editing',
  Write: 'editing',
  MultiEdit: 'editing',
  NotebookEdit: 'editing',
  Read: 'reading',
  NotebookRead: 'reading',
  Grep: 'searching',
  Glob: 'searching',
  LS: 'searching',
  WebFetch: 'web',
  WebSearch: 'web',
  Task: 'agent',
  Agent: 'agent',
}

export const toolKindOf = (command: string): { kind: ToolKind; target: string } => {
  const space = command.indexOf(' ')
  const name = space === -1 ? command : command.slice(0, space)
  const kind = TOOL_KIND_BY_NAME[name]

  if (kind === undefined) {
    return { kind: 'bash', target: command }
  }

  return { kind, target: space === -1 ? '' : command.slice(space + 1) }
}

export const toolNameOf = (command: string): string => command.split(' ')[0] ?? command

export type Activity = { kind: ActivityKind; word: string; icon: string; detail: string; tone: Tone }

const NOTED_WORD = /^(BG |quiet )/

const activityKindOf = (row: AgentRow): { kind: ActivityKind; detail: string } => {
  const isMain = row.id === MAIN_ID

  if (row.state === 'done') {
    return { kind: 'done', detail: '' }
  }

  if (row.state === 'failed') {
    return { kind: 'failed', detail: row.failReason ?? '' }
  }

  if (row.state === 'launched') {
    return { kind: isMain ? 'idle' : 'thinking', detail: '' }
  }

  if (row.state === 'waiting') {
    return row.command !== null && !isMain ? { kind: 'permission', detail: 'permission: ' + toolNameOf(row.command) } : { kind: 'needs-you', detail: 'needs you' }
  }

  if (row.state === 'tool' && row.command !== null) {
    const tool = toolKindOf(row.command)

    return { kind: tool.kind, detail: tool.target }
  }

  return { kind: 'thinking', detail: '' }
}

const toneOfKind = (kind: ActivityKind, isMain: boolean): Tone => {
  if (kind === 'done' || kind === 'failed') {
    return kind === 'done' ? 'done' : 'fail'
  }

  if (kind === 'idle') {
    return 'idle'
  }

  if (kind === 'needs-you' || kind === 'permission') {
    return 'warn'
  }

  return isMain ? 'ink' : 'run'
}

export const activityOf = (row: AgentRow, now: number): Activity => {
  const isMain = row.id === MAIN_ID
  const { kind, detail } = activityKindOf(row)
  const noted = stateWordOf(row, now)
  const idleSince = kind === 'idle' && row.segments.length > 0 ? 'since ' + formatSpan(now - lastEventAt(row)) : detail

  return { kind, word: ACTIVITY_WORD[kind], icon: ACTIVITY_ICON[kind], detail: NOTED_WORD.test(noted) ? noted.toLowerCase() : idleSince, tone: toneOfKind(kind, isMain) }
}

export const STRIP_CELLS = 24

export type CellKind = 'empty' | 'idle' | 'run' | 'runSoft' | 'ink' | 'inkSoft' | 'warn' | 'done' | 'doneSoft' | 'fail' | 'failSoft'

const MAIN_CELL: Readonly<Record<AgentState, CellKind>> = { launched: 'idle', thinking: 'inkSoft', tool: 'ink', waiting: 'warn', done: 'idle', failed: 'idle' }

const LIVE_CELL: Readonly<Record<AgentState, CellKind>> = { launched: 'runSoft', thinking: 'runSoft', tool: 'run', waiting: 'warn', done: 'done', failed: 'fail' }

const ENDED_CELL: Readonly<Record<'done' | 'failed', Readonly<Record<AgentState, CellKind>>>> = {
  done: { launched: 'doneSoft', thinking: 'doneSoft', tool: 'done', waiting: 'doneSoft', done: 'done', failed: 'fail' },
  failed: { launched: 'failSoft', thinking: 'failSoft', tool: 'fail', waiting: 'failSoft', done: 'done', failed: 'fail' },
}

export const cellKindOf = (row: AgentRow, state: AgentState): CellKind => {
  if (row.id === MAIN_ID) {
    return MAIN_CELL[state]
  }

  return row.state === 'done' || row.state === 'failed' ? ENDED_CELL[row.state][state] : LIVE_CELL[state]
}

export const cellsOf = (row: AgentRow, window: Window, now: number, count: number = STRIP_CELLS): CellKind[] => {
  const length = (window.end - window.start) / count

  return Array.from({ length: count }, (_, index) => {
    const from = window.start + index * length
    const state = stateInSlice(row, from, from + length, now)

    return state === null ? 'empty' : cellKindOf(row, state)
  })
}

export type CellRun = { kind: CellKind; from: number; count: number }

export const runsOf = (cells: readonly CellKind[]): CellRun[] =>
  cells.reduce<CellRun[]>((runs, kind, index) => {
    const last = runs.at(-1)

    return last !== undefined && last.kind === kind ? [...runs.slice(0, -1), { ...last, count: last.count + 1 }] : [...runs, { kind, from: index, count: 1 }]
  }, [])
