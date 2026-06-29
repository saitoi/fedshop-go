"""Phase 3: Query generation.

Reimplementation of reference-repos/FedShop/fedshop/query.py without
omegaconf, nltk, fasttext, or iso639.
"""

from __future__ import annotations

import json
import re as _re
from copy import deepcopy
from io import BytesIO, StringIO
from itertools import chain
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlencode, urlsplit

import pandas as pd
from rdflib.plugins.sparql.algebra import (
    _traverseAgg,
    translateQuery,
    traverse,
)
from rdflib.plugins.sparql.parser import parseQuery
from rdflib.plugins.sparql.parserutils import CompValue
from rdflib.term import Variable

from .algebra.rdflib_algebra import (
    collect_triple_variables,
    collect_variables,
    disable_offset,
    disable_orderby_limit,
    extract_where,
    inject_constant_into_placeholders,
    remove_filter_with_placeholders,
    translateAlgebra,
)
from .config import BenchmarkConfig
from .sparql import SparqlClient

PANDAS_RANDOM_STATE = 42
_SOURCE_LOCAL_REFERENCE_QUERIES = {"q06", "q08", "q09", "q10", "q11", "q12"}


# ─── Internal helpers ────────────────────────────────────────────────────────


def _uses_source_local_reference(query_name: str) -> bool:
    return query_name in _SOURCE_LOCAL_REFERENCE_QUERIES

def _parse_query_text(query_text: str) -> tuple:
    """Parse a SPARQL query string; returns (algebra, misc_options)."""
    misc = {"explicit_join_order": False}
    q = query_text
    if 'DEFINE sql:select-option "order"' in q:
        misc["explicit_join_order"] = True
        q = q.replace('DEFINE sql:select-option "order"', "")
    algebra = parseQuery(q)
    return algebra, misc


def _export_query(algebra, options: dict, *, outfile: Path | None = None) -> str:
    """Translate algebra back to a SPARQL string."""
    translated = translateQuery(algebra)
    query = translateAlgebra(translated)

    with StringIO(query) as f:
        lines = [line for line in f.readlines() if line.strip()]
    query = "".join(lines)

    if not query.strip():
        raise RuntimeError("Empty query after translation")

    if options.get("explicit_join_order"):
        query = f'DEFINE sql:select-option "order"\n{query}'

    if outfile is not None:
        outfile.write_text(query)

    return query


def _read_csv(csv_file: Path) -> pd.DataFrame:
    with open(csv_file) as f:
        header = f.readline().strip().replace('"', "").split(",")
    return pd.read_csv(csv_file, parse_dates=[h for h in header if "date" in h], low_memory=False)


# ─── Public API ──────────────────────────────────────────────────────────────

