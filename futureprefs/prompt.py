"""Render a fresh-context choice prompt. The choice, not the prose, is the score."""

from __future__ import annotations

from futureprefs.items import Item, Paraphrase
from futureprefs.prompt_text import fill, framing, text

# All wording lives in prompts/framing.yaml. These names are kept for existing imports.
SYSTEM_PROMPT = text("system", "futures")
TIMING_SYSTEM = text("system", "timing")
POLICY_SYSTEM = text("system", "policy")
ALLOCATION_SYSTEM = text("system", "allocation")
FUNDING_SYSTEM = text("system", "funding")
INSTRUCTION_TEXT = framing()["instructions"]["futures"]
POLICY_INSTRUCTION = framing()["instructions"]["policy"]
FUNDING_INSTRUCTION = framing()["instructions"]["funding"]


def _schema(allow_tie: bool) -> str:
    return text("choice_schema", "with_tie" if allow_tie else "plain")


def _tie_line(kind: str, allow_tie: bool) -> str:
    return text("tie_line", kind) if allow_tie else ""


def render_binary(
    item: Item,
    paraphrase: Paraphrase,
    order: str,
    context: dict[str, str],
    *,
    allow_tie: bool,
) -> tuple[str, str, str]:
    texts = paraphrase.options or item.options
    option_ids = list(item.options)
    if order == "ab":
        semantic_a, semantic_b = option_ids[0], option_ids[1]
    elif order == "ba":
        semantic_a, semantic_b = option_ids[1], option_ids[0]
    else:
        raise ValueError(order)
    return (
        _assemble(
            INSTRUCTION_TEXT[paraphrase.instruction],
            [("A", texts[semantic_a]), ("B", texts[semantic_b])],
            context,
            allow_tie=allow_tie,
        ),
        semantic_a,
        semantic_b,
    )


def render_pair(
    item: Item,
    paraphrase: Paraphrase,
    left_id: str,
    right_id: str,
    order: str,
    context: dict[str, str],
    *,
    allow_tie: bool,
) -> tuple[str, str, str]:
    texts = paraphrase.futures or item.futures
    if order == "ab":
        semantic_a, semantic_b = left_id, right_id
    else:
        semantic_a, semantic_b = right_id, left_id
    if item.frame == "funding":
        blocks = [
            fill(text("option_block"), label=label, body=texts[option_id].format_map(context).strip())
            for label, option_id in (("A", semantic_a), ("B", semantic_b))
        ]
        prompt = fill(
            text("funding_frame"),
            instruction=FUNDING_INSTRUCTION[paraphrase.instruction],
            question=(item.question or "").format_map(context).strip(),
            options="\n\n".join(blocks),
            schema=_schema(allow_tie),
            tie_line=_tie_line("funding", allow_tie),
        )
        return prompt, semantic_a, semantic_b
    return (
        _assemble(
            INSTRUCTION_TEXT[paraphrase.instruction],
            [("A", texts[semantic_a]), ("B", texts[semantic_b])],
            context,
            allow_tie=allow_tie,
        ),
        semantic_a,
        semantic_b,
    )


def render_policy(
    item: Item,
    paraphrase: Paraphrase,
    order: str,
    context: dict[str, str],
    *,
    allow_tie: bool,
) -> tuple[str, str, str]:
    texts = paraphrase.options or item.options
    option_ids = list(item.options)
    if order == "ab":
        semantic_a, semantic_b = option_ids[0], option_ids[1]
    elif order == "ba":
        semantic_a, semantic_b = option_ids[1], option_ids[0]
    else:
        raise ValueError(order)
    question = (item.question or "").format_map(context).strip()
    prompt = assemble_policy(
        question,
        texts[semantic_a].format_map(context),
        texts[semantic_b].format_map(context),
        instruction=paraphrase.instruction,
        allow_tie=allow_tie,
    )
    return prompt, semantic_a, semantic_b


def assemble_policy(
    question: str,
    option_a: str,
    option_b: str,
    *,
    instruction: str = "neutral",
    allow_tie: bool = False,
) -> str:
    """Shared framing for policy questions and Davidson stake sweeps."""
    blocks = [
        fill(text("option_block"), label=label, body=body.strip())
        for label, body in (("A", option_a), ("B", option_b))
    ]
    return fill(
        text("policy_frame"),
        instruction=POLICY_INSTRUCTION[instruction],
        question=question.strip(),
        options="\n\n".join(blocks),
        schema=_schema(allow_tie),
        tie_line=_tie_line("policy", allow_tie),
    )


def render_allocation(item: Item, context: dict[str, str]) -> str:
    labels = item.analysis.get("labels") or {}
    budget = str(item.analysis.get("budget", "1000000000"))
    lines = [
        fill(text("allocation_cause_line"), cause_id=cause_id, name=str(labels.get(cause_id, cause_id)),
             body=template.format_map(context).strip())
        for cause_id, template in item.futures.items()
    ]
    example = ", ".join(f'"{cause_id}": <dollars>' for cause_id in item.futures)
    question = (item.question or "").format_map(context).strip()
    return fill(text("allocation_frame"), question=question, budget=budget, causes="\n".join(lines), example=example)


def render_stated(item: Item, context: dict[str, str]) -> str:
    body = item.stated_prompt.format_map(context) if item.stated_prompt else ""
    return fill(text("stated_frame"), body=body.strip())


def _assemble(
    instruction: str,
    labeled_futures: list[tuple[str, str]],
    context: dict[str, str],
    *,
    allow_tie: bool,
) -> str:
    blocks = [fill(text("future_block"), label=label, body=template.format_map(context).strip()) for label, template in labeled_futures]
    return fill(
        text("futures_frame"),
        instruction=instruction,
        futures="\n\n".join(blocks),
        schema=_schema(allow_tie),
        tie_line=_tie_line("futures", allow_tie),
    )
