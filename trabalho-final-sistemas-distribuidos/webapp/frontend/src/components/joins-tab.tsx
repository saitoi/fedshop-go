/** Aba "Joins": o estado dos bindings dentro do motor em cada instante.
 *
 * Em cima, a tabela com as tuplas ATUAIS no motor (amostra do último passo
 * aplicado) e o total, com a seta de crescimento/redução. Embaixo, a linha do
 * tempo de passos (semear, join, union, optional, filter, pós-processamento) —
 * clicar num passo faz seek do player até aquele momento; o passo selecionado
 * abre o detalhe esquerda ⋈ direita → resultado com as amostras reais.
 */

import { ArrowDown, ArrowRight, ArrowUp } from "lucide-react"
import { useSyncExternalStore } from "react"

import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { fmt, type EngineStep } from "@/lib/compile"
import { player } from "@/lib/player"
import type { SampleRow } from "@/lib/types"
import { cn } from "@/lib/utils"

const STEP_ICON: Record<EngineStep["kind"], string> = {
  seed: "▶",
  join: "⋈",
  union: "∪",
  optional: "⟕",
  filter: "σ",
  postprocess: "✂",
}

function shortVal(v: string): string {
  const s = v.replace(/^https?:\/\/(www\.)?/, "")
  return s.length > 42 ? s.slice(0, 40) + "…" : s
}

function BindingsTable({ rows, vars, caption }: { rows: SampleRow[]; vars: string[]; caption?: string }) {
  const cols = vars.length ? vars : rows.length ? Object.keys(rows[0]) : []
  if (!rows.length) {
    return <p className="px-1 py-2 text-xs text-muted-foreground">{caption ?? "sem linhas"}</p>
  }
  return (
    <div className="flex min-w-0 flex-col gap-1">
      {caption && <span className="text-[11px] text-muted-foreground">{caption}</span>}
      <div className="max-h-56 overflow-auto rounded-md border">
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
            {rows.map((row, i) => (
              <TableRow key={i}>
                {cols.map((c) => (
                  <TableCell key={c} title={row[c] ?? ""} className="max-w-56 truncate px-2 py-1 font-mono">
                    {shortVal(row[c] ?? "")}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}

function DeltaBadge({ from, to }: { from: number | null; to: number | null }) {
  if (from == null || to == null || from === to) return null
  const grew = to > from
  return (
    <Badge variant="outline" className={cn("gap-1", grew ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400")}>
      {grew ? <ArrowUp className="size-3" /> : <ArrowDown className="size-3" />}
      {grew ? "+" : ""}
      {fmt.format(to - from)}
    </Badge>
  )
}

export function JoinsTab() {
  useSyncExternalStore(player.subscribeUI, player.getUIVersion)
  const tl = player.timeline
  const steps = tl?.steps ?? []
  const current = player.ui.currentStep

  if (!steps.length) {
    return (
      <Empty>
        <EmptyHeader>
          <EmptyTitle>Nenhum join ainda</EmptyTitle>
          <EmptyDescription>
            Execute uma consulta e avance a reprodução até a fase de execução: cada passo (semear, join,
            UNION, OPTIONAL, FILTER) aparece aqui com as tuplas reais dentro do motor.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  }

  const active: EngineStep | null = current >= 0 ? steps[current] : null

  return (
    <div className="flex flex-col gap-3">
      <Card size="sm">
        <CardHeader>
          <CardTitle className="flex flex-wrap items-center gap-2 text-sm">
            Bindings no motor agora
            {active?.outCount != null && (
              <Badge variant="secondary" className="font-mono tabular-nums">
                {fmt.format(active.outCount)} tuplas
              </Badge>
            )}
            {active && <DeltaBadge from={active.inCount} to={active.outCount} />}
          </CardTitle>
          <CardDescription>
            {active
              ? `Após o passo ${active.index + 1}/${steps.length}: ${active.title}`
              : "Antes do primeiro passo o motor ainda não tem bindings."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {active ? (
            active.sample.length ? (
              <BindingsTable
                rows={active.sample}
                vars={active.outVars}
                caption={
                  active.outCount != null && active.sample.length < active.outCount
                    ? `mostrando ${active.sample.length} de ${fmt.format(active.outCount)} tuplas`
                    : undefined
                }
              />
            ) : (
              <p className="text-xs text-muted-foreground">
                {active.kind === "postprocess"
                  ? "Este passo não registra amostra — a tabela final está na aba Resultados."
                  : "Sem tuplas neste passo."}
              </p>
            )
          ) : (
            <p className="text-xs text-muted-foreground">—</p>
          )}
        </CardContent>
      </Card>

      <Card size="sm">
        <CardHeader>
          <CardTitle className="text-sm">Passos de execução</CardTitle>
          <CardDescription>Clique num passo para levar a animação até ele.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-1">
          {steps.map((s) => {
            const isActive = s.index === current
            const isPast = s.index < current
            return (
              <button
                key={s.index}
                type="button"
                onClick={() => {
                  player.playing = false
                  player.seek(s.t + 1)
                }}
                className={cn(
                  "flex items-center gap-2 rounded-md border px-2 py-1.5 text-left text-xs transition-colors hover:bg-accent",
                  isActive && "border-primary bg-accent",
                  !isActive && !isPast && "opacity-55"
                )}
              >
                <span className="w-5 text-center font-mono text-sm">{STEP_ICON[s.kind]}</span>
                <span className="min-w-0 flex-1">
                  <span className="font-medium">{s.title}</span>
                  <span className="block truncate text-muted-foreground">{s.detail}</span>
                </span>
                <DeltaBadge from={s.inCount} to={s.outCount} />
                {s.outCount != null && (
                  <Badge variant="outline" className="shrink-0 font-mono tabular-nums">
                    {fmt.format(s.outCount)}
                  </Badge>
                )}
              </button>
            )
          })}
        </CardContent>
      </Card>

      {active && (active.kind === "join" || active.kind === "optional") && (
        <Card size="sm">
          <CardHeader>
            <CardTitle className="flex flex-wrap items-center gap-2 text-sm">
              Detalhe do passo: {active.title}
              {(active.ev.shared_vars ?? []).map((v) => (
                <Badge key={v} variant="secondary" className="font-mono">
                  ?{v}
                </Badge>
              ))}
            </CardTitle>
            <CardDescription>
              O motor casa as tuplas dos dois lados pelas variáveis compartilhadas (hash join).
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <div className="grid grid-cols-1 items-start gap-3 xl:grid-cols-2">
              <BindingsTable
                rows={active.ev.left_sample ?? []}
                vars={active.ev.left_vars ?? []}
                caption={`esquerda — ${fmt.format(active.ev.left ?? 0)} tuplas (acumulado no motor)`}
              />
              <BindingsTable
                rows={active.ev.right_sample ?? []}
                vars={active.ev.right_vars ?? []}
                caption={`direita — ${fmt.format(active.ev.right ?? 0)} tuplas (${active.ev.tp_id ?? ""} dos endpoints)`}
              />
            </div>
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <ArrowRight className="size-3.5" />
              resultado: {fmt.format(active.outCount ?? 0)} tuplas (tabela “Bindings no motor agora”)
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
