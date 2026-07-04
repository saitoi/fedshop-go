/** Stepper de progresso: seleção de fontes → planejamento → execução → resultados.
 * Cada passo reflete uma Phase da timeline; clicar leva a reprodução ao início
 * da fase. Assina os dois canais do player: "ui" (contadores) e "time" (playhead
 * decide pendente/ativo/concluído).
 */

import { Check, ChevronRight } from "lucide-react"
import { useSyncExternalStore } from "react"

import { Item, ItemContent, ItemDescription, ItemMedia, ItemTitle } from "@/components/ui/item"
import { fmt, type Phase, type PhaseId } from "@/lib/compile"
import { player } from "@/lib/player"
import { cn } from "@/lib/utils"

const STEPS: { id: PhaseId; n: number; label: string }[] = [
  { id: "sources", n: 1, label: "Seleção de fontes (ASK)" },
  { id: "planning", n: 2, label: "Planejamento" },
  { id: "execution", n: 3, label: "Execução (binding)" },
  { id: "results", n: 4, label: "Resultados" },
]

type Status = "pending" | "active" | "done"

function statusOf(phase: Phase | undefined, playhead: number): Status {
  if (!phase || playhead < phase.start) return "pending"
  if (phase.end != null && playhead >= phase.end) return "done"
  return "active"
}

/** Texto do chip enquanto a fase está ativa (contadores ao vivo). */
function liveMetric(id: PhaseId): string {
  const ui = player.ui
  switch (id) {
    case "sources":
      return `${ui.counters.ask} ASKs · ${ui.counters.pos} ✓`
    case "planning":
      return "ordenando padrões…"
    case "execution":
      return `${ui.counters.sel} SELECTs · ${ui.bind} bindings`
    case "results":
      return `${ui.rows} linha(s)`
    default:
      return ""
  }
}

export function PhaseStepper() {
  useSyncExternalStore(player.subscribeUI, player.getUIVersion)
  useSyncExternalStore(player.subscribeTime, player.getTimeVersion)

  const phases = player.timeline?.phases ?? []
  const playhead = player.playhead
  const rows = player.ui.results?.rows

  return (
    <div className="flex items-stretch gap-1 overflow-x-auto border-b px-4 py-2" role="group" aria-label="Progresso da execução">
      {STEPS.map((step, k) => {
        const phase = phases.find((p) => p.id === step.id)
        const status = statusOf(phase, playhead)
        const detail =
          status === "done"
            ? step.id === "results" && rows != null
              ? phase?.metric ?? `${fmt.format(rows)} linha(s)`
              : phase?.metric ?? "concluído"
            : status === "active"
              ? liveMetric(step.id)
              : "—"
        return (
          <div key={step.id} className="flex min-w-0 flex-1 items-center gap-1">
            <Item
              asChild
              size="xs"
              variant="outline"
              className={cn(
                "min-w-0 flex-1 cursor-pointer flex-nowrap hover:bg-accent",
                status === "active" && "border-primary bg-primary/5",
                status === "pending" && "opacity-55"
              )}
            >
              <button
                type="button"
                disabled={!phase}
                onClick={() => phase && player.seek(phase.start + 1)}
                title={phase ? `Ir para: ${step.label}` : undefined}
              >
                <ItemMedia>
                  <span
                    className={cn(
                      "flex size-5 shrink-0 items-center justify-center rounded-full border text-[10px] font-semibold",
                      status === "done" && "border-primary bg-primary text-primary-foreground",
                      status === "active" && "border-primary text-primary"
                    )}
                  >
                    {status === "done" ? <Check className="size-3" /> : step.n}
                  </span>
                </ItemMedia>
                <ItemContent className="min-w-0">
                  <ItemTitle className={cn("text-xs", status === "active" && "text-primary")}>{step.label}</ItemTitle>
                  <ItemDescription className="line-clamp-1 text-[11px]">{detail}</ItemDescription>
                </ItemContent>
              </button>
            </Item>
            {k < STEPS.length - 1 && <ChevronRight className="size-4 shrink-0 text-muted-foreground/50" aria-hidden />}
          </div>
        )
      })}
    </div>
  )
}
