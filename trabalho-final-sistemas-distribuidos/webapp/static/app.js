/* Visualizador do motor federado pyfedx.
 *
 * Arquitetura executar → gravar → reproduzir:
 *  1. POST /api/execute roda a consulta DE VERDADE e devolve um trace completo
 *     (cada ASK/SELECT com o SPARQL integral, durações reais, joins, filtros).
 *  2. compile(trace) transforma o trace numa timeline lógica pré-computada:
 *     partículas (mensagens viajando) + marks (mutações de estado da UI).
 *     A causalidade é garantida por construção: a partícula de resposta só
 *     parte no instante em que a de requisição chega ao endpoint.
 *  3. O player reproduz a timeline num relógio virtual: play/pausa, velocidade
 *     0.25×–8×, passo a passo e scrub — tudo determinístico (seek = reaplicar
 *     as marks até o instante escolhido).
 */

"use strict";

// ── Constantes de tempo lógico (ms a 1×) ────────────────────────────────────

const TRAVEL = 350;        // voo de uma partícula
const ASK_STAGGER = 70;    // espaçamento entre ASKs do mesmo tp
const SEL_STAGGER = 260;   // espaçamento entre SELECTs do mesmo tp
const DWELL_MIN = 140;     // "processamento" mínimo visível no endpoint
const DWELL_MAX = 700;
const GAP = 220;           // pausa entre grupos de eventos
const STEP_DUR = 450;      // duração visual de join/filtro/pós-processamento

const CSS = getComputedStyle(document.documentElement);
const COLOR = {
  vendor: CSS.getPropertyValue("--vendor").trim(),
  ratingsite: CSS.getPropertyValue("--ratingsite").trim(),
  engine: CSS.getPropertyValue("--engine").trim(),
  ask: CSS.getPropertyValue("--ask").trim(),
  select: CSS.getPropertyValue("--select-msg").trim(),
  ok: CSS.getPropertyValue("--ok").trim(),
  err: CSS.getPropertyValue("--err").trim(),
  muted: CSS.getPropertyValue("--muted").trim(),
  ink: CSS.getPropertyValue("--ink").trim(),
};

const fmt = new Intl.NumberFormat("pt-BR");
const $ = (id) => document.getElementById(id);

// ── Estado global ────────────────────────────────────────────────────────────

const state = {
  trace: null,       // eventos crus do backend
  timeline: null,    // {particles, marks, phases, total}
  nodes: {},         // id → {x, y, kind}
  endpoints: [],     // [{id, url, short}]
  triples: [],       // [{id, sparql, vars, context}]
  playhead: 0,
  playing: false,
  speed: 1,
  lastFrame: null,
  particleEls: new Map(),  // índice da partícula → elemento SVG
};

// ── SVG / grafo ──────────────────────────────────────────────────────────────

const svg = $("graph");
const SVGNS = "http://www.w3.org/2000/svg";
let W = 0, H = 0;

function el(tag, attrs, parent) {
  const e = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  (parent || svg).appendChild(e);
  return e;
}

const gEdges = el("g", {});
const gNodes = el("g", {});
const gParticles = el("g", {});

function resize() {
  W = svg.clientWidth;
  H = svg.clientHeight;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  if (state.endpoints.length) buildGraph();
}
window.addEventListener("resize", resize);

function shortId(id) {
  const m = id.match(/^(vendor|ratingsite)(\d+)$/);
  if (m) return (m[1] === "vendor" ? "v" : "r") + m[2];
  return id.slice(0, 4);
}