def build_value_selection_query(
    query_text: str,
    const_info: dict,
) -> dict:
    """Build subqueries for value-selection given a template query and const.json.

    Returns a dict: {sq0: {kind, query}, ...}
    """
    algebra, options = _parse_query_text(query_text)

    def has_constant(node, children, consts):
        if isinstance(node, Variable):
            return str(node) in consts
        elif isinstance(node, CompValue) and node.name == "vars":
            return str(node["var"]) in consts
        return any(children)

    def split_union_query(node, children):
        if isinstance(node, CompValue) and node.name == "SelectQuery":
            where = node["where"]["part"]
            if len(where) == 1 and where[0].name == "GroupOrUnionGraphPattern":
                graphs = where[0]["graph"]
                if len(graphs) > 1:
                    for graph in graphs:
                        children.append([graph])
        return list(chain(*children))

    def build_sub_query(node, new_where=None, new_proj=None):
        if isinstance(node, CompValue) and node.name in [
            "SelectQuery", "ConstructQuery", "DescribeQuery", "AskQuery"
        ]:
            node_args = {"modifier": "DISTINCT"}
            node_args["where"] = new_where if new_where else node["where"]
            if new_proj:
                node_args["projection"] = new_proj
            return CompValue("SelectQuery", **node_args)

    def collect_filter_variables(node, children):
        if isinstance(node, CompValue) and node.name == "Filter":
            children.append(list(map(str, _traverseAgg(node, collect_variables))))
        return list(chain(*children))

    cond_consts = set(const_info.keys())
    filter_consts = deepcopy(cond_consts)

    # Extract auxiliary variables referenced in "query" conditions (e.g. "'currentDate' < 'date'"
    # → need ?date in the subquery to later derive ?currentDate from it).
    aux_vars = set()
    for const, info in const_info.items():
        for var_ref in _re.findall(r"`(\w+)`", info.get("query", "")):
            if var_ref != const:
                aux_vars.add(var_ref)
    expanded_for_selection = cond_consts | aux_vars

    subq_bgp_algebras = []

    for const, info in const_info.items():
        if not info:
            continue
        if info.get("exclusive"):
            subq_bgp_algebras.append((
                "exclusive",
                traverse(algebra, lambda node: build_sub_query(node, new_proj=[
                    CompValue("vars", var=Variable(const))
                ])),
            ))
        if info.get("ignoreFilter") and const in filter_consts:
            filter_consts.remove(const)

    filter_consts &= set(_traverseAgg(algebra, collect_filter_variables))

    # Split UNION
    subq_bgp_algebras.extend([
        ("join", alg)
        for alg in _traverseAgg(algebra, split_union_query)
    ])

    # Always include a join subquery unless there's a UNION-based join already.
    # Exclusive subqueries only cover their specific variable; remaining vars
    # (e.g. ProductType, ProductFeature1 for q03) need a join subquery.
    exclusive_vars = {c for c, info in const_info.items() if info and info.get("exclusive")}
    has_join = any(kind in ("join", "optional") for kind, _ in subq_bgp_algebras)
    uncovered = expanded_for_selection - exclusive_vars
    if not has_join and uncovered:
        subq_bgp_algebras.append(("join", _traverseAgg(algebra, extract_where)[0]))

    subqueries = {}
    covered_vars: set[str] = set()  # vars already selected by preceding subqueries
    for subq_id, (kind, subq_bgp_algebra) in enumerate(subq_bgp_algebras):
        all_triple_vars = set(map(str, _traverseAgg(subq_bgp_algebra, collect_triple_variables)))
        subq_vars = (all_triple_vars & expanded_for_selection) - covered_vars

        subq_bgp_algebra = traverse(
            subq_bgp_algebra,
            visitPost=lambda x: remove_filter_with_placeholders(
                x, consts={"query": subq_vars, "filter": filter_consts}
            ),
        )
        subq_bgp_algebra = traverse(subq_bgp_algebra, visitPost=disable_orderby_limit)
        subq_bgp_algebra = traverse(subq_bgp_algebra, visitPost=disable_offset)

        if kind in ("join", "optional") and subq_vars:
            # For join subqueries, trim to ONLY the triple patterns that directly bind
            # a const variable. This avoids expensive star-joins (e.g. q02 has 13 patterns
            # all anchored at ?localProduct, but only one pattern binds ?product).
            # Apply BEFORE LeftJoin stripping so that OPTIONAL blocks containing const vars
            # are preserved (e.g. q07 where ?date only appears inside an OPTIONAL).
            _common_prefixes = frozenset(["rdf", "rdfs", "owl", "xsd"])

            def _pred_prefix(pred_node) -> str:
                """Extract the namespace prefix from a parsed predicate CompValue."""
                def find_prefix(node, children):
                    from itertools import chain
                    if isinstance(node, CompValue) and node.name == "pname":
                        return [node.get("prefix", "")]
                    return list(chain(*children))
                results = _traverseAgg(pred_node, find_prefix) if isinstance(pred_node, CompValue) else []
                return results[0] if results else ""

            def _filter_to_const_triples(node, _sv=frozenset(subq_vars)):
                if isinstance(node, CompValue) and node.name == "TriplesBlock":
                    triples = node["triples"]
                    anchor = [
                        t for t in triples
                        if any(isinstance(c, Variable) and str(c) in _sv for c in t)
                    ]
                    anchor_subs = {str(t[0]) for t in anchor if isinstance(t[0], Variable)}
                    anchor_sub_obj_vars = anchor_subs | {
                        str(t[2]) for t in anchor if isinstance(t[2], Variable)
                    }
                    # Keep type-constraint triples (same subject, URI/literal object — no variables).
                    type_triples = [
                        t for t in triples if t not in anchor
                        and isinstance(t[0], Variable) and str(t[0]) in anchor_subs
                        and not isinstance(t[2], Variable)
                    ]
                    # Keep one incoming domain edge for resources identified by
                    # an owl:sameAs anchor.  This distinguishes, for example,
                    # reviewed products from producers (q08) and products
                    # referenced by offers from producers (q10).
                    incoming = []
                    incoming_targets: set[str] = set()
                    for t in triples:
                        if t in anchor or t in type_triples:
                            continue
                        obj = str(t[2]) if isinstance(t[2], Variable) else None
                        if (
                            obj in anchor_subs
                            and obj not in incoming_targets
                            and _pred_prefix(t[1]) not in _common_prefixes
                        ):
                            incoming.append(t)
                            incoming_targets.add(obj)
                    # One domain-specific triple per anchor subject for entity disambiguation
                    # (avoids wrong entity types, e.g. Producer URIs for q02's ?product).
                    # Only pick triples with domain predicates (not rdf/rdfs/owl/xsd)
                    # and only if the object variable is fresh (not another anchor subject).
                    seen_subs: set = set()
                    disambig = []
                    for t in triples:
                        if t in anchor or t in type_triples:
                            continue
                        sub = str(t[0]) if isinstance(t[0], Variable) else None
                        obj_var = str(t[2]) if isinstance(t[2], Variable) else None
                        if (sub and sub in anchor_subs and sub not in seen_subs
                                and _pred_prefix(t[1]) not in _common_prefixes
                                and (obj_var is None or obj_var not in anchor_sub_obj_vars)):
                            disambig.append(t)
                            seen_subs.add(sub)
                    kept = anchor + type_triples + incoming + disambig
                    if not kept:
                        return CompValue("Placeholder", old=node)
                    node["triples"] = kept
                return node

            subq_bgp_algebra = traverse(subq_bgp_algebra, visitPost=_filter_to_const_triples)
            # Remove Placeholder nodes from part lists (left behind by filtered-out TriplesBlocks).
            def _drop_placeholder_parts(node, _ph=CompValue("Placeholder").name):
                if isinstance(node, CompValue) and "part" in node.keys() and isinstance(node["part"], list):
                    node["part"] = [
                        p for p in node["part"]
                        if not (isinstance(p, CompValue) and p.name == "Placeholder")
                    ]
                return node
            subq_bgp_algebra = traverse(subq_bgp_algebra, visitPost=_drop_placeholder_parts)

        # Strip OPTIONAL (LeftJoin) patterns that became empty after filtering.
        # OPTIONALs with const variables inside are preserved (e.g. q07 ?date).
        def _is_empty_algebra(node) -> bool:
            if not isinstance(node, CompValue):
                return False
            if node.name == "Placeholder":
                return True
            if node.name in ("GroupGraphPatternSub", "GroupOrUnionGraphPattern"):
                parts = node.get("part", [])
                return not parts or all(_is_empty_algebra(p) for p in parts)
            if node.name == "TriplesBlock":
                return not node.get("triples", [])
            return False

        def _strip_empty_leftjoins(node):
            if isinstance(node, CompValue) and node.name == "LeftJoin":
                if _is_empty_algebra(node.p2):
                    return node.p1
            return node

        subq_bgp_algebra = traverse(subq_bgp_algebra, visitPost=_strip_empty_leftjoins)

        if kind == "exclusive":
            # Exclusive subqueries project only their one const variable.
            # Only mark that variable as covered (not all triple-pattern vars).
            const_for_exclusive = next(
                (c for c, info in const_info.items() if info and info.get("exclusive")
                 and c not in covered_vars),
                None,
            )
            if const_for_exclusive is None:
                continue
            subqueries[f"sq{subq_id}"] = {
                "kind": kind,
                "query": _export_query(subq_bgp_algebra, options),
            }
            covered_vars.add(const_for_exclusive)
        elif kind in ("join", "optional"):
            if not subq_vars:
                continue
            subq_consts = [CompValue("vars", var=Variable(c)) for c in subq_vars]
            subq_algebra = traverse(
                algebra,
                visitPost=lambda node: build_sub_query(node, new_where=subq_bgp_algebra, new_proj=subq_consts),
            )
            subqueries[f"sq{subq_id}"] = {
                "kind": kind,
                "query": _export_query(subq_algebra, options),
            }
            covered_vars |= subq_vars

    return subqueries


