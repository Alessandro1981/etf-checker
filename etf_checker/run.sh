#!/command/with-contenv bash
set -euo pipefail

export PYTHONUNBUFFERED=1

exec /opt/venv/bin/python3 -m app.main
