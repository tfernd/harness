export type AgentState = 'launched' | 'thinking' | 'tool' | 'waiting' | 'done' | 'failed'

export type Range = '1m' | '5m' | '15m' | '1h' | 'session'

export type Scheme = 'light' | 'dark'

export type ThemeSetting = Scheme | 'auto'

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

export type AgentStore = { rows: AgentRow[]; main: AgentRow | null; evictedDone: number; evictedFailed: number }

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
  lastCallAt: number | null
  isSubscription: boolean
}

declare module 'claude-code' {
  interface PluginState {
    "harness-band": {
      isFolded: Shaped<boolean>
      range: Range
      foldedGroups: Shaped<string[]>
      agents: Shaped<AgentStore>
      roster: Shaped<Roster>
      gauges: Shaped<Gauges>
      turnStartedAt: number | null
      scheme: ThemeSetting
    }
  }
}
