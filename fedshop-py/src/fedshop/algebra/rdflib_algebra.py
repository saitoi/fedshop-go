"""SPARQL algebra → SPARQL string translator.

Ported from reference-repos/FedShop/fedshop/algebra/rdflib_algebra.py with three patches:
  1. XSD.date literal handling for YYYY-MM-DD strings in inject_constant_into_placeholders.
  2. translateAlgebra emits "-*-SELECT-*- {" (no WHERE keyword).
  3. query.txt side-channel replaced with io.StringIO for thread/process safety.
"""

import ast
import collections
from io import StringIO
from itertools import chain
import re
from typing import DefaultDict, List
import typing
import uuid

import dateutil.parser
import pandas as pd
from rdflib.plugins.sparql.parserutils import CompValue, Expr
from rdflib.plugins.sparql.sparql import Query
from rdflib.plugins.sparql.algebra import ExpressionNotCoveredException, traverse, _traverseAgg, translateQuery
from rdflib.namespace import XSD
from rdflib.term import Variable, Literal, URIRef, Identifier


def extract_where(node, children):
    if isinstance(node, CompValue):
        if node.name == "SelectQuery":
            children.append([node["where"]])
    return list(chain(*children))


def collect_variables(node, children):
    if isinstance(node, Variable):
        children.append([node])
    return list(chain(*children))


def collect_triple_variables(node, children):
    if isinstance(node, CompValue):
        if node.name == "TriplesBlock":
            for triple in node["triples"]:
                for component in triple:
                    if isinstance(component, Variable):
                        children.append([component])
                    elif isinstance(component, CompValue) and component.name == "vars":
                        children.append([component["var"]])
    return list(chain(*children))


def disable_orderby_limit(node):
    if isinstance(node, CompValue):
        node.pop("orderby", None)
        node.pop("limitoffset", None)
        return node


def disable_offset(node):
    if isinstance(node, CompValue) and node.name == "LimitOffsetClauses":
        node.pop("offset", None)
        return node


def inject_constant_into_placeholders(node, injection_dict):
    """Inject constant values into placeholder variables in the query algebra.

    Patch 1: handles YYYY-MM-DD date strings as XSD.date literals.
    """

    def normalize(value):
        if str(value).startswith("http") or str(value).startswith("nodeID"):
            return URIRef(value)
        try:
            value = ast.literal_eval(str(value))
            return Literal(value)
        except (ValueError, SyntaxError):
            pass

        # Patch 1: exact date format → XSD.date (not datetime)
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(value)):
            return Literal(str(value), datatype=XSD.date)

        try:
            dateutil.parser.parse(str(value))
            return Literal(pd.to_datetime(value))
        except (ValueError, OverflowError):
            pass

        return Literal(value)

    if isinstance(node, Variable):
        var_name = str(node)
        if var_name in injection_dict:
            return normalize(injection_dict[var_name])
    elif isinstance(node, CompValue):
        if node.name == "vars":
            var_name = str(node["var"])
            if var_name in injection_dict:
                normalize(injection_dict[var_name])


def add_graph_to_triple_pattern(node):
    if isinstance(node, CompValue):
        if node.name == "TriplesBlock":
            graph_triples = []
            for triple in node["triples"]:
                graph_id = str(uuid.uuid4())[:8]
                graph_node = CompValue(
                    "GraphGraphPattern",
                    term=Variable(f"g{graph_id}"),
                    graph=CompValue(
                        "GroupGraphPatternSub",
                        part=[CompValue("TriplesBlock", triples=[triple])],
                    ),
                )
                graph_triples.append(graph_node)
            node = graph_triples
            return node
        elif node.name == "GroupGraphPatternSub":
            new_part = []
            for part in node["part"]:
                if isinstance(part, list):
                    new_part.extend(part)
                else:
                    new_part.append(part)
            node["part"] = new_part
            return node


def collect_graphs_variables(node, children):
    if isinstance(node, CompValue):
        if node.name == "GraphGraphPattern":
            children.append([node["term"]])
    return list(chain(*children))


