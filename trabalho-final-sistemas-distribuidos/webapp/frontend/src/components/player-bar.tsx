/** Controles de reprodução: play/pausa, passo, timeline com fases, velocidade. */

import { Pause, Play, SkipBack, SkipForward } from "lucide-react"
import * as React from "react"
import { useSyncExternalStore } from "react"

import { Button } from "@/components/ui/button"
import { Kbd } from "@/components/ui/kbd"
import { Slider } from "@/components/ui/slider"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { player } from "@/lib/player"

export function PlayerBar() {
  useSyncExternalStore(player.subscribeTime, player.getTimeVersion)
  const [speedExp, setSpeedExp] = React.useState(0)

  const tl = player.timeline
  const total = tl?.total ?? 1
  const speed = Math.pow(2, speedExp)

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName
      if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA" || (e.target as HTMLElement).isContentEditable) return
      if (e.code === "Space") {
        e.preventDefault()
        player.togglePlay()
      }
      if (e.code === "ArrowRight") player.stepMark(1)
      if (e.code === "ArrowLeft") player.stepMark(-1)
    }
    document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
  }, [])

  return (
    <div className="flex flex-wrap items-center gap-3 border-t px-4 py-2 lg:flex-nowrap">
      <div className="flex items-center gap-1">
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="ghost" size="icon-sm" disabled={!tl} onClick={() => player.stepMark(-1)}>
              <SkipBack />
            </Button>
          </TooltipTrigger>
          <TooltipContent>
            Evento anterior <Kbd>←</Kbd>
          </TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="outline" size="icon-sm" disabled={!tl} onClick={() => player.togglePlay()}>
              {player.playing ? <Pause /> : <Play />}
            </Button>
          </TooltipTrigger>
          <TooltipContent>
            Reproduzir / pausar <Kbd>espaço</Kbd>
          </TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="ghost" size="icon-sm" disabled={!tl} onClick={() => player.stepMark(1)}>
              <SkipForward />
            </Button>
          </TooltipTrigger>
          <TooltipContent>
            Próximo evento <Kbd>→</Kbd>
          </TooltipContent>
        </Tooltip>
      </div>

      <div className="relative min-w-0 flex-1">
        {tl && (
          <div className="pointer-events-none absolute -top-1.5 left-0 flex h-1 w-full overflow-hidden rounded-full">
            {tl.phases.map((ph, i) => (
              <div
                key={i}
                title={ph.name}
                style={{
                  width: `${(((ph.end ?? tl.total) - ph.start) / tl.total) * 100}%`,
                  background: ph.color,
                  opacity: 0.65,
                }}
              />
            ))}
          </div>
        )}
        <Slider
          value={[player.playhead]}
          min={0}
          max={total}
          step={total / 1000}
          disabled={!tl}
          onValueChange={([v]) => {
            player.playing = false
            player.seek(v)
          }}
          aria-label="Posição na linha do tempo"
        />
      </div>

      <span className="w-14 text-right font-mono text-xs text-muted-foreground tabular-nums">
        {(player.playhead / 1000).toFixed(1)}s
      </span>

      <div className="order-last flex w-full basis-full items-center gap-2 lg:order-none lg:w-40 lg:basis-auto">
        <Slider
          value={[speedExp]}
          min={-2}
          max={3}
          step={0.5}
          onValueChange={([v]) => {
            setSpeedExp(v)
            player.setSpeed(Math.pow(2, v))
          }}
          aria-label="Velocidade da animação"
        />
        <span className="w-10 font-mono text-xs text-muted-foreground tabular-nums">
          {speed >= 1 ? `${speed.toFixed(speed >= 2 ? 0 : 1)}×` : `${speed.toFixed(2)}×`}
        </span>
      </div>
    </div>
  )
}
