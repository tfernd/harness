export type Payload = { readonly [field: string]: unknown }

export type Next = (event: Payload) => Promise<unknown>

type Handler = (host: Host, event: Payload, next: Next) => Promise<unknown>

type Registration = { name: string; filter: Payload; handler: Handler }

export type Timer = { cancel: () => void }

export type Atom<Value> = { readonly id: string; value: Value }

export type Sources = {
  usage: () => unknown
  listing: () => readonly unknown[]
  themeValue: () => string
}

export type Host = {
  clock: { now: () => Promise<number>; every: (intervalMs: number, run: () => void) => Timer }
  ui: { invalidate: (reason: string) => void; resolve: (event: Payload) => Elements; blit: () => Promise<void>; log: (message: string) => void }
  session: { usage: () => Promise<unknown> }
  config: { list: () => Promise<readonly unknown[]> }
  agent: { list: () => Promise<readonly unknown[]> }
}

type Elements = { Box: string; Text: string; Button: string; Svg: string }

export type Child = ViewNode | string

export type ViewNode = { type: string; props: Payload; children: readonly Child[] }

const STEP_MS = 500
const FLUSH_TURNS = 400

export const atom = <Value>(id: { plugin: string; key: string }, initial: Value): Atom<Value> => ({ id: `${id.plugin}/${id.key}`, value: initial })

export const read = async <Value>(_host: Host, source: Atom<Value>): Promise<Value> => source.value

export const update = async <Value>(host: Host, source: Atom<Value>, change: (current: Value) => Value): Promise<void> => {
  source.value = change(source.value)
  host.ui.invalidate(source.id)
}

const flattenChildren = (children: readonly unknown[]): Child[] =>
  children.flatMap((child): Child[] => {
    if (Array.isArray(child)) {
      return flattenChildren(child)
    }

    if (typeof child === 'string') {
      return [child]
    }

    if (typeof child === 'number') {
      return [String(child)]
    }

    return isViewNode(child) ? [child] : []
  })

const isViewNode = (value: unknown): value is ViewNode => typeof value === 'object' && value !== null && 'type' in value && 'props' in value && 'children' in value

export const h = (type: string, props: Payload | null, ...children: readonly unknown[]): ViewNode => ({ type, props: props ?? {}, children: flattenChildren(children) })

const isHandler = (value: unknown): value is Handler => typeof value === 'function'

const isFilter = (value: unknown): value is Payload => typeof value === 'object' && value !== null

const matches = (filter: Payload, event: Payload): boolean => Object.entries(filter).every(([field, wanted]) => event[field] === wanted)

export type Engine = {
  host: Host
  on: (name: string, ...rest: readonly unknown[]) => void
  dispatch: (name: string, event: Payload, base: Next) => Promise<unknown>
  now: () => number
  sleep: (milliseconds: number) => Promise<void>
  advance: (milliseconds: number) => Promise<void>
  onInvalidate: (listener: () => void) => void
}

const flushMicrotasks = async (): Promise<void> => {
  for (let turn = 0; turn < FLUSH_TURNS; turn += 1) {
    await Promise.resolve()
  }
}

export const createEngine = (input: { startMs: number; sources: Sources }): Engine => {
  const registrations: Registration[] = []
  const timers: { intervalMs: number; dueAt: number; run: () => void; isCancelled: boolean }[] = []
  const sleepers: { wakeAt: number; wake: () => void }[] = []
  const invalidateListeners: (() => void)[] = []
  let nowMs = input.startMs

  const elements: Elements = { Box: 'Box', Text: 'Text', Button: 'Button', Svg: 'Svg' }

  const host: Host = {
    clock: {
      now: async () => nowMs,
      every: (intervalMs, run) => {
        const timer = { intervalMs, dueAt: nowMs + intervalMs, run, isCancelled: false }
        timers.push(timer)

        return { cancel: () => void (timer.isCancelled = true) }
      },
    },
    ui: {
      invalidate: () => {
        for (const listener of invalidateListeners) {
          listener()
        }
      },
      resolve: () => elements,
      blit: async () => undefined,
      log: message => console.warn(message),
    },
    session: { usage: async () => input.sources.usage() },
    config: { list: async () => [{ key: 'theme', value: input.sources.themeValue() }] },
    agent: { list: async () => input.sources.listing() },
  }

  const on = (name: string, ...rest: readonly unknown[]): void => {
    const handler = rest.at(-1)
    const filter = rest.length > 1 ? rest[0] : {}

    if (!isHandler(handler) || !isFilter(filter)) {
      throw new Error(`on(${name}) needs a handler function and an optional filter object.`)
    }

    registrations.push({ name, filter, handler })
  }

  const dispatch = (name: string, event: Payload, base: Next): Promise<unknown> => {
    const chain = registrations.filter(registration => registration.name === name && matches(registration.filter, event))
    const run = chain.reduceRight<Next>((next, registration) => later => registration.handler(host, later, next), base)

    return run(event)
  }

  const advance = async (milliseconds: number): Promise<void> => {
    const target = nowMs + milliseconds

    while (nowMs < target) {
      nowMs = Math.min(target, nowMs + STEP_MS)

      for (const sleeper of sleepers.filter(candidate => candidate.wakeAt <= nowMs)) {
        sleepers.splice(sleepers.indexOf(sleeper), 1)
        sleeper.wake()
      }

      for (const timer of timers) {
        if (!timer.isCancelled && timer.dueAt <= nowMs) {
          timer.dueAt = nowMs + timer.intervalMs
          timer.run()
        }
      }

      await flushMicrotasks()
    }
  }

  return {
    host,
    on,
    dispatch,
    now: () => nowMs,
    sleep: milliseconds => new Promise<void>(resolve => void sleepers.push({ wakeAt: nowMs + milliseconds, wake: resolve })),
    advance,
    onInvalidate: listener => void invalidateListeners.push(listener),
  }
}
