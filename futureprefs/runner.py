"""Expand templates into fresh-context trials and call a model adapter."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import combinations
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

from futureprefs.adapters import Completion, MockAdapter, OpenAICompatibleAdapter
from futureprefs.bostrom import axes_from_item, cell_role, render_timing_prompt
from futureprefs.items import Catalog, Item, Paraphrase, TIER_RANK, load_catalog
from futureprefs.numbers import D, sigfigs
from futureprefs.parsing import parse_response
from futureprefs.prompt import (
    ALLOCATION_SYSTEM,
    POLICY_SYSTEM,
    SYSTEM_PROMPT,
    TIMING_SYSTEM,
    render_allocation,
    render_binary,
    render_pair,
    render_policy,
    render_stated,
)

PROFILE_SAMPLES = {"mini": 1, "pilot": 2, "full": 3}
PROFILE_TEMPERATURE = {"mini": 0.0, "pilot": 0.7, "full": 0.7}


@dataclass
class ModelSpec:
    id: str
    provider: str
    model: str
    policy: str | None = None
    reasoning_effort: str | None = None


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_environment() -> None:
    load_dotenv(project_root() / ".env")


def load_models(specs: list[str], models_file: str | None) -> list[ModelSpec]:
    loaded: list[ModelSpec] = []
    for raw in specs:
        raw = raw.strip()
        if not raw:
            continue
        if raw.startswith("mock-"):
            loaded.append(ModelSpec(id=raw, provider="mock", model=raw, policy=raw))
        else:
            loaded.append(ModelSpec(id=raw, provider="openrouter", model=raw))
    if models_file:
        import yaml

        document = yaml.safe_load(Path(models_file).read_text()) or {}
        for raw in document.get("models") or []:
            loaded.append(
                ModelSpec(
                    id=str(raw["id"]),
                    provider=str(raw.get("provider", "openrouter")),
                    model=str(raw.get("model", raw["id"])),
                    policy=raw.get("policy"),
                    reasoning_effort=raw.get("reasoning_effort"),
                )
            )
    if not loaded:
        raise SystemExit("Pass --models or --models-file. Mock ids such as mock-ev need no API key.")
    return loaded


def planned_trials(
    catalog: Catalog,
    models: list[ModelSpec],
    *,
    profile: str,
    item_ids: set[str] | None,
    domains: set[str] | None,
    paraphrase_ids: set[str] | None,
    samples: int,
    search: str,
    binary_steps: int,
    allow_tie: bool,
) -> list[dict]:
    del allow_tie
    items = [
        item
        for item in catalog.select(profile, item_ids=item_ids, domains=domains)
        if item.kind != "stated"
    ]
    stated = [item for item in catalog.select(profile, item_ids=item_ids, domains=domains) if item.kind == "stated"]
    rows = []
    for model in models:
        for item in items:
            paraphrases = _paraphrases(item, profile, paraphrase_ids)
            n_values = len(item.parameter.grid) if item.parameter and search == "grid" else None
            if item.kind == "timing":
                p0_values, g_values = axes_from_item(item)
                n_units = len(p0_values) * len(g_values)
            elif item.kind in ("coherence", "ranking"):
                n_units = len(list(combinations(item.futures, 2)))
            elif item.kind == "allocation":
                n_units = 1
            elif item.parameter and search == "binary":
                n_units = 2 + binary_steps
            elif item.parameter:
                n_units = n_values or 0
            else:
                n_units = 1
            orders = 1 if item.kind == "allocation" else 2
            for paraphrase in paraphrases:
                rows.append(
                    {
                        "model_id": model.id,
                        "kind": item.kind,
                        "item_id": item.id,
                        "paraphrase_id": paraphrase.id,
                        "calls": n_units * orders * samples,
                    }
                )
        for item in stated:
            rows.append(
                {
                    "model_id": model.id,
                    "kind": "stated",
                    "item_id": item.id,
                    "paraphrase_id": "stated",
                    "calls": samples,
                }
            )
    return rows


def run_benchmark(
    *,
    catalog: Catalog,
    models: list[ModelSpec],
    profile: str,
    out_path: Path,
    item_ids: set[str] | None = None,
    domains: set[str] | None = None,
    paraphrase_ids: set[str] | None = None,
    samples: int | None = None,
    temperature: float | None = None,
    search: str = "grid",
    binary_steps: int = 5,
    allow_tie: bool = False,
    workers: int = 1,
    max_tokens: int = 2500,
    resume: bool = False,
    run_id: str | None = None,
    reasoning_effort: str | None = None,
) -> int:
    samples = PROFILE_SAMPLES[profile] if samples is None else samples
    temperature = PROFILE_TEMPERATURE[profile] if temperature is None else temperature
    run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done = _completed_ids(out_path) if resume and out_path.exists() else set()
    adapters = {model.id: _adapter_for(model) for model in models}
    header = {
        "record_type": "run_header",
        "run_id": run_id,
        "profile": profile,
        "search": search,
        "samples": samples,
        "temperature": temperature,
        "allow_tie": allow_tie,
        "models": [model.id for model in models],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    lock = threading.Lock()
    mode = "a" if resume and out_path.exists() else "w"
    handle = out_path.open(mode)
    if mode == "w":
        handle.write(json.dumps(header) + "\n")
        handle.flush()
    counter = {"n": 0}

    def persist(record: dict) -> None:
        with lock:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
            counter["n"] += 1
            if counter["n"] % 25 == 0:
                print(f"completed {counter['n']} calls", file=sys.stderr)

    units = _units(
        catalog,
        models,
        profile=profile,
        item_ids=item_ids,
        domains=domains,
        paraphrase_ids=paraphrase_ids,
        samples=samples,
        temperature=temperature,
        allow_tie=allow_tie,
        search=search,
        run_id=run_id,
        reasoning_effort=reasoning_effort,
    )
    try:
        if search == "grid":
            specs = [spec for unit in units for spec in unit.grid_specs() if spec.trial_id not in done]
            _execute_many(specs, adapters, persist, workers, max_tokens)
        else:
            # Grid resume skips completed trial ids. Binary search re-probes,
            # because a later probe depends on the observed choice.
            run_binary_units(units, adapters, persist, workers, max_tokens, binary_steps, set())
    finally:
        handle.close()
    return counter["n"]


@dataclass
class TrialSpec:
    trial_id: str
    messages: list[dict]
    meta: dict
    record: dict

    def with_response(self, completion: Completion, *, allow_tie: bool) -> dict:
        parsed = parse_response(completion.text, kind=self.record["kind"], allow_tie=allow_tie)
        semantic = None
        if parsed.choice_letter == "A":
            semantic = self.record["semantic_a"]
        elif parsed.choice_letter == "B":
            semantic = self.record["semantic_b"]
        elif parsed.choice_letter == "T":
            semantic = "tie"
        stated_unbounded = self.record["kind"] == "stated" and parsed.parse_ok and parsed.stated_value is None
        updated = dict(self.record)
        updated.update(
            {
                "choice_letter": parsed.choice_letter,
                "choice_semantic": semantic,
                "confidence": parsed.confidence,
                "reasoning": parsed.reasoning,
                "stated_value": parsed.stated_value,
                "stated_unbounded": stated_unbounded,
                "parse_ok": parsed.parse_ok,
                "refusal": parsed.refusal,
                "raw_response": completion.text,
                "latency_s": round(completion.latency_s, 4),
                "error": completion.error,
                "response_id": completion.response_id,
                "usage": completion.usage,
            }
        )
        return updated


@dataclass
class WorkUnit:
    model: ModelSpec
    item: Item
    paraphrase: Paraphrase
    samples: int
    temperature: float
    allow_tie: bool
    run_id: str
    reasoning_effort: str | None
    kind: str

    def grid_specs(self) -> list[TrialSpec]:
        if self.kind == "stated":
            return [self._stated_spec(sample) for sample in range(self.samples)]
        if self.kind == "allocation":
            return [self._allocation_spec(sample) for sample in range(self.samples)]
        if self.kind == "timing":
            return self.timing_specs()
        if self.kind in ("coherence", "ranking"):
            return self.pair_specs()
        if self.item.parameter is None:
            return self._point_specs(None, None)
        return [
            spec
            for index, value in enumerate(self.item.parameter.grid)
            for spec in self._point_specs(value, self.item.parameter.grid_labels[index])
        ]

    def _point_specs(self, value: Decimal | None, label: str | None) -> list[TrialSpec]:
        context = self.item.context(value)
        specs = []
        for order in ("ab", "ba"):
            for sample in range(self.samples):
                if self.kind == "policy" or self.item.open_context:
                    prompt, semantic_a, semantic_b = render_policy(
                        self.item, self.paraphrase, order, context, allow_tie=self.allow_tie
                    )
                else:
                    prompt, semantic_a, semantic_b = render_binary(
                        self.item, self.paraphrase, order, context, allow_tie=self.allow_tie
                    )
                specs.append(
                    self._spec(
                        prompt=prompt,
                        semantic_a=semantic_a,
                        semantic_b=semantic_b,
                        order=order,
                        sample=sample,
                        parameter_label=label,
                        parameter_value=value,
                        pair_id=None,
                        pair_left=None,
                        pair_right=None,
                    )
                )
        return specs

    def pair_specs(self) -> list[TrialSpec]:
        context = self.item.context(None)
        future_ids = list(self.item.futures)
        # Every unordered pair, in catalog order. For a triad this is the
        # same three pairs the coherence test has always used.
        pairs = list(combinations(future_ids, 2))
        specs = []
        for left, right in pairs:
            for order in ("ab", "ba"):
                for sample in range(self.samples):
                    prompt, semantic_a, semantic_b = render_pair(
                        self.item,
                        self.paraphrase,
                        left,
                        right,
                        order,
                        context,
                        allow_tie=self.allow_tie,
                    )
                    specs.append(
                        self._spec(
                            prompt=prompt,
                            semantic_a=semantic_a,
                            semantic_b=semantic_b,
                            order=order,
                            sample=sample,
                            parameter_label=None,
                            parameter_value=None,
                            pair_id=f"{left}|{right}",
                            pair_left=left,
                            pair_right=right,
                        )
                    )
        return specs

    def timing_specs(self) -> list[TrialSpec]:
        p0_values, g_values = axes_from_item(self.item)
        specs = []
        for p0 in p0_values:
            for g in g_values:
                label = f"{p0:.6g}|{g:.6g}"
                for order in ("ab", "ba"):
                    prompt = render_timing_prompt(p0, g, order)
                    for sample in range(self.samples):
                        spec = self._spec(
                            prompt=prompt,
                            semantic_a=None,
                            semantic_b=None,
                            order=order,
                            sample=sample,
                            parameter_label=label,
                            parameter_value=None,
                            pair_id=None,
                            pair_left=None,
                            pair_right=None,
                            stated=True,
                        )
                        spec.record["p0"] = p0
                        spec.record["g"] = g
                        spec.record["cell_role"] = cell_role(p0, g)
                        spec.record["parameter_name"] = "p0_g"
                        spec.meta["p0"] = p0
                        spec.meta["g"] = g
                        spec.meta["kind"] = "timing"
                        specs.append(spec)
        return specs

    def _allocation_spec(self, sample: int) -> TrialSpec:
        prompt = render_allocation(self.item, self.item.context(None))
        spec = self._spec(
            prompt=prompt,
            semantic_a=None,
            semantic_b=None,
            order="na",
            sample=sample,
            parameter_label=None,
            parameter_value=None,
            pair_id=None,
            pair_left=None,
            pair_right=None,
        )
        spec.meta["future_ids"] = list(self.item.futures)
        spec.meta["budget"] = self.item.analysis.get("budget")
        return spec

    def _stated_spec(self, sample: int) -> TrialSpec:
        prompt = render_stated(self.item, self.item.context(None))
        mapped = self.item.maps_to_item
        return self._spec(
            prompt=prompt,
            semantic_a=None,
            semantic_b=None,
            order="na",
            sample=sample,
            parameter_label=None,
            parameter_value=None,
            pair_id=None,
            pair_left=None,
            pair_right=None,
            stated=True,
            maps_to_item=mapped,
        )

    def _spec(
        self,
        *,
        prompt: str,
        semantic_a: str | None,
        semantic_b: str | None,
        order: str,
        sample: int,
        parameter_label: str | None,
        parameter_value: Decimal | None,
        pair_id: str | None,
        pair_left: str | None,
        pair_right: str | None,
        stated: bool = False,
        maps_to_item: str | None = None,
    ) -> TrialSpec:
        analysis = self.item.analysis
        parameter_text = None if parameter_value is None else format(parameter_value, "f")
        if parameter_label is not None:
            parameter_text = format(D(parameter_label), "f") if _is_number(parameter_label) else parameter_label
        identity = {
            "model_id": self.model.id,
            "item_id": self.item.id,
            "paraphrase_id": self.paraphrase.id,
            "parameter_value": parameter_text or "",
            "order": order,
            "sample_index": sample,
            "temperature": self.temperature,
            "allow_tie": self.allow_tie,
            "pair_id": pair_id or "",
        }
        trial_id = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:20]
        seed = int(hashlib.sha256((trial_id + self.run_id).encode()).hexdigest()[:8], 16)
        option_ids = list(self.item.options) if self.item.options else list(self.item.futures)
        higher = analysis.get("higher_favors") or (self.item.parameter.higher_favors if self.item.parameter else None)
        other = None
        if higher and option_ids:
            others = [option_id for option_id in option_ids if option_id != higher]
            other = others[0] if others else None
        record = {
            "trial_id": trial_id,
            "run_id": self.run_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "kind": self.item.kind,
            "model_id": self.model.id,
            "provider": self.model.provider,
            "provider_model": self.model.model,
            "domain": self.item.domain,
            "item_id": self.item.id,
            "short": self.item.short,
            "tier": self.item.tier,
            "paraphrase_id": self.paraphrase.id,
            "wording": self.paraphrase.wording,
            "instruction": self.paraphrase.instruction,
            "parameter_name": self.item.parameter.name if self.item.parameter else None,
            "parameter_value": parameter_text,
            "parameter_scale": self.item.parameter.scale if self.item.parameter else None,
            "parameter_format": self.item.parameter.format if self.item.parameter else None,
            "order": order,
            "sample_index": sample,
            "temperature": self.temperature,
            "seed": seed,
            "allow_tie": self.allow_tie,
            "semantic_a": semantic_a,
            "semantic_b": semantic_b,
            "higher_favors": higher,
            "other_option": other,
            "quantity": analysis.get("quantity"),
            "higher_switch_means": analysis.get("higher_switch_means"),
            "pole": analysis.get("pole"),
            "pole_sign": analysis.get("pole_sign"),
            "reference_switch": analysis.get("reference_switch"),
            "reference_note": analysis.get("reference_note"),
            "expect_monotonic": analysis.get("expect_monotonic", True),
            "include_in_heatmap": analysis.get("include_in_heatmap", self.item.kind == "tradeoff"),
            "discount_delay_years": analysis.get("discount_delay_years"),
            "curve_example": self.item.curve_example,
            "correct": self.item.correct,
            "group": self.item.group,
            "arm": self.item.arm,
            "reference_choice": analysis.get("reference_choice"),
            "pair_id": pair_id,
            "pair_left": pair_left,
            "pair_right": pair_right,
            "future_ids": list(self.item.futures) if self.item.futures else None,
            "future_labels": analysis.get("labels"),
            "reference_order": analysis.get("reference_order"),
            "reference_utilities": (analysis.get("utilities") or {}).get("mock-ev"),
            "maps_to_item": maps_to_item or self.item.maps_to_item,
            "reported_option": analysis.get("reported_option"),
            "prompt": prompt,
            "mock_policy": self.model.policy,
            "reasoning_effort": self.reasoning_effort,
        }
        meta = {
            "kind": self.item.kind,
            "semantic_a": semantic_a,
            "semantic_b": semantic_b,
            "parameter_value": parameter_text,
            "higher_favors": higher,
            "other_option": other,
            "reference_switch": analysis.get("reference_switch"),
            "mock_cautious_switch": analysis.get("mock_cautious_switch"),
            "mock_ev_option": analysis.get("mock_ev_option"),
            "mock_cautious_option": analysis.get("mock_cautious_option"),
            "correct": self.item.correct,
            "arm": self.item.arm,
            "reference_choice": analysis.get("reference_choice"),
            "utilities": analysis.get("utilities") or {},
        }
        if self.kind == "timing":
            system = TIMING_SYSTEM
        elif self.kind == "allocation":
            system = ALLOCATION_SYSTEM
        elif self.kind == "policy" or self.item.open_context:
            system = POLICY_SYSTEM
        else:
            system = SYSTEM_PROMPT
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
        return TrialSpec(trial_id=trial_id, messages=messages, meta=meta, record=record)


def _units(
    catalog: Catalog,
    models: list[ModelSpec],
    *,
    profile: str,
    item_ids: set[str] | None,
    domains: set[str] | None,
    paraphrase_ids: set[str] | None,
    samples: int,
    temperature: float,
    allow_tie: bool,
    search: str,
    run_id: str,
    reasoning_effort: str | None,
) -> list[WorkUnit]:
    del search
    units: list[WorkUnit] = []
    items = catalog.select(profile, item_ids=item_ids, domains=domains)
    for model in models:
        for item in items:
            if item.kind == "stated":
                units.append(
                    WorkUnit(
                        model=model,
                        item=item,
                        paraphrase=item.paraphrases[0],
                        samples=samples,
                        temperature=temperature,
                        allow_tie=allow_tie,
                        run_id=run_id,
                        reasoning_effort=reasoning_effort or model.reasoning_effort,
                        kind="stated",
                    )
                )
                continue
            for paraphrase in _paraphrases(item, profile, paraphrase_ids):
                units.append(
                    WorkUnit(
                        model=model,
                        item=item,
                        paraphrase=paraphrase,
                        samples=samples,
                        temperature=temperature,
                        allow_tie=allow_tie,
                        run_id=run_id,
                        reasoning_effort=reasoning_effort or model.reasoning_effort,
                        kind=item.kind,
                    )
                )
    return units


def _paraphrases(item: Item, profile: str, paraphrase_ids: set[str] | None) -> list[Paraphrase]:
    chosen = []
    for paraphrase in item.paraphrases:
        if TIER_RANK[paraphrase.tier] > TIER_RANK[profile]:
            continue
        if paraphrase_ids is not None and paraphrase.id not in paraphrase_ids:
            continue
        chosen.append(paraphrase)
    return chosen


def _execute_many(specs: list[TrialSpec], adapters, persist, workers: int, max_tokens: int) -> None:
    if not specs:
        return

    def run(spec: TrialSpec) -> dict:
        model_id = spec.record["model_id"]
        return _execute_one(spec, adapters[model_id], max_tokens)

    if workers <= 1:
        for spec in specs:
            persist(run(spec))
        return
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(run, spec) for spec in specs]
        for future in as_completed(futures):
            persist(future.result())


def _execute_one(spec: TrialSpec, adapter, max_tokens: int) -> dict:
    extra = {
        "meta": spec.meta,
        "policy": spec.record.get("mock_policy"),
        "reasoning_effort": spec.record.get("reasoning_effort"),
    }
    completion = adapter.complete(
        model=spec.record["provider_model"],
        messages=spec.messages,
        temperature=spec.record["temperature"],
        seed=spec.record["seed"],
        max_tokens=max_tokens,
        extra=extra,
    )
    return spec.with_response(completion, allow_tie=spec.record["allow_tie"])


def run_binary_units(units: list[WorkUnit], adapters, persist, workers: int, max_tokens: int, steps: int, done: set[str]) -> None:
    binary_units = [unit for unit in units if unit.item.parameter is not None and unit.kind == "tradeoff"]
    binary_ids = {id(unit) for unit in binary_units}
    other_specs = []
    for unit in units:
        if id(unit) in binary_ids:
            continue
        other_specs.extend(spec for spec in unit.grid_specs() if spec.trial_id not in done)

    def search(unit: WorkUnit) -> None:
        parameter = unit.item.parameter
        assert parameter is not None
        lo = parameter.grid[0]
        hi = parameter.grid[-1]

        def evaluate(value: Decimal) -> str:
            label = format(sigfigs(value), "f")
            specs = unit._point_specs(value, label)
            semantics = []
            for spec in specs:
                record = _execute_one(spec, adapters[unit.model.id], max_tokens)
                persist(record)
                if record.get("parse_ok") and record.get("choice_semantic") not in (None, "tie"):
                    semantics.append(record["choice_semantic"])
            if not semantics or len(set(semantics)) != 1:
                return "tie"
            return semantics[0]

        left = evaluate(lo)
        right = evaluate(hi)
        for _ in range(steps):
            if left == right or left == "tie" or right == "tie":
                break
            if parameter.scale == "log":
                mid = sigfigs((lo * hi).sqrt())
            else:
                mid = sigfigs((lo + hi) / 2)
            if mid <= lo or mid >= hi:
                break
            middle = evaluate(mid)
            if middle == left:
                lo, left = mid, middle
            elif middle == right:
                hi, right = mid, middle
            else:
                break

    _execute_many(other_specs, adapters, persist, workers, max_tokens)
    if workers <= 1:
        for unit in binary_units:
            search(unit)
        return
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(search, unit) for unit in binary_units]
        for future in as_completed(futures):
            future.result()


def _adapter_for(model: ModelSpec):
    if model.provider == "mock":
        return MockAdapter()
    load_environment()
    if model.provider == "openai":
        key = os.environ.get("OPENAI_API_KEY", "")
        if not key:
            raise SystemExit("OPENAI_API_KEY is empty. Add it to .env.")
        return OpenAICompatibleAdapter(api_key=key, base_url=os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1")
    if model.provider == "openrouter":
        key = os.environ.get("OPENROUTER_API_KEY", "")
        if not key:
            raise SystemExit("OPENROUTER_API_KEY is empty. Add it to .env.")
        headers = {
            "HTTP-Referer": os.environ.get("OPENROUTER_HTTP_REFERER", "http://localhost"),
            "X-Title": os.environ.get("OPENROUTER_APP_TITLE", "FuturePrefs"),
        }
        return OpenAICompatibleAdapter(
            api_key=key,
            base_url=os.environ.get("OPENROUTER_BASE_URL") or "https://openrouter.ai/api/v1",
            default_headers=headers,
        )
    raise SystemExit(f"Unknown provider {model.provider}")


def _completed_ids(path: Path) -> set[str]:
    found: dict[str, bool] = {}
    with path.open() as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if "trial_id" not in row:
                continue
            found[row["trial_id"]] = bool(row.get("parse_ok")) and not row.get("error")
    return {trial_id for trial_id, ok in found.items() if ok}


def _is_number(value: str) -> bool:
    try:
        D(value)
    except Exception:  # noqa: BLE001
        return False
    return True


def count_calls(rows: list[dict]) -> int:
    return sum(int(row["calls"]) for row in rows)
