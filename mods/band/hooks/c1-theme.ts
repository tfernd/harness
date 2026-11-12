import type { ThemeSetting } from '../types'

export type C1Palette = { run: string; done: string; fail: string; warn: string; ink: string; onFill: string; rail: string; noteBackground: string }

export type Tone = 'run' | 'done' | 'fail' | 'warn' | 'ink'

const LIGHT: C1Palette = { run: '#5b21b6', done: '#0f6b3a', fail: '#b42318', warn: '#8a4b00', ink: '#1d2025', onFill: '#ffffff', rail: '#e4e0d6', noteBackground: '#fdebc8' }

const DARK: C1Palette = { run: '#c4b5fd', done: '#6ee7a0', fail: '#ff8a7a', warn: '#f5b84a', ink: '#e9eaec', onFill: '#1a1c20', rail: '#3a3e46', noteBackground: '#3a2d12' }

const AUTO: C1Palette = { run: 'suggestion', done: 'success', fail: 'error', warn: 'warning', ink: 'text', onFill: 'inverseText', rail: 'rgba(128,128,128,0.2)', noteBackground: 'rgba(245,184,74,0.15)' }

export const paletteOf = (setting: ThemeSetting): C1Palette => (setting === 'auto' ? AUTO : setting === 'dark' ? DARK : LIGHT)

const variablesOf = (palette: C1Palette): string => Object.entries(palette).map(([name, value]) => '--' + name + ':' + value).join(';')

export const svgStyleFor = (setting: ThemeSetting): string => {
  const rules = '.rail{fill:var(--rail)}.t-run{fill:var(--run)}.t-done{fill:var(--done)}.t-fail{fill:var(--fail)}.t-warn{fill:var(--warn)}.t-ink{fill:var(--ink)}.now{fill:var(--ink)}'

  if (setting === 'auto') {
    return ':root{' + variablesOf(LIGHT) + '}@media (prefers-color-scheme:dark){:root{' + variablesOf(DARK) + '}}' + rules
  }

  return ':root{' + variablesOf(paletteOf(setting)) + '}' + rules
}
