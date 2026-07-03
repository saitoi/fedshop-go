import * as React from "react"

/** Realce leve de SPARQL (IRIs, variáveis, palavras-chave) sem innerHTML. */

const TOKEN =
  /(<[^>\s]*>)|(\?[A-Za-z_][\w-]*)|(\b(?:PREFIX|SELECT|DISTINCT|WHERE|ASK|FILTER|OPTIONAL|UNION|ORDER BY|LIMIT|OFFSET|VALUES|GRAPH)\b)/g

export function SparqlView({ text, className }: { text: string; className?: string }) {
  const parts = React.useMemo(() => {
    const out: React.ReactNode[] = []
    let last = 0
    let m: RegExpExecArray | null
    const token = new RegExp(TOKEN.source, "g")
    let key = 0
    while ((m = token.exec(text)) !== null) {
      if (m.index > last) out.push(text.slice(last, m.index))
      if (m[1]) out.push(<span key={key++} className="text-sky-600 dark:text-sky-400">{m[1]}</span>)
      else if (m[2]) out.push(<span key={key++} className="text-amber-600 dark:text-amber-400">{m[2]}</span>)
      else out.push(<span key={key++} className="font-semibold text-violet-600 dark:text-violet-400">{m[3]}</span>)
      last = m.index + m[0].length
    }
    if (last < text.length) out.push(text.slice(last))
    return out
  }, [text])

  return (
    <pre className={"font-mono text-xs leading-relaxed whitespace-pre-wrap break-words " + (className ?? "")}>
      {parts}
    </pre>
  )
}
