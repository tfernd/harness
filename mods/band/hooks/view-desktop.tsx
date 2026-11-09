import type { Elements, RenderElement } from 'claude-code'

import type { AgentState } from '../types'

import { RANGES, countAgents, formatClock, formatShort, groupAgents } from './model'
import type { BandSvg, SvgInput } from './svg-band'
import { type GaugeSpec, foldedDetail, gaugeSpecs } from './svg-strip'
import type { Actions } from './view'

export type SvgTable = Elements['desktop'] | Elements['vscode'] | Elements['mobile']

export type DesktopView = {
  ui: SvgTable
  svgs: ReadonlyMap<string, BandSvg>
  input: SvgInput
  actions: Actions
}

const STATE_COLOR: Record<AgentState, string> = {
  launched: 'inactive',
  thinking: 'suggestion',
  tool: 'success',
  waiting: 'warning',
  done: 'inactive',
  failed: 'error',
}

const statusOf = (input: SvgInput): { word: string; state: AgentState } => {
  if (input.isWorking) {
    return { word: 'WORKING', state: 'thinking' }
  }

  return [...input.rows.values()].some(row => row.state === 'waiting')
    ? { word: 'WAITING', state: 'waiting' }
    : { word: 'IDLE', state: 'launched' }
}

const captionOf = (input: SvgInput): string => {
  if (input.isWorking && input.turnStartedAt !== null) {
    return `turn ${formatClock(input.now - input.turnStartedAt)}`
  }

  return input.gauges.sessionStartedAt === null ? '' : `up ${formatShort(input.now - input.gauges.sessionStartedAt)}`
}

const FRAME_PAD_X = 'md'
const SECTION_GAP = 'lg'
const ITEM_GAP = 'sm'

export const buildDesktopBand = (view: DesktopView): RenderElement => {
  const { Box, Text, Button, Svg } = view.ui
  const { input, actions } = view
  const { isFolded } = input
  const groups = groupAgents(input.roster.rows)
  const live = input.roster.rows.filter(row => row.phase === 'live')
  const counts = countAgents(input.roster.rows, { done: input.roster.evictedDone, failed: input.roster.evictedFailed })
  const status = statusOf(input)

  const svgOf = (key: string, alt: string) => {
    const svg = view.svgs.get(key)

    return svg === undefined ? null : <Svg key={key} source={svg.source} alt={alt} width={svg.width} height={svg.height} />
  }

  const gaugeBox = (spec: GaugeSpec) => (
    <Box key={`gauge-${spec.id}`} flexDirection="row" gap={ITEM_GAP} alignItems="center">
      {svgOf(`ring-${spec.id}`, `${spec.name} ${Math.round(spec.percent)}%`)}
      <Box flexDirection="column">
        <Text bold wrap="truncate-end">
          {spec.name}
        </Text>
        <Text dimColor={!spec.isDetailUrgent} color={spec.isDetailUrgent ? 'error' : undefined} wrap="truncate-end">
          {isFolded ? foldedDetail(spec) : spec.detail}
        </Text>
      </Box>
      <Box position="absolute" top={-2} left={0} display="none" hover={{ display: 'flex' }} borderStyle="round" paddingX={1}>
        <Text>{spec.tip}</Text>
      </Box>
    </Box>
  )

  const foldButton = (
    <Button key="fold" plain onPress={() => actions.toggleFold()}>
      {isFolded ? '▾' : '▴ fold'}
    </Button>
  )

  const rangeControl = (
    <Box key="ranges" flexDirection="row" gap="xs" alignItems="center">
      <Text dimColor>range</Text>
      <Box flexDirection="row" gap="xs" borderStyle="round" paddingX="xs">
        {RANGES.map(name =>
          name === input.range ? (
            <Text key={`range-${name}`} bold>
              {name}
            </Text>
          ) : (
            <Button key={`range-${name}`} plain dimColor onPress={() => actions.setRange(name)}>
              {name}
            </Button>
          ),
        )}
      </Box>
    </Box>
  )

  const groupControl = (
    <Box key="groups" flexDirection="row" gap={SECTION_GAP}>
      {groups.map(group => (
        <Button key={`group-button-${group.id}`} plain onPress={() => actions.toggleGroup(group.id)}>
          {`${input.foldedGroups.includes(group.id) ? '▸' : '▾'} ${group.label.replace(/^workflow /, '')}`}
        </Button>
      ))}
    </Box>
  )

  const statusBox = (
    <Box key="status" flexDirection="column">
      <Text bold color={STATE_COLOR[status.state]} wrap="truncate-end">
        {status.word}
      </Text>
      <Text dimColor wrap="truncate-end">
        {captionOf(input)}
      </Text>
    </Box>
  )

  const failText = (
    <Text color={counts.failed > 0 ? 'error' : undefined} dimColor={counts.failed === 0}>
      {`✕ ${counts.failed} fail`}
    </Text>
  )

  const doneFail = (
    <Box flexDirection="row" gap="xs">
      <Text dimColor>{`✓ ${counts.done} done ·`}</Text>
      {failText}
    </Box>
  )

  const countsBox = (
    <Box key="counts" flexDirection="column">
      <Text bold color="success">{`● ${counts.live} live`}</Text>
      {doneFail}
    </Box>
  )

  const countsInline = (
    <Box key="counts" flexDirection="row" gap="xs" flexShrink={0}>
      <Text bold color="success" wrap="truncate-end">{`● ${counts.live} live ·`}</Text>
      <Text dimColor wrap="truncate-end">{`${counts.done} ✓ ·`}</Text>
      <Text color={counts.failed > 0 ? 'error' : undefined} dimColor={counts.failed === 0} wrap="truncate-end">{`${counts.failed} ✕`}</Text>
    </Box>
  )

  if (isFolded) {
    return (
      <Box flexDirection="row" alignItems="center" gap="md" borderStyle="round" paddingX={FRAME_PAD_X}>
        {foldButton}
        {statusBox}
        {gaugeSpecs(input.gauges, input.now).map(gaugeBox)}
        {live.length === 0 ? null : svgOf('traces', `${live.length} live agent traces, last 60s`)}
        <Box key="spacer" flexGrow={1} />
        {countsInline}
      </Box>
    )
  }

  return (
    <Box flexDirection="column" borderStyle="round">
      <Box key="controls" flexDirection="row" alignItems="center" gap={SECTION_GAP} paddingX={FRAME_PAD_X} paddingY="xs">
        {foldButton}
        {rangeControl}
        <Box key="spacer" flexGrow={1} />
        {groups.length === 0 ? null : groupControl}
      </Box>
      <Box key="strip" flexDirection="row" flexWrap="wrap" alignItems="center" gap={SECTION_GAP} paddingX={FRAME_PAD_X} paddingY="xs">
        {statusBox}
        {gaugeSpecs(input.gauges, input.now).map(gaugeBox)}
        <Box key="spacer" flexGrow={1} />
        {countsBox}
      </Box>
      {svgOf('timeline', `Agent timeline over ${input.range}`)}
    </Box>
  )
}
