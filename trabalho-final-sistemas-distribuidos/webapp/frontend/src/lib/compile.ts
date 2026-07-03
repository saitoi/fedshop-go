/** Compilador: trace de execução real → timeline lógica de reprodução.
 *
 * A causalidade é garantida por construção: a partícula de resposta só parte
 * no instante em que a partícula de requisição chega ao endpoint. O seek é
 * determinístico (reaplicar as marks ≤ playhead a partir do zero).
 */

import type { SampleRow, TraceEvent } from "./types"

// Tempos lógicos (ms a 1×)
export const TRAVEL = 350
const ASK_STAGGER = 70
const SEL_STAGGER = 260
const DWELL_MIN = 140
const DWELL_MAX = 700
const GAP = 220
const STEP_DUR = 450

export const COLOR = {
  vendor: "#3987e5",
  ratingsite: "#199e70",
  engine: "#9085e9",
  ask: "#c98500",
  select: "#d55181",
  ok: "#0ca30c",
  err: "#d03b3b",
  muted: "#8a8a86",
  ink: "#e8e8e6",
}

export const fmt = new Intl.NumberFormat("pt-BR")

export function shortId(id: string): string {
  const m = id.match(/^(vendor|ratingsite)(\d+)$/)
  if (m) return (m[1] === "vendor" ? "v" : "r") + m[2]
  return id.slice(0, 4)
}

export interface Particle {
  t: number
  dur: number
  from: string
  to: string
  color: string
  label: string
  big?: boolean
}

export type MarkBody = (
  | { kind: "init"; ev: TraceEvent }
  | { kind: "phase"; label: string; engineStatus?: string }
  | { kind: "engineStatus"; text: string }
  | { kind: "log"; dot: string; real: number; msg: string }
  | { kind: "op"; op: "ASK" | "SELECT"; tp: string; endpoint: string; sparql: string; status: string; realDur: number; sample?: SampleRow[] }
  | { kind: "matrix"; tp: string; endpoint: string; result: boolean }
  | { kind: "tpActive"; tp: string | null }
  | { kind: "count"; counter: "ask" | "pos" | "sel"; delta: number }
  | { kind: "set"; counter: "bind" | "rows" | "time"; value: string }
  | { kind: "pulse"; node: string }
  | { kind: "results"; ev: TraceEvent }
  | { kind: "step"; index: number }
  | { kind: "error"; message: string }
)

export type Mark = MarkBody & { t: number }

/** Um passo de transformação dos bindings dentro do motor (aba Joins). */
export interface EngineStep {
  index: number
  t: number
  kind: "seed" | "join" | "union" | "optional" | "filter" | "postprocess"
  title: string
  detail: string
  ev: TraceEvent
  /** nº de bindings no motor DEPOIS deste passo (null = desconhecido) */
  outCount: number | null
  /** nº de bindings ANTES (para a seta de crescimento/redução) */
  inCount: number | null
  sample: SampleRow[]
  outVars: string[]
}

export interface Phase {
  name: string
  color: string
  start: number
  end?: number
}

export interface Timeline {
  particles: Particle[]
  marks: Mark[]
  phases: Phase[]
  steps: EngineStep[]
  total: number
}

function dwellOf(ev: TraceEvent, min = DWELL_MIN): number {
  return Math.max(min, Math.min(DWELL_MAX, (ev.t1 - ev.t0) * 1000))
}

