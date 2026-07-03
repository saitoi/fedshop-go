/** Grafo da federação: CLIENTE no topo, MOTOR ao centro, endpoints em círculo.
 * Nós/arestas são React; as partículas em voo são desenhadas imperativamente a
 * cada frame (assinatura "time" do player) para não re-renderizar a árvore.
 */

import * as React from "react"
import { useSyncExternalStore } from "react"

import { COLOR, shortId } from "@/lib/compile"
import { player } from "@/lib/player"

const SVGNS = "http://www.w3.org/2000/svg"

interface NodePos {
  x: number
  y: number
  kind: "vendor" | "ratingsite" | "engine" | "client"
}

function layout(endpointIds: string[], W: number, H: number): Record<string, NodePos> {
  const nodes: Record<string, NodePos> = {}
  const cx = W / 2
  const cy = H * 0.52
  const R = Math.min(W * 0.38, H * 0.4)
  const n = endpointIds.length
  const gap = Math.PI / 2.4 // abertura no topo para o cliente
  const span = 2 * Math.PI - gap
  endpointIds.forEach((id, i) => {
    const angle = -Math.PI / 2 + gap / 2 + span * ((i + 0.5) / n)
    nodes[id] = {
      x: cx + R * Math.cos(angle),
      y: cy + R * Math.sin(angle),
      kind: id.startsWith("ratingsite") ? "ratingsite" : "vendor",
    }
  })
  nodes.__ENGINE__ = { x: cx, y: cy, kind: "engine" }
  nodes.__CLIENT__ = { x: cx, y: Math.max(44, cy - R), kind: "client" }
  return nodes
}

export function Graph({ engineLabel }: { engineLabel: string }) {
  const svgRef = React.useRef<SVGSVGElement>(null)
  const particlesRef = React.useRef<SVGGElement>(null)
  const particleEls = React.useRef(new Map<number, SVGGElement>())
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

  // Partículas: desenhadas por frame, fora do ciclo do React.
  React.useEffect(() => {
    const render = () => {
      const g = particlesRef.current
      const tl = player.timeline
      if (!g || !tl) return
      const t = player.playhead
      const active = new Set<number>()
      tl.particles.forEach((p, idx) => {
        if (t < p.t || t > p.t + p.dur) return
        const from = nodesRef.current[p.from]
        const to = nodesRef.current[p.to]
        if (!from || !to) return
        active.add(idx)
        const f = (t - p.t) / p.dur
        const x = from.x + (to.x - from.x) * f
        const y = from.y + (to.y - from.y) * f
        let elG = particleEls.current.get(idx)
        if (!elG) {
          elG = document.createElementNS(SVGNS, "g") as SVGGElement
          const c = document.createElementNS(SVGNS, "circle")
          c.setAttribute("r", p.big ? "7" : "5")
          c.setAttribute("fill", p.color)
          elG.appendChild(c)
          const label = document.createElementNS(SVGNS, "text")
          label.setAttribute("y", "-9")
          label.setAttribute("fill", p.color)
          label.setAttribute("text-anchor", "middle")
          label.setAttribute("font-size", "10")
          label.setAttribute("font-family", "ui-monospace, monospace")
          label.textContent = p.label || ""
          elG.appendChild(label)
          g.appendChild(elG)
          particleEls.current.set(idx, elG)
        }
        elG.setAttribute("transform", `translate(${x},${y})`)
      })
      for (const [idx, elG] of particleEls.current) {
        if (!active.has(idx)) {
          elG.remove()
          particleEls.current.delete(idx)
        }
      }
    }
    render()
    return player.subscribeTime(render)
  }, [])

  const { tpActive, pulses, engineStatus } = player.ui
  const epR = Math.max(14, Math.min(24, 260 / Math.max(1, endpoints.length)))
  const engine = nodes.__ENGINE__
  const client = nodes.__CLIENT__
  const pulsed = new Set(pulses.map((p) => p.node))

  return (
    <svg
      ref={svgRef}
      className="h-full w-full"
      viewBox={`0 0 ${size.w} ${size.h}`}
      role="img"
      aria-label="Grafo da federação: cliente, motor de consultas e endpoints"
    >
      {endpoints.length === 0 ? (
        <text x={size.w / 2} y={size.h / 2} textAnchor="middle" className="fill-muted-foreground" fontSize="13">
          Execute uma consulta para ver a federação
        </text>
      ) : (
        <>
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
              const color = p.kind === "vendor" ? COLOR.vendor : COLOR.ratingsite
              const isPulsed = pulsed.has(ep.id)
              return (
                <g key={ep.id} transform={`translate(${p.x},${p.y})`}>
                  <circle r={isPulsed ? epR * 1.25 : epR} fill={color}
                    fillOpacity={isPulsed ? 0.45 : 0.16} stroke={color} strokeWidth={1.5} />
                  <text y={3} textAnchor="middle" fontSize="10" fontWeight={600} className="fill-foreground">
                    {shortId(ep.id)}
                  </text>
                  <text y={epR + 11} textAnchor="middle" fontSize="8.5" className="fill-muted-foreground">
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
              <circle r={pulsed.has("__CLIENT__") ? 30 : 24} fill="none" stroke="currentColor" strokeOpacity={0.7} strokeWidth={1.5} />
              <text y={3} textAnchor="middle" fontSize="10" fontWeight={600} className="fill-foreground">
                CLIENTE
              </text>
            </g>
          </g>
          <g ref={particlesRef} />
        </>
      )}
    </svg>
  )
}
