"""Persistence helpers for monitor state."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

STATE_PATH = Path("/data/monitor_state.json")


@dataclass(slots=True)
class MonitorState:
    baselines: dict[str, float] = field(default_factory=dict)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_state() -> MonitorState:
    raw = _load_json(STATE_PATH)
    baselines = raw.get("baselines", {})
    cleaned: dict[str, float] = {}
    if isinstance(baselines, dict):
        for symbol, value in baselines.items():
            try:
                cleaned[str(symbol).upper()] = float(value)
            except (TypeError, ValueError):
                continue
    return MonitorState(baselines=cleaned)


def save_state(state: MonitorState) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"baselines": state.baselines}
    with STATE_PATH.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
