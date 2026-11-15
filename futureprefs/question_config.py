"""Join the editable writeup questions with their internal experiment settings."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import yaml


def question_rows(path: Path) -> list[dict]:
    document = yaml.safe_load(path.read_text()) or {}
    # Continue accepting the original full item format in alternate prompt folders.
    if isinstance(document, list):
        return document
    if not isinstance(document, dict):
        raise ValueError(f"{path}: expected an items list")
    rows = document.get("items")
    if not isinstance(rows, list):
        raise ValueError(f"{path}: expected an items list")
    if "format" not in document:
        return rows
    if document["format"] != "editable-v1":
        raise ValueError(f"{path}: unknown question format {document['format']!r}")
    settings_path = path.with_name("_experiment_settings.yaml")
    settings = yaml.safe_load(settings_path.read_text())["items"]
    return [_expand(row, settings) for row in rows]


def _expand(row: dict, settings: dict) -> dict:
    item_id = row["id"]
    if item_id not in settings:
        raise ValueError(f"{item_id}: no experiment settings; keep existing question ids unchanged")
    result = deepcopy(settings[item_id])
    result["id"] = item_id
    allowed = {"id", "title", "fixed"}
    if "parameter" in result:
        allowed.add("grid")
    kind = result["kind"]
    if kind in {"ranking", "allocation"}:
        allowed.update({"causes", "labels"})
    if kind == "ranking" and result.get("frame") == "funding":
        allowed.add("question")
    if kind == "allocation":
        allowed.update({"question", "budget"})
    elif kind == "timing":
        allowed.add("timing")
    elif kind == "stated":
        allowed.add("question")
    elif kind not in {"ranking"}:
        allowed.add("options")
        if kind == "policy" or result.get("open_context"):
            allowed.add("question")
    unknown = set(row) - allowed
    if unknown:
        raise ValueError(f"{item_id}: unknown field(s) {', '.join(sorted(unknown))}; allowed: {', '.join(sorted(allowed))}")
    result["short"] = row.get("title", item_id)
    for name in ("fixed", "options"):
        if name in row:
            result[name] = row[name]
    if "parameter" in result:
        if "grid" not in row:
            raise ValueError(f"{item_id}: missing grid of values to test")
        result["parameter"]["grid"] = row["grid"]
    if "question" in row:
        result["stated_prompt" if kind == "stated" else "question"] = row["question"]
    elif kind == "stated":
        raise ValueError(f"{item_id}: missing question text")
    if "causes" in row:
        result["futures"] = row["causes"]
    for name in ("labels", "budget"):
        if name in row:
            result.setdefault("analysis", {})[name] = row[name]
    if kind == "timing":
        timing = row.get("timing", {})
        unknown = set(timing) - {"p0_grid", "g_grid", "p0_extra", "g_extra"}
        if unknown:
            raise ValueError(f"{item_id}: unknown timing setting(s): {', '.join(sorted(unknown))}")
        result.setdefault("analysis", {}).update(timing)
    return result
