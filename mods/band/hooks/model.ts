import type { AgentStatus } from 'claude-code'

import type { AgentRow, AgentState, AgentStore, Phase, Range, Roster, RosterRow, Scheme, ThemeSetting } from '../types'

export const RANGES: readonly Range[] = ['1m', '5m', '15m', '1h', 'session']
export const FOLDED_RANGE: Range = '1m'
export const MAX_AGENTS = 200
export const MAX_SEGMENTS = 200
export const LINGER_MS = 5000

const RANGE_MS = { '1m': 60_000, '5m': 300_000, '15m': 900_000, '1h': 3_600_000 } as const

export const DIRECT_GROUP = 'direct'
export const DIRECT_LABEL = 'direct agents'

export const MAIN_ID = 'main'
export const MAIN_LABEL = 'main session'

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

export type Window = { start: number; end: number }

export const windowFor = (range: Range, now: number, earliestStart: number): Window => {
  if (range === 'session') {
    return { start: Math.min(earliestStart, now - 60_000), end: now }
  }

  return { start: now - RANGE_MS[range], end: now }
}

export const earliestStart = (agents: readonly AgentRow[], fallback: number): number =>
  agents.reduce((earliest, agent) => (agent.id === MAIN_ID ? earliest : Math.min(earliest, agent.startedAt)), fallback)

export const isLingering = (endedAt: number, boundary: number): boolean => endedAt > boundary - LINGER_MS

export const isInWindow = (agent: { phase: Phase }, row: AgentRow | undefined, windowStart: number): boolean =>
  agent.phase === 'live' || row === undefined || row.endedAt === null || isLingering(row.endedAt, windowStart)

const startedOf = (row: AgentRow | undefined): number => row?.startedAt ?? 0

const endedOf = (row: AgentRow | undefined): number => row?.endedAt ?? 0

export const orderAgents = <Member extends { id: string; phase: Phase }>(
  agents: readonly Member[],
  rows: ReadonlyMap<string, AgentRow>,
): Member[] => {
  const live = agents.filter(agent => agent.phase === 'live')
  const ended = agents.filter(agent => agent.phase !== 'live')

  live.sort((left, right) => startedOf(rows.get(left.id)) - startedOf(rows.get(right.id)))
  ended.sort((left, right) => endedOf(rows.get(right.id)) - endedOf(rows.get(left.id)))

  return [...live, ...ended]
}

export const tracedRows = <Member extends { id: string; phase: Phase }>(
  members: readonly Member[],
  rows: ReadonlyMap<string, AgentRow>,
  now: number,
): Member[] =>
  orderAgents(
    members.filter(member => {
      const endedAt = rows.get(member.id)?.endedAt

      return member.phase === 'live' || (endedAt !== undefined && endedAt !== null && isLingering(endedAt, now))
    }),
    rows,
  )

export type WindowSplit<Member extends { id: string; phase: Phase }> = { shown: Member[]; earlier: number }

export const splitByWindow = <Member extends { id: string; phase: Phase }>(
  agents: readonly Member[],
  rows: ReadonlyMap<string, AgentRow>,
  windowStart: number,
): WindowSplit<Member> => {
  const shown = orderAgents(agents, rows).filter(agent => isInWindow(agent, rows.get(agent.id), windowStart))

  return { shown, earlier: agents.length - shown.length }
}

const leaveTimesOf = (endedAt: number, range: Range, isFolded: boolean): number[] => {
  if (isFolded) {
    return [endedAt + LINGER_MS]
  }

  if (range === 'session') {
    return []
  }

  const leavesAt = endedAt + RANGE_MS[range]

  return [leavesAt, leavesAt + LINGER_MS]
}

export const nextLeaveMs = (rows: Iterable<AgentRow>, range: Range, now: number, isFolded = false): number | null => {
  let soonest: number | null = null

  for (const row of rows) {
    for (const at of row.endedAt === null ? [] : leaveTimesOf(row.endedAt, range, isFolded)) {
      const wait = at - now

      if (wait > 0 && (soonest === null || wait < soonest)) {
        soonest = wait
      }
    }
  }

  return soonest
}

export const newAgent = (input: {
  id: string
  label: string
  group: string
  groupLabel: string
  now: number
}): AgentRow => ({
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
      rows: store.rows.map(agent =>
        agent.id === row.id ? { ...agent, label: row.label, group: row.group, groupLabel: row.groupLabel } : agent,
      ),
    }
  }

  return evictEnded({ ...store, rows: [...store.rows, row] }, row.startedAt)
}

export const sessionTotal = (store: AgentStore): number => store.rows.length + store.evictedDone + store.evictedFailed