def replace_select_projection_with_graph(node):
    if isinstance(node, CompValue):
        if node.name in ["SelectQuery", "ConstructQuery", "DescribeQuery", "AskQuery"]:
            graph_vars = _traverseAgg(node["where"], collect_graphs_variables)
            return CompValue(
                "SelectQuery",
                modifier="DISTINCT",
                projection=graph_vars,
                where=node["where"],
            )
    return node


def is_node_placeholder(node):
    return isinstance(node, CompValue) and node.name == "Placeholder"


def is_node_literal(node, children):
    if isinstance(node, CompValue):
        expr = node.get("expr")
        if expr and isinstance(expr, Literal):
            children.append([True])
    return list(chain(*children))


def get_old_node(node):
    if is_node_placeholder(node):
        return get_old_node(node["old"])
    return node


def remove_expression_with_placeholder(node, consts):
    if len(consts) == 0:
        return node

    if isinstance(node, Variable):
        if str(node) not in consts:
            return CompValue("Placeholder", old=node)
        return node
    elif isinstance(node, CompValue):
        is_binary_expr = "expr" in node.keys() and "other" in node.keys()
        is_unary_expr = "expr" in node.keys() and "other" not in node.keys()

        if is_unary_expr:
            expr = node["expr"]
            new_expr = traverse(expr, visitPost=lambda x: remove_expression_with_placeholder(x, consts))
            if is_node_placeholder(new_expr):
                return CompValue("Placeholder", old=expr["old"])
            else:
                node["expr"] = new_expr

        elif is_binary_expr:
            has_empty_expr = False
            has_empty_other = False
            is_other_literal = False

            expr = node["expr"]
            new_expr = traverse(expr, visitPost=lambda x: remove_expression_with_placeholder(x, consts))
            if is_node_placeholder(new_expr):
                has_empty_expr = True
            else:
                node["expr"] = new_expr

            other = node["other"]
            is_other_literal = all(_traverseAgg(other, is_node_literal))

            if is_node_placeholder(other):
                return CompValue("Placeholder", old=other["old"])

            if not isinstance(other, list):
                other = [other]

            new_other = []
            for o in other:
                new_o = traverse(o, visitPost=lambda x: remove_expression_with_placeholder(x, consts))
                if is_node_placeholder(new_o):
                    continue
                new_other.append(new_o)

            if len(new_other) == 1:
                new_other = new_other[0]

            if len(new_other) == 0:
                has_empty_other = True

            if not has_empty_expr and not has_empty_other:
                node["expr"] = new_expr
                node["other"] = new_other
            elif has_empty_expr and has_empty_other:
                return CompValue("Placeholder", old=node)

            if has_empty_expr:
                if is_other_literal:
                    node["expr"] = get_old_node(expr)
                elif isinstance(new_other, list):
                    node["expr"] = new_other.pop(0)
                    if len(new_other) == 0:
                        has_empty_other = True
                    elif len(new_other) == 1:
                        node["other"] = new_other[0]
                    else:
                        node["other"] = new_other
                else:
                    node["expr"] = new_other

            if has_empty_other:
                node.pop("other", None)

        elif node.name == "Function":
            raise NotImplementedError("Function expressions are not supported yet")
        elif node.name.startswith("Builtin"):
            if node.name == "Builtin_BOUND":
                arg = node["arg"]
                new_arg = traverse(arg, visitPost=lambda x: remove_expression_with_placeholder(x, consts))
                if is_node_placeholder(new_arg):
                    return CompValue("Placeholder", old=arg)
                node["arg"] = new_arg
            elif node.name == "Builtin_REGEX":
                new_text = traverse(node["text"], visitPost=lambda x: remove_expression_with_placeholder(x, consts))
                if is_node_placeholder(new_text):
                    return CompValue("Placeholder", old=node["text"])
                new_pattern = traverse(node["pattern"], visitPost=lambda x: remove_expression_with_placeholder(x, consts))
                if is_node_placeholder(new_pattern):
                    return CompValue("Placeholder", old=node["pattern"])
                node["text"] = new_text
                node["pattern"] = new_pattern

        return node


