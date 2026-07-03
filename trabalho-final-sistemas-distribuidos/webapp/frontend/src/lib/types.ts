/** Tipos do trace produzido pelo backend (tracer.py / fedshop-go --trace). */

export type SampleRow = Record<string, string>

export interface TraceEvent {
  seq: number
  type: string
  t0: number
  t1: number
  // run_start
  query?: string
  triples?: TriplePattern[]
  endpoints?: EndpointInfo[]
  select?: string[]
  distinct?: boolean
  limit?: number | null
  // phase
  name?: string
  // ask / select
  tp_id?: string
  endpoint_id?: string
  sparql?: string
  result?: boolean
  rows?: number
  sample?: SampleRow[]
  // source_selection_done
  sources?: Record<string, string[]> | string[]
  ask_count?: number
  // tp_exec
  order?: number
  // join
  left?: number
  right?: number
  out?: number
  shared_vars?: string[]
  left_sample?: SampleRow[]
  right_sample?: SampleRow[]
  left_vars?: string[]
  right_vars?: string[]
  out_vars?: string[]
  // union
  arm1?: number
  arm2?: number
  // filter
  expr?: string
  before?: number
  after?: number
  // note (fedshop-go)
  message?: string
  // postprocess
  before_distinct?: number
  before_limit?: number
  order_by?: [string, string][]
  final?: number
  // run_complete
  columns?: string[]
  http_requests?: number
  total_seconds?: number
}

export interface TriplePattern {
  id: string
  sparql: string
  vars: string[]
  context: string
}

export interface EndpointInfo {
  id: string
  url: string
  graph_iri?: string
}

export interface TraceResponse {
  events: TraceEvent[]
  error: string | null
  engine: string
}

export interface QueryOption {
  id: string
  label: string
  query: string
}

export interface ConfigOption {
  id: string
  label: string
}

export interface EngineOption {
  id: string
  label: string
}
