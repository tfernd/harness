import type { AgentStatus } from 'claude-code'

import type { AgentRow, AgentState, AgentStore, Phase, Roster, RosterRow } from '../types'

import { type TurnTokens, addUsage } from './cost'
import { formatSpan } from './format'

export const MAX_AGENTS = 200
export const MAX_SEGMENTS = 200
export const LINGER_MS = 5000
export const DIRECT_GROUP = 'direct'
export const DIRECT_LABEL = 'direct agents'
export const MAIN_ID = 'main'
export const MAIN_LABEL = 'main session'
export const NEEDS_YOU_WORD = 'NEEDS YOU'
export const OWNER_QUESTION_TOOLS: readonly string[] = ['AskUserQuestion', 'ExitPlanMode']
export const EMPTY_STORE: AgentStore = { rows: [], main: null, evictedDone: 0, evictedFailed: 0 }
export const EMPTY_ROSTER: Roster = { rows: [], evictedDone: 0, evictedFailed: 0 }

export const STATE_WORD: Record<AgentState, string> = {
  launched: 'STARTING',
  thinking: 'THINKING',
  tool: 'RUNNING',
  waiting: 'WAITING',
  done: 'FINISHED',
  failed: 'FAILED',
}

export const STATE_ICON: Record<AgentState, string> = {
  launched: '○',
  thinking: '●',
  tool: '●',
  waiting: '◐',
  done: '✓',
  failed: '✕',
}

export const phaseOf = (state: AgentState): Phase => (state === 'done' ? 'done' : state === 'failed' ? 'failed' : 'live')
export const isLive = (state: AgentState): boolean => phaseOf(state) === 'live'
export const isLingering = (endedAt: number, boundary: number): boolean => endedAt > boundary - LINGER_MS
export const agentTypeName = (type: string): string => type.slice(type.indexOf(':') + 1)

export const newAgent = (input: { id: string; label: string; group: string; groupLabel: string; now: number }): AgentRow => ({
  id: input.id,
  label: input.label,
  group: input.group,
  groupLabel: input.groupLabel,
  state: 'launched',
  command: null,
  startedAt: input.now,
  endedAt: null,
  segments: [{ state: 'launched', from: input.now, to: null }],
})

const evictEnded = (store: AgentStore, now: number): AgentStore => {
  let { rows, evictedDone, evictedFailed } = store
  const { main } = store

  while (rows.length > MAX_AGENTS) {
    const index = rows.findIndex(row => !isLive(row.state) && !(row.endedAt !== null && isLingering(row.endedAt, now)))

    if (index === -1) {
      break
    }

    if (rows[index]?.state === 'failed') {
      evictedFailed += 1
    } else {
      evictedDone += 1
    }

    rows = rows.filter((_, position) => position !== index)
  }

  return { rows, main, evictedDone, evictedFailed }
}

export const addAgent = (store: AgentStore, row: AgentRow): AgentStore => {
  const isKnown = store.rows.some(agent => agent.id === row.id)

  if (isKnown) {
    return {
      ...store,
      rows: store.rows.map(agent => (agent.id === row.id ? { ...agent, label: row.label, group: row.group, groupLabel: row.groupLabel } : agent)),
    }
  }

  return evictEnded({ ...store, rows: [...store.rows, row] }, row.startedAt)
}

export const sessionTotal = (store: AgentStore): number => store.rows.length + store.evictedDone + store.evictedFailed

export const isChange = (row: AgentRow, state: AgentState, command: string | null): boolean => row.state !== state || row.command !== command

const spanOf = (first: AgentRow['segments'][number], second: AgentRow['segments'][number]): number => (second.to ?? second.from) - first.from

export const compactSegments = (segments: AgentRow['segments']): AgentRow['segments'] => {
  let kept = segments

  while (kept.length > MAX_SEGMENTS) {
    let bestIndex = 0
    let bestSpan = Number.POSITIVE_INFINITY

    for (let index = 0; index < kept.length - 2; index += 1) {
      const first = kept[index]
      const second = kept[index + 1]
      const span = first === undefined || second === undefined ? Number.POSITIVE_INFINITY : spanOf(first, second)

      if (span < bestSpan) {
        bestSpan = span
        bestIndex = index
      }
    }

    const first = kept[bestIndex]
    const second = kept[bestIndex + 1]

    if (first === undefined || second === undefined) {
      break
    }

    const firstLength = (first.to ?? first.from) - first.from
    const secondLength = (second.to ?? second.from) - second.from
    const merged = { state: secondLength > firstLength ? second.state : first.state, from: first.from, to: second.to }
    kept = [...kept.slice(0, bestIndex), merged, ...kept.slice(bestIndex + 2)]
  }

  return kept
}

