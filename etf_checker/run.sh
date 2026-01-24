#!/usr/bin/env bash
set -euo pipefail

export PYTHONUNBUFFERED=1

LOG_LEVEL=$(/opt/venv/bin/python3 - <<'PY'
import json

level = "INFO"
try:
    with open("/data/options.json", "r", encoding="utf-8") as handle:
        data = json.load(handle)
    value = str(data.get("log_level", level)).upper()
    if value in {"DEBUG", "INFO", "WARNING", "ERROR"}:
        level = value
except Exception:
    pass

print(level)
PY
)
export LOG_LEVEL

exec /opt/venv/bin/python3 -m app.main