function buildGraph() {
  gEdges.innerHTML = "";
  gNodes.innerHTML = "";
  gParticles.innerHTML = "";
  state.particleEls.clear();
  state.nodes = {};

  const cx = W / 2, cy = H * 0.52;
  const R = Math.min(W * 0.38, H * 0.40);
  const eps = state.endpoints;

  // Endpoints em círculo ao redor do motor, com uma folga no topo para o
  // cliente. Vendors preenchem a metade esquerda, ratingsites a direita.
  const n = eps.length;
  const gap = Math.PI / 2.4;               // abertura no topo (~75°)
  const span = 2 * Math.PI - gap;
  eps.forEach((ep, i) => {
    // -90° é o topo; começa logo após a folga e dá a volta completa
    const angle = -Math.PI / 2 + gap / 2 + span * ((i + 0.5) / n);
    state.nodes[ep.id] = {
      x: cx + R * Math.cos(angle),
      y: cy + R * Math.sin(angle),
      kind: ep.id.startsWith("vendor") ? "vendor" : ep.id.startsWith("ratingsite") ? "ratingsite" : "vendor",
    };
  });
  state.nodes.__ENGINE__ = { x: cx, y: cy, kind: "engine" };
  state.nodes.__CLIENT__ = { x: cx, y: Math.max(44, cy - R), kind: "client" };

  for (const ep of eps) {
    const p = state.nodes[ep.id];
    el("line", { class: "edge", x1: cx, y1: cy, x2: p.x, y2: p.y }, gEdges);
  }
  const cl = state.nodes.__CLIENT__;
  el("line", { class: "edge", x1: cl.x, y1: cl.y, x2: cx, y2: cy }, gEdges);

  const epR = Math.max(14, Math.min(24, 260 / n));
  for (const ep of eps) {
    const p = state.nodes[ep.id];
    const color = p.kind === "vendor" ? COLOR.vendor : COLOR.ratingsite;
    const g = el("g", { id: `node-${ep.id}`, transform: `translate(${p.x},${p.y})` }, gNodes);
    el("circle", {
      class: "node-circle", r: epR, fill: color,
      "fill-opacity": 0.16, stroke: color,
    }, g);
    el("text", { class: "node-label", y: 3 }, g).textContent = shortId(ep.id);
    el("text", { class: "node-sublabel", y: epR + 11 }, g).textContent =
      ep.id.length > 13 ? ep.id.slice(0, 12) + "…" : ep.id;
  }

  const gE = el("g", { id: "node-__ENGINE__", transform: `translate(${cx},${cy})` }, gNodes);
  el("circle", {
    class: "node-circle", r: 40, fill: COLOR.engine,
    "fill-opacity": 0.2, stroke: COLOR.engine,
  }, gE);
  el("text", { class: "node-label", y: -4, "font-weight": 700 }, gE).textContent = "MOTOR";
  el("text", { class: "node-sublabel", y: 9 }, gE).textContent = "pyfedx";
  el("text", { class: "engine-status", y: 58, id: "engine-status" }, gE).textContent = "";

  const gC = el("g", { id: "node-__CLIENT__", transform: `translate(${cl.x},${cl.y})` }, gNodes);
  el("circle", {
    class: "node-circle", r: 24, fill: "none",
    stroke: COLOR.ink, "stroke-opacity": 0.7,
  }, gC);
  el("text", { class: "node-label", y: 3 }, gC).textContent = "CLIENTE";
}

function pulseNode(id) {
  const g = document.getElementById(`node-${id}`);
  if (!g) return;
  const c = g.querySelector("circle");
  const base = parseFloat(c.getAttribute("r"));
  c.setAttribute("r", base * 1.25);
  c.setAttribute("fill-opacity", 0.45);
  setTimeout(() => { c.setAttribute("r", base); c.setAttribute("fill-opacity", 0.16); }, 260);
}

// ── Compilador: trace → timeline lógica ─────────────────────────────────────
//
// particles: {t, dur, from, to, color, label}
// marks:     {t, ...payload} — mutações de estado aplicadas quando o playhead
//            cruza t; o seek reaplica todas as marks ≤ playhead do zero.

function dwellOf(ev, min = DWELL_MIN) {
  return Math.max(min, Math.min(DWELL_MAX, (ev.t1 - ev.t0) * 1000));
}

