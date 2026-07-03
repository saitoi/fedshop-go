/** Grafo da federação: vendedores em coluna à esquerda, sites de avaliação à
 * direita, MOTOR ao centro e um cliente pequeno acima dele.
 *
 * As arestas são Béziers em "S" (saída horizontal do endpoint, chegada pela
 * lateral do motor) e terminam na borda dos círculos, não no centro. As
 * partículas percorrem a própria curva; enquanto uma viaja, a aresta acende na
 * cor da operação. Nós/arestas são React; partículas e destaque das arestas
 * são desenhados imperativamente a cada frame (assinatura "time" do player).
 * Hover numa partícula mostra a tripla enviada ou o resultado que ela carrega.
 */

import * as React from "react"
import { useSyncExternalStore } from "react"

import { COLOR, shortId } from "@/lib/compile"
import { player } from "@/lib/player"

const SVGNS = "http://www.w3.org/2000/svg"

const ENGINE_R = 40
const CLIENT_R = 15
const COL_TOP = 64
/** acima disso, o nome completo do endpoint sai da tela e vira <title> */
const MAX_SIDE_LABELS = 12

interface NodePos {
  x: number
  y: number
  kind: "vendor" | "ratingsite" | "other" | "engine" | "client"
}

interface Pt {
  x: number
  y: number
}

/** Aresta nó→motor: Bézier cúbica com extremos na borda dos círculos. */
interface Edge {
  p0: Pt
  c1: Pt
  c2: Pt
  p3: Pt
}

function bez(e: Edge, u: number): Pt {
  const w = 1 - u
  return {
    x: w * w * w * e.p0.x + 3 * w * w * u * e.c1.x + 3 * w * u * u * e.c2.x + u * u * u * e.p3.x,
    y: w * w * w * e.p0.y + 3 * w * w * u * e.c1.y + 3 * w * u * u * e.c2.y + u * u * u * e.p3.y,
  }
}

function pathOf(e: Edge): string {
  return `M ${e.p0.x} ${e.p0.y} C ${e.c1.x} ${e.c1.y}, ${e.c2.x} ${e.c2.y}, ${e.p3.x} ${e.p3.y}`
}

function layout(endpointIds: string[], W: number, H: number): Record<string, NodePos> {
  const nodes: Record<string, NodePos> = {}
  const vendors = endpointIds.filter((id) => id.startsWith("vendor"))
  const ratings = endpointIds.filter((id) => id.startsWith("ratingsite"))
  const others = endpointIds.filter((id) => !id.startsWith("vendor") && !id.startsWith("ratingsite"))

  const bottom = H - 30
  const column = (ids: string[], x: number, kind: NodePos["kind"]) => {
    ids.forEach((id, i) => {
      const y = ids.length === 1 ? (COL_TOP + bottom) / 2 : COL_TOP + ((bottom - COL_TOP) * i) / (ids.length - 1)
      nodes[id] = { x, y, kind }
    })
  }
  column(vendors, W * 0.13, "vendor")
  column(ratings, W * 0.87, "ratingsite")
  // Endpoints fora do padrão vendor/ratingsite: linha discreta na base.
  others.forEach((id, i) => {
    nodes[id] = { x: W * (0.35 + (0.3 * (i + 0.5)) / Math.max(1, others.length)), y: bottom, kind: "other" }
  })

  nodes.__ENGINE__ = { x: W / 2, y: H * 0.56, kind: "engine" }
  nodes.__CLIENT__ = { x: W / 2, y: Math.max(46, H * 0.12), kind: "client" }
  return nodes
}

/** Curvas nó→motor. Vendedores chegam pelo arco esquerdo do motor, ratings
 * pelo direito — a posição no arco acompanha a altura do nó, abrindo o feixe. */
