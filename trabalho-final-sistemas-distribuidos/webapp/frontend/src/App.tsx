import { Play } from "lucide-react"
import * as React from "react"
import { useSyncExternalStore } from "react"

import { Graph } from "@/components/graph"
import { JoinsTab } from "@/components/joins-tab"
import { LogTab } from "@/components/log-tab"
import { OverviewTab } from "@/components/overview-tab"
import { PlayerBar } from "@/components/player-bar"
import { ResultsTab } from "@/components/results-tab"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Spinner } from "@/components/ui/spinner"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { TooltipProvider } from "@/components/ui/tooltip"
import { executeQuery, fetchConfigs, fetchEngines, fetchQueries, fetchQueryText } from "@/lib/api"
import { compile } from "@/lib/compile"
import { player } from "@/lib/player"
import type { ConfigOption, EngineOption, QueryOption } from "@/lib/types"

function HeaderSelect<T extends { id: string; label: string }>({
  label,
  items,
  value,
  onChange,
  width,
}: {
  label: string
  items: T[]
  value: string
  onChange: (v: string) => void
  width: string
}) {
  return (
    <div className="flex items-center gap-2">
      <Label className="text-xs text-muted-foreground">{label}</Label>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger size="sm" className={width}>
          <SelectValue placeholder="—" />
        </SelectTrigger>
        <SelectContent>
          {items.map((it) => (
            <SelectItem key={it.id} value={it.id}>
              {it.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}

export function App() {
  useSyncExternalStore(player.subscribeUI, player.getUIVersion)

  const [queries, setQueries] = React.useState<QueryOption[]>([])
  const [configs, setConfigs] = React.useState<ConfigOption[]>([])
  const [engines, setEngines] = React.useState<EngineOption[]>([])
  const [queryId, setQueryId] = React.useState("")
  const [configId, setConfigId] = React.useState("")
  const [engineId, setEngineId] = React.useState("pyfedx")
  const [running, setRunning] = React.useState(false)
  const [fetchError, setFetchError] = React.useState<string | null>(null)

  React.useEffect(() => {
    Promise.all([fetchQueries(), fetchConfigs(), fetchEngines()])
      .then(([qs, cs, es]) => {
        setQueries(qs)
        setConfigs(cs)
        setEngines(es)
        if (qs.length) setQueryId(qs[0].id)
        if (cs.length) setConfigId(cs[0].id)
        if (es.length) setEngineId(es[0].id)
      })
      .catch((e) => setFetchError(`Falha ao carregar consultas/federações: ${e.message}`))
  }, [])

  const run = async () => {
    if (!queryId || !configId || running) return
    setRunning(true)
    setFetchError(null)
    try {
      const query = await fetchQueryText(queryId)
      const trace = await executeQuery({ query, config_id: configId, engine: engineId, timeout: 60 })
      player.load(compile(trace.events))
      player.playing = true
    } catch (e) {
      setFetchError(`Falha ao executar: ${(e as Error).message}`)
    } finally {
      setRunning(false)
    }
  }

  const ui = player.ui
  const engineLabel = engineId === "fedshop-go" ? "fedshop-go" : "pyfedx"

  return (
    <TooltipProvider>
      <div className="flex h-svh flex-col">
        <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b px-4 py-2.5">
          <h1 className="text-sm font-semibold">
            Visualizador do motor federado
            <span className="ml-2 text-xs font-normal text-muted-foreground">FedShop · SPARQL</span>
          </h1>
          <div className="flex flex-1 flex-wrap items-center justify-end gap-3">
            <HeaderSelect label="Consulta" items={queries} value={queryId} onChange={setQueryId} width="w-44" />
            <HeaderSelect label="Federação" items={configs} value={configId} onChange={setConfigId} width="w-28" />
            <HeaderSelect label="Motor" items={engines} value={engineId} onChange={setEngineId} width="w-52" />
            <Button size="sm" onClick={run} disabled={running || !queryId || !configId}>
              {running ? <Spinner /> : <Play />}
              {running ? "Executando…" : "Executar"}
            </Button>
            <Badge variant={ui.errorMessage ? "destructive" : "secondary"}>
              {running ? "executando de verdade…" : ui.phaseLabel}
            </Badge>
          </div>
        </header>

        {fetchError && (
          <Alert variant="destructive" className="mx-4 mt-3">
            <AlertTitle>Erro</AlertTitle>
            <AlertDescription>{fetchError}</AlertDescription>
          </Alert>
        )}
        {ui.errorMessage && (
          <Alert variant="destructive" className="mx-4 mt-3">
            <AlertTitle>A execução terminou com erro</AlertTitle>
            <AlertDescription>{ui.errorMessage}</AlertDescription>
          </Alert>
        )}

        <main className="grid min-h-0 flex-1 grid-cols-1 gap-0 lg:grid-cols-[minmax(0,1fr)_minmax(24rem,30rem)]">
          <section className="flex min-h-0 flex-col border-r">
            <div className="min-h-0 flex-1">
              <Graph engineLabel={engineLabel} />
            </div>
            <PlayerBar />
          </section>

          <aside className="min-h-0">
            <Tabs defaultValue="overview" className="flex h-full flex-col gap-0">
              <TabsList className="mx-3 mt-2 self-start">
                <TabsTrigger value="overview">Visão geral</TabsTrigger>
                <TabsTrigger value="joins">Joins</TabsTrigger>
                <TabsTrigger value="log">Log</TabsTrigger>
                <TabsTrigger value="results">Resultados</TabsTrigger>
              </TabsList>
              <div className="min-h-0 flex-1 overflow-y-auto">
                <div className="p-3">
                  <TabsContent value="overview">
                    <OverviewTab />
                  </TabsContent>
                  <TabsContent value="joins">
                    <JoinsTab />
                  </TabsContent>
                  <TabsContent value="log">
                    <LogTab />
                  </TabsContent>
                  <TabsContent value="results">
                    <ResultsTab />
                  </TabsContent>
                </div>
              </div>
            </Tabs>
          </aside>
        </main>
      </div>
    </TooltipProvider>
  )
}

export default App
