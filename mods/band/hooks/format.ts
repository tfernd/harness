import type { Scheme, ThemeSetting } from '../types'

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

export const formatAge = (milliseconds: number): string => {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000))

  if (seconds < 60) {
    return `${seconds}s`
  }

  if (seconds < 3600) {
    return `${Math.floor(seconds / 60)}m${pad(seconds % 60)}s`
  }

  if (seconds < 86_400) {
    return `${Math.floor(seconds / 3600)}h${pad(Math.floor((seconds % 3600) / 60))}m`
  }

  return `${Math.floor(seconds / 86_400)}d${Math.floor((seconds % 86_400) / 3600)}h`
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

export const formatTokens = (tokens: number): string => (tokens >= 1_000_000 ? `${Number((tokens / 1_000_000).toFixed(1))}M` : tokens >= 1000 ? `${Math.round(tokens / 1000)}k` : String(tokens))

export const barText = (percent: number, width: number): string => {
  const filled = Math.max(0, Math.min(width, Math.round((percent / 100) * width)))

  return '█'.repeat(filled) + '░'.repeat(width - filled)
}