function buildEdges(nodes: Record<string, NodePos>, epR: number, H: number): Record<string, Edge> {
  const engine = nodes.__ENGINE__
  const edges: Record<string, Edge> = {}
  for (const [id, n] of Object.entries(nodes)) {
    if (n.kind === "engine") continue
    if (n.kind === "client") {
      const p0 = { x: n.x, y: n.y + CLIENT_R }
      const p3 = { x: engine.x, y: engine.y - ENGINE_R }
      const my = (p0.y + p3.y) / 2
      edges[id] = { p0, c1: { x: p0.x, y: my }, c2: { x: p3.x, y: my }, p3 }
      continue
    }
    if (n.kind === "other") {
      const p0 = { x: n.x, y: n.y - epR }
      const p3 = { x: engine.x, y: engine.y + ENGINE_R }
      const my = (p0.y + p3.y) / 2
      edges[id] = { p0, c1: { x: p0.x, y: my }, c2: { x: p3.x, y: my }, p3 }
      continue
    }
    const left = n.kind === "vendor"
    const p0 = { x: n.x + (left ? epR : -epR), y: n.y }
    // ângulo de chegada no arco lateral do motor, proporcional à altura do nó
    const t = Math.max(-1, Math.min(1, (n.y - engine.y) / (H * 0.45)))
    const a = left ? Math.PI - t * 0.85 : t * 0.85
    const p3 = { x: engine.x + ENGINE_R * Math.cos(a), y: engine.y + ENGINE_R * Math.sin(a) }
    const mx = (p0.x + p3.x) / 2
    edges[id] = { p0, c1: { x: mx, y: p0.y }, c2: { x: mx, y: p3.y }, p3 }
  }
  return edges
}

const LEGEND: { color: string; label: string }[] = [
  { color: COLOR.ask, label: "ASK" },
  { color: COLOR.select, label: "SELECT" },
  { color: COLOR.ok, label: "sim" },
  { color: COLOR.muted, label: "não" },
]

