export type AgentState = 'launched' | 'thinking' | 'tool' | 'waiting' | 'done' | 'failed'

export type Range = '1m' | '5m' | '15m' | '1h' | 'session'

export type Scheme = 'light' | 'dark'

export type Segment = { state: AgentState; from: number; to: number | null }

export type AgentRow = {
  id: string
  label: string
  group: string
  groupLabel: string
  state: AgentState
  command: string | null
  startedAt: number
  endedAt: number | null
  segments: Segment[]
}

export type AgentStore = { rows: AgentRow[]; evictedDone: number; evictedFailed: number }

export type Phase = 'live' | 'done' | 'failed'

export type RosterRow = { id: string; label: string; group: string; groupLabel: string; phase: Phase }

export type Roster = { rows: RosterRow[]; evictedDone: number; evictedFailed: number }

export type Limit = { percent: number; resetsAt: number | null }

export type Gauges = {
  contextPercent: number | null
  contextTokens: number | null
  contextWindow: number | null
  compactedFrom: number | null
  cachePercent: number | null
  fiveHour: Limit | null
  sevenDay: Limit | null
  sessionStartedAt: number | null
}

declare module 'claude-code' {
  interface PluginState {
    "harness-band": {
      isFolded: boolean
      range: Range
      foldedGroups: string[]
      agents: Shaped<AgentStore>
      roster: Shaped<Roster>
      gauges: Shaped<Gauges>
      turnStartedAt: number | null
      scheme: Scheme
    }
  }
}