function compile(events) {
  const particles = [];
  const marks = [];
  const phases = [];
  let cursor = 0;

  const mark = (t, m) => { m.t = t; marks.push(m); return m; };
  const phase = (name, color) => phases.push({ name, color, start: cursor });
  const closePhase = () => { if (phases.length) phases[phases.length - 1].end = cursor; };

  let i = 0;
  while (i < events.length) {
    const ev = events[i];

    if (ev.type === "run_start") {
      phase("consulta", COLOR.ink);
      mark(cursor, { kind: "init", ev });
      particles.push({ t: cursor, dur: 500, from: "__CLIENT__", to: "__ENGINE__", color: COLOR.ink, label: "query" });
      mark(cursor, { kind: "log", dot: COLOR.ink, real: ev.t0, msg: `Cliente envia a consulta ao motor (<b>${ev.triples.length}</b> padrões de tripla, <b>${ev.endpoints.length}</b> endpoints)` });
      mark(cursor + 500, { kind: "pulse", node: "__ENGINE__" });
      mark(cursor + 500, { kind: "log", dot: COLOR.engine, real: ev.t0, msg: `Motor decompõe a consulta em <b>${ev.triples.length}</b> padrões de tripla (tp1…tp${ev.triples.length})` });
      cursor += 500 + GAP;
      closePhase();
      i++;
      continue;
    }

    if (ev.type === "phase") {
      if (ev.name === "source_selection") {
        phase("seleção de fontes", COLOR.ask);
        mark(cursor, { kind: "phase", label: "seleção de fontes", engineStatus: "sondando endpoints (ASK)…" });
        mark(cursor, { kind: "log", dot: COLOR.ask, real: ev.t0, msg: "<b>Fase 1 — seleção de fontes:</b> para cada padrão de tripla, o motor pergunta a cada endpoint (ASK) se ele possui dados que casam" });
      } else if (ev.name === "execution") {
        closePhase();
        phase("execução", COLOR.select);
        mark(cursor, { kind: "phase", label: "execução", engineStatus: "buscando bindings (SELECT)…" });
        mark(cursor, { kind: "log", dot: COLOR.select, real: ev.t0, msg: "<b>Fase 2 — execução:</b> o motor busca os bindings de cada padrão apenas nas fontes selecionadas e faz os joins" });
      }
      i++;
      continue;
    }

    if (ev.type === "ask") {
      // Grupo: todos os ASKs consecutivos do mesmo tp (um por endpoint),
      // animados com pequeno escalonamento.
      const tp = ev.tp_id;
      const group = [];
      while (i < events.length && events[i].type === "ask" && events[i].tp_id === tp) group.push(events[i++]);
      mark(cursor, { kind: "tpActive", tp });
      mark(cursor, { kind: "log", dot: COLOR.ask, real: group[0].t0, msg: `<b>${tp}</b>: ASK enviado a ${group.length} endpoint(s)` });
      let groupEnd = cursor;
      group.forEach((a, k) => {
        const s = cursor + k * ASK_STAGGER;
        const dwell = dwellOf(a);
        particles.push({ t: s, dur: TRAVEL, from: "__ENGINE__", to: a.endpoint_id, color: COLOR.ask, label: tp });
        mark(s, { kind: "op", op: "ASK", tp, endpoint: a.endpoint_id, sparql: a.sparql, status: "em voo…", realDur: a.t1 - a.t0 });
        mark(s, { kind: "count", counter: "ask", delta: 1 });
        const back = s + TRAVEL + dwell;
        particles.push({
          t: back, dur: TRAVEL, from: a.endpoint_id, to: "__ENGINE__",
          color: a.result ? COLOR.ok : COLOR.muted, label: a.result ? "sim" : "não",
        });
        const arrive = back + TRAVEL;
        mark(arrive, { kind: "matrix", tp, endpoint: a.endpoint_id, result: a.result });
        mark(arrive, { kind: "op", op: "ASK", tp, endpoint: a.endpoint_id, sparql: a.sparql, status: a.result ? "→ TEM dados (true)" : "→ não tem (false)", realDur: a.t1 - a.t0 });
        if (a.result) mark(arrive, { kind: "count", counter: "pos", delta: 1 });
        groupEnd = Math.max(groupEnd, arrive);
      });
      const positives = group.filter((a) => a.result).map((a) => a.endpoint_id);
      mark(groupEnd, {
        kind: "log", dot: positives.length ? COLOR.ok : COLOR.muted, real: group[group.length - 1].t1,
        msg: `<b>${tp}</b>: ${positives.length ? `fontes = ${positives.map(shortId).join(", ")}` : "nenhuma fonte possui esse padrão"}`,
      });
      cursor = groupEnd + GAP;
      continue;
    }

    if (ev.type === "source_selection_done") {
      mark(cursor, { kind: "tpActive", tp: null });
      const nsrc = Object.values(ev.sources).filter((s) => s.length).length;
      const ntp = Object.keys(ev.sources).length;
      mark(cursor, { kind: "log", dot: COLOR.ok, real: ev.t1, msg: `Seleção de fontes concluída: <b>${ev.ask_count}</b> ASKs em <b>${(ev.t1 - ev.t0).toFixed(2)}s</b> reais — ${nsrc}/${ntp} padrões têm fontes` });
      cursor += GAP;
      i++;
      continue;
    }

    if (ev.type === "tp_exec") {
      mark(cursor, { kind: "tpActive", tp: ev.tp_id });
      mark(cursor, { kind: "log", dot: COLOR.select, real: ev.t0, msg: `Executando <b>${ev.tp_id}</b> (${ev.order}º na ordem do plano) em ${ev.sources.length} fonte(s): ${ev.sources.map(shortId).join(", ")}` });
      cursor += 150;
      i++;
      continue;
    }

    if (ev.type === "select") {
      const tp = ev.tp_id;
      const group = [];
      while (i < events.length && events[i].type === "select" && events[i].tp_id === tp) group.push(events[i++]);
      let groupEnd = cursor;
      group.forEach((s0, k) => {
        const s = cursor + k * SEL_STAGGER;
        const dwell = dwellOf(s0, 200);
        particles.push({ t: s, dur: TRAVEL, from: "__ENGINE__", to: s0.endpoint_id, color: COLOR.select, label: tp });
        mark(s, { kind: "op", op: "SELECT", tp, endpoint: s0.endpoint_id, sparql: s0.sparql, status: "em voo…", realDur: s0.t1 - s0.t0 });
        mark(s, { kind: "count", counter: "sel", delta: 1 });
        const back = s + TRAVEL + dwell;
        particles.push({
          t: back, dur: TRAVEL, from: s0.endpoint_id, to: "__ENGINE__",
          color: COLOR.select, label: fmt.format(s0.rows), big: s0.rows > 0,
        });
        const arrive = back + TRAVEL;
        mark(arrive, { kind: "op", op: "SELECT", tp, endpoint: s0.endpoint_id, sparql: s0.sparql, status: `→ ${fmt.format(s0.rows)} linha(s)`, realDur: s0.t1 - s0.t0, sample: s0.sample });
        mark(arrive, { kind: "log", dot: COLOR.select, real: s0.t1, msg: `<b>${shortId(s0.endpoint_id)}</b> devolve <b>${fmt.format(s0.rows)}</b> linha(s) para ${tp} (${((s0.t1 - s0.t0) * 1000).toFixed(0)}ms reais)` });
        groupEnd = Math.max(groupEnd, arrive);
      });
      cursor = groupEnd + GAP;
      continue;
    }

    if (ev.type === "join") {
      mark(cursor, { kind: "pulse", node: "__ENGINE__" });
      mark(cursor, { kind: "count", counter: "bind", set: fmt.format(ev.out) });
      const shared = ev.shared_vars && ev.shared_vars.length ? ` em ?${ev.shared_vars.join(", ?")}` : "";
      const msg = ev.left === 0
        ? `<b>${ev.tp_id}</b> semeia o resultado com <b>${fmt.format(ev.out)}</b> binding(s)`
        : `⋈ join <b>${ev.tp_id}</b>${shared}: ${fmt.format(ev.left)} × ${fmt.format(ev.right)} → <b>${fmt.format(ev.out)}</b> binding(s)`;
      mark(cursor, { kind: "log", dot: COLOR.engine, real: ev.t1, msg });
      mark(cursor, { kind: "engineStatus", text: `join ${ev.tp_id}: ${fmt.format(ev.out)} bindings` });
      cursor += STEP_DUR;
      i++;
      continue;
    }

    if (ev.type === "union_merge") {
      mark(cursor, { kind: "pulse", node: "__ENGINE__" });
      mark(cursor, { kind: "log", dot: COLOR.engine, real: ev.t1, msg: `UNION: ${fmt.format(ev.arm1)} ∪ ${fmt.format(ev.arm2)} → <b>${fmt.format(ev.out)}</b> binding(s)` });
      mark(cursor, { kind: "count", counter: "bind", set: fmt.format(ev.out) });
      cursor += STEP_DUR;
      i++;
      continue;
    }

    if (ev.type === "optional_join") {
      mark(cursor, { kind: "pulse", node: "__ENGINE__" });
      mark(cursor, { kind: "log", dot: COLOR.engine, real: ev.t1, msg: `OPTIONAL (left outer join): ${fmt.format(ev.left)} ⟕ ${fmt.format(ev.right)} → <b>${fmt.format(ev.out)}</b> binding(s)` });
      mark(cursor, { kind: "count", counter: "bind", set: fmt.format(ev.out) });
      cursor += STEP_DUR;
      i++;
      continue;
    }

    if (ev.type === "filter") {
      mark(cursor, { kind: "pulse", node: "__ENGINE__" });
      const expr = ev.expr.length > 90 ? ev.expr.slice(0, 88) + "…" : ev.expr;
      mark(cursor, { kind: "log", dot: COLOR.engine, real: ev.t1, msg: `FILTER(${escHtml(expr)}): ${fmt.format(ev.before)} → <b>${fmt.format(ev.after)}</b> binding(s)` });
      mark(cursor, { kind: "count", counter: "bind", set: fmt.format(ev.after) });
      cursor += STEP_DUR;
      i++;
      continue;
    }

    if (ev.type === "postprocess") {
      const parts = [];
      if (ev.distinct) parts.push(`DISTINCT: ${fmt.format(ev.before_distinct)} → ${fmt.format(ev.before_limit)}`);
      if (ev.order_by && ev.order_by.length) parts.push(`ORDER BY ?${ev.order_by.map((o) => o[0]).join(", ?")}`);
      if (ev.limit != null) parts.push(`LIMIT ${ev.limit}: ${fmt.format(ev.before_limit)} → ${fmt.format(ev.final)}`);
      if (parts.length) {
        mark(cursor, { kind: "pulse", node: "__ENGINE__" });
        mark(cursor, { kind: "log", dot: COLOR.engine, real: ev.t1, msg: `Pós-processamento: ${parts.join(" · ")}` });
        cursor += STEP_DUR;
      }
      i++;
      continue;
    }

    if (ev.type === "run_complete") {
      closePhase();
      phase("resposta", COLOR.ok);
      mark(cursor, { kind: "tpActive", tp: null });
      particles.push({ t: cursor, dur: 550, from: "__ENGINE__", to: "__CLIENT__", color: COLOR.ok, label: `${fmt.format(ev.rows)} linhas`, big: true });
      const arrive = cursor + 550;
      mark(arrive, { kind: "pulse", node: "__CLIENT__" });
      mark(arrive, { kind: "phase", label: "concluído ✓", engineStatus: "" });
      mark(arrive, { kind: "count", counter: "rows", set: fmt.format(ev.rows) });
      mark(arrive, { kind: "count", counter: "time", set: `${ev.total_seconds.toFixed(2)}s` });
      mark(arrive, { kind: "log", dot: COLOR.ok, real: ev.t1, msg: `<b>Resposta entregue ao cliente:</b> ${fmt.format(ev.rows)} linha(s) · ${ev.http_requests} requisições HTTP · ${ev.total_seconds.toFixed(2)}s reais` });
      mark(arrive, { kind: "results", ev });
      cursor = arrive + GAP;
      closePhase();
      i++;
      continue;
    }

    if (ev.type === "error") {
      closePhase();
      phase("erro", COLOR.err);
      mark(cursor, { kind: "phase", label: "erro ✕", engineStatus: "" });
      mark(cursor, { kind: "log", dot: COLOR.err, real: ev.t1, msg: `<b>Erro:</b> ${escHtml(ev.message)}` });
      cursor += GAP;
      closePhase();
      i++;
      continue;
    }

    i++;
  }

  closePhase();
  marks.sort((a, b) => a.t - b.t);
  return { particles, marks, phases, total: cursor };
}

