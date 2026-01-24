#!/usr/bin/with-contenv bashio
set -euo pipefail

export PYTHONUNBUFFERED=1

exec python3 -m app.main
