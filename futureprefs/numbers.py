"""Exact decimal formatting for scenario numbers.

Counts are kept as strings in the item files and parsed with Decimal so that
values such as 10^25 are not damaged by binary floating point.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

_SCALE_NAMES = {
    3: "thousand",
    6: "million",
    9: "billion",
    12: "trillion",
    15: "quadrillion",
    18: "quintillion",
    21: "sextillion",
    24: "septillion",
    27: "octillion",
    30: "nonillion",
}


def D(value: Decimal | int | str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def trim(value: Decimal, places: str = "0.000001") -> str:
    quantized = D(value).quantize(Decimal(places), rounding=ROUND_HALF_UP)
    text = format(quantized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def format_count(value: Decimal | int | str) -> str:
    number = D(value)
    if number == 0:
        return "0"
    sign = "-" if number < 0 else ""
    number = abs(number)
    if number != number.to_integral_value():
        return sign + trim(number)
    digits = str(int(number))
    exponent = len(digits) - 1
    if exponent < 3:
        return sign + f"{int(number):,}"
    scale = (exponent // 3) * 3
    if scale not in _SCALE_NAMES:
        coefficient = Decimal(digits[0] + ("." + digits[1:4] if len(digits) > 1 else ""))
        return f"{sign}{trim(coefficient)}×10^{exponent}"
    coefficient_length = exponent - scale + 1
    coefficient = int(digits[:coefficient_length])
    rest = digits[coefficient_length:]
    if any(character != "0" for character in rest):
        coefficient_text = digits[0] + ("." + digits[1:4] if len(digits) > 1 else "")
        return f"{sign}{trim(Decimal(coefficient_text))}×10^{exponent}"
    if coefficient == 10 ** (exponent - scale):
        scientific = f"10^{exponent}"
    elif scale == exponent:
        scientific = f"{coefficient}×10^{exponent}"
    else:
        scientific = f"{coefficient}×10^{scale}"
    return f"{sign}{coefficient} {_SCALE_NAMES[scale]} ({scientific})"


def format_probability(value: Decimal | int | str) -> str:
    probability = D(value)
    if probability == 0:
        return "0 percent"
    if probability == 1:
        return "100 percent"
    percent = trim(probability * Decimal(100))
    if probability < Decimal("0.01"):
        inverse = Decimal(1) / probability
        return f"{percent} percent (1 in {format_count(inverse)})"
    return f"{percent} percent"


def format_multiplier(value: Decimal | int | str) -> str:
    number = D(value)
    if number >= 1000:
        return f"{format_count(number)} times"
    return f"{trim(number)} times"


def format_years(value: Decimal | int | str) -> str:
    number = D(value)
    if number == number.to_integral_value() and number >= 1000:
        return f"{int(number):,} years"
    if number == number.to_integral_value():
        return f"{int(number)} years"
    return f"{trim(number)} years"


def format_percent_points(value: Decimal | int | str) -> str:
    return f"{trim(D(value))} percentage points"


def format_number(value: Decimal | int | str, kind: str) -> str:
    if kind == "count":
        return format_count(value)
    if kind == "probability":
        return format_probability(value)
    if kind == "fraction":
        return format_probability(value)
    if kind == "multiplier":
        return format_multiplier(value)
    if kind == "years":
        return format_years(value)
    if kind == "percent_points":
        return format_percent_points(value)
    if kind == "number":
        return trim(D(value))
    raise ValueError(f"Unknown number format: {kind}")


def sigfigs(value: Decimal, figures: int = 6) -> Decimal:
    if value == 0:
        return Decimal(0)
    sign = Decimal(1) if value > 0 else Decimal(-1)
    rendered = format(abs(value), f".{figures}e")
    return sign * Decimal(rendered)
