import { createBandView } from './dom'
import { type Child, createEngine, h } from './engine'
import { type Billing, createSim } from './sim'
import { register } from '../../mods/band/hooks/register'

const SPEED = 6
const FRAME_MS = 250
const MAX_REAL_STEP_MS = 1000
const SEED_VIRTUAL_MS = 8 * 60 * 1000
const COLUMN_PX = 8
const DEFAULT_COLUMNS = 100
const SIM_SEED = 20_260_113

const required = (parent: ParentNode, selector: string): HTMLElement => {
  const found = parent.querySelector(selector)

  if (!(found instanceof HTMLElement)) {
    throw new Error(`The band page is missing ${selector}.`)
  }

  return found
}

const isChild = (value: unknown): value is Child => typeof value === 'string' || (typeof value === 'object' && value !== null && 'type' in value && 'props' in value && 'children' in value)

const themeOf = (): 'light' | 'dark' => (document.documentElement.dataset['theme'] === 'dark' ? 'dark' : 'light')

const start = async (): Promise<void> => {
  Reflect.set(globalThis, 'h', h)
  const root = required(document, '[data-band]')
  const view = createBandView(root)
  const sim = createSim({ startMs: Date.now(), seed: SIM_SEED })
  const engine = createEngine({ startMs: Date.now(), sources: sim.sources })
  register(engine.on)
  let columns = DEFAULT_COLUMNS
  let isDrawingEnabled = false
  let isDrawing = false
  let isDrawWanted = false

  const setColumns = (): void => {
    columns = Math.max(1, Math.floor(root.clientWidth / COLUMN_PX))
    document.dispatchEvent(new CustomEvent('band-columns', { detail: columns }))
  }

  const draw = async (): Promise<void> => {
    if (!isDrawingEnabled) {
      return
    }

    if (isDrawing) {
      isDrawWanted = true

      return
    }

    isDrawing = true

    try {
      const event = { component: 'AbovePrompt', surface: 'desktop', requestId: 'band', props: { hasSurvey: false, isWorking: sim.isWorking(), maxRows: 30, bodyColumns: columns, scroll: { offset: 0, bodyRows: 30 }, view: {} } }
      const tree = await engine.dispatch('ui.render', event, async () => null)
      view.show(isChild(tree) ? tree : null)
    } finally {
      isDrawing = false
    }

    if (isDrawWanted) {
      isDrawWanted = false
      await draw()
    }
  }

  engine.onInvalidate(() => void draw().catch(cause => console.error('The band could not be drawn.', cause)))
  const reportDraw = (): void => void draw().catch(cause => console.error('The band could not be drawn.', cause))

  await sim.start(engine)
  await engine.advance(SEED_VIRTUAL_MS)
  setColumns()
  isDrawingEnabled = true
  await draw()

  new ResizeObserver(() => {
    setColumns()
    reportDraw()
  }).observe(root)

  new MutationObserver(() => void sim.setTheme(engine, themeOf()).catch(cause => console.error('The theme could not be set.', cause))).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
  await sim.setTheme(engine, themeOf())

  const billingButtons = [...document.querySelectorAll('[data-billing-choice]')]

  for (const button of billingButtons) {
    button.addEventListener('click', () => {
      const billing: Billing = button instanceof HTMLElement && button.dataset['billingChoice'] === 'api' ? 'api' : 'subscription'

      for (const other of billingButtons) {
        other.setAttribute('aria-pressed', String(other === button))
      }

      void sim.setBilling(engine, billing).catch(cause => console.error('The billing could not be set.', cause))
    })
  }

  const pause = required(document, '[data-pause]')
  let isPaused = window.matchMedia('(prefers-reduced-motion: reduce)').matches

  const showPause = (): void => {
    pause.textContent = isPaused ? 'Resume' : 'Pause'
    pause.setAttribute('aria-pressed', String(isPaused))
  }

  pause.addEventListener('click', () => {
    isPaused = !isPaused
    showPause()
  })
  showPause()

  let lastRealMs = performance.now()
  let isAdvancing = false

  setInterval(() => {
    const realMs = performance.now()
    const elapsedMs = Math.min(realMs - lastRealMs, MAX_REAL_STEP_MS)
    lastRealMs = realMs

    if (isPaused || document.hidden || isAdvancing) {
      return
    }

    isAdvancing = true
    engine
      .advance(elapsedMs * SPEED)
      .then(draw)
      .catch(cause => console.error('The band simulation stopped.', cause))
      .finally(() => void (isAdvancing = false))
  }, FRAME_MS)
}

start().catch(cause => console.error('The band page could not start.', cause))
