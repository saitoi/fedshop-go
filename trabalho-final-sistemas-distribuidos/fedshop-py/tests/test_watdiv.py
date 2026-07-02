from __future__ import annotations

from io import StringIO

from rdflib import ConjunctiveGraph

RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"


MODEL = """
#namespace ex=http://example.test/vocab/
#namespace rdf=http://www.w3.org/1999/02/22-rdf-syntax-ns#
#namespace __provenance=http://example.test/source/
#namespace __output_org=monolithic
#namespace __output_file=test

<type> ex:Parent 1
<pgroup> 1.0
#predicate ex:label string3
</pgroup>
</type>

<type> ex:Child 4
<pgroup> 1.0
#predicate ex:value integer 1 10 normal
</pgroup>
</type>

#association ex:Child ex:parent ex:Parent 2 1 NORMAL NORMAL
#association1 ex:Child rdf:type ex:Parent 2 1 NORMAL NORMAL
"""


def test_parse_template_preserves_resources_predicates_and_constraints():
    from fedshop.watdiv import parse_template

    model = parse_template(MODEL)

    assert model.namespaces["ex"] == "http://example.test/vocab/"
    assert [resource.type_prefix for resource in model.resources] == ["ex:Parent", "ex:Child"]
    assert model.resources[1].predicate_groups[0].predicates[0].literal_type == "integer"
    assert [association.constraint for association in model.associations] == [
        "chosen",
        "previously_existed",
    ]


def test_parse_template_matches_cpp_tolerance_for_repeated_type_close():
    from fedshop.watdiv import parse_template

    model = parse_template("""
#namespace ex=http://example.test/
<type> ex:Thing 1
</type>
<pgroup> 1.0
#predicate ex:value integer
</pgroup>
</type>
""")

    assert model.resources[0].predicate_groups[0].predicates[0].label == "ex:value"


def test_name_with_length_matches_cpp_undefined_literal_behavior():
    from fedshop.watdiv import generate_literal, parse_template
    import random

    model = parse_template("""
#namespace ex=http://example.test/
<type> ex:Person 1
<pgroup>
#predicate ex:name name3
</pgroup>
</type>
""")
    predicate = model.resources[0].predicate_groups[0].predicates[0]

    assert predicate.literal_type == "undefined"
    assert generate_literal(predicate, random.Random(1)) == '""'


def test_run_emits_valid_nquads_and_only_existing_subjects_for_association1():
    from fedshop.watdiv import run

    output = StringIO()
    run(MODEL, 1, output, seed=7)
    text = output.getvalue()

    graph = ConjunctiveGraph()
    graph.parse(data=text, format="nquads")
    assert len(graph) > 0
    assert "http://example.test/source/Child" in text
    assert "http://example.test/vocab/parent" in text


def test_run_scales_only_scalable_resource_types():
    from fedshop.watdiv import parse_template

    model = parse_template(MODEL)
    model.apply_scale(3)

    assert model.resources[0].count == 3
    assert model.resources[1].count == 12


def test_run_writes_fragmented_resources_to_type_directories(tmp_path):
    from fedshop.watdiv import run

    model = MODEL.replace("__output_org=monolithic", "__output_org=fragmented")
    run(model, 1, tmp_path, seed=7)

    fragments = list(tmp_path.glob("*/*.nq"))
    assert fragments
    assert all(path.parent.name in {"Child", "Parent"} for path in fragments)
    graph = ConjunctiveGraph()
    for fragment in fragments:
        graph.parse(fragment, format="nquads")
    assert len(graph) > 0


def test_run_localizes_and_recursively_copies_fragmented_dependencies(tmp_path):
    from fedshop.watdiv import run

    dep = tmp_path / "dep"
    (dep / "Product").mkdir(parents=True)
    (dep / "Producer").mkdir(parents=True)
    vocab = "http://example.test/vocab/"
    graph = "http://example.test/global/"
    (dep / "Product" / "Product0.nq").write_text(
        f"<{vocab}Product0>\t<{RDF_TYPE}>\t<{vocab}Product>\t<{graph}> .\n"
        f"<{vocab}Product0>\t<http://www.w3.org/2002/07/owl#sameAs>\t<{vocab}Product0>\t<{graph}> .\n"
        f"<{vocab}Product0>\t<{vocab}producer>\t<{vocab}Producer0>\t<{graph}> .\n"
    )
    (dep / "Producer" / "Producer0.nq").write_text(
        f"<{vocab}Producer0>\t<{RDF_TYPE}>\t<{vocab}Producer>\t<{graph}> .\n"
    )
    model = f"""
#namespace ex={vocab}
#namespace __provenance=http://example.test/source/
#namespace __output_org=monolithic
#namespace __output_file=source
#namespace __output_dep={dep}
#namespace __output_dep_org=fragmented
#namespace __output_dep_rename_exception_predicates=
<type> ex:Product 1
</type>
<type> ex:Offer 1
<pgroup> 1.0
#predicate ex:value integer 1 1
</pgroup>
</type>
#association ex:Offer ex:product ex:Product 2 1 1.0 NORMAL
"""
    output = StringIO()
    run(model, 1, output, seed=1)

    text = output.getvalue()
    assert "<http://example.test/source/Product0>" in text
    assert any(
        line.startswith("<http://example.test/source/Producer0>\t")
        for line in text.splitlines()
    )
    assert f"<{vocab}Product>" in text
    assert text.count(f"<{vocab}Product>") == 2
