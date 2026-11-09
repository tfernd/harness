import type { AgentState, Scheme, ThemeSetting } from '../types'

type Tokens = Record<string, string>

const LIGHT: Tokens = {
  surface: '#fbfaf7',
  panel: 'rgba(60,50,20,0.06)',
  lane: '#e4e0d6',
  line: '#e4e0d6',
  'line-strong': '#8f8470',
  ink: '#1d2025',
  muted: '#5b626d',
  hover: 'rgba(60,50,20,0.07)',
  accent: '#3d434c',
  now: '#3d434c',
  'seg-launched': '#9aa5b4',
  'seg-thinking': '#3557c8',
  'seg-tool': '#0f7266',
  'seg-waiting': '#c9820a',
  'seg-done': '#5b626d',
  'seg-failed': '#b42318',
  'seg-edge': 'rgba(0,0,0,0.22)',
  tick: 'rgba(255,255,255,0.45)',
  stripe: 'rgba(70,40,0,0.38)',
  shimmer: 'rgba(255,255,255,0.5)',
  'pill-tool-bg': '#dcefeb',
  'pill-tool-fg': '#0b5a50',
  'pill-thinking-bg': '#e3e9fa',
  'pill-thinking-fg': '#2a45a3',
  'pill-waiting-bg': '#f8e3b3',
  'pill-waiting-fg': '#5e3d00',
  'pill-done-bg': '#e9ebee',
  'pill-done-fg': '#3d434c',
  'pill-failed-bg': '#fbe4e1',
  'pill-failed-fg': '#8f1d14',
  'pill-launched-bg': '#e8e2d6',
  'pill-launched-fg': '#463f33',
  'pill-quiet-bg': '#f3ead2',
  'pill-quiet-fg': '#6b5320',
  'pill-needs-bg': '#c9820a',
  'pill-needs-fg': '#1f1300',
}

const DARK: Tokens = {
  surface: '#1a1c20',
  panel: 'rgba(255,255,255,0.05)',
  lane: '#3a3e46',
  line: '#33373f',
  'line-strong': '#6f7b8c',
  ink: '#e9eaec',
  muted: '#a0a6b0',
  hover: 'rgba(255,255,255,0.06)',
  accent: '#c9ced6',
  now: '#c9ced6',
  'seg-launched': '#6b7788',
  'seg-thinking': '#7b96f0',
  'seg-tool': '#3cc2b0',
  'seg-waiting': '#e0a02e',
  'seg-done': '#a0a6b0',
  'seg-failed': '#ff8a7a',
  'seg-edge': 'rgba(0,0,0,0.35)',
  tick: 'rgba(0,0,0,0.3)',
  stripe: 'rgba(0,0,0,0.32)',
  shimmer: 'rgba(255,255,255,0.35)',
  'pill-tool-bg': '#17403b',
  'pill-tool-fg': '#9fe6da',
  'pill-thinking-bg': '#26315a',
  'pill-thinking-fg': '#c5d3ff',
  'pill-waiting-bg': '#46330a',
  'pill-waiting-fg': '#f5d891',
  'pill-done-bg': '#2c3036',
  'pill-done-fg': '#d3d7de',
  'pill-failed-bg': '#4a211d',
  'pill-failed-fg': '#ffc2b9',
  'pill-launched-bg': '#302f2b',
  'pill-launched-fg': '#dcd5c8',
  'pill-quiet-bg': '#33291a',
  'pill-quiet-fg': '#d2bb83',
  'pill-needs-bg': '#e0a02e',
  'pill-needs-fg': '#1f1300',
}

const TOKENS: Record<Scheme, Tokens> = { light: LIGHT, dark: DARK }

export type BandColors = { surface: string | undefined; tint: string; selected: string; line: string; frame: string }

const BAND_COLORS: Record<Scheme, BandColors> = {
  light: { surface: '#fbfaf7', tint: '#f1efe9', selected: '#ffffff', line: '#e4e0d6', frame: '#d9d4c7' },
  dark: { surface: '#1a1c20', tint: '#22252b', selected: '#33373f', line: '#33373f', frame: '#3a3e46' },
}

