import type { AgentUsage } from '../types'

export type ModelPrice = { inputPerMillion: number; outputPerMillion: number; cacheReadPerMillion: number; cacheWritePerMillion: number }

type PriceEntry = { family: string; price: ModelPrice }

const priceFromInput = (inputPerMillion: number, outputPerMillion: number): ModelPrice => ({
  inputPerMillion,
  outputPerMillion,
  cacheReadPerMillion: inputPerMillion * 0.1,
  cacheWritePerMillion: inputPerMillion * 1.25,
})

export const MODEL_PRICES: readonly PriceEntry[] = [
  { family: 'opus', price: priceFromInput(5, 25) },
  { family: 'sonnet', price: priceFromInput(3, 15) },
  { family: 'haiku', price: priceFromInput(1, 5) },
]

const TOKENS_PER_MILLION = 1_000_000

export const priceOf = (model: string | undefined): ModelPrice | null => {
  if (model === undefined) {
    return null
  }

  const lowered = model.toLowerCase()

  return MODEL_PRICES.find(entry => lowered.includes(entry.family))?.price ?? null
}

export const estimateCostUsd = (usage: AgentUsage, model: string | undefined): number | null => {
  const price = priceOf(model)

  if (price === null) {
    return null
  }

  const dollars = usage.input * price.inputPerMillion + usage.output * price.outputPerMillion + usage.cacheRead * price.cacheReadPerMillion + usage.cacheWrite * price.cacheWritePerMillion

  return dollars / TOKENS_PER_MILLION
}

export const EMPTY_USAGE: AgentUsage = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }

export type TurnTokens = { input_tokens: number; output_tokens: number; cache_read_input_tokens: number; cache_creation_input_tokens: number }

export const addUsage = (total: AgentUsage | undefined, turn: TurnTokens): AgentUsage => {
  const base = total ?? EMPTY_USAGE

  return {
    input: base.input + turn.input_tokens,
    output: base.output + turn.output_tokens,
    cacheRead: base.cacheRead + turn.cache_read_input_tokens,
    cacheWrite: base.cacheWrite + turn.cache_creation_input_tokens,
  }
}

export const tokensInOf = (usage: AgentUsage): number => usage.input + usage.cacheRead + usage.cacheWrite

export const formatUsd = (usd: number): string => (usd > 0 && usd < 0.005 ? '<$0.01' : '$' + usd.toFixed(2))
