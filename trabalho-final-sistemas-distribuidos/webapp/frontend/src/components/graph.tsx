/** Grafo da federação: vendedores em coluna à esquerda, sites de avaliação à
 * direita, MOTOR ao centro e um cliente pequeno acima dele.
 * Nós/arestas são React; as partículas em voo são desenhadas imperativamente a
 * cada frame (assinatura "time" do player) para não re-renderizar a árvore.
 * Hover numa partícula mostra a tripla enviada ou o resultado que ela carrega.
 */

import * as React from "react"
import { useSyncExternalStore } from "react"

import { COLOR, shortId } from "@/lib/compile"
import { player } from "@/lib/player"

const SVGNS = "http://www.w3.org/2000/svg"

interface NodePos {
  x: number
  y: number
  kind: "vendor" | "ratingsite" | "other" | "engine" | "client"
}

const COL_TOP = 64

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
  const hoveredRef = React.useRef<number | null>(null)
  const tipRef = React.useRef<HTMLDivElement>(null)
  const tipTitleRef = React.useRef<HTMLDivElement>(null)
  const tipBodyRef = React.useRef<HTMLDivElement>(null)
  const [size, setSize] = React.useState({ w: 800, h: 520 })

  useSyncExternalStore(player.subscribeUI, player.getUIVersion)

  const endpoints = player.ui.endpoints
  const nodes = React.useMemo(
    () => layout(endpoints.map((e) => e.id), size.w, size.h),
    [endpoints, size]
  )
  const nodesRef = React.useRef(nodes)
  React.useEffect(() => {
    nodesRef.current = nodes
  }, [nodes])

  React.useEffect(() => {
    const el = svgRef.current
    if (!el) return
    const ro = new ResizeObserver(() => {
      setSize({ w: el.clientWidth, h: el.clientHeight })
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // Partículas + tooltip de hover: desenhados por frame, fora do ciclo do React.
  React.useEffect(() => {
    const render = () => {
      const g = particlesRef.current
      const tl = player.timeline
      if (!g || !tl) return
      const t = player.playhead
      const active = new Set<number>()
      const positions = new Map<number, { x: number; y: number }>()
      tl.particles.forEach((p, idx) => {
        if (t < p.t || t > p.t + p.dur) return
        const from = nodesRef.current[p.from]
        const to = nodesRef.current[p.to]
        if (!from || !to) return
        active.add(idx)
        const f = (t - p.t) / p.dur
        const x = from.x + (to.x - from.x) * f
        const y = from.y + (to.y - from.y) * f
        positions.set(idx, { x, y })
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
  const nVend = endpoints.filter((e) => e.id.startsWith("vendor")).length
  const nRate = endpoints.filter((e) => e.id.startsWith("ratingsite")).length
  const epR = Math.max(13, Math.min(22, ((size.h - COL_TOP - 30) / Math.max(2, Math.max(nVend, nRate))) * 0.38))
  const engine = nodes.__ENGINE__
  const client = nodes.__CLIENT__
  const pulsed = new Set(pulses.map((p) => p.node))

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
            <g>
              {endpoints.map((ep) => {
                const p = nodes[ep.id]
                return (
                  <line key={ep.id} x1={engine.x} y1={engine.y} x2={p.x} y2={p.y}
                    stroke="currentColor" strokeOpacity={0.08} />
                )
              })}
              <line x1={client.x} y1={client.y} x2={engine.x} y2={engine.y}
                stroke="currentColor" strokeOpacity={0.08} />
            </g>
            <g>
              {endpoints.map((ep) => {
                const p = nodes[ep.id]
                const color = p.kind === "vendor" ? COLOR.vendor : p.kind === "ratingsite" ? COLOR.ratingsite : COLOR.muted
                const isPulsed = pulsed.has(ep.id)
                return (
                  <g key={ep.id} transform={`translate(${p.x},${p.y})`}>
                    <circle r={isPulsed ? epR * 1.25 : epR} fill={color}
                      fillOpacity={isPulsed ? 0.45 : 0.16} stroke={color} strokeWidth={1.5} />
                    <text y={3} textAnchor="middle" fontSize="10" fontWeight={600} className="fill-foreground">
                      {shortId(ep.id)}
                    </text>
                    <text
                      x={p.kind === "vendor" ? -(epR + 7) : p.kind === "ratingsite" ? epR + 7 : 0}
                      y={p.kind === "other" ? epR + 11 : 3.5}
                      textAnchor={p.kind === "vendor" ? "end" : p.kind === "ratingsite" ? "start" : "middle"}
                      fontSize="8.5"
                      className="fill-muted-foreground"
                    >
                      {ep.id.length > 13 ? ep.id.slice(0, 12) + "…" : ep.id}
                    </text>
                  </g>
                )
              })}
              <g transform={`translate(${engine.x},${engine.y})`}>
                <circle r={pulsed.has("__ENGINE__") ? 50 : 40} fill={COLOR.engine}
                  fillOpacity={pulsed.has("__ENGINE__") ? 0.4 : 0.2} stroke={COLOR.engine} strokeWidth={1.5} />
                <text y={-4} textAnchor="middle" fontSize="11" fontWeight={700} className="fill-foreground">
                  MOTOR
                </text>
                <text y={9} textAnchor="middle" fontSize="9" className="fill-muted-foreground">
                  {engineLabel}
                </text>
                {tpActive && (
                  <text y={-50} textAnchor="middle" fontSize="10" fontFamily="ui-monospace, monospace" fill={COLOR.engine}>
                    {tpActive}
                  </text>
                )}
                <text y={58} textAnchor="middle" fontSize="10" className="fill-muted-foreground">
                  {engineStatus}
                </text>
              </g>
              <g transform={`translate(${client.x},${client.y})`}>
                <circle r={pulsed.has("__CLIENT__") ? 19 : 15} fill="none" stroke="currentColor" strokeOpacity={0.7} strokeWidth={1.5} />
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
        className="pointer-events-none absolute z-10 max-w-xs rounded-md border bg-popover px-3 py-1.5 text-xs text-popover-foreground shadow-md transition-opacity"
        style={{ opacity: 0 }}
      >
        <div ref={tipTitleRef} className="font-medium" />
        <div ref={tipBodyRef} className="mt-0.5 font-mono text-[11px] leading-snug break-words text-muted-foreground" />
      </div>
    </div>
  )
}