def remove_filter_with_placeholders(node, consts):
    query_consts = set(consts["query"])

    select_consts = None
    if "select" in consts.keys():
        select_consts = set(consts["select"]) & query_consts
    filter_consts = set(consts["filter"]) & query_consts

    if isinstance(node, CompValue):
        if node.name == "SelectQuery":
            if select_consts:
                node["projection"] = list(map(lambda x: CompValue("vars", var=Variable(x)), select_consts))
            node["modifier"] = "DISTINCT"
            return node

        if node.name == "Filter":
            node = traverse(node, visitPost=lambda x: remove_expression_with_placeholder(x, filter_consts))
            return node

        if "part" in node.keys():
            if isinstance(node["part"], list):
                new_parts = []
                for part in node["part"]:
                    if is_node_placeholder(part):
                        continue
                    new_parts.append(part)
                node["part"] = new_parts

        node.pop("orderby", None)
        node.pop("limitoffset", None)
        return node


def add_values_with_placeholders(node, inline_data):
    if isinstance(node, CompValue):
        if node.name == "SelectQuery":
            inline_data_keys = [Variable(k) for k in inline_data.keys()]
            inline_data_values = [
                [URIRef(v) if str(v).startswith("http") else Literal(v) for v in values]
                for values in inline_data.values()
            ]
            if len(inline_data_keys) == 1:
                inline_data_values = inline_data_values[0]

            values_clause = CompValue(
                "InlineData",
                var=inline_data_keys,
                value=inline_data_values,
            )
            node["where"]["part"].insert(0, values_clause)
            return node


# --------- MISC ------------