// ── Aplicação de marks (estado da UI) ────────────────────────────────────────

function resetUI() {
  ["s-ask", "s-pos", "s-sel"].forEach((id) => ($(id).textContent = "0"));
  ["s-bind", "s-rows", "s-time"].forEach((id) => ($(id).textContent = "—"));
  $("log-wrap").innerHTML = "";
  $("op-meta").textContent = "—";
  $("op-sparql").textContent = "—";
  $("phase-badge").textContent = "aguardando";
  $("results-drawer").hidden = true;
  const es = document.getElementById("engine-status");
  if (es) es.textContent = "";
  buildMatrix();
}

function buildMatrix() {
  const wrap = $("matrix-wrap");
  if (!state.triples.length) { wrap.innerHTML = '<div class="placeholder">—</div>'; return; }
  let html = '<table class="matrix"><tr><th class="rowh"></th>';
  for (const ep of state.endpoints) html += `<th title="${escHtml(ep.id)}">${shortId(ep.id)}</th>`;
  html += "</tr>";
  for (const tp of state.triples) {
    html += `<tr id="mrow-${tp.id}"><th class="rowh" title="${escHtml(tp.sparql)}">${tp.id}</th>`;
    for (const ep of state.endpoints) html += `<td class="unknown" id="mcell-${tp.id}-${ep.id}"></td>`;
    html += "</tr>";
  }
  wrap.innerHTML = html + "</table>";
}

