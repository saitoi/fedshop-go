"""Small, in-process implementation of WatDiv's dataset-generation mode.

Only the model directives used by FedShop's BSBM templates are supported.  The
query and statistics modes of the original executable intentionally remain out
of scope.
"""

from __future__ import annotations

import bisect
from collections import OrderedDict
import random
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import TextIO

RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
OWL_SAME_AS = "http://www.w3.org/2002/07/owl#sameAs"
XSD = "http://www.w3.org/2001/XMLSchema#"

COUNTRIES = ["US", "UK", "JP", "CN", "DE", "FR", "ES", "RU", "KR", "AT"]
COUNTRY_WEIGHTS = [40, 10, 10, 10, 5, 5, 5, 5, 5, 5]
LANGTAGS = ["en", "ja", "zh", "de", "fr", "es", "ru", "kr", "at"]
LANG_WEIGHTS = [50, 10, 10, 5, 5, 5, 5, 5, 5]


@dataclass
class PredicateDef:
    label: str
    literal_type: str
    variable_length: int = 0
    range_min: str | None = None
    range_max: str | None = None
    distribution: str = "uniform"


@dataclass
class PredicateGroupDef:
    probability: float = 1.0
    restriction: str | None = None
    predicates: list[PredicateDef] = field(default_factory=list)


@dataclass
class ResourceDef:
    type_prefix: str
    base_count: int
    scalable: bool = True
    count: int = 0
    predicate_groups: list[PredicateGroupDef] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.count = self.base_count


@dataclass
class AssociationDef:
    subject_type: str
    predicate: str
    object_type: str
    left_cardinality: int = 1
    right_cardinality: int = 1
    left_distribution: str = "uniform"
    right_distribution: str = "uniform"
    left_cover: float | None = None
    left_cardinality_distribution: str | None = None
    right_cardinality_distribution: str | None = None
    subject_restriction: str | None = None
    object_restriction: str | None = None
    constraint: str = "chosen"


@dataclass
class Model:
    namespaces: dict[str, str]
    resources: list[ResourceDef]
    associations: list[AssociationDef]

    def apply_scale(self, scale_factor: int) -> None:
        if scale_factor < 1:
            raise ValueError("scale_factor must be at least 1")
        for resource in self.resources:
            resource.count = resource.base_count * (scale_factor if resource.scalable else 1)


def _parse_predicate(tokens: list[str]) -> PredicateDef:
    if len(tokens) not in {3, 5, 6}:
        raise ValueError(f"invalid #predicate directive: {' '.join(tokens)}")
    type_token = tokens[2].lower()
    match = re.fullmatch(r"string(\d*)", type_token)
    variable_length = int(match.group(1) or 25) if match else 0
    literal_type = "string" if match else type_token
    if re.fullmatch(r"name\d+", literal_type):
        literal_type = "undefined"
    if literal_type not in {"integer", "float", "string", "name", "country", "date", "undefined"}:
        raise ValueError(f"unsupported literal type: {tokens[2]}")
    return PredicateDef(
        label=tokens[1],
        literal_type=literal_type,
        variable_length=variable_length,
        range_min=tokens[3] if len(tokens) >= 5 else None,
        range_max=tokens[4] if len(tokens) >= 5 else None,
        distribution=tokens[5].lower() if len(tokens) == 6 else "uniform",
    )


def _cardinality(token: str) -> tuple[int, str | None]:
    match = re.fullmatch(r"(\d+)(?:\[(uniform|normal)\])?", token, re.IGNORECASE)
    if not match:
        raise ValueError(f"invalid association cardinality: {token}")
    return int(match.group(1)), match.group(2).lower() if match.group(2) else None


def _parse_association(tokens: list[str]) -> AssociationDef:
    if len(tokens) not in {4, 6, 7, 8, 10}:
        raise ValueError(f"invalid association directive: {' '.join(tokens)}")
    constraints = {
        "#association": "chosen",
        "#association1": "previously_existed",
        "#association2": "chosen_or_previously_existed",
        "#association3": "chosen_and_previously_existed",
    }
    assoc = AssociationDef(tokens[1], tokens[2], tokens[3], constraint=constraints[tokens[0]])
    if len(tokens) >= 6:
        assoc.left_cardinality, assoc.left_cardinality_distribution = _cardinality(tokens[4])
        assoc.right_cardinality, assoc.right_cardinality_distribution = _cardinality(tokens[5])
    for index, attribute in ((6, "left_distribution"), (7, "right_distribution")):
        if len(tokens) > index:
            token = tokens[index].lower()
            try:
                assoc.left_cover = float(token)
            except ValueError:
                if token not in {"uniform", "normal", "zipfian"}:
                    raise ValueError(f"unsupported distribution: {token}") from None
                setattr(assoc, attribute, token)
    if len(tokens) == 10:
        assoc.subject_restriction = None if tokens[8].lower() == "@null" else tokens[8].removeprefix("@")
        assoc.object_restriction = None if tokens[9].lower() == "@null" else tokens[9].removeprefix("@")
    return assoc


