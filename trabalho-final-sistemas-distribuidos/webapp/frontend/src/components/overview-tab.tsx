/** Aba "Visão geral": operação em curso (SPARQL integral), matriz de seleção
 * de fontes (triplas × endpoints) e métricas acumuladas. */

import { useSyncExternalStore } from "react"

import { SparqlView } from "@/components/sparql-view"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty"
import { COLOR, fmt, shortId } from "@/lib/compile"
import { player } from "@/lib/player"

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5 rounded-lg border px-3 py-2">
      <span className="text-[11px] text-muted-foreground">{label}</span>
      <span className="truncate font-mono text-sm font-semibold tabular-nums">{value}</span>
    </div>
  )
}

export function OverviewTab() {
  useSyncExternalStore(player.subscribeUI, player.getUIVersion)
  const ui = player.ui

  if (!ui.triples.length) {
    return (
      <Empty>
        <EmptyHeader>
          <EmptyTitle>Nenhuma execução ainda</EmptyTitle>
          <EmptyDescription>
            Escolha uma consulta, a federação e o motor no topo e clique em Executar. A consulta roda de
            verdade contra os endpoints e a animação reproduz cada operação.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  }

  return (
    <div className="flex flex-col gap-3">
      <Card size="sm">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm">
            Operação atual
            {ui.op && (
              <Badge
                style={{ background: ui.op.op === "ASK" ? COLOR.ask : COLOR.select, color: "#fff" }}
              >
                {ui.op.op}
              </Badge>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          {ui.op ? (
            <>
              <div className="text-xs text-muted-foreground">
                <span className="font-mono font-semibold text-foreground">{ui.op.tp}</span>
                {" → "}
                <span className="font-mono">{ui.op.endpoint}</span>
                {" · "}
                {(ui.op.realDur * 1000).toFixed(0)}ms reais · {ui.op.status}
              </div>
              <div className="max-h-44 overflow-auto rounded-md border bg-muted/40 p-2">
                <SparqlView text={ui.op.sparql} />
              </div>
            </>
          ) : (
            <p className="text-xs text-muted-foreground">Nenhuma requisição em curso.</p>
          )}
        </CardContent>
      </Card>

      <Card size="sm">
        <CardHeader>
          <CardTitle className="text-sm">Seleção de fontes (ASK)</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="w-full overflow-x-auto">
            <table className="text-[11px]">
              <thead>
                <tr>
                  <th className="pr-2 text-left font-medium text-muted-foreground">tp</th>
                  {ui.endpoints.map((ep) => (
                    <th key={ep.id} title={ep.id} className="px-1 text-center font-medium text-muted-foreground">
                      {shortId(ep.id)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {ui.triples.map((tp) => (
                  <tr
                    key={tp.id}
                    className={tp.id === ui.tpActive ? "bg-accent" : undefined}
                  >
                    <th title={tp.sparql} className="pr-2 text-left font-mono font-medium">
                      {tp.id}
                    </th>
                    {ui.endpoints.map((ep) => {
                      const v = ui.matrix.get(`${tp.id}|${ep.id}`)
                      return (
                        <td key={ep.id} className="px-1 text-center">
                          {v === undefined ? (
                            <span className="text-muted-foreground/40">·</span>
                          ) : v ? (
                            <span style={{ color: COLOR.ok }}>✓</span>
                          ) : (
                            <span className="text-muted-foreground/60">✕</span>
                          )}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-3 gap-2">
        <Metric label="ASKs enviados" value={fmt.format(ui.counters.ask)} />
        <Metric label="ASKs positivos" value={fmt.format(ui.counters.pos)} />
        <Metric label="SELECTs" value={fmt.format(ui.counters.sel)} />
        <Metric label="Bindings no motor" value={ui.bind} />
        <Metric label="Linhas finais" value={ui.rows} />
        <Metric label="Tempo real" value={ui.time} />
      </div>
    </div>
  )
}
