import type { MainActivity } from './model'

export type OpenCall = { token: number; command: string; isQuestion: boolean }

export type CallActivity = NonNullable<MainActivity>

export const withCall = (calls: readonly OpenCall[], call: OpenCall): OpenCall[] => [...calls, call]

export const withoutCall = (calls: readonly OpenCall[], token: number): OpenCall[] => calls.filter(call => call.token !== token)

export const activityOf = (calls: readonly OpenCall[]): CallActivity => {
  if (calls.some(call => call.isQuestion)) {
    return { state: 'waiting', command: null }
  }

  const latest = calls.at(-1)

  return latest === undefined ? { state: 'thinking', command: null } : { state: 'tool', command: latest.command }
}