export function Graph({ engineLabel }: { engineLabel: string }) {
  const svgRef = React.useRef<SVGSVGElement>(null)
  const particlesRef = React.useRef<SVGGElement>(null)
  const particleEls = React.useRef(new Map<number, SVGGElement>())
  const edgeEls = React.useRef(new Map<string, SVGPathElement>())
  const hoveredRef = React.useRef<number | null>(null)
  const tipRef = React.useRef<HTMLDivElement>(null)
  const tipTitleRef = React.useRef<HTMLDivElement>(null)
  const tipBodyRef = React.useRef<HTMLDivElement>(null)
  const [size, setSize] = React.useState({ w: 800, h: 520 })

  useSyncExternalStore(player.subscribeUI, player.getUIVersion)

  const endpoints = player.ui.endpoints
  const nVend = endpoints.filter((e) => e.id.startsWith("vendor")).length
  const nRate = endpoints.filter((e) => e.id.startsWith("ratingsite")).length
  const epR = Math.max(11, Math.min(22, ((size.h - COL_TOP - 30) / Math.max(2, Math.max(nVend, nRate))) * 0.38))
  const sideLabels = Math.max(nVend, nRate) <= MAX_SIDE_LABELS

  const nodes = React.useMemo(
    () => layout(endpoints.map((e) => e.id), size.w, size.h),
    [endpoints, size]
  )
  const edges = React.useMemo(() => buildEdges(nodes, epR, size.h), [nodes, epR, size.h])
  const edgesRef = React.useRef(edges)
  React.useEffect(() => {
    edgesRef.current = edges
  }, [edges])

  React.useEffect(() => {
    const el = svgRef.current
    if (!el) return
    const ro = new ResizeObserver(() => {
      setSize({ w: el.clientWidth, h: el.clientHeight })
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // Partículas, destaque das arestas e tooltip: por frame, fora do ciclo do React.
  React.useEffect(() => {
    const render = () => {
      const g = particlesRef.current
      const tl = player.timeline
      if (!g || !tl) return
      const t = player.playhead
      const active = new Set<number>()
      const positions = new Map<number, Pt>()
      const litEdges = new Map<string, string>() // nó → cor da partícula em voo
      tl.particles.forEach((p, idx) => {
        if (t < p.t || t > p.t + p.dur) return
        const other = p.from === "__ENGINE__" ? p.to : p.from
        const edge = edgesRef.current[other]
        if (!edge) return
        active.add(idx)
        const f = (t - p.t) / p.dur
        const { x, y } = bez(edge, p.from === "__ENGINE__" ? 1 - f : f)
        positions.set(idx, { x, y })
        litEdges.set(other, p.color)
        let elG = particleEls.current.get(idx)
        if (!elG) {
          elG = document.createElementNS(SVGNS, "g") as SVGGElement
          const c = document.createElementNS(SVGNS, "circle")
          c.setAttribute("r", p.big ? "7" : "5")
          c.setAttribute("fill", p.color)
          c.setAttribute("data-dot", "1")
          elG.appendChild(c)
          const label = document.createElementNS(SVGNS, "text")
          label.setAttribute("y", "-9")
          label.setAttribute("fill", p.color)
          label.setAttribute("text-anchor", "middle")
          label.setAttribute("font-size", "10")
          label.setAttribute("font-family", "ui-monospace, monospace")
          label.textContent = p.label || ""
          elG.appendChild(label)
          if (p.tip) {
            // Alvo de hover maior que a bolinha, invisível.
            const hit = document.createElementNS(SVGNS, "circle")
            hit.setAttribute("r", "14")
            hit.setAttribute("fill", "transparent")
            hit.style.pointerEvents = "all"
            hit.style.cursor = "pointer"
            // render() na entrada/saída: com o player pausado não há frame novo,
            // então o tooltip precisa ser desenhado aqui mesmo.
            hit.addEventListener("pointerenter", () => {
              hoveredRef.current = idx
              render()
            })
            hit.addEventListener("pointerleave", () => {
              if (hoveredRef.current === idx) hoveredRef.current = null
              render()
            })
            elG.appendChild(hit)
          }
          g.appendChild(elG)
          particleEls.current.set(idx, elG)
        }
        const hovered = hoveredRef.current === idx
        const dot = elG.querySelector("[data-dot]") as SVGCircleElement | null
        if (dot) {
          dot.setAttribute("r", hovered ? (p.big ? "9" : "7") : p.big ? "7" : "5")
          dot.setAttribute("stroke", hovered ? "white" : "none")
          dot.setAttribute("stroke-width", hovered ? "1.5" : "0")
        }
        elG.setAttribute("transform", `translate(${x},${y})`)
      })
      for (const [idx, elG] of particleEls.current) {
        if (!active.has(idx)) {
          elG.remove()
          particleEls.current.delete(idx)
          if (hoveredRef.current === idx) hoveredRef.current = null
        }
      }
      // Aresta ativa acende na cor da operação em voo.
      for (const [id, pathEl] of edgeEls.current) {
        const color = litEdges.get(id)
        if (color) {
          pathEl.setAttribute("stroke", color)
          pathEl.setAttribute("stroke-opacity", "0.4")
          pathEl.setAttribute("stroke-width", "1.5")
        } else {
          pathEl.setAttribute("stroke", "currentColor")
          pathEl.setAttribute("stroke-opacity", "0.05")
          pathEl.setAttribute("stroke-width", "1")
        }
      }
      // Tooltip segue a partícula sob o cursor.
      const tip = tipRef.current
      if (tip) {
        const hi = hoveredRef.current
        const pos = hi != null ? positions.get(hi) : undefined
        const p = hi != null ? tl.particles[hi] : undefined
        if (pos && p?.tip) {
          if (tipTitleRef.current) tipTitleRef.current.textContent = p.tip.title
          if (tipBodyRef.current) tipBodyRef.current.textContent = p.tip.body
          const flip = pos.x > size.w * 0.55
          tip.style.left = flip ? "auto" : `${pos.x + 16}px`
          tip.style.right = flip ? `${size.w - pos.x + 16}px` : "auto"
          tip.style.top = `${Math.max(8, pos.y - 12)}px`
          tip.style.opacity = "1"
        } else {
          tip.style.opacity = "0"
        }
      }
    }
    render()
    return player.subscribeTime(render)
  }, [size.w])

  const { tpActive, pulses, engineStatus } = player.ui
  const engine = nodes.__ENGINE__
  const client = nodes.__CLIENT__
  const pulsed = new Set(pulses.map((p) => p.node))
  const enginePulseAt = pulses.filter((p) => p.node === "__ENGINE__").map((p) => p.at).pop()

  return (
    <div className="relative h-full w-full">
      <svg
        ref={svgRef}
        className="h-full w-full"
        viewBox={`0 0 ${size.w} ${size.h}`}
        role="img"
        aria-label="Grafo da federação: cliente, motor de consultas, vendedores à esquerda e sites de avaliação à direita"
      >
        {endpoints.length === 0 ? (
          <text x={size.w / 2} y={size.h / 2} textAnchor="middle" className="fill-muted-foreground" fontSize="13">
            Execute uma consulta para ver a federação
          </text>
        ) : (
          <>
            {/* rótulos das colunas + legenda */}
            <text x={size.w * 0.13} y={30} textAnchor="middle" fontSize="11" fontWeight={600} fill={COLOR.vendor}>
              Vendedores{nVend ? ` (${nVend})` : ""}
            </text>
            <text x={size.w * 0.87} y={30} textAnchor="middle" fontSize="11" fontWeight={600} fill={COLOR.ratingsite}>
              Sites de avaliação{nRate ? ` (${nRate})` : ""}
            </text>
            <g transform={`translate(${size.w * 0.13 + 60}, ${size.h - 14})`}>
              {LEGEND.map((l, k) => (
                <g key={l.label} transform={`translate(${k * 78}, 0)`}>
                  <circle r={4.5} fill={l.color} />
                  <text x={9} y={3.5} fontSize="10" className="fill-muted-foreground">
                    {l.label}
                  </text>
                </g>
              ))}
            </g>
            <g fill="none">
              {[...endpoints.map((e) => e.id), "__CLIENT__"].map((id) => {
                const e = edges[id]
                if (!e) return null
                return (
                  <path
                    key={id}
                    d={pathOf(e)}
                    stroke="currentColor"
                    strokeOpacity={0.05}
                    ref={(el) => {
                      if (el) edgeEls.current.set(id, el)
                      else edgeEls.current.delete(id)
                    }}
                  />
                )
              })}
            </g>
            <g>
              {endpoints.map((ep) => {
                const p = nodes[ep.id]
                const color = p.kind === "vendor" ? COLOR.vendor : p.kind === "ratingsite" ? COLOR.ratingsite : COLOR.muted
                const isPulsed = pulsed.has(ep.id)
                return (
                  <g key={ep.id} transform={`translate(${p.x},${p.y})`}>
                    <title>{`${ep.id} — ${ep.url}`}</title>
                    <circle r={isPulsed ? epR * 1.25 : epR} className="fill-background" />
                    <circle r={isPulsed ? epR * 1.25 : epR} fill={color}
                      fillOpacity={isPulsed ? 0.45 : 0.16} stroke={color} strokeWidth={1.5} />
                    <text y={3} textAnchor="middle" fontSize="10" fontWeight={600} className="fill-foreground">
                      {shortId(ep.id)}
                    </text>
                    {sideLabels && p.kind !== "other" && (
                      <text
                        x={p.kind === "vendor" ? -(epR + 7) : epR + 7}
                        y={3.5}
                        textAnchor={p.kind === "vendor" ? "end" : "start"}
                        fontSize="8.5"
                        className="fill-muted-foreground"
                      >
                        {ep.id.length > 13 ? ep.id.slice(0, 12) + "…" : ep.id}
                      </text>
                    )}
                  </g>
                )
              })}
              <g transform={`translate(${engine.x},${engine.y})`}>
                {/* fundo opaco: as arestas terminam na borda e nada vaza para dentro */}
                <circle r={ENGINE_R} className="fill-background" />
                <circle r={ENGINE_R} fill={COLOR.engine} fillOpacity={0.18} stroke={COLOR.engine} strokeWidth={1.5} />
                {enginePulseAt != null && (
                  <circle key={enginePulseAt} r={ENGINE_R + 2} fill="none" stroke={COLOR.engine} strokeWidth={2} className="graph-pulse" />
                )}
                <text y={-4} textAnchor="middle" fontSize="11" fontWeight={700} className="fill-foreground">
                  MOTOR
                </text>
                <text y={9} textAnchor="middle" fontSize="9" className="fill-muted-foreground">
                  {engineLabel}
                </text>
                {tpActive && (
                  <text y={-(ENGINE_R + 10)} textAnchor="middle" fontSize="10" fontFamily="ui-monospace, monospace" fill={COLOR.engine}>
                    {tpActive}
                  </text>
                )}
                <text y={ENGINE_R + 18} textAnchor="middle" fontSize="10" className="fill-muted-foreground">
                  {engineStatus}
                </text>
              </g>
              <g transform={`translate(${client.x},${client.y})`}>
                <circle r={pulsed.has("__CLIENT__") ? CLIENT_R + 4 : CLIENT_R} fill="none" stroke="currentColor" strokeOpacity={0.7} strokeWidth={1.5} />
                <text y={-22} textAnchor="middle" fontSize="9.5" fontWeight={600} className="fill-foreground">
                  CLIENTE
                </text>
              </g>
            </g>
            <g ref={particlesRef} />
          </>
        )}
      </svg>
      {/* Tooltip das partículas — posicionado imperativamente junto com o frame. */}
      <div
        ref={tipRef}
        className="pointer-events-none absolute z-10 max-w-sm rounded-md border bg-popover px-3 py-1.5 text-xs text-popover-foreground shadow-md transition-opacity"
        style={{ opacity: 0 }}
      >
        <div ref={tipTitleRef} className="font-medium" />
        <div ref={tipBodyRef} className="mt-0.5 font-mono text-[11px] leading-snug break-words whitespace-pre-wrap text-muted-foreground" />
      </div>
    </div>
  )
}