const counters = { ask: 0, pos: 0, sel: 0 };

function applyMark(m, live) {
  switch (m.kind) {
    case "init": {
      state.triples = m.ev.triples;
      state.endpoints = m.ev.endpoints.map((e) => ({ ...e }));
      buildGraph();
      buildMatrix();
      break;
    }
    case "phase":
      $("phase-badge").textContent = m.label;
      if (m.engineStatus !== undefined) setEngineStatus(m.engineStatus);
      break;
    case "engineStatus":
      setEngineStatus(m.text);
      break;
    case "log":
      addLog(m.dot, m.real, m.msg);
      break;
    case "op":
      renderOp(m);
      break;
    case "matrix": {
      const cell = document.getElementById(`mcell-${m.tp}-${m.endpoint}`);
      if (cell) { cell.className = m.result ? "yes" : "no"; cell.textContent = m.result ? "✓" : "·"; }
      break;
    }
    case "tpActive":
      document.querySelectorAll("tr.tp-active").forEach((r) => r.classList.remove("tp-active"));
      if (m.tp) {
        const row = document.getElementById(`mrow-${m.tp}`);
        if (row) { row.classList.add("tp-active"); row.scrollIntoView({ block: "nearest" }); }
      }
      break;
    case "count":
      if (m.set !== undefined) {
        $({ bind: "s-bind", rows: "s-rows", time: "s-time" }[m.counter]).textContent = m.set;
      } else {
        counters[m.counter] += m.delta;
        $({ ask: "s-ask", pos: "s-pos", sel: "s-sel" }[m.counter]).textContent = fmt.format(counters[m.counter]);
      }
      break;
    case "pulse":
      if (live) pulseNode(m.node);
      break;
    case "results":
      renderResults(m.ev);
      break;
  }
}

