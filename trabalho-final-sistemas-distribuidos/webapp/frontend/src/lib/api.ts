import type { ConfigOption, EngineOption, QueryOption, TraceResponse } from "./types"

async function getJSON<T>(url: string): Promise<T> {
  const r = await fetch(url)
  if (!r.ok) throw new Error(`HTTP ${r.status} em ${url}`)
  return r.json()
}

export const fetchQueries = () => getJSON<QueryOption[]>("/api/queries")
export const fetchConfigs = () => getJSON<ConfigOption[]>("/api/configs")
export const fetchEngines = () => getJSON<EngineOption[]>("/api/engines")
export const fetchQueryText = async (id: string) =>
  (await getJSON<{ content: string }>(`/api/query/${encodeURIComponent(id)}`)).content

export async function executeQuery(body: {
  query: string
  config_id: string
  engine: string
  timeout?: number
}): Promise<TraceResponse> {
  const r = await fetch("/api/execute", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ timeout: 180, ...body }),
  })
  if (!r.ok) {
    let detail = `HTTP ${r.status}`
    try {
      detail = (await r.json()).detail ?? detail
    } catch {
      /* corpo não-JSON */
    }
    throw new Error(detail)
  }
  return r.json()
}