export const isChange = (row: AgentRow, state: AgentState, command: string | null): boolean =>
  row.state !== state || row.command !== command

const spanOf = (first: AgentRow['segments'][number], second: AgentRow['segments'][number]): number =>
  (second.to ?? second.from) - first.from

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

export const moveAgent = (
  store: AgentStore,
  change: { id: string; state: AgentState; command: string | null; now: number; from?: AgentState },
): AgentStore => {
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

export type MainActivity = { state: 'thinking' | 'tool'; command: string | null } | null

export const MAIN_STATE_WORD: Record<AgentState, string> = {
  launched: 'IDLE',
  thinking: 'WORKING',
  tool: 'TOOL',
  waiting: 'IDLE',
  done: 'IDLE',
  failed: 'IDLE',
}

export const moveMain = (
  store: AgentStore,
  change: { activity: MainActivity; now: number; from?: AgentState },
): AgentStore => {
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

  const base: AgentRow = current ?? {
    id: MAIN_ID,
    label: MAIN_LABEL,
    group: MAIN_ID,
    groupLabel: MAIN_LABEL,
    state: 'launched',
    command: null,
    startedAt: now,
    endedAt: null,
    segments: [],
  }
  const closed = base.segments.map(segment => (segment.to === null ? { ...segment, to: now } : segment))
  const segments =
    base.state === state && activity !== null
      ? base.segments
      : compactSegments(activity === null ? closed : [...closed, { state, from: now, to: null }])

  return { ...store, main: { ...base, state, command, segments } }
}

export const stateFromStatus = (status: AgentStatus, current: AgentState): AgentState => {
  if (status === 'failed' || status === 'killed') return 'failed'
  if (status === 'completed' || status === 'idle') return current === 'failed' ? 'failed' : 'done'
  if (current === 'done' || current === 'failed') return current
  if (status === 'waiting') return 'waiting'
  if (status === 'pending') return current
  return current === 'tool' || current === 'thinking' ? current : 'thinking'
}

export type Listing = { id: string; status: AgentStatus; name?: string; type: string }

const isLiveStatus = (status: AgentStatus): boolean => status === 'pending' || status === 'running' || status === 'waiting'

export const applyListing = (store: AgentStore, list: readonly Listing[], now: number): AgentStore =>
  list.reduce((current, info) => {
    const row = current.rows.find(agent => agent.id === info.id)

    if (row === undefined) {
      if (!isLiveStatus(info.status)) {
        return current
      }

      const total = sessionTotal(current) + 1
      const added = addAgent(
        current,
        newAgent({ id: info.id, label: `${info.name ?? info.type}-${total}`, group: DIRECT_GROUP, groupLabel: DIRECT_LABEL, now }),
      )

      return moveAgent(added, { id: info.id, state: stateFromStatus(info.status, 'launched'), command: null, now })
    }

    const state = stateFromStatus(info.status, row.state)

    return moveAgent(current, { id: row.id, state, command: state === 'tool' ? row.command : null, now })
  }, store)

export const rosterOf = (store: AgentStore): Roster => ({
  rows: store.rows.map(
    (row): RosterRow => ({
      id: row.id,
      label: row.label,
      group: row.group,
      groupLabel: row.groupLabel,
      phase: phaseOf(row.state),
    }),
  ),
  evictedDone: store.evictedDone,
  evictedFailed: store.evictedFailed,
})

export const isSameRoster = (left: Roster, right: Roster): boolean => JSON.stringify(left) === JSON.stringify(right)

export type Counts = { live: number; done: number; failed: number; total: number }

export const countAgents = (
  members: readonly { phase: Phase }[],
  evicted: { done: number; failed: number } = { done: 0, failed: 0 },
): Counts => {
  const live = members.filter(member => member.phase === 'live').length
  const failed = members.filter(member => member.phase === 'failed').length + evicted.failed
  const done = members.filter(member => member.phase === 'done').length + evicted.done

  return { live, failed, done, total: members.length + evicted.done + evicted.failed }
}

export const stateInSlice = (agent: AgentRow, from: number, to: number, now: number): AgentState | null => {
  if (agent.endedAt !== null && agent.endedAt >= from && agent.endedAt < to) {
    return agent.state
  }

  let best: AgentState | null = null
  let bestOverlap = 0

  for (const segment of agent.segments) {
    const segmentEnd = segment.to ?? now
    const overlap = Math.min(to, segmentEnd) - Math.max(from, segment.from)

    if (overlap > bestOverlap) {
      best = segment.state
      bestOverlap = overlap
    }
  }

  return best
}

export type GroupMember = { id: string; group: string; groupLabel: string; phase: Phase }

export type GroupView<Member extends GroupMember> = { id: string; label: string; agents: Member[]; counts: Counts }

export const groupAgents = <Member extends GroupMember>(agents: readonly Member[]): GroupView<Member>[] => {
  const order: string[] = []
  const byId = new Map<string, Member[]>()

  for (const agent of agents) {
    const members = byId.get(agent.group)

    if (members === undefined) {
      order.push(agent.group)
      byId.set(agent.group, [agent])
    } else {
      members.push(agent)
    }
  }

  const workflows = order.filter(id => id !== DIRECT_GROUP)
  const sorted = byId.has(DIRECT_GROUP) ? [...workflows, DIRECT_GROUP] : workflows

  return sorted.map(id => {
    const members = byId.get(id) ?? []

    return { id, label: members[0]?.groupLabel ?? id, agents: members, counts: countAgents(members) }
  })
}

const pad = (value: number): string => String(value).padStart(2, '0')

export const formatClock = (milliseconds: number): string => {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000))
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)

  return hours > 0 ? `${hours}:${pad(minutes)}:${pad(seconds % 60)}` : `${minutes}:${pad(seconds % 60)}`
}

