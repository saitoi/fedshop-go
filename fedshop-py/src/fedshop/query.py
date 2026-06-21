"""Phase 3: Query generation.

Reimplementation of reference-repos/FedShop/fedshop/query.py without
omegaconf, nltk, fasttext, or iso639.
"""

from __future__ import annotations

import json
from copy import deepcopy
from io import BytesIO, StringIO
from itertools import chain
from pathlib import Path

import pandas as pd
from rdflib.plugins.sparql.algebra import (
    _traverseAgg,
    pprintAlgebra,
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


# ─── Internal helpers ────────────────────────────────────────────────────────

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
    try:
        from .algebra.pandas_algebra import collect_constants, parse_expr
    except ImportError:
        collect_constants = parse_expr = None  # type: ignore[assignment]

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

    if not subq_bgp_algebras:
        subq_bgp_algebras = [("join", _traverseAgg(algebra, extract_where)[0])]

    subqueries = {}
    for subq_id, (kind, subq_bgp_algebra) in enumerate(subq_bgp_algebras):
        subq_vars = set(map(str, _traverseAgg(subq_bgp_algebra, collect_triple_variables))) & cond_consts

        subq_bgp_algebra = traverse(
            subq_bgp_algebra,
            visitPost=lambda x: remove_filter_with_placeholders(
                x, consts={"query": subq_vars, "filter": filter_consts}
            ),
        )
        subq_bgp_algebra = traverse(subq_bgp_algebra, visitPost=disable_orderby_limit)
        subq_bgp_algebra = traverse(subq_bgp_algebra, visitPost=disable_offset)

        if kind == "exclusive":
            subqueries[f"sq{subq_id}"] = {
                "kind": kind,
                "query": _export_query(subq_bgp_algebra, options),
            }
        elif kind in ("join", "optional"):
            subq_consts = [CompValue("vars", var=Variable(c)) for c in subq_vars]
            subq_algebra = traverse(
                algebra,
                visitPost=lambda node: build_sub_query(node, new_where=subq_bgp_algebra, new_proj=subq_consts),
            )
            subqueries[f"sq{subq_id}"] = {
                "kind": kind,
                "query": _export_query(subq_algebra, options),
            }

    return subqueries


def sample_workload_values(
    subqueries: dict,
    endpoint: str,
    n_instances: int,
    *,
    seed: int = PANDAS_RANDOM_STATE,
    sparql_client: SparqlClient | None = None,
) -> pd.DataFrame:
    """Fire subqueries against the endpoint, join results, sample n_instances rows."""
    if sparql_client is None:
        sparql_client = SparqlClient()

    dfs: list[pd.DataFrame] = []
    for sq_id, sq_info in subqueries.items():
        raw = sparql_client.select_csv(endpoint, sq_info["query"])
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
) -> pd.DataFrame:
    """Execute an injected SPARQL query and return results as a DataFrame."""
    if sparql_client is None:
        sparql_client = SparqlClient()
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

    # Step 1: build value-selection subqueries
    value_sel_file = output_dir / "value_selection.json"
    if not value_sel_file.exists():
        subqueries = build_value_selection_query(query_text, const_info)
        value_sel_file.write_text(json.dumps(subqueries, indent=2))
    else:
        subqueries = json.loads(value_sel_file.read_text())

    # Step 2: sample workload values
    wvs_file = output_dir / "workload_value_selection.csv"
    if not wvs_file.exists():
        wvs_df = sample_workload_values(
            subqueries, endpoint, n_instances, sparql_client=sparql_client
        )
        wvs_df.to_csv(wvs_file, index=False)
    else:
        wvs_df = _read_csv(wvs_file)

    # Step 3+4: instantiate and execute reference queries per instance
    rows = wvs_df.to_dict(orient="records")
    for instance_id, row in enumerate(rows[:n_instances]):
        inst_dir = output_dir / f"instance_{instance_id}"
        inst_dir.mkdir(parents=True, exist_ok=True)

        injected_path = inst_dir / "injected.sparql"
        if not injected_path.exists():
            injected = instantiate_workload(query_text, row)
            injected_path.write_text(injected)
        else:
            injected = injected_path.read_text()

        comp_path = inst_dir / "composition.json"
        if not comp_path.exists():
            comp = decompose_query(injected)
            comp_path.write_text(json.dumps(comp, indent=2))

        ref_results_path = inst_dir / f"results-batch{batch_id}.csv"
        if not ref_results_path.exists():
            ref_df = execute_reference_query(injected, endpoint, sparql_client=sparql_client)
            ref_df.to_csv(ref_results_path, index=False)
