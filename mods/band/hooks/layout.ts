import type { AgentRow, AgentState, Phase, Range } from '../types'

import { DIRECT_GROUP, LINGER_MS, MAIN_ID, isLingering } from './model'

export const RANGES: readonly Range[] = ['1m', '5m', '15m', '1h', 'session']
export const FOLDED_RANGE: Range = '1m'
const RANGE_MS = { '1m': 60_000, '5m': 300_000, '15m': 900_000, '1h': 3_600_000 } as const
export type Window = { start: number; end: number }

export const windowFor = (range: Range, now: number, earliestStart: number): Window => {
  if (range === 'session') {
    return { start: Math.min(earliestStart, now - 60_000), end: now }
  }

  return { start: now - RANGE_MS[range], end: now }
}

export const earliestStart = (agents: readonly AgentRow[], fallback: number): number => agents.reduce((earliest, agent) => (agent.id === MAIN_ID ? earliest : Math.min(earliest, agent.startedAt)), fallback)

export const isInWindow = (agent: { phase: Phase }, row: AgentRow | undefined, windowStart: number): boolean => agent.phase === 'live' || row === undefined || row.endedAt === null || isLingering(row.endedAt, windowStart)

const startedOf = (row: AgentRow | undefined): number => row?.startedAt ?? 0
const endedOf = (row: AgentRow | undefined): number => row?.endedAt ?? 0

export const orderAgents = <Member extends { id: string; phase: Phase }>(agents: readonly Member[], rows: ReadonlyMap<string, AgentRow>): Member[] => {
  const live = agents.filter(agent => agent.phase === 'live')
  const ended = agents.filter(agent => agent.phase !== 'live')

  live.sort((left, right) => startedOf(rows.get(left.id)) - startedOf(rows.get(right.id)))
  ended.sort((left, right) => endedOf(rows.get(right.id)) - endedOf(rows.get(left.id)))

  return [...live, ...ended]
}

const isTraced = (member: { id: string; phase: Phase }, rows: ReadonlyMap<string, AgentRow>, now: number): boolean => {
  const endedAt = rows.get(member.id)?.endedAt

  return member.phase === 'live' || (endedAt !== undefined && endedAt !== null && isLingering(endedAt, now))
}

export const tracedRows = <Member extends { id: string; phase: Phase }>(members: readonly Member[], rows: ReadonlyMap<string, AgentRow>, now: number): Member[] =>
  orderAgents(
    members.filter(member => isTraced(member, rows, now)),
    rows,
  )

export type WindowSplit<Member extends { id: string; phase: Phase }> = { shown: Member[]; earlier: number }

export const splitByWindow = <Member extends { id: string; phase: Phase }>(agents: readonly Member[], rows: ReadonlyMap<string, AgentRow>, windowStart: number): WindowSplit<Member> => {
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

export type Counts = { live: number; done: number; failed: number; total: number }

export const countAgents = (members: readonly { phase: Phase }[], evicted: { done: number; failed: number } = { done: 0, failed: 0 }): Counts => {
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

export const partWidth = (part: BandPartName, hasDetail: boolean): number => PART_WIDTH[part] + (hasDetail ? DETAIL_WIDTH[part] : 0) + 1

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