export const moveAgent = (store: AgentStore, change: { id: string; state: AgentState; command: string | null; now: number; from?: AgentState }): AgentStore => {
  const row = store.rows.find(agent => agent.id === change.id)

  if (row === undefined || !isChange(row, change.state, change.command)) {
    return store
  }

  if (change.from !== undefined && row.state !== change.from) {
    return store
  }

  const closed = row.segments.map(segment => (segment.to === null ? { ...segment, to: change.now } : segment))
  const isEnd = !isLive(change.state)
  const opened = { state: change.state, from: change.now, to: isEnd ? change.now : null }
  const moved: AgentRow = {
    ...row,
    state: change.state,
    command: change.command,
    endedAt: isEnd ? change.now : null,
    segments: row.state === change.state ? row.segments : compactSegments([...closed, opened]),
  }

  return { ...store, rows: store.rows.map(agent => (agent.id === change.id ? moved : agent)) }
}

export const newMainRow = (now: number): AgentRow => ({
  id: MAIN_ID,
  label: MAIN_LABEL,
  group: MAIN_ID,
  groupLabel: MAIN_LABEL,
  state: 'launched',
  command: null,
  startedAt: now,
  endedAt: null,
  segments: [],
})

export type MainActivity = { state: 'thinking' | 'tool' | 'waiting'; command: string | null } | null

export const MAIN_STATE_WORD: Record<AgentState, string> = {
  launched: 'IDLE',
  thinking: 'WORKING',
  tool: 'TOOL',
  waiting: NEEDS_YOU_WORD,
  done: 'IDLE',
  failed: 'IDLE',
}

export const QUIET_AFTER_MS = 120_000
const QUIET_STEP_MS = 60_000

export const lastEventAt = (row: AgentRow): number => {
  const last = row.segments.at(-1)

  return last === undefined ? row.startedAt : (last.to ?? last.from)
}

export const quietMs = (row: AgentRow, now: number): number | null => {
  const isAwaitingOwner = row.id === MAIN_ID && row.state === 'waiting'
  const isMainIdle = row.id === MAIN_ID && row.state === 'launched'

  if (!isLive(row.state) || isAwaitingOwner || isMainIdle) {
    return null
  }

  const quiet = now - lastEventAt(row)

  return quiet >= QUIET_AFTER_MS ? quiet : null
}

export const stateWordOf = (row: AgentRow, now: number): string => {
  const background = row.background ?? 0
  const isHeldByBackground = row.id === MAIN_ID ? row.state === 'launched' : row.state === 'waiting' && row.isHeld === true

  if (background > 0 && isHeldByBackground) {
    return `BG ${background}`
  }

  const quiet = quietMs(row, now)

  if (quiet !== null) {
    return `quiet ${formatSpan(quiet)}`
  }

  return row.id === MAIN_ID ? MAIN_STATE_WORD[row.state] : STATE_WORD[row.state]
}

export const nextQuietChangeMs = (rows: Iterable<AgentRow>, now: number): number | null => {
  let soonest: number | null = null

  for (const row of rows) {
    const isTracked = isLive(row.state) && !(row.id === MAIN_ID && row.state === 'launched')
    const quiet = now - lastEventAt(row)
    const wait = quiet < QUIET_AFTER_MS ? QUIET_AFTER_MS - quiet : QUIET_STEP_MS - ((quiet - QUIET_AFTER_MS) % QUIET_STEP_MS)

    if (isTracked && (soonest === null || wait < soonest)) {
      soonest = wait
    }
  }

  return soonest
}

export const moveMain = (store: AgentStore, change: { activity: MainActivity; now: number; from?: AgentState }): AgentStore => {
  const { activity, now } = change
  const state: AgentState = activity === null ? 'launched' : activity.state
  const command = activity === null ? null : activity.command
  const current = store.main

  if (current === null ? activity === null : !isChange(current, state, command)) {
    return store
  }

  if (current !== null && change.from !== undefined && current.state !== change.from) {
    return store
  }

  const base: AgentRow = current ?? newMainRow(now)
  const closed = base.segments.map(segment => (segment.to === null ? { ...segment, to: now } : segment))
  const segments = base.state === state ? base.segments : compactSegments([...closed, { state, from: now, to: null }])

  return { ...store, main: { ...base, state, command, segments } }
}