def sample_workload_values(
    subqueries: dict,
    endpoint: str,
    n_instances: int,
    *,
    seed: int = PANDAS_RANDOM_STATE,
    sparql_client: SparqlClient | None = None,
    timeout: int | None = 30,
    fallback_endpoints: list[str] | None = None,
) -> pd.DataFrame:
    """Fire subqueries against the endpoint, join results, sample n_instances rows."""
    if sparql_client is None:
        sparql_client = SparqlClient()

    dfs: list[pd.DataFrame] = []
    limit = n_instances * 10 + 20  # cap rows to prevent Virtuoso OOM on complex joins
    for sq_id, sq_info in subqueries.items():
        query = sq_info["query"].strip()
        if "LIMIT" not in query.upper():
            query = query + f" LIMIT {limit}"
        if fallback_endpoints:
            scoped_frames: list[pd.DataFrame] = []
            for fallback_endpoint in fallback_endpoints:
                fallback_raw = sparql_client.select_csv(
                    fallback_endpoint, query, timeout
                )
                fallback_df = pd.read_csv(BytesIO(fallback_raw))
                if not fallback_df.empty:
                    scoped_frames.append(fallback_df)
                if sum(len(frame) for frame in scoped_frames) >= n_instances:
                    break
            if scoped_frames:
                df = pd.concat(scoped_frames, ignore_index=True).drop_duplicates()
            else:
                df = pd.DataFrame()
        else:
            raw = sparql_client.select_csv(endpoint, query, timeout)
            df = pd.read_csv(BytesIO(raw))
        if df.empty:
            continue
        # percentile filter for numeric columns to remove extreme outliers
        for col in df.select_dtypes(include="number").columns:
            lo = df[col].quantile(0.10)
            hi = df[col].quantile(0.90)
            df = df[(df[col] >= lo) & (df[col] <= hi)]
        dfs.append(df)

    if not dfs:
        return pd.DataFrame()

    result = dfs[0]
    for other in dfs[1:]:
        shared = list(set(result.columns) & set(other.columns))
        if shared:
            result = result.merge(other, on=shared, how="inner")
        else:
            # Cross join (rare, but handle it)
            result = result.merge(other, how="cross")

    if len(result) > n_instances:
        result = result.sample(n_instances, random_state=seed)

    return result.reset_index(drop=True)


