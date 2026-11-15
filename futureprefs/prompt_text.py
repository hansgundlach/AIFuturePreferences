"""Load the editable prompt text in prompts/.

prompts/framing.yaml holds every system prompt and frame. prompts/davidson_sweeps.yaml
holds the Davidson stake-sweep scenarios. Templates use ${name} placeholders
(string.Template), so JSON braces in a template need no escaping. A missing
placeholder value raises an error instead of sending a half-filled prompt.

Set FUTUREPREFS_PROMPTS to another folder to try alternative wording without
editing the defaults.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from string import Template

import yaml

PROMPTS_DIR = Path(os.environ.get("FUTUREPREFS_PROMPTS", Path(__file__).resolve().parents[1] / "prompts"))


@lru_cache(maxsize=None)
def _load(name: str) -> dict:
    path = PROMPTS_DIR / name
    with path.open() as handle:
        return yaml.safe_load(handle)


def framing() -> dict:
    return _load("framing.yaml")


def sweeps() -> dict:
    return _load("davidson_sweeps.yaml")["scenarios"]


def text(*keys: str) -> str:
    """A raw entry from framing.yaml, for example text("system", "futures")."""
    node = framing()
    for key in keys:
        node = node[key]
    if not isinstance(node, str):
        raise KeyError(f"prompts/framing.yaml entry {'.'.join(keys)} is not text")
    return node


def fill(template: str, **values: object) -> str:
    return Template(template).substitute({key: str(value) for key, value in values.items()})
