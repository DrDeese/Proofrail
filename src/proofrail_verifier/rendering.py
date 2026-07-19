"""Render verifier results as stable machine-readable JSON."""

from __future__ import annotations

import json
from typing import Any


def render_json(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
