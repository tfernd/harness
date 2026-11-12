import type { Scheme, ThemeSetting } from '../types'

export type BandColors = { surface: string | undefined; tint: string; selected: string; line: string; frame: string }

const BAND_COLORS: Record<Scheme, BandColors> = {
  light: { surface: '#fbfaf7', tint: '#f1efe9', selected: '#ffffff', line: '#e4e0d6', frame: '#d9d4c7' },
  dark: { surface: '#1a1c20', tint: '#22252b', selected: '#33373f', line: '#33373f', frame: '#3a3e46' },
}

const AUTO_COLORS: BandColors = { surface: undefined, tint: 'rgba(128,128,128,0.12)', selected: 'rgba(128,128,128,0.2)', line: 'rgba(128,128,128,0.25)', frame: 'promptBorder' }

export const bandColorsOf = (setting: ThemeSetting): BandColors => (setting === 'auto' ? AUTO_COLORS : BAND_COLORS[setting])

export const DRIFT_MS = 60_000