def instantiate_workload(query_text: str, row: dict) -> str:
    """Substitute placeholder variables in SPARQL algebra with concrete values.

    Preserves the inequality-direction epsilon fix from the handoff doc:
    the injection replaces Variable nodes in the algebra, which correctly
    handles !=, <, <=, >, >= by operating at the algebra level, not string-level.
    """
    algebra, options = _parse_query_text(query_text)
    algebra = traverse(algebra, visitPost=lambda node: inject_constant_into_placeholders(node, row))
    algebra = traverse(algebra, visitPost=disable_offset)
    return _export_query(algebra, options)


def decompose_query(query_text: str) -> dict:
    """Return composition dict {tp0: [s, p, o], ...} for a query."""
    from itertools import chain

    def translate_node(node, children):
        if isinstance(node, CompValue) and node.name == "pname":
            return f'{node["prefix"]}:{node["localname"]}'
        elif callable(getattr(node, "n3", None)):
            # CompValue.__getattr__ returns None for missing attrs instead of raising
            # AttributeError, so we must check callable() to distinguish rdflib terms
            # (URIRef/Variable/Literal with a real n3() method) from CompValues.
            return str(node)
        return children[0] if isinstance(children, list) and children else children

    def visit_add_triple(node, children):
        if isinstance(node, CompValue) and node.name == "TriplesBlock":
            for triple in node["triples"]:
                s = _traverseAgg(triple[0], translate_node)
                p = _traverseAgg(triple[1], translate_node)
                o = _traverseAgg(triple[2], translate_node)
                children.append([(s, p, o)])
        return list(chain(*children))

    algebra, _ = _parse_query_text(query_text)
    composition = {}
    for triple_id, triple in enumerate(_traverseAgg(algebra, visit_add_triple)):
        composition[f"tp{triple_id}"] = list(triple)
    return composition


