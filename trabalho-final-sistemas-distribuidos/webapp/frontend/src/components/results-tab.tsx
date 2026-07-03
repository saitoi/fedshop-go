/** Aba "Resultados": a tabela final entregue ao cliente + métricas da execução. */

import { useSyncExternalStore } from "react"

import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { fmt } from "@/lib/compile"
import { player } from "@/lib/player"

export function ResultsTab() {
  useSyncExternalStore(player.subscribeUI, player.getUIVersion)
  const ev = player.ui.results

  if (!ev) {
    return (
      <Empty>
        <EmptyHeader>
          <EmptyTitle>Sem resultados ainda</EmptyTitle>
          <EmptyDescription>
            A tabela final aparece quando a animação chega à entrega da resposta ao cliente.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  }

  const cols = ev.columns ?? []
  const sample = ev.sample ?? []

  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2 text-sm">
          Resposta ao cliente
          <Badge variant="secondary" className="font-mono tabular-nums">
            {fmt.format(ev.rows ?? 0)} linha(s)
          </Badge>
          <Badge variant="outline" className="font-mono tabular-nums">
            {ev.http_requests} req. HTTP
          </Badge>
          <Badge variant="outline" className="font-mono tabular-nums">
            {(ev.total_seconds ?? 0).toFixed(2)}s reais
          </Badge>
        </CardTitle>
        {(ev.rows ?? 0) > sample.length && (
          <CardDescription>Mostrando {sample.length} de {fmt.format(ev.rows ?? 0)} linhas.</CardDescription>
        )}
      </CardHeader>
      <CardContent>
        {sample.length ? (
          <div className="max-h-[28rem] overflow-auto rounded-md border">
            <Table className="text-[11px]">
              <TableHeader>
                <TableRow>
                  {cols.map((c) => (
                    <TableHead key={c} className="h-7 px-2 font-mono">
                      ?{c}
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {sample.map((row, i) => (
                  <TableRow key={i}>
                    {cols.map((c) => (
                      <TableCell key={c} title={row[c] ?? ""} className="max-w-64 truncate px-2 py-1 font-mono">
                        {row[c] ?? ""}
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">A consulta não retornou linhas.</p>
        )}
      </CardContent>
    </Card>
  )
}
