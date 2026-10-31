"""Load and validate scenario templates."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

import yaml

from futureprefs.numbers import D, format_number

TIERS = {"mini", "pilot", "full"}
TIER_RANK = {"mini": 0, "pilot": 1, "full": 2}
INSTRUCTIONS = {"neutral", "advisor"}
SCALES = {"linear", "log"}
FORMATS = {
    "count",
    "probability",
    "fraction",
    "multiplier",
    "years",
    "percent_points",
    "number",
}
KINDS = {
    "tradeoff",
    "coherence",
    "ranking",
    "dominance",
    "population_sensitivity",
    "framing",
    "scale",
    "cue",
    "stated",
    "timing",
    "policy",
    "allocation",
}


class ItemError(ValueError):
    pass


def _eval_arith(expression: str, env: dict[str, Decimal]) -> Decimal:
    tree = ast.parse(expression, mode="eval")

    def walk(node: ast.AST) -> Decimal:
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float, str)):
            return D(node.value)
        if isinstance(node, ast.Name):
            if node.id not in env:
                raise ItemError(f"Unknown name {node.id} in expression {expression!r}")
            return env[node.id]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -walk(node.operand)
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            left = walk(node.left)
            right = walk(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            return left / right
        raise ItemError(f"Unsupported expression: {expression}")

    return walk(tree)


def infer_format(name: str, parameter_name: str | None, parameter_format: str | None, explicit: dict[str, str]) -> str:
    if name in explicit:
        return explicit[name]
    if parameter_name and name == parameter_name and parameter_format:
        return parameter_format
    if name.startswith("p_") or name.startswith("q_"):
        return "probability"
    if name in {"kept", "miss_now"} or "fraction" in name:
        return "fraction"
    if "population" in name or name.endswith("_lives"):
        return "count"
    if name in {"delay", "horizon"} or name.endswith("_years"):
        return "years"
    if "fraction" in name or name.startswith("f_"):
        return "fraction"
    return "number"


@dataclass
class Parameter:
    name: str
    format: str
    scale: str
    grid: list[Decimal]
    grid_labels: list[str]
    higher_favors: str


@dataclass
class Paraphrase:
    id: str
    tier: str
    wording: str
    instruction: str
    options: dict[str, str] | None = None
    futures: dict[str, str] | None = None


@dataclass
class Item:
    id: str
    domain: str
    kind: str
    tier: str
    short: str
    curve_example: bool
    open_context: bool
    parameter: Parameter | None
    fixed: dict[str, Decimal]
    fixed_labels: dict[str, str]
    derived: dict[str, str]
    formats: dict[str, str]
    options: dict[str, str]
    futures: dict[str, str]
    paraphrases: list[Paraphrase]
    correct: str | None
    group: str | None
    arm: str | None
    maps_to_item: str | None
    stated_prompt: str | None
    question: str | None
    allow_cue_words: bool
    analysis: dict
    source: str

    def included(self, profile: str) -> bool:
        return TIER_RANK[self.tier] <= TIER_RANK[profile]

    def context(self, value: Decimal | None = None) -> dict[str, str]:
        env: dict[str, Decimal] = dict(self.fixed)
        labels = dict(self.fixed_labels)
        parameter_format = self.parameter.format if self.parameter else None
        parameter_name = self.parameter.name if self.parameter else None
        if self.parameter and value is not None:
            env[self.parameter.name] = value
            labels[self.parameter.name] = format(value, "f")
        for name, expression in self.derived.items():
            env[name] = _eval_arith(expression, env)
            labels[name] = format(env[name], "f")
        rendered: dict[str, str] = {}
        for name, numeric in env.items():
            kind = infer_format(name, parameter_name, parameter_format, self.formats)
            rendered[name] = trim_label(labels.get(name, format(numeric, "f")))
            rendered[f"{name}_text"] = format_number(numeric, kind)
        return rendered


def trim_label(text: str) -> str:
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _require_str_map(raw: dict, field_name: str, item_id: str) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ItemError(f"{item_id}.{field_name} must be a mapping")
    cleaned: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(value, str):
            raise ItemError(
                f"{item_id}.{field_name}.{key} must be a quoted string so large numbers stay exact"
            )
        cleaned[str(key)] = value
    return cleaned


def _parse_parameter(raw: dict | None, item_id: str) -> Parameter | None:
    if raw is None:
        return None
    name = str(raw["name"])
    number_format = str(raw["format"])
    scale = str(raw["scale"])
    if number_format not in FORMATS:
        raise ItemError(f"{item_id} has unknown parameter format {number_format}")
    if scale not in SCALES:
        raise ItemError(f"{item_id} has unknown scale {scale}")
    grid_raw = raw["grid"]
    if not isinstance(grid_raw, list) or len(grid_raw) < 3:
        raise ItemError(f"{item_id} grid must contain at least 3 quoted values")
    labels: list[str] = []
    grid: list[Decimal] = []
    for entry in grid_raw:
        if not isinstance(entry, str):
            raise ItemError(f"{item_id} grid values must be quoted strings")
        labels.append(entry)
        grid.append(D(entry))
    if grid != sorted(grid) or len(set(grid)) != len(grid):
        raise ItemError(f"{item_id} grid must be strictly increasing")
    if scale == "log" and any(point <= 0 for point in grid):
        raise ItemError(f"{item_id} log-scale grid must be positive")
    return Parameter(
        name=name,
        format=number_format,
        scale=scale,
        grid=grid,
        grid_labels=labels,
        higher_favors=str(raw["higher_favors"]),
    )


def _parse_paraphrases(raw_list: list, item_id: str) -> list[Paraphrase]:
    if not isinstance(raw_list, list) or not raw_list:
        raise ItemError(f"{item_id} needs at least one paraphrase")
    paraphrases: list[Paraphrase] = []
    seen: set[str] = set()
    for raw in raw_list:
        paraphrase_id = str(raw["id"])
        if paraphrase_id in seen:
            raise ItemError(f"Duplicate paraphrase {paraphrase_id} on {item_id}")
        seen.add(paraphrase_id)
        tier = str(raw["tier"])
        instruction = str(raw["instruction"])
        if tier not in TIERS:
            raise ItemError(f"{item_id} paraphrase {paraphrase_id} has bad tier {tier}")
        if instruction not in INSTRUCTIONS:
            raise ItemError(f"{item_id} paraphrase {paraphrase_id} has bad instruction {instruction}")
        options = raw.get("options")
        futures = raw.get("futures")
        paraphrases.append(
            Paraphrase(
                id=paraphrase_id,
                tier=tier,
                wording=str(raw.get("wording", "plain")),
                instruction=instruction,
                options={str(k): str(v) for k, v in options.items()} if options else None,
                futures={str(k): str(v) for k, v in futures.items()} if futures else None,
            )
        )
    return paraphrases


def _parse_item(raw: dict, source: str) -> Item:
    item_id = str(raw["id"])
    kind = str(raw.get("kind", "tradeoff"))
    if kind not in KINDS:
        raise ItemError(f"{item_id} has unknown kind {kind}")
    tier = str(raw["tier"])
    if tier not in TIERS:
        raise ItemError(f"{item_id} has unknown tier {tier}")
    parameter = _parse_parameter(raw.get("parameter"), item_id)
    fixed_labels = _require_str_map(raw.get("fixed") or {}, "fixed", item_id)
    fixed = {key: D(value) for key, value in fixed_labels.items()}
    derived = {str(k): str(v) for k, v in (raw.get("derived") or {}).items()}
    formats = {str(k): str(v) for k, v in (raw.get("formats") or {}).items()}
    for name, number_format in formats.items():
        if number_format not in FORMATS:
            raise ItemError(f"{item_id} format {name}={number_format} is unknown")
    options = {str(k): str(v) for k, v in (raw.get("options") or {}).items()}
    futures = {str(k): str(v) for k, v in (raw.get("futures") or {}).items()}
    paraphrases = _parse_paraphrases(raw.get("paraphrases") or [{"id": "plain_neutral", "tier": tier, "wording": "plain", "instruction": "neutral"}], item_id)
    if kind == "stated":
        paraphrases = [
            Paraphrase(id="stated", tier=tier, wording="stated", instruction="neutral")
        ]
    analysis = dict(raw.get("analysis") or {})
    item = Item(
        id=item_id,
        domain=str(raw.get("domain", "")),
        kind=kind,
        tier=tier,
        short=str(raw.get("short", item_id)),
        curve_example=bool(raw.get("curve_example", False)),
        open_context=bool(raw.get("open_context", False)),
        parameter=parameter,
        fixed=fixed,
        fixed_labels=fixed_labels,
        derived=derived,
        formats=formats,
        options=options,
        futures=futures,
        paraphrases=paraphrases,
        correct=str(raw["correct"]) if raw.get("correct") is not None else None,
        group=str(raw["group"]) if raw.get("group") is not None else None,
        arm=str(raw["arm"]) if raw.get("arm") is not None else None,
        maps_to_item=str(raw["maps_to_item"]) if raw.get("maps_to_item") else None,
        stated_prompt=str(raw["stated_prompt"]) if raw.get("stated_prompt") else None,
        question=str(raw["question"]) if raw.get("question") else None,
        allow_cue_words=bool(raw.get("allow_cue_words", False)),
        analysis=analysis,
        source=source,
    )
    _validate_item(item)
    return item


def _validate_item(item: Item) -> None:
    if item.kind == "tradeoff":
        if item.parameter is None:
            raise ItemError(f"{item.id} is a tradeoff and needs a parameter")
        if len(item.options) != 2:
            raise ItemError(f"{item.id} must have exactly two options")
        if item.parameter.higher_favors not in item.options:
            raise ItemError(f"{item.id} higher_favors is not an option id")
        if "reference_note" not in item.analysis:
            raise ItemError(f"{item.id} needs analysis.reference_note")
        if "higher_switch_means" not in item.analysis:
            raise ItemError(f"{item.id} needs analysis.higher_switch_means")
        include = item.analysis.get("include_in_heatmap", True)
        if include:
            if "pole" not in item.analysis or "pole_sign" not in item.analysis:
                raise ItemError(f"{item.id} heatmap items need analysis.pole and analysis.pole_sign")
            if int(item.analysis["pole_sign"]) not in (-1, 1):
                raise ItemError(f"{item.id} pole_sign must be -1 or 1")
        # Rendering every grid point catches placeholder and derived-expression errors.
        for value in item.parameter.grid:
            context = item.context(value)
            if item.open_context:
                if not item.question:
                    raise ItemError(f"{item.id} open-context tradeoffs need a question")
                item.question.format_map(_Safe(context))
            for paraphrase in item.paraphrases:
                texts = paraphrase.options or item.options
                if set(texts) != set(item.options):
                    raise ItemError(f"{item.id} paraphrase {paraphrase.id} must override both options or neither")
                for text in texts.values():
                    text.format_map(_Safe(context))
    elif item.kind in {"coherence", "ranking"}:
        if item.kind == "coherence" and len(item.futures) != 3:
            raise ItemError(f"{item.id} coherence items need exactly three futures")
        if item.kind == "ranking" and not 3 <= len(item.futures) <= 10:
            raise ItemError(f"{item.id} ranking items need between 3 and 10 futures")
        utilities = item.analysis.get("utilities") or {}
        if "mock-ev" not in utilities:
            raise ItemError(f"{item.id} needs analysis.utilities.mock-ev")
        for policy, table in utilities.items():
            if set(table) != set(item.futures):
                raise ItemError(f"{item.id} utilities for {policy} must name every future")
        reference_order = item.analysis.get("reference_order")
        if reference_order is not None and set(reference_order) != set(item.futures):
            raise ItemError(f"{item.id} reference_order must list every future exactly once")
        context = item.context(None)
        for paraphrase in item.paraphrases:
            texts = paraphrase.futures or item.futures
            if set(texts) != set(item.futures):
                raise ItemError(f"{item.id} paraphrase {paraphrase.id} must name the same futures")
            for text in texts.values():
                text.format_map(_Safe(context))
    elif item.kind == "timing":
        _validate_timing(item)
    elif item.kind == "policy":
        _validate_policy(item)
    elif item.kind == "allocation":
        _validate_allocation(item)
    elif item.kind == "stated":
        if not item.stated_prompt or not item.maps_to_item:
            raise ItemError(f"{item.id} stated items need stated_prompt and maps_to_item")
        item.stated_prompt.format_map(_Safe(item.context(None)))
    else:
        if len(item.options) != 2:
            raise ItemError(f"{item.id} controls need exactly two options")
        context = item.context(None)
        for paraphrase in item.paraphrases:
            texts = paraphrase.options or item.options
            for text in texts.values():
                text.format_map(_Safe(context))


def _validate_policy(item: Item) -> None:
    if item.parameter is not None:
        raise ItemError(f"{item.id} policy items have no searched parameter")
    if len(item.options) != 2:
        raise ItemError(f"{item.id} policy items need exactly two options")
    if not item.question:
        raise ItemError(f"{item.id} policy items need a question")
    reported = item.analysis.get("reported_option")
    if reported not in item.options:
        raise ItemError(f"{item.id} analysis.reported_option must be one of the option ids")
    context = item.context(None)
    item.question.format_map(_Safe(context))
    for paraphrase in item.paraphrases:
        texts = paraphrase.options or item.options
        if set(texts) != set(item.options):
            raise ItemError(f"{item.id} paraphrase {paraphrase.id} must override both options or neither")
        for text in texts.values():
            text.format_map(_Safe(context))


def _validate_allocation(item: Item) -> None:
    if item.parameter is not None or item.options:
        raise ItemError(f"{item.id} allocation items have no searched parameter and no binary options")
    if len(item.futures) < 2:
        raise ItemError(f"{item.id} allocation items need at least two causes")
    if not item.question:
        raise ItemError(f"{item.id} allocation items need a question")
    labels = item.analysis.get("labels") or {}
    if set(labels) != set(item.futures):
        raise ItemError(f"{item.id} analysis.labels must name every cause")
    budget = item.analysis.get("budget")
    if budget is None:
        raise ItemError(f"{item.id} needs analysis.budget")
    context = item.context(None)
    item.question.format_map(_Safe(context))
    for text in item.futures.values():
        text.format_map(_Safe(context))


def _validate_timing(item: Item) -> None:
    if item.parameter is not None or item.options or item.futures:
        raise ItemError(f"{item.id} timing items have no tradeoff parameter, options, or futures")
    p0 = _timing_axis(item, "p0_grid")
    g_values = _timing_axis(item, "g_grid")
    if any(value <= 0 or value > 1 for value in p0):
        raise ItemError(f"{item.id} p0_grid values must lie in (0, 1]")
    if any(value < 0 or value >= 1 for value in g_values):
        raise ItemError(f"{item.id} g_grid values must lie in [0, 1)")
    for name in ("p0_extra", "g_extra"):
        extra = item.analysis.get(name) or []
        if not isinstance(extra, list):
            raise ItemError(f"{item.id} analysis.{name} must be a list of quoted numbers")
        _timing_numbers(extra, f"{item.id} analysis.{name}")


def _timing_axis(item: Item, name: str) -> list[Decimal]:
    raw = item.analysis.get(name)
    if not isinstance(raw, list) or len(raw) < 3:
        raise ItemError(f"{item.id} analysis.{name} must contain at least 3 quoted values")
    return _timing_numbers(raw, f"{item.id} analysis.{name}")


def _timing_numbers(raw: list, label: str) -> list[Decimal]:
    values: list[Decimal] = []
    for entry in raw:
        if not isinstance(entry, str):
            raise ItemError(f"{label} values must be quoted strings")
        values.append(D(entry))
    if len(set(values)) != len(values):
        raise ItemError(f"{label} contains a duplicate")
    return values


class _Safe(dict):
    def __missing__(self, key: str) -> str:
        raise ItemError(f"Missing placeholder {{{key}}}")


@dataclass
class Catalog:
    items: list[Item] = field(default_factory=list)

    def by_id(self) -> dict[str, Item]:
        return {item.id: item for item in self.items}

    def select(
        self,
        profile: str,
        *,
        item_ids: set[str] | None = None,
        domains: set[str] | None = None,
        kinds: set[str] | None = None,
    ) -> list[Item]:
        chosen: list[Item] = []
        for item in self.items:
            if not item.included(profile):
                continue
            if item_ids is not None and item.id not in item_ids:
                continue
            if domains is not None and item.domain not in domains:
                continue
            if kinds is not None and item.kind not in kinds:
                continue
            chosen.append(item)
        return chosen


def load_catalog(items_dir: Path) -> Catalog:
    paths = sorted(items_dir.glob("*.yaml"))
    if not paths:
        raise ItemError(f"No YAML templates in {items_dir}")
    items: list[Item] = []
    seen: set[str] = set()
    errors: list[str] = []
    for path in paths:
        document = yaml.safe_load(path.read_text()) or {}
        rows = document["items"] if isinstance(document, dict) and "items" in document else document
        if not isinstance(rows, list):
            raise ItemError(f"{path} must contain a list or an items: list")
        for raw in rows:
            try:
                item = _parse_item(raw, str(path.name))
            except Exception as exc:  # noqa: BLE001 — collect every template error
                errors.append(f"{path.name}: {exc}")
                continue
            if item.id in seen:
                errors.append(f"Duplicate item id {item.id}")
            seen.add(item.id)
            items.append(item)
    if errors:
        raise ItemError("Item catalog failed validation:\n- " + "\n- ".join(errors))
    known = {item.id for item in items}
    for item in items:
        if item.maps_to_item and item.maps_to_item not in known:
            errors.append(f"{item.id} maps to unknown item {item.maps_to_item}")
    if errors:
        raise ItemError("Item catalog failed validation:\n- " + "\n- ".join(errors))
    return Catalog(items)
