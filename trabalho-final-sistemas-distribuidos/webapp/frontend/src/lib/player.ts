/** Player determinístico da timeline: relógio virtual, play/pausa, velocidade,
 * passo a passo e scrub. Seek para trás = reset + reaplicar marks.
 *
 * Dois canais de assinatura para o React:
 *  - "ui": muda quando marks são aplicadas (painéis, log, matriz, contadores)
 *  - "time": muda a cada frame (playhead — relógio, slider, partículas)
 */

import type { Mark, Timeline } from "./compile"
import type { EndpointInfo, SampleRow, TraceEvent, TriplePattern } from "./types"

export interface LogEntry {
  dot: string
  real: number
  msg: string
}

export interface CurrentOp {
  op: "ASK" | "SELECT"
  tp: string
  endpoint: string
  sparql: string
  status: string
  realDur: number
  sample?: SampleRow[]
}

export interface UIState {
  triples: TriplePattern[]
  endpoints: EndpointInfo[]
  phaseLabel: string
  engineStatus: string
  counters: { ask: number; pos: number; sel: number }
  bind: string
  rows: string
  time: string
  matrix: Map<string, boolean> // "tp|endpoint" → resultado do ASK
  tpActive: string | null
  log: LogEntry[]
  op: CurrentOp | null
  results: TraceEvent | null
  currentStep: number // índice do último EngineStep aplicado (-1 = nenhum)
  errorMessage: string | null
  pulses: { node: string; at: number }[] // efêmero, consumido pelo grafo
}

function freshUI(): UIState {
  return {
    triples: [],
    endpoints: [],
    phaseLabel: "aguardando",
    engineStatus: "",
    counters: { ask: 0, pos: 0, sel: 0 },
    bind: "—",
    rows: "—",
    time: "—",
    matrix: new Map(),
    tpActive: null,
    log: [],
    op: null,
    results: null,
    currentStep: -1,
    errorMessage: null,
    pulses: [],
  }
}

type Listener = () => void

export class Player {
  timeline: Timeline | null = null
  playhead = 0
  playing = false
  speed = 1
  ui: UIState = freshUI()

  private appliedMarks = 0
  private uiVersion = 0
  private timeVersion = 0
  private uiListeners = new Set<Listener>()
  private timeListeners = new Set<Listener>()
  private raf = 0
  private lastFrame: number | null = null

  constructor() {
    this.raf = requestAnimationFrame(this.frame)
  }

  // — assinatura (useSyncExternalStore) —
  subscribeUI = (fn: Listener) => {
    this.uiListeners.add(fn)
    return () => {
      this.uiListeners.delete(fn)
    }
  }
  subscribeTime = (fn: Listener) => {
    this.timeListeners.add(fn)
    return () => {
      this.timeListeners.delete(fn)
    }
  }
  getUIVersion = () => this.uiVersion
  getTimeVersion = () => this.timeVersion

  private notifyUI() {
    this.uiVersion++
    for (const fn of this.uiListeners) fn()
  }
  private notifyTime() {
    this.timeVersion++
    for (const fn of this.timeListeners) fn()
  }

  load(timeline: Timeline) {
    this.timeline = timeline
    this.playhead = 0
    this.playing = false
    this.appliedMarks = 0
    this.ui = freshUI()
    this.notifyUI()
    this.notifyTime()
  }

  seek(t: number, opts: { live?: boolean; rebuild?: boolean } = {}) {
    const tl = this.timeline
    if (!tl) return
    t = Math.max(0, Math.min(tl.total, t))
    const backwards = t < this.playhead
    this.playhead = t
    if (backwards || opts.rebuild) {
      this.ui = freshUI()
      this.appliedMarks = 0
    }
    let changed = backwards || !!opts.rebuild
    const live = !backwards && !opts.rebuild && !!opts.live
    while (this.appliedMarks < tl.marks.length && tl.marks[this.appliedMarks].t <= t) {
      this.applyMark(tl.marks[this.appliedMarks], live)
      this.appliedMarks++
      changed = true
    }
    // Apaga pulsos antigos para os nós voltarem ao tamanho normal.
    if (this.ui.pulses.length) {
      const fresh = this.ui.pulses.filter((p) => performance.now() - p.at < 320)
      if (fresh.length !== this.ui.pulses.length) {
        this.ui.pulses = fresh
        changed = true
      }
    }
    if (changed) this.notifyUI()
    this.notifyTime()
  }

  private applyMark(m: Mark, live: boolean) {
    const ui = this.ui
    switch (m.kind) {
      case "init":
        ui.triples = m.ev.triples ?? []
        ui.endpoints = m.ev.endpoints ?? []
        break
      case "phase":
        ui.phaseLabel = m.label
        if (m.engineStatus !== undefined) ui.engineStatus = m.engineStatus
        break
      case "engineStatus":
        ui.engineStatus = m.text
        break
      case "log":
        ui.log = [...ui.log, { dot: m.dot, real: m.real, msg: m.msg }]
        break
      case "op":
        ui.op = { op: m.op, tp: m.tp, endpoint: m.endpoint, sparql: m.sparql, status: m.status, realDur: m.realDur, sample: m.sample }
        break
      case "matrix":
        ui.matrix = new Map(ui.matrix).set(`${m.tp}|${m.endpoint}`, m.result)
        break
      case "tpActive":
        ui.tpActive = m.tp
        break
      case "count":
        ui.counters = { ...ui.counters, [m.counter]: ui.counters[m.counter] + m.delta }
        break
      case "set":
        ui[m.counter] = m.value
        break
      case "pulse":
        if (live) ui.pulses = [...ui.pulses.filter((p) => performance.now() - p.at < 400), { node: m.node, at: performance.now() }]
        break
      case "results":
        ui.results = m.ev
        break
      case "step":
        ui.currentStep = m.index
        break
      case "error":
        ui.errorMessage = m.message
        break
    }
  }

  togglePlay() {
    if (!this.timeline) return
    if (!this.playing && this.playhead >= this.timeline.total) this.seek(0, { rebuild: true })
    this.playing = !this.playing
    this.notifyTime()
  }

  setSpeed(s: number) {
    this.speed = s
    this.notifyTime()
  }

  stepMark(dir: 1 | -1) {
    const tl = this.timeline
    if (!tl) return
    this.playing = false
    const times = [...new Set(tl.marks.map((m) => m.t))].sort((a, b) => a - b)
    if (dir > 0) {
      const next = times.find((t) => t > this.playhead + 1)
      this.seek(next ?? tl.total)
    } else {
      const prev = [...times].reverse().find((t) => t < this.playhead - 1)
      this.seek(prev ?? 0)
    }
  }

  private frame = (ts: number) => {
    if (this.playing && this.timeline) {
      if (this.lastFrame != null) {
        const dt = (ts - this.lastFrame) * this.speed
        const next = this.playhead + dt
        if (next >= this.timeline.total) {
          this.seek(this.timeline.total, { live: true })
          this.playing = false
        } else {
          this.seek(next, { live: true })
        }
      }
      this.lastFrame = ts
    } else {
      this.lastFrame = null
    }
    this.raf = requestAnimationFrame(this.frame)
  }

  dispose() {
    cancelAnimationFrame(this.raf)
  }
}

export const player = new Player()