def execute_reference_query(
    query_text: str,
    endpoint: str,
    *,
    sparql_client: SparqlClient | None = None,
    timeout: int | None = None,
    scoped_endpoints: list[str] | None = None,
) -> pd.DataFrame:
    """Execute an injected SPARQL query and return results as a DataFrame."""
    if sparql_client is None:
        sparql_client = SparqlClient()
    if scoped_endpoints:
        matching_endpoints = []
        for scoped in scoped_endpoints:
            graphs = parse_qs(urlsplit(scoped).query).get(
                "default-graph-uri", []
            )
            if any(f"<{graph}" in query_text for graph in graphs):
                matching_endpoints.append(scoped)
        targets = matching_endpoints or scoped_endpoints
        frames = [
            pd.read_csv(
                BytesIO(sparql_client.select_csv(scoped, query_text, timeout))
            )
            for scoped in targets
        ]
        return pd.concat(frames, ignore_index=True).drop_duplicates(
            ignore_index=True
        )
    raw = sparql_client.select_csv(endpoint, query_text, timeout)
    return pd.read_csv(BytesIO(raw))


def generate_queries_for_template(
    template_path: Path,
    const_path: Path,
    output_dir: Path,
    config: BenchmarkConfig,
    batch_id: int,
    *,
    sparql_client: SparqlClient | None = None,
) -> None:
    """Orchestrate the four query-generation steps for one template.

    Writes to output_dir:
      - value_selection.json
      - workload_value_selection.csv
      - instance_{i}/injected.sparql
      - instance_{i}/composition.json
      - instance_{i}/results-batch{batch_id}.csv
    """
    if sparql_client is None:
        sparql_client = SparqlClient()

    query_text = template_path.read_text()
    const_info: dict = json.loads(const_path.read_text())
    endpoint = config.generation.virtuoso.default_endpoint
    n_instances = config.generation.n_query_instances
    mapping_file = (
        Path(config.generation.workdir)
        / f"virtuoso-proxy-mapping-batch{batch_id}.json"
    )
    mapping: dict[str, str] = {}
    if mapping_file.exists():
        mapping = json.loads(mapping_file.read_text())
    fallback_endpoints = [
        unquote(str(endpoint_url)).replace("host.docker.internal", "localhost")
        for endpoint_url in mapping.values()
    ]
    reference_endpoint = endpoint
    if mapping:
        separator = "&" if "?" in endpoint else "?"
        graph_query = urlencode(
            [("default-graph-uri", graph_iri) for graph_iri in mapping]
        )
        reference_endpoint = f"{endpoint}{separator}{graph_query}"

    # Step 1: build value-selection subqueries
    value_sel_file = output_dir / "value_selection.json"
    _locked = value_sel_file.exists() and json.loads(value_sel_file.read_text()).get("_locked")
    if not _locked and (batch_id == 0 or not value_sel_file.exists()):
        subqueries = build_value_selection_query(query_text, const_info)
        value_sel_file.write_text(json.dumps(subqueries, indent=2))
    else:
        subqueries = {k: v for k, v in json.loads(value_sel_file.read_text()).items() if not k.startswith("_")}

    # Step 2: sample workload values
    wvs_file = output_dir / "workload_value_selection.csv"
    wvs_df: pd.DataFrame = pd.DataFrame()
    _wvs_loaded = False
    if wvs_file.exists():
        try:
            wvs_df = _read_csv(wvs_file)
            required_columns = set(const_info)
            _wvs_loaded = (
                batch_id > 0
                and
                len(wvs_df) >= n_instances
                and required_columns.issubset(wvs_df.columns)
            )
        except Exception:
            pass
    if not _wvs_loaded:
        wvs_df = sample_workload_values(
            subqueries,
            endpoint,
            n_instances,
            sparql_client=sparql_client,
            timeout=120,
            fallback_endpoints=fallback_endpoints,
        )

    # Derive missing const columns from "query" conditions in const_info.
    # E.g. "'word1' in 'label'" → extract first word of label as word1.
    # E.g. "'currentDate' < 'date'" → use the date value as currentDate.
    _derived = False
    for const_name, info in const_info.items():
        if wvs_df.empty or const_name in wvs_df.columns:
            continue
        query_cond = info.get("query", "")
        m = _re.match(r"`(\w+)`\s+in\s+`(\w+)`", query_cond.strip())
        if m and m.group(2) in wvs_df.columns:
            wvs_df[const_name] = wvs_df[m.group(2)].apply(
                lambda v: str(v).split()[0] if pd.notna(v) and str(v).strip() else v
            )
            _derived = True
            continue
        m = _re.match(r"`(\w+)`\s*([<>]=?)\s*`(\w+)`", query_cond.strip())
        if m and m.group(3) in wvs_df.columns:
            src_col = m.group(3)
            op = m.group(2)
            src = wvs_df[src_col]
            try:
                src_dt = pd.to_datetime(src, errors="coerce")
                if src_dt.notna().all():
                    delta = pd.Timedelta(days=365)
                    # const < src → const must be earlier; const > src → const must be later
                    adjusted = src_dt - delta if op.startswith("<") else src_dt + delta
                    wvs_df[const_name] = adjusted.dt.strftime("%Y-%m-%d")
                else:
                    wvs_df[const_name] = src
            except Exception:
                wvs_df[const_name] = src
            _derived = True

    if not _wvs_loaded or _derived:
        wvs_df.to_csv(wvs_file, index=False)

    # Step 3+4: instantiate and execute reference queries per instance
    rows = wvs_df.to_dict(orient="records")
    for instance_id, row in enumerate(rows[:n_instances]):
        inst_dir = output_dir / f"instance_{instance_id}"
        inst_dir.mkdir(parents=True, exist_ok=True)

        injected_path = inst_dir / "injected.sparql"
        if batch_id == 0 or not injected_path.exists():
            # Only inject actual const variables; auxiliary columns (used to derive
            # const values) should not replace query variables.
            const_row = {k: v for k, v in row.items() if k in const_info}
            injected = instantiate_workload(query_text, const_row)
            injected_path.write_text(injected)
        else:
            injected = injected_path.read_text()

        comp_path = inst_dir / "composition.json"
        if batch_id == 0 or not comp_path.exists():
            comp = decompose_query(injected)
            comp_path.write_text(json.dumps(comp, indent=2))
        else:
            comp = json.loads(comp_path.read_text())

        ref_results_path = inst_dir / f"results-batch{batch_id}.csv"
        ref_df = execute_reference_query(
            injected,
            reference_endpoint,
            sparql_client=sparql_client,
            scoped_endpoints=(
                fallback_endpoints
                if _uses_source_local_reference(template_path.stem)
                else None
            ),
        )
        ref_df.to_csv(ref_results_path, index=False)