def parse_template(model_text: str) -> Model:
    """Parse WatDiv model text used by FedShop."""
    namespaces: dict[str, str] = {}
    resources: list[ResourceDef] = []
    associations: list[AssociationDef] = []
    current_resource: ResourceDef | None = None
    current_group: PredicateGroupDef | None = None

    for number, raw_line in enumerate(model_text.splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("//"):
            continue
        tokens = line.split()
        try:
            if tokens[0] == "#namespace":
                alias, prefix = tokens[1].split("=", 1)
                namespaces[alias] = prefix
            elif tokens[0] in {"<type>", "<type*>"}:
                current_resource = ResourceDef(tokens[1], int(tokens[2]), tokens[0] == "<type>")
                resources.append(current_resource)
            elif tokens[0] == "</type>":
                # WatDiv's stack parser attaches later groups to the same type;
                # FedShop's product template relies on this permissive behavior.
                pass
            elif tokens[0] == "<pgroup>":
                if current_resource is None:
                    raise ValueError("predicate group outside a resource")
                current_group = PredicateGroupDef(
                    float(tokens[1]) if len(tokens) > 1 else 1.0,
                    tokens[2].removeprefix("@") if len(tokens) > 2 else None,
                )
                current_resource.predicate_groups.append(current_group)
            elif tokens[0] == "</pgroup>":
                current_group = None
            elif tokens[0] == "#predicate":
                if current_group is None:
                    raise ValueError("predicate outside a predicate group")
                current_group.predicates.append(_parse_predicate(tokens))
            elif tokens[0].startswith("#association"):
                associations.append(_parse_association(tokens))
        except (IndexError, ValueError) as exc:
            raise ValueError(f"invalid WatDiv model at line {number}: {line}: {exc}") from exc
    return Model(namespaces, resources, associations)


@lru_cache(maxsize=16)
def _zipfian_cdf(item_count: int) -> tuple[float, ...]:
    if item_count <= 0:
        return (1.0,)
    total = sum(1.0 / i for i in range(1, item_count + 1))
    cumulative = 0.0
    values = []
    for i in range(1, item_count + 1):
        cumulative += (1.0 / i) / total
        values.append(cumulative)
    return tuple(values)


def _generate_random(rng: random.Random, distribution: str, item_count: int = 1) -> float:
    if distribution == "normal":
        value = rng.gauss(0.5, 0.5 / 3.0)
    elif distribution == "zipfian":
        index = bisect.bisect_left(_zipfian_cdf(item_count), rng.random())
        value = index / item_count if item_count else 0.0
    else:
        value = rng.random()
    return max(0.0, min(1.0, value))


@lru_cache(maxsize=1)
def _word_lists() -> tuple[tuple[str, ...], tuple[str, ...]]:
    data = files("fedshop").joinpath("data")
    first = tuple(sorted(data.joinpath("firstnames").read_text().split()))
    last = tuple(sorted(data.joinpath("lastnames").read_text().split()))
    words_file = data.joinpath("words")
    words = tuple(sorted(words_file.read_text().split())) if words_file.is_file() else tuple(sorted(first + last))
    return words, first


def _parse_date(value: str) -> date:
    year, month, day = (int(part) for part in value.split("T", 1)[0].split("-"))
    return date(year, month, day)


def _escape_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def generate_literal(predicate: PredicateDef, rng: random.Random) -> str:
    """Generate and format one RDF object for a literal predicate."""
    kind = predicate.literal_type
    if kind == "undefined":
        return '""'
    minimum = predicate.range_min
    maximum = predicate.range_max
    if kind == "integer":
        lo, hi = int(minimum or 0), int(maximum or 65535)
        value = str(lo + round(_generate_random(rng, predicate.distribution, hi - lo) * (hi - lo)))
        return f'"{value}"^^<{XSD}integer>'
    if kind == "float":
        lo, hi = float(minimum or 0), float(maximum or 65535)
        value = lo + _generate_random(rng, predicate.distribution, round(hi - lo)) * (hi - lo)
        return f'"{value:.2f}"^^<{XSD}double>'
    if kind == "country":
        country = rng.choices(COUNTRIES, weights=COUNTRY_WEIGHTS, k=1)[0]
        return f"<http://downlode.org/rdf/iso-3166/countries#{country}>"
    if kind == "date":
        lo = _parse_date(minimum or "1970-01-01")
        hi = _parse_date(maximum or date.today().isoformat())
        value = lo + timedelta(days=round(_generate_random(rng, predicate.distribution, (hi - lo).days) * (hi - lo).days))
        return f'"{value.isoformat()}"^^<{XSD}dateTime>'
    words, firstnames = _word_lists()
    source = firstnames if kind == "name" else words
    first = source[round(_generate_random(rng, predicate.distribution, len(source) - 1) * (len(source) - 1))]
    if kind == "name":
        return f'"{_escape_literal(first)}"'
    extras = rng.randrange(predicate.variable_length) if predicate.variable_length else 0
    value = " ".join([first, *(rng.choice(words) for _ in range(extras))])
    lang = rng.choices(LANGTAGS, weights=LANG_WEIGHTS, k=1)[0]
    return f'"{_escape_literal(value)}"@{lang}'


class _Generator:
    def __init__(self, model: Model, output: TextIO | Path, rng: random.Random):
        self.model = model
        self.output = output
        self.rng = rng
        self.resources = {resource.type_prefix: resource for resource in model.resources}
        self.generated: set[str] = set()
        self.types: dict[str, set[str]] = {}
        self._fragment_streams: OrderedDict[Path, TextIO] = OrderedDict()

    def expand(self, value: str) -> str:
        if ":" not in value:
            return value
        alias, suffix = value.split(":", 1)
        return self.model.namespaces[alias] + suffix

    def localized(self, type_prefix: str, identifier: int) -> str:
        return self.model.namespaces["__provenance"] + type_prefix.split(":", 1)[1] + str(identifier)

    def emit(self, subject: str, predicate: str, obj: str) -> None:
        line = f"<{subject}>\t<{predicate}>\t{obj}\t<{self.model.namespaces['__provenance']}> .\n"
        if isinstance(self.output, Path):
            localized = subject.removeprefix(self.model.namespaces["__provenance"])
            match = re.match(r"([A-Za-z_]+)(\d+)$", localized)
            if match is None:
                raise ValueError(f"cannot derive fragment path from subject: {subject}")
            resource_type, identifier = match.groups()
            path = self.output / resource_type / f"{resource_type}{identifier}.nq"
            stream = self._fragment_streams.get(path)
            if stream is None:
                if len(self._fragment_streams) >= 128:
                    _, oldest = self._fragment_streams.popitem(last=False)
                    oldest.close()
                path.parent.mkdir(parents=True, exist_ok=True)
                stream = path.open("a")
                self._fragment_streams[path] = stream
            else:
                self._fragment_streams.move_to_end(path)
            stream.write(line)
        else:
            self.output.write(line)

    def generate_one(self, resource: ResourceDef, identifier: int, *, dependency_recursive: bool = False) -> None:
        subject = self.localized(resource.type_prefix, identifier)
        if subject in self.generated:
            return
        self.generated.add(subject)
        if not resource.predicate_groups:
            self.generate_dependency(resource, identifier)
            if not dependency_recursive:
                # The C++ implementation follows the fragment's own sameAs
                # before its caller records the resource, copying it twice.
                self.generate_dependency(resource, identifier, recurse=False)
            return
        global_subject = self.expand(resource.type_prefix) + str(identifier)
        self.emit(subject, RDF_TYPE, f"<{self.expand(resource.type_prefix)}>")
        self.emit(subject, OWL_SAME_AS, f"<{global_subject}>")
        for group in resource.predicate_groups:
            if group.restriction is None and self.rng.random() <= group.probability:
                for predicate in group.predicates:
                    self.emit(subject, self.expand(predicate.label), generate_literal(predicate, self.rng))

    @staticmethod
    def _uri(value: str) -> str | None:
        return value[1:-1] if value.startswith("<") and value.endswith(">") else None

    def _localized_object(self, predicate: str, obj: str) -> str:
        uri = self._uri(obj)
        if uri is None:
            return obj
        exceptions = {
            value.strip()
            for value in self.model.namespaces.get("__output_dep_rename_exception_predicates", "").split(";")
            if value.strip()
        }
        raw_predicate = f"<{predicate}>"
        suffix = re.split(r"[#/]", uri)[-1]
        if predicate == OWL_SAME_AS or raw_predicate in exceptions:
            return obj
        if predicate == RDF_TYPE and re.fullmatch(r"[A-Za-z_]+", suffix):
            return obj
        return f"<{self.model.namespaces['__provenance']}{suffix}>"

    def generate_dependency(self, resource: ResourceDef, identifier: int, *, recurse: bool = True) -> None:
        dependency_dir = self.model.namespaces.get("__output_dep")
        if dependency_dir is None:
            raise ValueError(f"resource {resource.type_prefix} has no predicates and __output_dep is not configured")
        resource_type = resource.type_prefix.split(":", 1)[1]
        path = Path(dependency_dir) / resource_type / f"{resource_type}{identifier}.nq"
        if not path.exists():
            raise FileNotFoundError(f"WatDiv dependency fragment not found: {path}")
        for line in path.read_text().splitlines():
            fields = line.removesuffix(" .").rstrip().split("\t")
            if len(fields) != 4:
                raise ValueError(f"invalid dependency N-Quad in {path}: {line}")
            source_subject, source_predicate, source_object, _ = fields
            subject_uri = self._uri(source_subject)
            predicate_uri = self._uri(source_predicate)
            if subject_uri is None or predicate_uri is None:
                raise ValueError(f"invalid dependency N-Quad in {path}: {line}")
            localized_subject = self.model.namespaces["__provenance"] + re.split(r"[#/]", subject_uri)[-1]
            localized_object = self._localized_object(predicate_uri, source_object)
            self.emit(localized_subject, predicate_uri, localized_object)

            object_uri = self._uri(source_object)
            if not recurse or object_uri is None:
                continue
            object_suffix = re.split(r"[#/]", object_uri)[-1]
            match = re.fullmatch(r"([A-Za-z_]+)(\d+)", object_suffix)
            if match is None:
                continue
            object_type, object_id = match.group(1), int(match.group(2))
            dependency = next(
                (candidate for candidate in self.model.resources if candidate.type_prefix.split(":", 1)[1] == object_type),
                None,
            )
            if dependency is None:
                object_prefix = object_uri[: -len(object_suffix)]
                alias = next(
                    (
                        name
                        for name, prefix in self.model.namespaces.items()
                        if not name.startswith("__") and prefix == object_prefix
                    ),
                    None,
                )
                if alias is not None:
                    dependency = ResourceDef(f"{alias}:{object_type}", 0)
            if dependency is not None:
                self.generate_one(dependency, object_id, dependency_recursive=True)

    def association(self, association: AssociationDef) -> None:
        left = self.resources[association.subject_type]
        right = self.resources[association.object_type]
        mapped_left: set[int] = set()
        mapped_right: set[int] = set()
        for i in range(left.count):
            left_id = i
            if association.left_cover is None:
                left_id = min(round(_generate_random(self.rng, association.left_distribution, left.count) * left.count), left.count - 1)
                chosen = left_id not in mapped_left
            else:
                chosen = self.rng.random() <= association.left_cover
            if association.constraint == "previously_existed":
                left_id = i
            subject = self.localized(left.type_prefix, left_id)
            existed = subject in self.generated
            condition = {
                "chosen": chosen,
                "previously_existed": existed,
                "chosen_or_previously_existed": chosen or existed,
                "chosen_and_previously_existed": chosen and existed,
            }[association.constraint]
            if not condition:
                continue
            mapped_left.add(left_id)
            right_size = association.right_cardinality
            if association.right_cardinality_distribution and right_size > 1:
                right_size = min(round(right_size * _generate_random(self.rng, association.right_cardinality_distribution, right_size)), right_size)
            for _ in range(right_size):
                right_id = 0
                for attempt in range(50):
                    right_id = min(round(_generate_random(self.rng, association.right_distribution, right.count) * right.count), right.count - 1)
                    if right_id not in mapped_right:
                        break
                else:
                    continue
                if association.left_cardinality == 1:
                    mapped_right.add(right_id)
                self.generate_one(left, left_id)
                self.generate_one(right, right_id)
                obj = self.localized(right.type_prefix, right_id)
                self.emit(subject, self.expand(association.predicate), f"<{obj}>")
                if self.expand(association.predicate) == RDF_TYPE:
                    self.types.setdefault(subject, set()).add(obj)

    def generate(self) -> None:
        try:
            for association in self.model.associations:
                self.association(association)
        finally:
            for stream in self._fragment_streams.values():
                stream.close()


def run(model_text: str, scale_factor: int, output: TextIO | Path, *, seed: int | None = None) -> None:
    """Generate N-Quads from a WatDiv model into an open text stream."""
    model = parse_template(model_text)
    model.apply_scale(scale_factor)
    _Generator(model, output, random.Random(seed)).generate()
