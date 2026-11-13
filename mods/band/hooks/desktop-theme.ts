import type { ThemeSetting } from '../types'

export type Tone = 'run' | 'done' | 'fail' | 'warn' | 'ink' | 'idle'

export type ArcId = 'fiveHour' | 'week' | 'fable' | 'context'

export const ARC_IDS: readonly ArcId[] = ['fiveHour', 'week', 'fable', 'context']

export type DesktopPalette = {
  run: string
  runSoft: string
  done: string
  doneSoft: string
  fail: string
  failSoft: string
  warn: string
  warnSoft: string
  warnWash: string
  ink: string
  inkSoft: string
  muted: string
  rail: string
  arcFiveHour: string
  arcWeek: string
  arcFable: string
  arcContext: string
}

const LIGHT: DesktopPalette = {
  run: '#5b21b6',
  runSoft: '#c9b5ef',
  done: '#11672e',
  doneSoft: '#b5dcc1',
  fail: '#b3261e',
  failSoft: '#f2bdb7',
  warn: '#8a4b00',
  warnSoft: '#f3d39b',
  warnWash: '#fbebcf',
  ink: '#1f1e1d',
  inkSoft: '#c9c5b8',
  muted: '#5c5a55',
  rail: '#dedbcf',
  arcFiveHour: '#2457c5',
  arcWeek: '#b02a8f',
  arcFable: '#0b8577',
  arcContext: '#5d6b7a',
}

const DARK: DesktopPalette = {
  run: '#cdb0ff',
  runSoft: '#5a4785',
  done: '#6fd68a',
  doneSoft: '#2f5a3b',
  fail: '#ff8a80',
  failSoft: '#6e3430',
  warn: '#ffb454',
  warnSoft: '#6b4d20',
  warnWash: '#43321a',
  ink: '#ece9e0',
  inkSoft: '#6b685f',
  muted: '#a8a498',
  rail: '#3d3b37',
  arcFiveHour: '#6ea8ff',
  arcWeek: '#ff7ad1',
  arcFable: '#4fe0d0',
  arcContext: '#9aa8b8',
}

const AUTO: DesktopPalette = {
  run: 'suggestion',
  runSoft: 'rgba(139,92,246,0.35)',
  done: 'success',
  doneSoft: 'rgba(34,160,90,0.35)',
  fail: 'error',
  failSoft: 'rgba(230,80,70,0.35)',
  warn: 'warning',
  warnSoft: 'rgba(245,184,74,0.4)',
  warnWash: 'rgba(245,184,74,0.15)',
  ink: 'text',
  inkSoft: 'rgba(128,128,128,0.45)',
  muted: 'inactive',
  rail: 'rgba(128,128,128,0.2)',
  arcFiveHour: '#3b82f6',
  arcWeek: '#d946a8',
  arcFable: '#14a3b8',
  arcContext: '#7a8794',
}

export const paletteOf = (setting: ThemeSetting): DesktopPalette => (setting === 'auto' ? AUTO : setting === 'dark' ? DARK : LIGHT)

export const ARC_KEY: Readonly<Record<ArcId, keyof DesktopPalette>> = { fiveHour: 'arcFiveHour', week: 'arcWeek', fable: 'arcFable', context: 'arcContext' }

export const arcColorOf = (palette: DesktopPalette, id: ArcId): string => palette[ARC_KEY[id]]

export const STATE_COLOR_KEYS: readonly (keyof DesktopPalette)[] = ['run', 'done', 'fail', 'warn']

const variablesOf = (palette: DesktopPalette, keys: readonly (keyof DesktopPalette)[]): string => keys.map(key => '--' + key + ':' + palette[key]).join(';')

const SVG_KEYS: readonly (keyof DesktopPalette)[] = ['run', 'runSoft', 'done', 'doneSoft', 'fail', 'failSoft', 'warn', 'warnSoft', 'ink', 'inkSoft', 'muted', 'rail', 'arcFiveHour', 'arcWeek', 'arcFable', 'arcContext']

const ARC_KEYS: readonly (keyof DesktopPalette)[] = ['arcFiveHour', 'arcWeek', 'arcFable', 'arcContext']

const SVG_RULES = SVG_KEYS.map(key => '.f-' + key + '{fill:var(--' + key + ')}.s-' + key + '{stroke:var(--' + key + ')}').join('')

export const svgStyleFor = (setting: ThemeSetting): string => {
  if (setting === 'auto') {
    return ':root{' + variablesOf(LIGHT, SVG_KEYS) + '}@media (prefers-color-scheme:dark){:root{' + variablesOf(DARK, SVG_KEYS) + '}}:root{' + variablesOf(AUTO, ARC_KEYS) + '}' + SVG_RULES
  }

  return ':root{' + variablesOf(paletteOf(setting), SVG_KEYS) + '}' + SVG_RULES
}