def translateAlgebra(query_algebra) -> str:
    """Translate a parsed SPARQL algebra back to a SPARQL query string.

    Patch 2: emits '-*-SELECT-*- {' (no WHERE keyword) to match generated query syntax.
    Patch 3: uses io.StringIO instead of a query.txt file on disk to avoid race conditions
             under parallel pytest runs.
    """

    buf: list[str] = [""]

    def overwrite(text: str) -> None:
        buf[0] = text

    def replace(
        old: str,
        new: str,
        search_from_match: str = None,
        search_from_match_occurrence: int = None,
        count: int = 1,
    ) -> None:
        filedata = buf[0]

        def find_nth(haystack: str, needle: str, n: int) -> int:
            start = haystack.lower().find(needle)
            while start >= 0 and n > 1:
                start = haystack.lower().find(needle, start + len(needle))
                n -= 1
            return start

        if search_from_match and search_from_match_occurrence:
            position = find_nth(filedata, search_from_match, search_from_match_occurrence)
            filedata_pre = filedata[:position]
            filedata_post = filedata[position:].replace(old, new, count)
            filedata = filedata_pre + filedata_post
        else:
            filedata = filedata.replace(old, new, count)

        buf[0] = filedata

    aggr_vars: dict = collections.defaultdict(list)

    def convert_node_arg(node_arg: typing.Union[Identifier, CompValue, Expr, str]) -> str:
        if isinstance(node_arg, Identifier):
            if node_arg in aggr_vars.keys():
                grp_var = aggr_vars[node_arg].pop(0).n3()
                return grp_var
            else:
                return node_arg.n3()
        elif isinstance(node_arg, CompValue):
            return "{" + node_arg.name + "}"
        elif isinstance(node_arg, Expr):
            return "{" + node_arg.name + "}"
        elif isinstance(node_arg, str):
            return node_arg
        else:
            raise ExpressionNotCoveredException(
                "The expression {0} might not be covered yet.".format(node_arg)
            )

    def sparql_query_text(node):
        identation_level = 0
        identation_token = " " * 4
        breakline_token = "\n"

        if isinstance(node, CompValue):
            identation = identation_token * identation_level
            next_level_identation = identation_token * (identation_level + 1)

            # Patch 2: no WHERE keyword — emit "-*-SELECT-*- {"
            if node.name == "SelectQuery":
                overwrite(
                    identation + "-*-SELECT-*- " + "{" + node.p.name + "}" + breakline_token +
                    identation + breakline_token
                )
                identation_level += 1

            elif node.name == "BGP":
                triples = "".join(
                    identation + triple[0].n3() + " " + triple[1].n3() + " " + triple[2].n3() + "." + breakline_token
                    for triple in node.triples
                )
                replace("{BGP}", triples)
                replace("-*-SELECT-*-", "SELECT", count=-1)
                replace("{GroupBy}", "", count=-1)
                replace("{Having}", "", count=-1)
            elif node.name == "Join":
                replace(
                    "{Join}",
                    "{" + node.p1.name + "}" + breakline_token +
                    "{" + node.p2.name + "}" + breakline_token,
                )
            elif node.name == "LeftJoin":
                replace(
                    "{LeftJoin}",
                    identation + "{" + node.p1.name + "}" + breakline_token +
                    identation + "OPTIONAL" + "{" + breakline_token +
                    identation + "{" + node.p2.name + "}" + breakline_token +
                    identation + "}" + breakline_token,
                )
            elif node.name == "Filter":
                if isinstance(node.expr, CompValue):
                    expr = node.expr.name
                else:
                    raise ExpressionNotCoveredException("This expression might not be covered yet.")
                if node.p:
                    if node.p.name == "AggregateJoin":
                        replace(
                            "{Filter}",
                            identation + breakline_token +
                            identation + "{" + node.p.name + "}" + breakline_token,
                        )
                        replace(
                            "{Having}",
                            identation + "HAVING({" + expr + "})" + breakline_token,
                        )
                    else:
                        replace(
                            "{Filter}",
                            identation + "FILTER({" + expr + "})" + breakline_token +
                            "{" + node.p.name + "}" + breakline_token,
                        )
                else:
                    replace("{Filter}", identation + "FILTER({" + expr + "})" + breakline_token)

            elif node.name == "Union":
                replace(
                    "{Union}",
                    identation + "{" + breakline_token +
                    next_level_identation + "{" + node.p1.name + "}" + breakline_token +
                    identation + "} UNION {" + breakline_token +
                    next_level_identation + "{" + node.p2.name + "}" + breakline_token +
                    identation + "}" + breakline_token,
                )
            elif node.name == "Graph":
                expr = (
                    identation + "GRAPH " + node.term.n3() + " {" + breakline_token +
                    next_level_identation + "{" + node.p.name + "}" + breakline_token +
                    identation + "}" + breakline_token
                )
                replace("{Graph}", expr)
            elif node.name == "Extend":
                query_string = buf[0].lower()
                select_occurrences = query_string.count("-*-select-*-")
                replace(
                    node.var.n3(),
                    "(" + convert_node_arg(node.expr) + " as " + node.var.n3() + ")",
                    search_from_match="-*-select-*-",
                    search_from_match_occurrence=select_occurrences,
                )
                replace("{Extend}", identation + "{" + node.p.name + "}")
            elif node.name == "Minus":
                expr = (
                    next_level_identation + "{" + node.p1.name + "}" + breakline_token +
                    identation + "} MINUS {" + breakline_token +
                    next_level_identation + "{" + node.p2.name + "}" + breakline_token +
                    identation + "}" + breakline_token
                )
                replace("{Minus}", expr)
            elif node.name == "Group":
                group_by_vars = []
                if node.expr:
                    for var in node.expr:
                        if isinstance(var, Identifier):
                            group_by_vars.append(var.n3())
                        else:
                            raise ExpressionNotCoveredException("This expression might not be covered yet.")
                    replace("{Group}", "{" + node.p.name + "}")
                    replace("{GroupBy}", "GROUP BY " + " ".join(group_by_vars) + " ")
                else:
                    replace("{Group}", "{" + node.p.name + "}")
            elif node.name == "AggregateJoin":
                replace("{AggregateJoin}", "{" + node.p.name + "}")
                for agg_func in node.A:
                    if isinstance(agg_func.res, Identifier):
                        identifier = agg_func.res.n3()
                    else:
                        raise ExpressionNotCoveredException("This expression might not be covered yet.")
                    aggr_vars[agg_func.res].append(agg_func.vars)

                    agg_func_name = agg_func.name.split("_")[1]
                    distinct = ""
                    if agg_func.distinct:
                        distinct = agg_func.distinct + " "
                    if agg_func_name == "GroupConcat":
                        replace(
                            identifier,
                            "GROUP_CONCAT(" + distinct + agg_func.vars.n3() + ";SEPARATOR=" + agg_func.separator.n3() + ")",
                        )
                    else:
                        replace(
                            identifier,
                            agg_func_name.upper() + "(" + distinct + convert_node_arg(agg_func.vars) + ")",
                        )
                    replace(
                        "(SAMPLE({0}) as {0})".format(convert_node_arg(agg_func.vars)),
                        convert_node_arg(agg_func.vars),
                    )
            elif node.name == "GroupGraphPatternSub":
                replace(
                    "GroupGraphPatternSub",
                    identation + "{" + breakline_token +
                    "".join([
                        next_level_identation + convert_node_arg(pattern)
                        for pattern in node.part
                    ]) +
                    identation + "}" + breakline_token,
                )
                identation_level += 1

            elif node.name == "TriplesBlock":
                replace(
                    "{TriplesBlock}",
                    "".join(
                        identation + triple[0].n3() + " " + triple[1].n3() + " " + triple[2].n3() + "." + breakline_token
                        for triple in node.triples
                    ),
                )

            elif node.name == "ToList":
                raise ExpressionNotCoveredException("This expression might not be covered yet.")
            elif node.name == "OrderBy":
                order_conditions = []
                for c in node.expr:
                    if isinstance(c.expr, Identifier):
                        var = c.expr.n3()
                        cond = (c.order + "(" + var + ")") if c.order is not None else var
                        order_conditions.append(cond)
                    elif isinstance(c.expr, CompValue):
                        if c.expr.name == "Function":
                            function_iri = c.expr.iri.n3()
                            function_expr = c.expr.expr
                            if isinstance(function_expr, list):
                                function_expr = ", ".join(convert_node_arg(expr) for expr in function_expr)
                            order_conditions.append(f"{function_iri}({function_expr})")
                        else:
                            raise ExpressionNotCoveredException("This expression might not be covered yet.")
                    else:
                        raise ExpressionNotCoveredException("This expression might not be covered yet.")
                replace("{OrderBy}", "{" + node.p.name + "}")
                replace("{OrderConditions}", " ".join(order_conditions) + " ")
            elif node.name == "Project":
                project_variables = []
                for var in node.PV:
                    if isinstance(var, Identifier):
                        project_variables.append(var.n3())
                    else:
                        raise ExpressionNotCoveredException("This expression might not be covered yet.")
                order_by_pattern = ""
                if node.p.name == "OrderBy":
                    order_by_pattern = "ORDER BY {OrderConditions}"
                replace(
                    "{Project}",
                    " ".join(project_variables) + " " +
                    "{" + breakline_token +
                    "{" + node.p.name + "}" + breakline_token +
                    "}" + breakline_token +
                    "{GroupBy}" + breakline_token +
                    order_by_pattern + breakline_token +
                    "{Having}" + breakline_token,
                )
            elif node.name == "Distinct":
                replace("{Distinct}", "DISTINCT {" + node.p.name + "}")
            elif node.name == "Reduced":
                replace("{Reduced}", "REDUCED {" + node.p.name + "}")
            elif node.name == "Slice":
                slice_str = "OFFSET " + str(node.start) + " LIMIT " + str(node.length)
                replace("{Slice}", "{" + node.p.name + "}" + slice_str)
            elif node.name == "ToMultiSet":
                if node.p.name == "values":
                    replace(
                        "{ToMultiSet}",
                        next_level_identation + "{" + node.p.name + "}" + breakline_token,
                    )
                else:
                    replace(
                        "{ToMultiSet}",
                        next_level_identation + "-*-SELECT-*- " + "{" + node.p.name + "}" + breakline_token,
                    )

            elif node.name == "RelationalExpression":
                expr = convert_node_arg(node.expr)
                op = node.op
                if isinstance(list, type(node.other)):
                    other = "(" + ", ".join(convert_node_arg(e) for e in node.other) + ")"
                else:
                    other = convert_node_arg(node.other)
                condition = "{left} {operator} {right}".format(left=expr, operator=op, right=other)
                replace("{RelationalExpression}", condition)
            elif node.name == "ConditionalAndExpression":
                inner_nodes = " && ".join([convert_node_arg(expr) for expr in node.other])
                replace("{ConditionalAndExpression}", convert_node_arg(node.expr) + " && " + inner_nodes)
            elif node.name == "ConditionalOrExpression":
                inner_nodes = " || ".join([convert_node_arg(expr) for expr in node.other])
                replace("{ConditionalOrExpression}", "(" + convert_node_arg(node.expr) + " || " + inner_nodes + ")")
            elif node.name == "MultiplicativeExpression":
                left_side = convert_node_arg(node.expr)
                multiplication = left_side
                for i, operator in enumerate(node.op):
                    multiplication += " " + operator + " " + convert_node_arg(node.other[i]) + " "
                replace("{MultiplicativeExpression}", multiplication)
            elif node.name == "AdditiveExpression":
                left_side = convert_node_arg(node.expr)
                addition = left_side
                for i, operator in enumerate(node.op):
                    addition += " " + operator + " " + convert_node_arg(node.other[i]) + " "
                replace("{AdditiveExpression}", addition)
            elif node.name == "UnaryNot":
                replace("{UnaryNot}", "!" + convert_node_arg(node.expr))

            elif node.name.endswith("BOUND"):
                replace("{Builtin_BOUND}", "bound(" + convert_node_arg(node.arg) + ")")
            elif node.name.endswith("IF"):
                if_expression = "IF(" + "{" + node.arg1.name + "}, " + convert_node_arg(node.arg2) + ", " + convert_node_arg(node.arg3) + ")"
                replace("{Builtin_IF}", if_expression)
            elif node.name.endswith("COALESCE"):
                replace("{Builtin_COALESCE}", "COALESCE(" + ", ".join(convert_node_arg(arg) for arg in node.arg) + ")")
            elif node.name.endswith("Builtin_EXISTS"):
                replace(
                    "{Builtin_EXISTS}",
                    identation + "EXISTS " + "{{" + breakline_token +
                    next_level_identation + node.graph.name + breakline_token +
                    identation + "}}" + breakline_token,
                )
                traverse(node.graph, visitPre=sparql_query_text)
                return node.graph
            elif node.name.endswith("Builtin_NOTEXISTS"):
                replace(
                    "{Builtin_NOTEXISTS}",
                    identation + "NOT EXISTS " + "{{" + breakline_token +
                    next_level_identation + node.graph.name + breakline_token +
                    identation + "}}" + breakline_token,
                )
                traverse(node.graph, visitPre=sparql_query_text)
                return node.graph
            elif node.name.endswith("sameTerm"):
                replace("{Builtin_sameTerm}", "SAMETERM(" + convert_node_arg(node.arg1) + ", " + convert_node_arg(node.arg2) + ")")
            elif node.name.endswith("Builtin_isIRI"):
                replace("{Builtin_isIRI}", "isIRI(" + convert_node_arg(node.arg) + ")")
            elif node.name.endswith("Builtin_isBLANK"):
                replace("{Builtin_isBLANK}", "isBLANK(" + convert_node_arg(node.arg) + ")")
            elif node.name.endswith("Builtin_isLITERAL"):
                replace("{Builtin_isLITERAL}", "isLITERAL(" + convert_node_arg(node.arg) + ")")
            elif node.name.endswith("Builtin_isNUMERIC"):
                replace("{Builtin_isNUMERIC}", "isNUMERIC(" + convert_node_arg(node.arg) + ")")
            elif node.name.endswith("Builtin_STR"):
                replace("{Builtin_STR}", "STR(" + convert_node_arg(node.arg) + ")")
            elif node.name.endswith("Builtin_LANG"):
                replace("{Builtin_LANG}", "LANG(" + convert_node_arg(node.arg) + ")")
            elif node.name.endswith("Builtin_DATATYPE"):
                replace("{Builtin_DATATYPE}", "DATATYPE(" + convert_node_arg(node.arg) + ")")
            elif node.name.endswith("Builtin_IRI"):
                replace("{Builtin_IRI}", "IRI(" + convert_node_arg(node.arg) + ")")
            elif node.name.endswith("Builtin_BNODE"):
                replace("{Builtin_BNODE}", "BNODE(" + convert_node_arg(node.arg) + ")")
            elif node.name.endswith("STRDT"):
                replace("{Builtin_STRDT}", "STRDT(" + convert_node_arg(node.arg1) + ", " + convert_node_arg(node.arg2) + ")")
            elif node.name.endswith("Builtin_STRLANG"):
                replace("{Builtin_STRLANG}", "STRLANG(" + convert_node_arg(node.arg1) + ", " + convert_node_arg(node.arg2) + ")")
            elif node.name.endswith("Builtin_UUID"):
                replace("{Builtin_UUID}", "UUID()")
            elif node.name.endswith("Builtin_STRUUID"):
                replace("{Builtin_STRUUID}", "STRUUID()")
            elif node.name.endswith("Builtin_STRLEN"):
                replace("{Builtin_STRLEN}", "STRLEN(" + convert_node_arg(node.arg) + ")")
            elif node.name.endswith("Builtin_SUBSTR"):
                args = [convert_node_arg(node.arg), node.start]
                if node.length:
                    args.append(node.length)
                replace("{Builtin_SUBSTR}", "SUBSTR(" + ", ".join(str(a) for a in args) + ")")
            elif node.name.endswith("Builtin_UCASE"):
                replace("{Builtin_UCASE}", "UCASE(" + convert_node_arg(node.arg) + ")")
            elif node.name.endswith("Builtin_LCASE"):
                replace("{Builtin_LCASE}", "LCASE(" + convert_node_arg(node.arg) + ")")
            elif node.name.endswith("Builtin_STRSTARTS"):
                replace("{Builtin_STRSTARTS}", "STRSTARTS(" + convert_node_arg(node.arg1) + ", " + convert_node_arg(node.arg2) + ")")
            elif node.name.endswith("Builtin_STRENDS"):
                replace("{Builtin_STRENDS}", "STRENDS(" + convert_node_arg(node.arg1) + ", " + convert_node_arg(node.arg2) + ")")
            elif node.name.endswith("Builtin_CONTAINS"):
                replace("{Builtin_CONTAINS}", "CONTAINS(" + convert_node_arg(node.arg1) + ", " + convert_node_arg(node.arg2) + ")")
            elif node.name.endswith("Builtin_STRBEFORE"):
                replace("{Builtin_STRBEFORE}", "STRBEFORE(" + convert_node_arg(node.arg1) + ", " + convert_node_arg(node.arg2) + ")")
            elif node.name.endswith("Builtin_STRAFTER"):
                replace("{Builtin_STRAFTER}", "STRAFTER(" + convert_node_arg(node.arg1) + ", " + convert_node_arg(node.arg2) + ")")
            elif node.name.endswith("Builtin_ENCODE_FOR_URI"):
                replace("{Builtin_ENCODE_FOR_URI}", "ENCODE_FOR_URI(" + convert_node_arg(node.arg) + ")")
            elif node.name.endswith("Builtin_CONCAT"):
                replace("{Builtin_CONCAT}", "CONCAT({vars})".format(vars=", ".join(convert_node_arg(elem) for elem in node.arg)))
            elif node.name.endswith("Builtin_LANGMATCHES"):
                replace("{Builtin_LANGMATCHES}", "LANGMATCHES(" + convert_node_arg(node.arg1) + ", " + convert_node_arg(node.arg2) + ")")
            elif node.name.endswith("REGEX"):
                args = [convert_node_arg(node.text), convert_node_arg(node.pattern)]
                replace("{Builtin_REGEX}", "REGEX(" + ", ".join(args) + ")")
            elif node.name.endswith("REPLACE"):
                replace("{Builtinreplace}", "REPLACE(" + convert_node_arg(node.arg) + ", " + convert_node_arg(node.pattern) + ", " + convert_node_arg(node.replacement) + ")")
            elif node.name == "Builtin_ABS":
                replace("{Builtin_ABS}", "ABS(" + convert_node_arg(node.arg) + ")")
            elif node.name == "Builtin_ROUND":
                replace("{Builtin_ROUND}", "ROUND(" + convert_node_arg(node.arg) + ")")
            elif node.name == "Builtin_CEIL":
                replace("{Builtin_CEIL}", "CEIL(" + convert_node_arg(node.arg) + ")")
            elif node.name == "Builtin_FLOOR":
                replace("{Builtin_FLOOR}", "FLOOR(" + convert_node_arg(node.arg) + ")")
            elif node.name == "Builtin_RAND":
                replace("{Builtin_RAND}", "RAND()")
            elif node.name == "Builtin_NOW":
                replace("{Builtin_NOW}", "NOW()")
            elif node.name == "Builtin_YEAR":
                replace("{Builtin_YEAR}", "YEAR(" + convert_node_arg(node.arg) + ")")
            elif node.name == "Builtin_MONTH":
                replace("{Builtin_MONTH}", "MONTH(" + convert_node_arg(node.arg) + ")")
            elif node.name == "Builtin_DAY":
                replace("{Builtin_DAY}", "DAY(" + convert_node_arg(node.arg) + ")")
            elif node.name == "Builtin_HOURS":
                replace("{Builtin_HOURS}", "HOURS(" + convert_node_arg(node.arg) + ")")
            elif node.name == "Builtin_MINUTES":
                replace("{Builtin_MINUTES}", "MINUTES(" + convert_node_arg(node.arg) + ")")
            elif node.name == "Builtin_SECONDS":
                replace("{Builtin_SECONDS}", "SECONDS(" + convert_node_arg(node.arg) + ")")
            elif node.name == "Builtin_TIMEZONE":
                replace("{Builtin_TIMEZONE}", "TIMEZONE(" + convert_node_arg(node.arg) + ")")
            elif node.name == "Builtin_TZ":
                replace("{Builtin_TZ}", "TZ(" + convert_node_arg(node.arg) + ")")
            elif node.name == "Builtin_MD5":
                replace("{Builtin_MD5}", "MD5(" + convert_node_arg(node.arg) + ")")
            elif node.name == "Builtin_SHA1":
                replace("{Builtin_SHA1}", "SHA1(" + convert_node_arg(node.arg) + ")")
            elif node.name == "Builtin_SHA256":
                replace("{Builtin_SHA256}", "SHA256(" + convert_node_arg(node.arg) + ")")
            elif node.name == "Builtin_SHA384":
                replace("{Builtin_SHA384}", "SHA384(" + convert_node_arg(node.arg) + ")")
            elif node.name == "Builtin_SHA512":
                replace("{Builtin_SHA512}", "SHA512(" + convert_node_arg(node.arg) + ")")
            elif node.name == "values":
                columns = []
                for key in node.res[0].keys():
                    if isinstance(key, Identifier):
                        columns.append(key.n3())
                    else:
                        raise ExpressionNotCoveredException(
                            "The expression {0} might not be covered yet.".format(key)
                        )
                values = "VALUES (" + " ".join(columns) + ")"
                rows = ""
                for elem in node.res:
                    row = []
                    for term in elem.values():
                        if isinstance(term, Identifier):
                            row.append(term.n3())
                        elif isinstance(term, str):
                            row.append(term)
                        else:
                            raise ExpressionNotCoveredException(
                                "The expression {0} might not be covered yet.".format(term)
                            )
                    rows += identation + "(" + " ".join(row) + ")" + breakline_token
                replace(
                    "{values}",
                    identation + values + "{" + breakline_token +
                    next_level_identation + rows + breakline_token +
                    identation + "}" + breakline_token,
                )
            elif node.name == "ServiceGraphPattern":
                replace(
                    "{ServiceGraphPattern}",
                    identation + "SERVICE " + convert_node_arg(node.term) + breakline_token +
                    "{" + node.graph.name + "}",
                )
                traverse(node.graph, visitPre=sparql_query_text)
                return node.graph

    traverse(query_algebra.algebra, visitPre=sparql_query_text)
    return buf[0]
