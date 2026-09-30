#!/usr/bin/env bash
# Sangam prototype launcher.
#   ./run.sh                  set up on first run (Python venv + UI build), then serve http://127.0.0.1:8765
#   ./run.sh --demo           also load the April-2026 reference run from ../../Docs/input first
#   ./run.sh --demo --fresh   wipe the prototype database, then load the reference run
#   PORT=9000 ./run.sh        serve on another port
set -euo pipefail
cd "$(dirname "$0")"
HOST=${HOST:-127.0.0.1}
PORT=${PORT:-8765}
DEMO=0
FRESH=0
for a in "$@"; do
  case "$a" in
    --demo) DEMO=1 ;;
    --fresh) FRESH=1 ;;
    -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
    *) echo "unknown option: $a" >&2; exit 2 ;;
  esac
done

if [ ! -x backend/.venv/bin/python ]; then
  echo "» creating the Python environment (backend/.venv)"
  python3 -m venv backend/.venv
  backend/.venv/bin/pip install -q --upgrade pip
  backend/.venv/bin/pip install -q -r backend/requirements.txt
fi

if [ ! -f frontend/dist/index.html ]; then
  echo "» building the UI (frontend/dist)"
  (cd frontend && npm install --no-audit --no-fund && npm run build)
fi

cd backend
if [ "$DEMO" = 1 ]; then
  args=(demo)
  [ "$FRESH" = 1 ] && args+=(--fresh)
  if ! .venv/bin/python -m sangam.cli "${args[@]}"; then
    echo "!! the reference check reported a difference or a failed invariant - see above" >&2
  fi
fi
echo "» Sangam on http://$HOST:$PORT  (API docs at /docs)"
exec .venv/bin/python -m sangam.cli serve --host "$HOST" --port "$PORT"