function setEngineStatus(text) {
  const es = document.getElementById("engine-status");
  if (es) es.textContent = text;
}

function escHtml(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function addLog(dot, realT, msgHtml) {
  const wrap = $("log-wrap");
  const e = document.createElement("div");
  e.className = "log-entry";
  e.innerHTML =
    `<div class="log-dot" style="background:${dot}"></div>` +
    `<span class="log-time">${realT.toFixed(2)}s</span>` +
    `<span class="log-msg">${msgHtml}</span>`;
  wrap.appendChild(e);
  wrap.scrollTop = wrap.scrollHeight;
}

function highlightSparql(q) {
  let h = escHtml(q);
  h = h.replace(/&lt;[^&]*?&gt;/g, (m) => `<span class="iri">${m}</span>`);
  h = h.replace(/\?[A-Za-z_][\w-]*/g, (m) => `<span class="var">${m}</span>`);
  h = h.replace(/\b(PREFIX|SELECT|DISTINCT|WHERE|ASK|FILTER|OPTIONAL|UNION|ORDER BY|LIMIT|OFFSET)\b/g,
    (m) => `<span class="kw">${m}</span>`);
  return h;
}

function renderOp(m) {
  const color = m.op === "ASK" ? COLOR.ask : COLOR.select;
  const ms = (m.realDur * 1000).toFixed(0);
  $("op-meta").innerHTML =
    `<span class="tag" style="background:${color}">${m.op}</span>` +
    `<b>${m.tp}</b> → ${escHtml(m.endpoint)} · <span style="color:${COLOR.muted}">${ms}ms reais</span> · ${escHtml(m.status)}`;
  $("op-sparql").innerHTML = highlightSparql(m.sparql);
}

function renderResults(ev) {
  const drawer = $("results-drawer");
  $("results-count").textContent = `${fmt.format(ev.rows)} linha(s)` + (ev.rows > ev.sample.length ? ` — mostrando ${ev.sample.length}` : "");
  const cols = ev.columns || [];
  let html = '<table class="results"><tr>' + cols.map((c) => `<th>?${escHtml(c)}</th>`).join("") + "</tr>";
  for (const row of ev.sample) {
    html += "<tr>" + cols.map((c) => `<td title="${escHtml(row[c] || "")}">${escHtml(row[c] || "")}</td>`).join("") + "</tr>";
  }
  html += "</table>";
  if (!ev.sample.length) html = '<div class="placeholder">A consulta não retornou linhas.</div>';
  $("results-table-wrap").innerHTML = html;
  drawer.hidden = false;
}

// ── Player ───────────────────────────────────────────────────────────────────

let appliedMarks = 0; // quantas marks (ordenadas) já foram aplicadas

function seek(t, opts = {}) {
  const tl = state.timeline;
  if (!tl) return;
  t = Math.max(0, Math.min(tl.total, t));
  const backwards = t < state.playhead;
  state.playhead = t;
  if (backwards || opts.rebuild) {
    resetUI();
    Object.keys(counters).forEach((k) => (counters[k] = 0));
    appliedMarks = 0;
  }
  while (appliedMarks < tl.marks.length && tl.marks[appliedMarks].t <= t) {
    applyMark(tl.marks[appliedMarks], !backwards && !opts.rebuild && opts.live);
    appliedMarks++;
  }
  renderParticles();
  updatePlayerBar();
}

function renderParticles() {
  const tl = state.timeline;
  const t = state.playhead;
  const active = new Set();
  tl.particles.forEach((p, idx) => {
    if (t < p.t || t > p.t + p.dur) return;
    active.add(idx);
    const from = state.nodes[p.from], to = state.nodes[p.to];
    if (!from || !to) return;
    const f = (t - p.t) / p.dur;
    const x = from.x + (to.x - from.x) * f;
    const y = from.y + (to.y - from.y) * f;
    let g = state.particleEls.get(idx);
    if (!g) {
      g = el("g", {}, gParticles);
      el("circle", { r: p.big ? 7 : 5, fill: p.color }, g);
      const label = el("text", { class: "particle-label", y: -9, fill: p.color }, g);
      label.textContent = p.label || "";
      state.particleEls.set(idx, g);
    }
    g.setAttribute("transform", `translate(${x},${y})`);
  });
  for (const [idx, g] of state.particleEls) {
    if (!active.has(idx)) { g.remove(); state.particleEls.delete(idx); }
  }
}

function updatePlayerBar() {
  const tl = state.timeline;
  $("timeline").value = tl ? Math.round((state.playhead / tl.total) * 1000) : 0;
  $("clock").textContent = (state.playhead / 1000).toFixed(1) + "s";
  $("pb-play").textContent = state.playing ? "❚❚" : "▶";
}

function frame(ts) {
  if (state.playing && state.timeline) {
    if (state.lastFrame != null) {
      const dt = (ts - state.lastFrame) * state.speed;
      const next = state.playhead + dt;
      if (next >= state.timeline.total) {
        seek(state.timeline.total, { live: true });
        state.playing = false;
        updatePlayerBar();
      } else {
        seek(next, { live: true });
      }
    }
    state.lastFrame = ts;
  } else {
    state.lastFrame = null;
  }
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);

function togglePlay() {
  if (!state.timeline) return;
  if (!state.playing && state.playhead >= state.timeline.total) seek(0, { rebuild: true });
  state.playing = !state.playing;
  updatePlayerBar();
}

function stepMark(dir) {
  const tl = state.timeline;
  if (!tl) return;
  state.playing = false;
  const times = [...new Set(tl.marks.map((m) => m.t))].sort((a, b) => a - b);
  if (dir > 0) {
    const next = times.find((t) => t > state.playhead + 1);
    seek(next != null ? next : tl.total);
  } else {
    const prev = [...times].reverse().find((t) => t < state.playhead - 1);
    seek(prev != null ? prev : 0);
  }
}

function renderPhaseBar() {
  const tl = state.timeline;
  const bar = $("timeline-phases");
  bar.innerHTML = "";
  if (!tl) return;
  for (const ph of tl.phases) {
    const seg = document.createElement("div");
    seg.className = "phase-seg";
    seg.style.width = (((ph.end ?? tl.total) - ph.start) / tl.total) * 100 + "%";
    seg.style.background = ph.color;
    seg.style.opacity = 0.65;
    seg.title = ph.name;
    bar.appendChild(seg);
  }
}

// ── Controles ────────────────────────────────────────────────────────────────

$("pb-play").addEventListener("click", togglePlay);
$("pb-back").addEventListener("click", () => stepMark(-1));
$("pb-fwd").addEventListener("click", () => stepMark(1));

$("timeline").addEventListener("input", function () {
  if (!state.timeline) return;
  state.playing = false;
  seek((parseInt(this.value, 10) / 1000) * state.timeline.total);
});

$("speed").addEventListener("input", function () {
  state.speed = Math.pow(2, parseFloat(this.value));
  $("speed-label").textContent =
    state.speed >= 1 ? `${state.speed.toFixed(state.speed >= 2 ? 0 : 1)}×` : `${state.speed.toFixed(2)}×`;
});

document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "SELECT" || e.target.tagName === "INPUT") return;
  if (e.code === "Space") { e.preventDefault(); togglePlay(); }
  if (e.code === "ArrowRight") stepMark(1);
  if (e.code === "ArrowLeft") stepMark(-1);
});