export const stateFromStatus = (status: AgentStatus, current: AgentState): AgentState => {
  if (status === 'failed' || status === 'killed') return 'failed'
  if (status === 'completed') return current === 'failed' ? 'failed' : 'done'
  if (status === 'idle') return current
  if (current === 'done' || current === 'failed') return current
  if (status === 'waiting') return 'waiting'
  if (status === 'pending') return current
  return current === 'tool' || current === 'thinking' ? current : 'thinking'
}

const withTaskCount = (row: AgentRow, count: number): AgentRow => ({ ...row, background: count })
const taskIdsOf = (store: AgentStore, owner: string): string[] => store.tasks?.[owner] ?? []

const settleHeld = (store: AgentStore, owner: string, now: number): AgentStore => {
  const count = taskIdsOf(store, owner).length

  if (owner === MAIN_ID) {
    return store.main === null ? store : { ...store, main: withTaskCount(store.main, count) }
  }

  const row = store.rows.find(agent => agent.id === owner)

  if (row === undefined) {
    return store
  }

  const counted = { ...store, rows: store.rows.map(agent => (agent.id === owner ? withTaskCount(agent, count) : agent)) }

  if (count > 0 && row.state === 'done') {
    const revived = moveAgent(counted, { id: owner, state: 'waiting', command: null, now })

    return { ...revived, rows: revived.rows.map(agent => (agent.id === owner ? { ...agent, isHeld: true } : agent)) }
  }

  if (count === 0 && row.isHeld === true) {
    const { isHeld: _released, ...rest } = row
    const released = { ...counted, rows: counted.rows.map(agent => (agent.id === owner ? { ...rest, background: 0 } : agent)) }

    return row.state === 'waiting' ? moveAgent(released, { id: owner, state: 'done', command: null, now }) : released
  }

  return counted
}

const withTasks = (store: AgentStore, owner: string, ids: string[]): AgentStore => {
  const tasks = { ...store.tasks }

  if (ids.length === 0) {
    delete tasks[owner]
  } else {
    tasks[owner] = ids
  }

  return { ...store, tasks }
}

const ensureMain = (store: AgentStore, now: number): AgentStore => (store.main !== null ? store : { ...store, main: newMainRow(now) })

export const startBackgroundTask = (store: AgentStore, input: { owner: string; taskId: string; now: number }): AgentStore => {
  const { owner, taskId, now } = input
  const ids = taskIdsOf(store, owner)

  if (ids.includes(taskId)) {
    return store
  }

  const base = owner === MAIN_ID ? ensureMain(store, now) : store

  return settleHeld(withTasks(base, owner, [...ids, taskId]), owner, now)
}

const releaseTask = (store: AgentStore, owner: string, input: { taskId: string; now: number }): AgentStore => {
  const remaining = taskIdsOf(store, owner).filter(id => id !== input.taskId)

  return settleHeld(withTasks(store, owner, remaining), owner, input.now)
}

export const endBackgroundTask = (store: AgentStore, input: { taskId: string; now: number }): AgentStore => {
  const owners = Object.keys(store.tasks ?? {}).filter(owner => taskIdsOf(store, owner).includes(input.taskId))

  return owners.reduce((current, owner) => releaseTask(current, owner, input), store)
}

const withFailReason = (store: AgentStore, id: string, reason: string | undefined): AgentStore => (reason === undefined ? store : { ...store, rows: store.rows.map(row => (row.id === id ? { ...row, failReason: reason } : row)) })

export const recordTurnUsage = (store: AgentStore, input: { id: string; tokens: TurnTokens; model: string; now: number }): AgentStore => {
  const grow = (row: AgentRow): AgentRow => ({ ...row, model: input.model, usage: addUsage(row.usage, input.tokens) })

  if (input.id === MAIN_ID) {
    const ready = ensureMain(store, input.now)

    return ready.main === null ? ready : { ...ready, main: grow(ready.main) }
  }

  return { ...store, rows: store.rows.map(row => (row.id === input.id ? grow(row) : row)) }
}

export type PendingUsage = { id: string; tokens: TurnTokens; model: string }