const AUTO_COLORS: BandColors = { surface: undefined, tint: 'rgba(128,128,128,0.12)', selected: 'rgba(128,128,128,0.2)', line: 'rgba(128,128,128,0.25)', frame: 'promptBorder' }

export const bandColorsOf = (setting: ThemeSetting): BandColors => (setting === 'auto' ? AUTO_COLORS : BAND_COLORS[setting])

export const STATES: readonly AgentState[] = ['launched', 'thinking', 'tool', 'waiting', 'done', 'failed']

export const DRIFT_MS = 60_000

const FONT = 'system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",sans-serif'

const variables = (scheme: Scheme): string =>
  Object.entries(TOKENS[scheme])
    .map(([name, value]) => `--${name}:${value}`)
    .join(';')

const TONES = ['quiet', 'needs'] as const

const perTone = (): string => TONES.map(tone => `.pb-${tone}{fill:var(--pill-${tone}-bg)}.pf-${tone}{fill:var(--pill-${tone}-fg)}`).join('')

const perState = (): string =>
  perTone() +
  STATES.map(
    state =>
      `.pb-${state}{fill:var(--pill-${state}-bg)}.pf-${state}{fill:var(--pill-${state}-fg)}` +
      `.sg-${state}{fill:var(--seg-${state})}.tx-${state}{fill:var(--seg-${state})}`,
  ).join('')

const rootRules = (setting: ThemeSetting): string =>
  setting === 'auto'
    ? `:root{${variables('light')}}@media (prefers-color-scheme:dark){:root{${variables('dark')}}}`
    : `:root{${variables(setting)}}`

export const styleFor = (setting: ThemeSetting): string =>
  rootRules(setting) +
  `text{font-family:${FONT};font-size:12px;fill:var(--ink);font-variant-numeric:tabular-nums}` +
  '.m{fill:var(--muted)}.b{font-weight:600}.s{font-size:11px}.x{font-size:9px}.n{font-size:10px;font-weight:700}' +
  '.acc{fill:var(--accent)}.end{text-anchor:end}.mid{text-anchor:middle}.cap{letter-spacing:.08em}' +
  '.surf{fill:var(--surface)}.pan{fill:var(--panel)}.lan{fill:var(--lane)}.inkf{fill:var(--ink)}' +
  '.ln{stroke:var(--line);fill:none;stroke-width:1}.lns{stroke:var(--ink);fill:none;stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round}' +
  '.chev{stroke:currentColor;fill:none}' +
  '.ring-t{fill:none;stroke:var(--lane);stroke-width:4}.nowl{stroke:var(--now);stroke-width:1;fill:none}.ring-v{fill:none;stroke-width:4;stroke-linecap:round}' +
  '.r-ok{stroke:var(--accent)}.r-warn{stroke:var(--seg-waiting)}.r-bad{stroke:var(--seg-failed)}' +
    '.dot{fill:var(--accent)}.bad{fill:var(--seg-failed)}' +
  '.ico{fill:none;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round}.ic-ok{stroke:var(--seg-tool)}.ic-bad{stroke:var(--seg-failed)}.ic-live{fill:var(--seg-thinking)}.ic-dim{opacity:.4}' +
  '.hit{fill:transparent}.row:hover .hit,.gauge:hover .hit{fill:var(--hover)}' +
  '.card .face{stroke:var(--line);stroke-width:1}.card:hover .face{stroke:var(--line-strong)}' +
  perState() +
  '.drift{animation:drift 60s linear forwards}' +
  '@keyframes drift{to{transform:translateX(var(--dx))}}' +
  '.blink{animation:blink 1.1s ease-in-out infinite}@keyframes blink{50%{opacity:.55}}' +
  '.shim{animation:shim 1.8s linear infinite}@keyframes shim{from{transform:translateX(-40px)}to{transform:translateX(var(--w))}}' +
  '.stripes{animation:stripes .7s linear infinite}@keyframes stripes{to{transform:translateX(12px)}}' +
  '@media (prefers-reduced-motion:reduce){.drift,.blink,.shim,.stripes{animation:none}}'
