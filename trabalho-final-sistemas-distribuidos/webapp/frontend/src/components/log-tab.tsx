/** Aba "Log": narrativa de tudo que o motor fez, com o tempo real de execução. */

import * as React from "react"
import { useSyncExternalStore } from "react"

import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty"
import { player } from "@/lib/player"

export function LogTab() {
  useSyncExternalStore(player.subscribeUI, player.getUIVersion)
  const endRef = React.useRef<HTMLDivElement>(null)
  const log = player.ui.log

  React.useEffect(() => {
    endRef.current?.scrollIntoView({ block: "nearest" })
  }, [log.length])

  if (!log.length) {
    return (
      <Empty>
        <EmptyHeader>
          <EmptyTitle>Log vazio</EmptyTitle>
          <EmptyDescription>Os eventos da execução aparecem aqui conforme a animação avança.</EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  }

  return (
    <div className="flex flex-col gap-1.5">
      {log.map((e, i) => (
        <div key={i} className="flex items-baseline gap-2 text-xs">
          <span className="mt-1 size-2 shrink-0 self-start rounded-full" style={{ background: e.dot }} />
          <span className="w-12 shrink-0 text-right font-mono text-muted-foreground tabular-nums">
            {e.real.toFixed(2)}s
          </span>
          <span className="min-w-0">{e.msg}</span>
        </div>
      ))}
      <div ref={endRef} />
    </div>
  )
}
