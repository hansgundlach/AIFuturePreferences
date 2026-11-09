"""Parse model outputs. The primary datum is the choice letter."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)
_OBJECT = re.compile(r"\{[^{}]*\}", re.DOTALL)
# A reply can be cut off after the value, once hidden reasoning has used the token budget.
_VALUE = re.compile(
    r'"value"\s*:\s*(?:"(never(?:\s+deploy)?)"|(-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?))',
    re.IGNORECASE,
)
_REFUSAL = re.compile(
    r"\b(i can(?:not|'t)|i won(?:'t|’t)|i must refuse|as an ai|i'm unable|i am unable)\b",
    re.IGNORECASE,
)


@dataclass
class Parsed:
    choice_letter: str | None
    confidence: float | None
    reasoning: str | None
    stated_value: str | None
    parse_ok: bool
    refusal: bool


def parse_response(text: str, *, kind: str, allow_tie: bool) -> Parsed:
    if not text or not text.strip():
        return Parsed(None, None, None, None, False, False)
    payload = _extract_object(text)
    refusal = bool(_REFUSAL.search(text)) and payload is None
    if payload is None and kind in {"stated", "timing"}:
        salvaged = _salvage_value(text)
        if salvaged is not None:
            return _parsed_stated(salvaged, None, None, kind)
    if payload is None:
        return Parsed(None, None, _clean(text), None, False, refusal or _looks_like_refusal(text))
    reasoning = _clean(str(payload.get("reasoning", ""))) or None
    confidence = _confidence(payload.get("confidence"))
    if kind == "allocation":
        return _parsed_allocation(payload.get("amounts"), reasoning)
    if kind in {"stated", "timing"}:
        if "value" not in payload:
            return Parsed(None, confidence, reasoning, None, False, False)
        if payload.get("value") is None:
            # A stated item may decline to give a number. A timing item uses "never" for that answer.
            return Parsed(None, confidence, reasoning, None, kind == "stated", False)
        return _parsed_stated(payload.get("value"), confidence, reasoning, kind)
    letter = _letter(payload.get("choice"), allow_tie=allow_tie)
    if letter is None:
        return Parsed(None, confidence, reasoning, None, False, _looks_like_refusal(text))
    return Parsed(letter, confidence, reasoning, None, True, False)


def _parsed_allocation(raw: object, reasoning: str | None) -> Parsed:
    if not isinstance(raw, dict) or not raw:
        return Parsed(None, None, reasoning, None, False, False)
    amounts: dict[str, str] = {}
    for key, value in raw.items():
        number = _amount(value)
        if number is None or number < 0:
            return Parsed(None, None, reasoning, None, False, False)
        amounts[str(key)] = format(number, "f")
    return Parsed(None, None, reasoning, json.dumps(amounts, sort_keys=True), True, False)


def _amount(raw: object) -> float | None:
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip().replace(",", "").replace("$", "")
    if text.endswith("%"):
        text = text[:-1].strip()
    try:
        return float(Decimal(text))
    except (InvalidOperation, ValueError):
        return None


def _parsed_stated(raw: object, confidence: float | None, reasoning: str | None, kind: str) -> Parsed:
    if kind == "timing" and _is_never(raw):
        return Parsed(None, confidence, reasoning, "never", True, False)
    stated = _stated_value(raw)
    if kind == "timing" and (stated is None or stated.startswith("-")):
        return Parsed(None, confidence, reasoning, None, False, False)
    return Parsed(None, confidence, reasoning, stated, stated is not None, False)


def _extract_object(text: str) -> dict | None:
    stripped = text.strip()
    direct = _loads_relevant(stripped)
    if direct is not None:
        return direct
    start = stripped.find("{")
    if start != -1:
        try:
            payload, _end = json.JSONDecoder().raw_decode(stripped[start:])
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict) and ("choice" in payload or "value" in payload or "amounts" in payload):
            return payload
    candidates: list[str] = []
    candidates.extend(_FENCE.findall(text))
    candidates.extend(_OBJECT.findall(text))
    # Prefer the last object that actually parses and carries a relevant key.
    found: dict | None = None
    for candidate in candidates:
        parsed = _loads_relevant(candidate)
        if parsed is not None:
            found = parsed
    return found


def _loads_relevant(text: str) -> dict | None:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict) and ("choice" in payload or "value" in payload or "amounts" in payload):
        return payload
    return None


def _salvage_value(text: str) -> object | None:
    match = _VALUE.search(text)
    if match is None:
        return None
    if match.group(1) is not None:
        return match.group(1)
    return match.group(2)


def _letter(raw: object, *, allow_tie: bool) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip().upper()
    if text in {"A", "B"}:
        return text
    if text in {"T", "TIE", "EQUAL", "INDIFFERENT", "SAME"}:
        return "T" if allow_tie else None
    if text.startswith("FUTURE A") or text == "OPTION A":
        return "A"
    if text.startswith("FUTURE B") or text == "OPTION B":
        return "B"
    return None


def _confidence(raw: object) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value != value:  # NaN
        return None
    return max(0.0, min(1.0, value))


def _is_never(raw: object) -> bool:
    return isinstance(raw, str) and raw.strip().lower() in {"never", "never deploy"}


def _stated_value(raw: object) -> str | None:
    if raw is None:
        return None
    try:
        decimal = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None
    if not decimal.is_finite():
        return None
    text = format(decimal, "f")
    # Trim zeros only after a decimal point, so 20 stays 20 and 2.50 becomes 2.5.
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _clean(text: str) -> str:
    compact = " ".join(text.split())
    return compact[:2000]


def _looks_like_refusal(text: str) -> bool:
    return bool(_REFUSAL.search(text))