export const formatShort = (milliseconds: number): string => {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000))

  if (seconds < 60) {
    return `${seconds}s`
  }

  return seconds < 3600 ? `${Math.floor(seconds / 60)}m${pad(seconds % 60)}` : `${Math.floor(seconds / 3600)}h${pad(Math.floor((seconds % 3600) / 60))}`
}

export const formatSpan = (milliseconds: number): string => {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000))

  if (seconds < 60) {
    return `${seconds}s`
  }

  const minutes = Math.floor(seconds / 60)

  return minutes < 60 ? `${minutes}m` : `${Math.floor(minutes / 60)}h`
}

export const themeOf = (value: unknown): ThemeSetting => {
  if (typeof value !== 'string') {
    return 'light'
  }

  return value.includes('light') ? 'light' : value.includes('dark') ? 'dark' : value.includes('auto') ? 'auto' : 'light'
}

export const terminalSchemeOf = (setting: ThemeSetting): Scheme => (setting === 'light' ? 'light' : 'dark')

export const formatReset = (milliseconds: number): string => {
  const minutes = Math.max(0, Math.round(milliseconds / 60_000))

  if (minutes < 60) {
    return `${minutes}m`
  }

  const hours = Math.floor(minutes / 60)

  return hours < 48 ? `${hours}h${pad(minutes % 60)}` : `${Math.floor(hours / 24)}d${hours % 24}h`
}

export const formatTokens = (tokens: number): string =>
  tokens >= 1_000_000 ? `${Number((tokens / 1_000_000).toFixed(1))}M` : tokens >= 1000 ? `${Math.round(tokens / 1000)}k` : String(tokens)

export const barText = (percent: number, width: number): string => {
  const filled = Math.max(0, Math.min(width, Math.round((percent / 100) * width)))

  return '█'.repeat(filled) + '░'.repeat(width - filled)
}

export type BandPartName = 'status' | 'context' | 'cache' | 'fiveHour' | 'sevenDay' | 'counts' | 'toggle'

export type BandLayout = { parts: readonly BandPartName[]; hasDetail: boolean }

const PART_WIDTH: Record<BandPartName, number> = {
  status: 13,
  context: 11,
  cache: 11,
  fiveHour: 11,
  sevenDay: 11,
  counts: 12,
  toggle: 3,
}

const DETAIL_WIDTH: Record<BandPartName, number> = {
  status: 0,
  context: 10,
  cache: 9,
  fiveHour: 6,
  sevenDay: 6,
  counts: 0,
  toggle: 0,
}

export const DROP_ORDER: readonly BandPartName[] = ['sevenDay', 'fiveHour', 'cache', 'context']

export const partWidth = (part: BandPartName, hasDetail: boolean): number =>
  PART_WIDTH[part] + (hasDetail ? DETAIL_WIDTH[part] : 0) + 1

export const layoutBand = (columns: number, present: readonly BandPartName[]): BandLayout => {
  let parts = present
  let hasDetail = true
  const widthOf = (): number => parts.reduce((sum, part) => sum + partWidth(part, hasDetail), 0)

  if (widthOf() > columns) {
    hasDetail = false
  }

  for (const dropped of DROP_ORDER) {
    if (widthOf() <= columns) {
      break
    }

    parts = parts.filter(part => part !== dropped)
  }

  return { parts, hasDetail }
}