export const applyPendingUsage = (store: AgentStore, pending: readonly PendingUsage[], now: number): { store: AgentStore; applied: readonly PendingUsage[] } => {
  const applied = pending.filter(entry => store.rows.some(row => row.id === entry.id))

  return { store: applied.reduce((current, entry) => recordTurnUsage(current, { ...entry, now }), store), applied }
}

export const noteAgentKind = (store: AgentStore, input: { id: string; type: string; model: string | undefined }): AgentStore => ({
  ...store,
  rows: store.rows.map(row => (row.id === input.id ? { ...row, type: input.type, ...(input.model === undefined || row.model !== undefined ? {} : { model: input.model }) } : row)),
})

export const finishAgent = (store: AgentStore, input: { id: string; state: 'done' | 'failed'; now: number; reason?: string }): AgentStore => {
  const isHeldByTasks = input.state === 'done' && taskIdsOf(store, input.id).length > 0
  const moved = withFailReason(moveAgent(store, { id: input.id, state: input.state, command: null, now: input.now }), input.id, input.state === 'failed' ? input.reason : undefined)

  if (input.state === 'failed') {
    return settleHeld(withTasks(moved, input.id, []), input.id, input.now)
  }

  return isHeldByTasks ? settleHeld(moved, input.id, input.now) : moved
}

const failLiveRows = (store: AgentStore, at: number): AgentStore => store.rows.filter(row => isLive(row.state)).reduce((current, row) => finishAgent(current, { id: row.id, state: 'failed', now: at, reason: 'session ended' }), store)

export const closeOpen = (store: AgentStore, closeAt: number): AgentStore => {
  const failed = failLiveRows(store, closeAt)
  const main = failed.main

  if (main === null) {
    return failed
  }

  const segments = main.segments.map(segment => (segment.to === null ? { ...segment, to: closeAt } : segment))
  const rested: AgentRow = { ...main, state: 'launched', command: null, background: 0, segments: compactSegments(segments) }

  return { ...withTasks(failed, MAIN_ID, []), main: rested }
}

export type Listing = { id: string; status: AgentStatus; name?: string; type: string }
const isLiveStatus = (status: AgentStatus): boolean => status === 'pending' || status === 'running' || status === 'waiting'

export const applyListing = (store: AgentStore, list: readonly Listing[], now: number, previouslyListed: ReadonlySet<string>): AgentStore => {
  const reduced = applyListed(store, list, now)
  const listedIds = new Set(list.map(info => info.id))

  return reduced.rows.filter(row => isLive(row.state) && previouslyListed.has(row.id) && !listedIds.has(row.id)).reduce((current, row) => (row.isHeld === true && row.state === 'waiting' ? releaseHeld(current, row.id, now) : finishAgent(current, { id: row.id, state: 'failed', now })), reduced)
}

const releaseHeld = (store: AgentStore, id: string, now: number): AgentStore => settleHeld(withTasks(store, id, []), id, now)

const applyListed = (store: AgentStore, list: readonly Listing[], now: number): AgentStore =>
  list.reduce((current, info) => {
    const row = current.rows.find(agent => agent.id === info.id)

    if (row === undefined) {
      if (!isLiveStatus(info.status)) {
        return current
      }

      const total = sessionTotal(current) + 1
      const added = addAgent(current, newAgent({ id: info.id, label: `${info.name ?? agentTypeName(info.type)}-${total}`, group: DIRECT_GROUP, groupLabel: DIRECT_LABEL, now }))

      return moveAgent(added, { id: info.id, state: stateFromStatus(info.status, 'launched'), command: null, now })
    }

    const isEnded = info.status === 'failed' || info.status === 'killed'
    const cleared = isEnded ? settleHeld(withTasks(current, row.id, []), row.id, now) : current
    const state = row.isHeld === true && !isEnded ? row.state : stateFromStatus(info.status, row.state)

    return moveAgent(cleared, { id: row.id, state, command: state === 'tool' ? row.command : null, now })
  }, store)

export const rosterOf = (store: AgentStore): Roster => ({
  rows: store.rows.map((row): RosterRow => ({
    id: row.id,
    label: row.label,
    group: row.group,
    groupLabel: row.groupLabel,
    phase: phaseOf(row.state),
  })),
  evictedDone: store.evictedDone,
  evictedFailed: store.evictedFailed,
})

export const isSameRoster = (left: Roster, right: Roster): boolean => JSON.stringify(left) === JSON.stringify(right)
