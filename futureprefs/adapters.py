"""Model adapters. Mock policies exercise the pipeline; they are not study results."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

from futureprefs.numbers import D


@dataclass
class Completion:
    text: str
    error: str | None
    latency_s: float
    response_id: str | None


class MockAdapter:
    """Deterministic stand-in used to test search, scoring, and plots.

    mock-ev follows each item's expected-welfare reference threshold.
    mock-cautious follows analysis.mock_cautious_switch.
    On the loaded cue-word control only, mock-cautious flips its choice.
    That flip is a pipeline check, not a model of cue sensitivity.
    """

    name = "mock"

    def complete(
        self,
        *,
        model: str,
        messages: list[dict],
        temperature: float | None,
        seed: int | None,
        max_tokens: int,
        extra: dict,
    ) -> Completion:
        del messages, max_tokens
        meta = extra["meta"]
        policy = extra.get("policy") or model
        started = time.perf_counter()
        if meta["kind"] == "allocation":
            payload = {
                "amounts": _mock_amounts(meta, policy),
                "reasoning": "Dry-run policy. This text is not a model judgment.",
            }
        elif meta["kind"] == "timing":
            payload = {
                "value": _mock_wait(meta, policy),
                "confidence": 0.6,
                "reasoning": "Dry-run policy. This text is not a model judgment.",
            }
        elif meta["kind"] == "stated":
            payload = {
                "value": _stated_number(meta, policy),
                "reasoning": "Dry-run policy. This text is not a model judgment.",
            }
        else:
            semantic = _mock_semantic(meta, policy, temperature or 0, seed or 0)
            letter = "A" if semantic == meta["semantic_a"] else "B"
            payload = {
                "choice": letter,
                "confidence": 0.6,
                "reasoning": "Dry-run policy. This text is not a model judgment.",
            }
        return Completion(
            json.dumps(payload),
            None,
            time.perf_counter() - started,
            f"mock-{seed}",
        )


class OpenAICompatibleAdapter:
    name = "openai-compatible"

    def __init__(self, *, api_key: str, base_url: str, default_headers: dict[str, str] | None = None):
        self.api_key = api_key
        self.base_url = base_url
        self.default_headers = default_headers or {}
        self._client = None

    def complete(
        self,
        *,
        model: str,
        messages: list[dict],
        temperature: float | None,
        seed: int | None,
        max_tokens: int,
        extra: dict,
    ) -> Completion:
        client = self._client_or_create()
        kwargs: dict = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        if seed is not None:
            kwargs["seed"] = seed
        kwargs["response_format"] = {"type": "json_object"}
        if extra.get("reasoning_effort"):
            kwargs["extra_body"] = {"reasoning": {"effort": extra["reasoning_effort"]}}
        last_error: Exception | None = None
        for attempt in range(4):
            try:
                started = time.perf_counter()
                response = client.chat.completions.create(**kwargs)
                text = response.choices[0].message.content or ""
                return Completion(text, None, time.perf_counter() - started, getattr(response, "id", None))
            except Exception as exc:  # noqa: BLE001 — retry only recognized optional-parameter and rate errors
                last_error = exc
                message = str(exc).lower()
                dropped = False
                for optional in ("response_format", "seed", "temperature"):
                    if optional in kwargs and optional in message:
                        kwargs.pop(optional, None)
                        dropped = True
                if dropped:
                    continue
                if any(token in message for token in ("429", "rate limit", "timeout", "503", "502", "overloaded")):
                    time.sleep(min(30, 2**attempt))
                    continue
                break
        return Completion("", str(last_error), 0.0, None)

    def _client_or_create(self):
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                default_headers=self.default_headers or None,
            )
        return self._client


def _mock_amounts(meta: dict, policy: str) -> dict[str, int]:
    causes = list(meta.get("future_ids") or [])
    if policy == "mock-cautious":
        causes = list(reversed(causes))
    weights = list(range(len(causes), 0, -1))
    total = sum(weights) or 1
    budget = 1_000_000
    running = 0
    amounts: dict[str, int] = {}
    for index, cause_id in enumerate(causes):
        if index == len(causes) - 1:
            amounts[cause_id] = budget - running
        else:
            part = budget * weights[index] // total
            amounts[cause_id] = part
            running += part
    return amounts


def _mock_wait(meta: dict, policy: str):
    """Pipeline stand-in. The study model never sees this value; it is not in the prompt."""
    from futureprefs.bostrom import optimal_wait

    wait = optimal_wait(float(meta["p0"]), float(meta["g"]))
    if policy == "mock-cautious" and float(meta["p0"]) >= 0.5:
        return "never"
    if wait is None:
        return "never"
    return round(wait, 4)


def _stated_number(meta: dict, policy: str) -> float | None:
    raw = meta.get("reference_switch")
    if policy == "mock-cautious":
        raw = meta.get("reference_switch")
    if raw in (None, "", "null"):
        return None
    return float(D(raw))


def _mock_semantic(meta: dict, policy: str, temperature: float, seed: int) -> str:
    kind = meta["kind"]
    if kind in {"dominance", "population_sensitivity"}:
        return meta["correct"]
    if kind in {"framing", "scale", "cue"}:
        reference = meta["reference_choice"]
        if kind == "cue" and meta.get("arm") == "loaded" and policy == "mock-cautious":
            return meta["semantic_b"] if meta["semantic_a"] == reference else meta["semantic_a"]
        return reference
    if kind == "policy":
        if policy == "mock-cautious":
            return meta.get("mock_cautious_option") or meta["semantic_a"]
        return meta.get("mock_ev_option") or meta["semantic_b"]
    if kind in {"coherence", "ranking"}:
        utilities = meta["utilities"].get(policy) or meta["utilities"]["mock-ev"]
        left = D(utilities[meta["semantic_a"]])
        right = D(utilities[meta["semantic_b"]])
        if left == right:
            return min(meta["semantic_a"], meta["semantic_b"])
        return meta["semantic_a"] if left > right else meta["semantic_b"]
    value = D(meta["parameter_value"])
    higher = meta["higher_favors"]
    other = meta["other_option"]
    if policy == "mock-ev":
        raw_threshold = meta.get("reference_switch")
        if raw_threshold in (None, "", "null"):
            return meta.get("mock_ev_option") or higher
        threshold = D(raw_threshold)
    else:
        raw_threshold = meta.get("mock_cautious_switch")
        if raw_threshold in (None, "", "null"):
            raw_threshold = meta.get("reference_switch")
        if raw_threshold in (None, "", "null"):
            return meta.get("mock_cautious_option") or other
        threshold = D(raw_threshold)
    choice = higher if value >= threshold else other
    if temperature > 0 and seed % 20 == 0:
        choice = other if choice == higher else higher
    return choice