export function compile(events: TraceEvent[]): Timeline {
  const particles: Particle[] = []
  const marks: Mark[] = []
  const phases: Phase[] = []
  const steps: EngineStep[] = []
  let cursor = 0

  const mark = (t: number, m: MarkBody) => {
    marks.push({ ...m, t })
  }
  const phase = (name: string, color: string) => phases.push({ name, color, start: cursor })
  const closePhase = () => {
    if (phases.length) phases[phases.length - 1].end = cursor
  }
  const pushStep = (s: Omit<EngineStep, "index" | "t">) => {
    const step: EngineStep = { ...s, index: steps.length, t: cursor }
    steps.push(step)
    mark(cursor, { kind: "step", index: step.index })
    return step
  }

  let i = 0
  while (i < events.length) {
    const ev = events[i]

    if (ev.type === "run_start") {
      phase("consulta", COLOR.ink)
      mark(cursor, { kind: "init", ev })
      particles.push({ t: cursor, dur: 500, from: "__CLIENT__", to: "__ENGINE__", color: COLOR.ink, label: "query" })
      mark(cursor, {
        kind: "log", dot: COLOR.ink, real: ev.t0,
        msg: `Cliente envia a consulta ao motor (${ev.triples!.length} padrões de tripla, ${ev.endpoints!.length} endpoints)`,
      })
      mark(cursor + 500, { kind: "pulse", node: "__ENGINE__" })
      mark(cursor + 500, {
        kind: "log", dot: COLOR.engine, real: ev.t0,
        msg: `Motor decompõe a consulta em ${ev.triples!.length} padrões de tripla`,
      })
      cursor += 500 + GAP
      closePhase()
      i++
      continue
    }

    if (ev.type === "phase") {
      if (ev.name === "source_selection") {
        phase("seleção de fontes", COLOR.ask)
        mark(cursor, { kind: "phase", label: "seleção de fontes", engineStatus: "sondando endpoints (ASK)…" })
        mark(cursor, {
          kind: "log", dot: COLOR.ask, real: ev.t0,
          msg: "Fase 1 — seleção de fontes: para cada padrão de tripla, o motor pergunta a cada endpoint (ASK) se ele possui dados que casam",
        })
      } else if (ev.name === "execution") {
        closePhase()
        phase("execução", COLOR.select)
        mark(cursor, { kind: "phase", label: "execução", engineStatus: "buscando bindings (SELECT)…" })
        mark(cursor, {
          kind: "log", dot: COLOR.select, real: ev.t0,
          msg: "Fase 2 — execução: o motor busca os bindings de cada padrão apenas nas fontes selecionadas e faz os joins",
        })
      }
      i++
      continue
    }

    if (ev.type === "ask") {
      // Coleta a sequência contígua de ASKs (no fedshop-go eles são concorrentes
      // e chegam intercalados entre tps) e agrupa por tp_id.
      const run: TraceEvent[] = []
      while (i < events.length && events[i].type === "ask") run.push(events[i++])
      const byTp = new Map<string, TraceEvent[]>()
      for (const a of run) {
        const list = byTp.get(a.tp_id!) ?? []
        list.push(a)
        byTp.set(a.tp_id!, list)
      }
      for (const [tp, group] of byTp) {
        mark(cursor, { kind: "tpActive", tp })
        mark(cursor, { kind: "log", dot: COLOR.ask, real: group[0].t0, msg: `${tp}: ASK enviado a ${group.length} endpoint(s)` })
        let groupEnd = cursor
        group.forEach((a, k) => {
          const s = cursor + k * ASK_STAGGER
          const dwell = dwellOf(a)
          particles.push({ t: s, dur: TRAVEL, from: "__ENGINE__", to: a.endpoint_id!, color: COLOR.ask, label: tp })
          mark(s, { kind: "op", op: "ASK", tp, endpoint: a.endpoint_id!, sparql: a.sparql!, status: "em voo…", realDur: a.t1 - a.t0 })
          mark(s, { kind: "count", counter: "ask", delta: 1 })
          const back = s + TRAVEL + dwell
          particles.push({
            t: back, dur: TRAVEL, from: a.endpoint_id!, to: "__ENGINE__",
            color: a.result ? COLOR.ok : COLOR.muted, label: a.result ? "sim" : "não",
          })
          const arrive = back + TRAVEL
          mark(arrive, { kind: "matrix", tp, endpoint: a.endpoint_id!, result: !!a.result })
          mark(arrive, {
            kind: "op", op: "ASK", tp, endpoint: a.endpoint_id!, sparql: a.sparql!,
            status: a.result ? "→ TEM dados (true)" : "→ não tem (false)", realDur: a.t1 - a.t0,
          })
          if (a.result) mark(arrive, { kind: "count", counter: "pos", delta: 1 })
          groupEnd = Math.max(groupEnd, arrive)
        })
        const positives = group.filter((a) => a.result).map((a) => a.endpoint_id!)
        mark(groupEnd, {
          kind: "log", dot: positives.length ? COLOR.ok : COLOR.muted, real: group[group.length - 1].t1,
          msg: `${tp}: ${positives.length ? `fontes = ${positives.map(shortId).join(", ")}` : "nenhuma fonte possui esse padrão"}`,
        })
        cursor = groupEnd + GAP
      }
      continue
    }

    if (ev.type === "source_selection_done") {
      mark(cursor, { kind: "tpActive", tp: null })
      const sources = ev.sources as Record<string, string[]>
      const nsrc = Object.values(sources).filter((s) => s.length).length
      const ntp = Object.keys(sources).length
      mark(cursor, {
        kind: "log", dot: COLOR.ok, real: ev.t1,
        msg: `Seleção de fontes concluída: ${ev.ask_count} ASKs em ${(ev.t1 - ev.t0).toFixed(2)}s reais — ${nsrc}/${ntp} padrões têm fontes`,
      })
      cursor += GAP
      i++
      continue
    }

    if (ev.type === "tp_exec") {
      const srcs = (ev.sources as string[]) ?? []
      mark(cursor, { kind: "tpActive", tp: ev.tp_id! })
      mark(cursor, {
        kind: "log", dot: COLOR.select, real: ev.t0,
        msg: `Executando ${ev.tp_id} (${ev.order}º na ordem do plano) em ${srcs.length} fonte(s): ${srcs.map(shortId).join(", ")}`,
      })
      cursor += 150
      i++
      continue
    }

    if (ev.type === "select") {
      const tp = ev.tp_id!
      const group: TraceEvent[] = []
      while (i < events.length && events[i].type === "select" && events[i].tp_id === tp) group.push(events[i++])
      let groupEnd = cursor
      group.forEach((s0, k) => {
        const s = cursor + k * SEL_STAGGER
        const dwell = dwellOf(s0, 200)
        particles.push({ t: s, dur: TRAVEL, from: "__ENGINE__", to: s0.endpoint_id!, color: COLOR.select, label: tp })
        mark(s, { kind: "op", op: "SELECT", tp, endpoint: s0.endpoint_id!, sparql: s0.sparql!, status: "em voo…", realDur: s0.t1 - s0.t0 })
        mark(s, { kind: "count", counter: "sel", delta: 1 })
        const back = s + TRAVEL + dwell
        particles.push({
          t: back, dur: TRAVEL, from: s0.endpoint_id!, to: "__ENGINE__",
          color: COLOR.select, label: fmt.format(s0.rows!), big: (s0.rows ?? 0) > 0,
        })
        const arrive = back + TRAVEL
        mark(arrive, {
          kind: "op", op: "SELECT", tp, endpoint: s0.endpoint_id!, sparql: s0.sparql!,
          status: `→ ${fmt.format(s0.rows!)} linha(s)`, realDur: s0.t1 - s0.t0, sample: s0.sample,
        })
        mark(arrive, {
          kind: "log", dot: COLOR.select, real: s0.t1,
          msg: `${shortId(s0.endpoint_id!)} devolve ${fmt.format(s0.rows!)} linha(s) para ${tp} (${((s0.t1 - s0.t0) * 1000).toFixed(0)}ms reais)`,
        })
        groupEnd = Math.max(groupEnd, arrive)
      })
      cursor = groupEnd + GAP
      continue
    }

    if (ev.type === "join") {
      mark(cursor, { kind: "pulse", node: "__ENGINE__" })
      mark(cursor, { kind: "set", counter: "bind", value: fmt.format(ev.out!) })
      const isSeed = ev.left === 0 || (ev.left === 1 && !(ev.left_vars ?? []).length)
      const shared = ev.shared_vars?.length ? ` em ?${ev.shared_vars.join(", ?")}` : ""
      const msg = isSeed
        ? `${ev.tp_id} semeia o resultado com ${fmt.format(ev.out!)} binding(s)`
        : `⋈ join ${ev.tp_id}${shared}: ${fmt.format(ev.left!)} × ${fmt.format(ev.right!)} → ${fmt.format(ev.out!)} binding(s)`
      mark(cursor, { kind: "log", dot: COLOR.engine, real: ev.t1, msg })
      mark(cursor, { kind: "engineStatus", text: `join ${ev.tp_id}: ${fmt.format(ev.out!)} bindings` })
      pushStep({
        kind: isSeed ? "seed" : "join",
        title: isSeed ? `Semear com ${ev.tp_id}` : `Join ⋈ ${ev.tp_id}`,
        detail: isSeed
          ? `${fmt.format(ev.out!)} bindings iniciais`
          : `${fmt.format(ev.left!)} × ${fmt.format(ev.right!)} → ${fmt.format(ev.out!)}${shared}`,
        ev,
        inCount: isSeed ? null : ev.left ?? null,
        outCount: ev.out ?? null,
        sample: ev.sample ?? [],
        outVars: ev.out_vars ?? [],
      })
      cursor += STEP_DUR
      i++
      continue
    }

    if (ev.type === "union_merge") {
      mark(cursor, { kind: "pulse", node: "__ENGINE__" })
      mark(cursor, {
        kind: "log", dot: COLOR.engine, real: ev.t1,
        msg: `UNION: ${fmt.format(ev.arm1!)} ∪ ${fmt.format(ev.arm2!)} → ${fmt.format(ev.out!)} binding(s)`,
      })
      mark(cursor, { kind: "set", counter: "bind", value: fmt.format(ev.out!) })
      pushStep({
        kind: "union",
        title: "UNION ∪",
        detail: `${fmt.format(ev.arm1!)} ∪ ${fmt.format(ev.arm2!)} → ${fmt.format(ev.out!)}`,
        ev,
        inCount: ev.arm1 ?? null,
        outCount: ev.out ?? null,
        sample: ev.sample ?? [],
        outVars: ev.out_vars ?? [],
      })
      cursor += STEP_DUR
      i++
      continue
    }

    if (ev.type === "optional_join") {
      mark(cursor, { kind: "pulse", node: "__ENGINE__" })
      mark(cursor, {
        kind: "log", dot: COLOR.engine, real: ev.t1,
        msg: `OPTIONAL (left outer join): ${fmt.format(ev.left!)} ⟕ ${fmt.format(ev.right!)} → ${fmt.format(ev.out!)} binding(s)`,
      })
      mark(cursor, { kind: "set", counter: "bind", value: fmt.format(ev.out!) })
      pushStep({
        kind: "optional",
        title: "OPTIONAL ⟕",
        detail: `${fmt.format(ev.left!)} ⟕ ${fmt.format(ev.right!)} → ${fmt.format(ev.out!)}`,
        ev,
        inCount: ev.left ?? null,
        outCount: ev.out ?? null,
        sample: ev.sample ?? [],
        outVars: ev.out_vars ?? [],
      })
      cursor += STEP_DUR
      i++
      continue
    }

    if (ev.type === "filter") {
      mark(cursor, { kind: "pulse", node: "__ENGINE__" })
      const expr = (ev.expr ?? "").length > 90 ? ev.expr!.slice(0, 88) + "…" : ev.expr ?? ""
      mark(cursor, {
        kind: "log", dot: COLOR.engine, real: ev.t1,
        msg: `FILTER(${expr}): ${fmt.format(ev.before!)} → ${fmt.format(ev.after!)} binding(s)`,
      })
      mark(cursor, { kind: "set", counter: "bind", value: fmt.format(ev.after!) })
      pushStep({
        kind: "filter",
        title: "FILTER σ",
        detail: `${expr}: ${fmt.format(ev.before!)} → ${fmt.format(ev.after!)}`,
        ev,
        inCount: ev.before ?? null,
        outCount: ev.after ?? null,
        sample: ev.sample ?? [],
        outVars: ev.out_vars ?? [],
      })
      cursor += STEP_DUR
      i++
      continue
    }

    if (ev.type === "note") {
      // fedshop-go: otimizações do plano (grupos exclusivos, post-bind, ...)
      mark(cursor, { kind: "log", dot: COLOR.muted, real: ev.t1, msg: `Plano: ${ev.message ?? ""}` })
      cursor += 120
      i++
      continue
    }

    if (ev.type === "postprocess") {
      const parts: string[] = []
      if (ev.distinct) parts.push(`DISTINCT: ${fmt.format(ev.before_distinct!)} → ${fmt.format(ev.before_limit!)}`)
      if (ev.order_by?.length) parts.push(`ORDER BY ?${ev.order_by.map((o) => o[0]).join(", ?")}`)
      if (ev.limit != null && ev.limit >= 0) parts.push(`LIMIT ${ev.limit}: ${fmt.format(ev.before_limit!)} → ${fmt.format(ev.final!)}`)
      if (parts.length) {
        mark(cursor, { kind: "pulse", node: "__ENGINE__" })
        mark(cursor, { kind: "log", dot: COLOR.engine, real: ev.t1, msg: `Pós-processamento: ${parts.join(" · ")}` })
        pushStep({
          kind: "postprocess",
          title: "Pós-processamento",
          detail: parts.join(" · "),
          ev,
          inCount: ev.before_distinct ?? ev.before_limit ?? null,
          outCount: ev.final ?? ev.before_limit ?? null,
          sample: [],
          outVars: [],
        })
        cursor += STEP_DUR
      }
      i++
      continue
    }

    if (ev.type === "run_complete") {
      closePhase()
      phase("resposta", COLOR.ok)
      mark(cursor, { kind: "tpActive", tp: null })
      particles.push({ t: cursor, dur: 550, from: "__ENGINE__", to: "__CLIENT__", color: COLOR.ok, label: `${fmt.format(ev.rows!)} linhas`, big: true })
      const arrive = cursor + 550
      mark(arrive, { kind: "pulse", node: "__CLIENT__" })
      mark(arrive, { kind: "phase", label: "concluído ✓", engineStatus: "" })
      mark(arrive, { kind: "set", counter: "rows", value: fmt.format(ev.rows!) })
      mark(arrive, { kind: "set", counter: "time", value: `${ev.total_seconds!.toFixed(2)}s` })
      mark(arrive, {
        kind: "log", dot: COLOR.ok, real: ev.t1,
        msg: `Resposta entregue ao cliente: ${fmt.format(ev.rows!)} linha(s) · ${ev.http_requests} requisições HTTP · ${ev.total_seconds!.toFixed(2)}s reais`,
      })
      mark(arrive, { kind: "results", ev })
      cursor = arrive + GAP
      closePhase()
      i++
      continue
    }

    if (ev.type === "error") {
      closePhase()
      phase("erro", COLOR.err)
      mark(cursor, { kind: "phase", label: "erro ✕", engineStatus: "" })
      mark(cursor, { kind: "error", message: ev.message ?? "erro desconhecido" })
      mark(cursor, { kind: "log", dot: COLOR.err, real: ev.t1, msg: `Erro: ${ev.message}` })
      cursor += GAP
      closePhase()
      i++
      continue
    }

    i++
  }

  closePhase()
  marks.sort((a, b) => a.t - b.t)
  return { particles, marks, phases, steps, total: cursor }
}