$("results-close").addEventListener("click", () => ($("results-drawer").hidden = true));

// ── Execução ────────────────────────────────────────────────────────────────

$("run-btn").addEventListener("click", async () => {
  const queryId = $("query-select").value;
  const configId = $("config-select").value;
  if (!queryId || !configId) return;

  const btn = $("run-btn");
  btn.disabled = true;
  state.playing = false;
  state.timeline = null;
  $("exec-overlay").hidden = false;
  $("phase-badge").textContent = "executando…";

  try {
    const qr = await fetch(`/api/query/${encodeURIComponent(queryId)}`);
    if (!qr.ok) throw new Error(`consulta '${queryId}' não encontrada`);
    const { content: query } = await qr.json();

    const r = await fetch("/api/execute", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, config_id: configId, timeout: 60 }),
    });
    if (!r.ok) throw new Error((await r.json()).detail || `HTTP ${r.status}`);
    const trace = await r.json();

    state.trace = trace;
    state.timeline = compile(trace.events);
    renderPhaseBar();
    seek(0, { rebuild: true });
    state.playing = true;
    updatePlayerBar();
  } catch (err) {
    $("phase-badge").textContent = "erro ✕";
    $("op-meta").textContent = "—";
    $("op-sparql").textContent = `Falha ao executar: ${err.message}`;
  } finally {
    $("exec-overlay").hidden = true;
    btn.disabled = false;
  }
});

// ── Boot ────────────────────────────────────────────────────────────────────

async function boot() {
  resize();
  try {
    const [qs, cs] = await Promise.all([
      fetch("/api/queries").then((r) => r.json()),
      fetch("/api/configs").then((r) => r.json()),
    ]);
    $("query-select").innerHTML = qs.map((q) => `<option value="${q.id}">${escHtml(q.label)}</option>`).join("")
      || "<option value=''>nenhuma consulta</option>";
    $("config-select").innerHTML = cs.map((c) => `<option value="${c.id}">${escHtml(c.label)}</option>`).join("")
      || "<option value=''>nenhuma federação</option>";
  } catch {
    $("query-select").innerHTML = "<option value=''>erro ao carregar</option>";
  }
}
boot();
